# NEXUS MR40 PUBLIC Bybit Spot 4h WebSocket probe — research only.
# No authentication, private API, trade request, scheduler, background service,
# Laptop2 Paper writes, order payload or live execution code.
param(
  [Parameter(Mandatory=$true)][string]$Protocol,
  [Parameter(Mandatory=$true)][string]$Output
)
$ErrorActionPreference = 'Stop'
if(Test-Path -LiteralPath $Output){throw 'refuse_to_overwrite_market_evidence'}
$p = Get-Content -Raw -LiteralPath $Protocol | ConvertFrom-Json
if($p.schema -ne 'nexus.mr40.bybit_spot_websocket_public_probe.v1' -or
   $p.url -ne 'wss://stream.bybit.com/v5/public/spot' -or
   $p.subscribe_payload.args[0] -ne 'kline.240.BTCUSDT' -or
   $p.safety.orders -ne 0 -or $p.safety.live -ne $false){
    throw 'precommitted_public_protocol_not_valid'
}
$run = [ordered]@{
 schema='nexus.mr40.bybit.public_spot_ws_one_shot_result.v1'
 protocol_sha256=(Get-FileHash -Algorithm SHA256 -LiteralPath $Protocol).Hash.ToLowerInvariant()
 started_utc=[DateTimeOffset]::UtcNow.ToString('o')
 endpoint=$p.url
 topic='kline.240.BTCUSDT'
 public_ws_connected=$false
 subscribe_ack_success=$false
 received_frames=@()
 frames_seen=0
 topic_message_count=0
 confirmed_closed_4h_received=0
 accepted_closed_4h_from_realtime=$false
 live_execution_qualification=$false
 bybit_rest_unblocked=$false
 failure_type=$null
 failure_reason=$null
 finished_utc=$null
 paper_modified=$false
 orders_sent=0
 private_api_used=$false
}
$ws = $null
try {
 $ws=[System.Net.WebSockets.ClientWebSocket]::new()
 $url=[Uri]::new([string]$p.url)
 $connect=[System.Threading.CancellationTokenSource]::new([TimeSpan]::FromSeconds(8))
 try {
    $ws.ConnectAsync($url,$connect.Token).GetAwaiter().GetResult()
 } finally { $connect.Dispose() }
 if($ws.State -ne [System.Net.WebSockets.WebSocketState]::Open){throw 'ws_handshake_not_open'}
 $run.public_ws_connected=$true
 $arg=[ordered]@{op='subscribe';args=@('kline.240.BTCUSDT')}
 $bytes=[System.Text.Encoding]::UTF8.GetBytes(($arg | ConvertTo-Json -Compress -Depth 5))
 $sendSegment=[ArraySegment[byte]]::new($bytes)
 $send=[System.Threading.CancellationTokenSource]::new([TimeSpan]::FromSeconds(5))
 try {
    $ws.SendAsync($sendSegment,[System.Net.WebSockets.WebSocketMessageType]::Text,$true,$send.Token).GetAwaiter().GetResult()
 } finally { $send.Dispose() }
 $deadline=[DateTimeOffset]::UtcNow.AddSeconds(25)
 for($index=0;$index -lt 8;$index++){
    $remaining=($deadline-[DateTimeOffset]::UtcNow).TotalSeconds
    if($remaining -le 0){break}
    $waitSecs=[Math]::Min(7,[Math]::Max(1,$remaining))
    $cts=[System.Threading.CancellationTokenSource]::new([TimeSpan]::FromSeconds($waitSecs))
    $buff=New-Object byte[] 65536
    $seg=[ArraySegment[byte]]::new($buff)
    try{
       $received=$ws.ReceiveAsync($seg,$cts.Token).GetAwaiter().GetResult()
    } catch [System.OperationCanceledException] {
       break
    } catch {
       if($_.Exception.ToString().Contains('canceled') -or $_.Exception.ToString().Contains('cancelled')){break}
       throw
    } finally { $cts.Dispose() }
    if($received.MessageType -eq [System.Net.WebSockets.WebSocketMessageType]::Close){break}
    $run.frames_seen++
    if($received.MessageType -ne [System.Net.WebSockets.WebSocketMessageType]::Text){continue}
    if(-not $received.EndOfMessage){throw 'unsupported_fragmented_market_message'}
    $frame=[System.Text.Encoding]::UTF8.GetString($buff,0,$received.Count)
    $obj=$frame | ConvertFrom-Json
    if($obj.op -eq 'subscribe' -and $obj.success -eq $true){
       $run.subscribe_ack_success=$true
    }
    if($obj.topic -eq 'kline.240.BTCUSDT'){
       $run.topic_message_count++
       foreach($bar in @($obj.data)){
          if($null -eq $bar){continue}
          $dataPoint=[ordered]@{
              received_utc=[DateTimeOffset]::UtcNow.ToString('o')
              bar_start_ms=$bar.start
              interval=$bar.interval
              open=$bar.open
              high=$bar.high
              low=$bar.low
              close=$bar.close
              base_volume=$bar.volume
              confirmed_closed=($bar.confirm -eq $true)
              bybit_message_ts=$obj.ts
          }
          $run.received_frames+= $dataPoint
          if($bar.confirm -eq $true){$run.confirmed_closed_4h_received++}
       }
    }
    if($run.topic_message_count -ge 2){break}
 }
 $run.accepted_closed_4h_from_realtime=($run.subscribe_ack_success -and $run.confirmed_closed_4h_received -gt 0)
} catch {
   $run.failure_type=$_.Exception.GetType().Name
   $run.failure_reason=($_.Exception.Message -replace '[\r\n]+',' ')
   if($run.failure_reason.Length -gt 500){$run.failure_reason=$run.failure_reason.Substring(0,500)}
} finally {
 if($null -ne $ws){try{$ws.Dispose()}catch{}}
}
$run.finished_utc=[DateTimeOffset]::UtcNow.ToString('o')
$dir=Split-Path -Parent $Output
if(-not (Test-Path $dir)){New-Item -ItemType Directory -Path $dir -Force | Out-Null}
$run | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $Output -Encoding UTF8 -NoNewline
$run | ConvertTo-Json -Depth 10
