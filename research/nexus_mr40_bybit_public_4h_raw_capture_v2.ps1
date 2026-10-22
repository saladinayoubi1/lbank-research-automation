# MR40 / Official Bybit PUBLIC BTCUSDT SPOT 4h confirmed-close raw capture v2.
# Research only; fixed candle 2026-10-22 16:00-20:00 UTC.
# No API secrets, no auth, no order, no scheduler, no daemon and NO live trading.
param(
 [Parameter(Mandatory=$true)][string]$Protocol,
 [Parameter(Mandatory=$true)][string]$Output
)
$ErrorActionPreference='Stop'
if(Test-Path -LiteralPath $Output){throw 'refuse_overwrite_4h_raw_capture'}
$p=Get-Content -Raw -LiteralPath $Protocol | ConvertFrom-Json
if($p.schema -ne 'nexus.mr40.bybit_spot_4h_close_proof_v2.protocol' -or
   $p.topic -ne 'kline.240.BTCUSDT' -or
   $p.url -ne 'wss://stream.bybit.com/v5/public/spot' -or
   [long]$p.fixed_bar_start_ms -ne 1792684800000 -or
   [long]$p.fixed_bar_end_ms_inclusive -ne 1792699199999 -or
   $p.safety.orders -ne 0 -or $p.safety.live -ne $false){
  throw 'locked_4h_close_v2_protocol_mismatch'
}
$utcNow=[DateTimeOffset]::UtcNow
$windowStart=[DateTimeOffset]::Parse('2026-10-22T19:58:00Z')
$windowEnd=[DateTimeOffset]::Parse('2026-10-22T20:02:00Z')
if($utcNow -lt $windowStart -or $utcNow -ge $windowEnd){
 throw ('outside_fixed_one_shot_capture_window_no_network UTC='+$utcNow.ToString('o'))
}
# The above guard executes BEFORE any network operations.
$run=[ordered]@{
 schema='nexus.mr40.bybit.public_spot_fourhour_raw_close_v2.results.v1'
 protocol_sha256=(Get-FileHash -Algorithm SHA256 -LiteralPath $Protocol).Hash.ToLowerInvariant()
 endpoint='wss://stream.bybit.com/v5/public/spot'
 topic='kline.240.BTCUSDT'
 started_utc=$utcNow.ToString('o')
 finished_utc=$null
 public_ws_connected=$false
 subscribe_ack_success=$false
 raw_topic_receipts=@()
 confirmed_true_native_boolean_count=0
 raw_frames_seen=0
 close_source_proven_by_validator=$false
 MR40_source_authorized=$false
 failure_type=$null
 failure_reason=$null
 paper_modified=$false
 orders_sent=0
 private_api_used=$false
 live_enabled=$false
}
$ws=$null
try {
 $ws=[System.Net.WebSockets.ClientWebSocket]::new()
 $ws.Options.KeepAliveInterval=[TimeSpan]::FromSeconds(20)
 $connectToken=[System.Threading.CancellationTokenSource]::new([TimeSpan]::FromSeconds(10))
 try{[void]$ws.ConnectAsync([Uri]$p.url,$connectToken.Token).GetAwaiter().GetResult()}
 finally{$connectToken.Dispose()}
 if($ws.State -ne [System.Net.WebSockets.WebSocketState]::Open){throw 'public_4h_spot_socket_not_open'}
 $run.public_ws_connected=$true
 $req=[System.Text.Encoding]::UTF8.GetBytes('{"op":"subscribe","args":["kline.240.BTCUSDT"]}')
 $sendToken=[System.Threading.CancellationTokenSource]::new([TimeSpan]::FromSeconds(6))
 try{
  [void]$ws.SendAsync([ArraySegment[byte]]::new($req),[System.Net.WebSockets.WebSocketMessageType]::Text,$true,$sendToken.Token).GetAwaiter().GetResult()
 }finally{$sendToken.Dispose()}
 $deadline=[DateTimeOffset]::UtcNow.AddSeconds(180)
 while([DateTimeOffset]::UtcNow -lt $deadline -and
       $run.raw_topic_receipts.Count -lt 70 -and
       $run.confirmed_true_native_boolean_count -lt 1){
  $rem=($deadline-[DateTimeOffset]::UtcNow).TotalSeconds
  if($rem -le 0){break}
  $buff=New-Object byte[] 65536
  $receiveToken=[System.Threading.CancellationTokenSource]::new([TimeSpan]::FromSeconds([Math]::Max(1,$rem)))
  try{
    $response=$ws.ReceiveAsync([ArraySegment[byte]]::new($buff),$receiveToken.Token).GetAwaiter().GetResult()
  }catch{
    if($_.Exception.ToString().ToLowerInvariant().Contains('canceled')){break}
    throw
  }finally{$receiveToken.Dispose()}
  if($response.MessageType -eq [System.Net.WebSockets.WebSocketMessageType]::Close){break}
  if($response.MessageType -ne [System.Net.WebSockets.WebSocketMessageType]::Text){continue}
  if(-not $response.EndOfMessage){throw 'fragmented_market_source_ws_message_fail_closed'}
  $raw=[System.Text.Encoding]::UTF8.GetString($buff,0,$response.Count)
  $received=[DateTimeOffset]::UtcNow.ToString('o')
  $doc=$raw | ConvertFrom-Json
  $run.raw_frames_seen++
  if($doc.op -eq 'subscribe' -and $doc.success -is [bool] -and $doc.success -eq $true){
    $run.subscribe_ack_success=$true
  }elseif($doc.op -eq 'subscribe' -and $doc.success -eq $false){
    throw 'public_4h_spot_subscribe_rejected'
  }
  if($doc.topic -ne 'kline.240.BTCUSDT'){continue}
  # Retain ORIGINAL WebSocket payload as raw JSON string. Do NOT reinterpret
  # or coerce confirm as in the old v1 capture.
  $run.raw_topic_receipts+=([ordered]@{received_utc=$received;raw_text=$raw})
  foreach($bar in @($doc.data)){
    if($null -ne $bar -and $bar.confirm -is [bool] -and $bar.confirm -eq $true){
       $run.confirmed_true_native_boolean_count++
    }
  }
 }
}catch {
 $run.failure_type=$_.Exception.GetType().Name
 $run.failure_reason=($_.Exception.Message -replace '[\r\n]+',' ')
 if($run.failure_reason.Length -gt 450){$run.failure_reason=$run.failure_reason.Substring(0,450)}
}finally{
 if($null -ne $ws){try{$ws.Dispose()}catch{}}
}
$run.finished_utc=[DateTimeOffset]::UtcNow.ToString('o')
# Only independently pinned Python gate (after saving) can qualify a close.
# Collector never claims source/MR40 authorization itself.
$dir=Split-Path -Parent $Output
if(-not (Test-Path -LiteralPath $dir)){
 New-Item -ItemType Directory -Path $dir -Force|Out-Null
}
$run | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $Output -Encoding UTF8 -NoNewline
$run | ConvertTo-Json -Depth 12
