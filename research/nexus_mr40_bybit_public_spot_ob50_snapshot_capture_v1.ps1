# One-shot PUBLIC Bybit BTCUSDT SPOT L50 orderbook snapshot; NO trading or private API.
param([Parameter(Mandatory=$true)][string]$Protocol,
      [Parameter(Mandatory=$true)][string]$Output)
$ErrorActionPreference='Stop'
if(Test-Path -LiteralPath $Output){throw 'refuse_overwrite_orderbook_research_evidence'}
$p=Get-Content -Raw -LiteralPath $Protocol|ConvertFrom-Json
if($p.schema -ne 'nexus.mr40.bybit_public_spot_orderbook50_cost_snapshot.v1' -or
   $p.endpoint -ne 'wss://stream.bybit.com/v5/public/spot' -or
   $p.topic -ne 'orderbook.50.BTCUSDT' -or
   $p.stop_after_seconds -ne 16 -or
   $p.safety.orders -ne 0 -or $p.safety.live -ne $false){
 throw 'precommitted_public_spot_orderbook_protocol_not_valid'
}
$x=[ordered]@{
 schema='nexus.mr40.bybit_public_spot_ob50_snapshot_capture.results.v1'
 protocol_sha256=(Get-FileHash -LiteralPath $Protocol -Algorithm SHA256).Hash.ToLowerInvariant()
 endpoint='wss://stream.bybit.com/v5/public/spot'
 topic='orderbook.50.BTCUSDT'
 start_utc=[DateTimeOffset]::UtcNow.ToString('o')
 end_utc=$null
 connected=$false
 subscription_ack=$false
 snapshot_received=$false
 source_received_utc=$null
 raw_snapshot_text=$null
 frame_count=0
 failure_kind=$null
 failure_reason=$null
 orders_sent=0
 paper_modified=$false
 private_api_used=$false
 live_enabled=$false
}
$ws=$null
try{
 $ws=[System.Net.WebSockets.ClientWebSocket]::new()
 $ct=[System.Threading.CancellationTokenSource]::new([TimeSpan]::FromSeconds(8))
 try{[void]$ws.ConnectAsync([Uri]$x.endpoint,$ct.Token).GetAwaiter().GetResult()}
 finally{$ct.Dispose()}
 if($ws.State -ne [System.Net.WebSockets.WebSocketState]::Open){throw 'public_spot_WSS_not_open'}
 $x.connected=$true
 $req=[System.Text.Encoding]::UTF8.GetBytes('{"op":"subscribe","args":["orderbook.50.BTCUSDT"]}')
 $st=[System.Threading.CancellationTokenSource]::new([TimeSpan]::FromSeconds(5))
 try{[void]$ws.SendAsync([ArraySegment[byte]]::new($req),[System.Net.WebSockets.WebSocketMessageType]::Text,$true,$st.Token).GetAwaiter().GetResult()}
 finally{$st.Dispose()}
 $deadline=[DateTimeOffset]::UtcNow.AddSeconds(16)
 while([DateTimeOffset]::UtcNow -lt $deadline -and $x.frame_count -lt 150){
    $remaining=($deadline-[DateTimeOffset]::UtcNow).TotalSeconds
    if($remaining -le 0){break}
    $bytes=New-Object byte[] 200000
    $rt=[System.Threading.CancellationTokenSource]::new([TimeSpan]::FromSeconds([Math]::Max(1,$remaining)))
    try{
      $res=$ws.ReceiveAsync([ArraySegment[byte]]::new($bytes),$rt.Token).GetAwaiter().GetResult()
    }catch{
      if($_.Exception.ToString().ToLowerInvariant().Contains('canceled')){break}
      throw
    }finally{$rt.Dispose()}
    if($res.MessageType -eq [System.Net.WebSockets.WebSocketMessageType]::Close){break}
    if($res.MessageType -ne [System.Net.WebSockets.WebSocketMessageType]::Text){continue}
    if(-not $res.EndOfMessage){throw 'incomplete_fragmented_public_source_frame'}
    $raw=[System.Text.Encoding]::UTF8.GetString($bytes,0,$res.Count)
    $received=[DateTimeOffset]::UtcNow.ToString('o')
    $frame=$raw|ConvertFrom-Json
    $x.frame_count++
    if($frame.op -eq 'subscribe' -and $frame.success -is [bool] -and $frame.success -eq $true){
        $x.subscription_ack=$true
    }elseif($frame.op -eq 'subscribe' -and $frame.success -eq $false){
        throw 'public_spot_L50_subscription_rejected'
    }
    if($frame.topic -eq 'orderbook.50.BTCUSDT' -and $frame.type -eq 'snapshot' -and -not $x.snapshot_received){
        $x.raw_snapshot_text=$raw
        $x.source_received_utc=$received
        $x.snapshot_received=$true
    }
    if($x.subscription_ack -and $x.snapshot_received){break}
 }
}catch{
 $x.failure_kind=$_.Exception.GetType().Name
 $x.failure_reason=($_.Exception.Message -replace '[\r\n]+',' ')
 if($x.failure_reason.Length -gt 400){$x.failure_reason=$x.failure_reason.Substring(0,400)}
}finally{
 if($null -ne $ws){try{$ws.Dispose()}catch{}}
}
$x.end_utc=[DateTimeOffset]::UtcNow.ToString('o')
$dir=Split-Path -Parent $Output
if(-not (Test-Path -LiteralPath $dir)){New-Item -ItemType Directory -Path $dir -Force|Out-Null}
$x|ConvertTo-Json -Depth 10|Set-Content -LiteralPath $Output -Encoding UTF8 -NoNewline
# Do not spam full market book to remote terminal; save raw receipt locally.
[ordered]@{
 connected=$x.connected
 subscription_ack=$x.subscription_ack
 snapshot_received=$x.snapshot_received
 source_received_utc=$x.source_received_utc
 frame_count=$x.frame_count
 bytes_raw=($(if($x.raw_snapshot_text){$x.raw_snapshot_text.Length}else{0}))
 failure_reason=$x.failure_reason
 real_orders_sent=$x.orders_sent
 output_file=$Output
}|ConvertTo-Json -Depth 4
