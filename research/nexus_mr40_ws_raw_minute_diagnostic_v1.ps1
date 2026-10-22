# One last bounded RAW ONLY Bybit SPOT BTCUSDT minute WS diagnostic.
# No strategy, no confirm qualification, no broker credentials or orders.
param([Parameter(Mandatory=$true)][string]$Protocol,[Parameter(Mandatory=$true)][string]$Output)
$ErrorActionPreference='Stop'
if(Test-Path $Output){throw 'refuse_overwrite_raw_evidence'}
$p=Get-Content -Raw $Protocol|ConvertFrom-Json
if($p.schema -ne 'nexus.mr40.public_spot_ws_raw_minute_diagnostic.v1' -or
   $p.topic -ne 'kline.1.BTCUSDT' -or $p.time_limit_seconds -ne 80 -or
   $p.safety.orders -ne 0){throw 'locked_raw_diagnostic_protocol_invalid'}
$result=[ordered]@{
schema='nexus.mr40.bybit_spot_raw_minute_diagnostic.results.v1'
protocol_sha256=(Get-FileHash $Protocol -Algorithm SHA256).Hash.ToLowerInvariant()
started_utc=[DateTimeOffset]::UtcNow.ToString('o')
finished_utc=$null
endpoint=$p.endpoint
topic=$p.topic
connected=$false
subscription_ack=$false
captured_topic_count=0
observed_confirm_true=$false
raw_frames=@()
error=$null
allow_feed_to_mr40=$false
paper_unchanged=$true;orders_sent=0;private_api=$false;live=$false
}
$ws=$null
try{
 $ws=[System.Net.WebSockets.ClientWebSocket]::new()
 $ct=[System.Threading.CancellationTokenSource]::new([TimeSpan]::FromSeconds(9))
 try{[void]$ws.ConnectAsync([Uri]$p.endpoint,$ct.Token).GetAwaiter().GetResult()}finally{$ct.Dispose()}
 if($ws.State -ne [System.Net.WebSockets.WebSocketState]::Open){throw 'public_ws_not_open'}
 $result.connected=$true
 $payload=[System.Text.Encoding]::UTF8.GetBytes('{"op":"subscribe","args":["kline.1.BTCUSDT"]}')
 $st=[System.Threading.CancellationTokenSource]::new([TimeSpan]::FromSeconds(5))
 try{[void]$ws.SendAsync([ArraySegment[byte]]::new($payload),[System.Net.WebSockets.WebSocketMessageType]::Text,$true,$st.Token).GetAwaiter().GetResult()}finally{$st.Dispose()}
 $stop=[DateTimeOffset]::UtcNow.AddSeconds(80)
 while([DateTimeOffset]::UtcNow -lt $stop -and $result.captured_topic_count -lt 24 -and -not $result.observed_confirm_true){
  $remaining=($stop-[DateTimeOffset]::UtcNow).TotalSeconds
  if($remaining -le 0){break}
  $buffer=New-Object byte[] 65536
  $wait=[System.Threading.CancellationTokenSource]::new([TimeSpan]::FromSeconds([Math]::Max(1,$remaining)))
  try{$x=$ws.ReceiveAsync([ArraySegment[byte]]::new($buffer),$wait.Token).GetAwaiter().GetResult()}
  catch{if($_.Exception.ToString().ToLowerInvariant().Contains('canceled')){break};throw}
  finally{$wait.Dispose()}
  if($x.MessageType -eq [System.Net.WebSockets.WebSocketMessageType]::Close){break}
  if($x.MessageType -ne [System.Net.WebSockets.WebSocketMessageType]::Text){continue}
  if(-not $x.EndOfMessage){throw 'fragmented_ws_payload'}
  $message=[System.Text.Encoding]::UTF8.GetString($buffer,0,$x.Count)
  $doc=$message|ConvertFrom-Json
  if($doc.op -eq 'subscribe' -and $doc.success -eq $true){$result.subscription_ack=$true}
  if($doc.topic -eq 'kline.1.BTCUSDT'){
    $result.captured_topic_count++
    $result.raw_frames+=([ordered]@{
      received_utc=[DateTimeOffset]::UtcNow.ToString('o')
      payload=$doc
    })
    foreach($bar in @($doc.data)){if($null -ne $bar -and $bar.confirm -is [bool] -and $bar.confirm -eq $true){$result.observed_confirm_true=$true}}
  }
 }
}catch{
 $result.error=($_.Exception.Message -replace '[\r\n]+',' ')
 if($result.error.Length -gt 300){$result.error=$result.error.Substring(0,300)}
}finally{if($null -ne $ws){try{$ws.Dispose()}catch{}}}
$result.finished_utc=[DateTimeOffset]::UtcNow.ToString('o')
$dir=Split-Path -Parent $Output
if(-not (Test-Path $dir)){New-Item -ItemType Directory -Path $dir -Force|Out-Null}
$result|ConvertTo-Json -Depth 15|Set-Content -LiteralPath $Output -Encoding UTF8 -NoNewline
$result|ConvertTo-Json -Depth 15
