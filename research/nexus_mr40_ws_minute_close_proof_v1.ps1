# NEXUS MR40 public Spot WS 1m CONFIRM proof; single bounded read-only run.
# Absolutely no private APIs, orders, trading signals, daemon or schedules.
param([Parameter(Mandatory=$true)][string]$Protocol,
      [Parameter(Mandatory=$true)][string]$Output)
$ErrorActionPreference='Stop'
if(Test-Path -LiteralPath $Output){throw 'refuse_overwrite_preexisting_proof'}
$p=Get-Content -LiteralPath $Protocol -Raw | ConvertFrom-Json
if($p.schema -ne 'nexus.mr40.public_spot_ws_minute_close_proof.v1' -or
   $p.url -ne 'wss://stream.bybit.com/v5/public/spot' -or
   $p.subscription.args[0] -ne 'kline.1.BTCUSDT' -or
   $p.time_budget_seconds -ne 95 -or
   $p.constraints.orders -ne 0 -or $p.constraints.live -ne $false){
    throw 'locked_proof_protocol_invalid'
}
$r=[ordered]@{
 schema='nexus.mr40.public_spot_minute_confirmation_one_shot.results.v1'
 protocol_sha256=(Get-FileHash $Protocol -Algorithm SHA256).Hash.ToLowerInvariant()
 start_utc=[DateTimeOffset]::UtcNow.ToString('o')
 finish_utc=$null
 endpoint=[string]$p.url
 topic='kline.1.BTCUSDT'
 handshake_ok=$false
 subscribe_ack=$false
 received_topic_frames=0
 confirmed_valid_minute_count=0
 invalid_frame_count=0
 confirmations=@()
 observed_unconfirmed_count=0
 first_unconfirmed=@()
 bybit_fourhour_bar_confirmed=$false
 fourhour_history_gap_repaired=$false
 must_never_feed_MR40=$true
 paper_changed=$false
 orders=0
 private_api=$false
 live_enabled=$false
 error_kind=$null
 error_text=$null
}
$ws=$null
try{
 $ws=[System.Net.WebSockets.ClientWebSocket]::new()
 $connectCts=[System.Threading.CancellationTokenSource]::new([TimeSpan]::FromSeconds(8))
 try{[void]$ws.ConnectAsync([Uri]$p.url,$connectCts.Token).GetAwaiter().GetResult()}
 finally{$connectCts.Dispose()}
 if($ws.State -ne [System.Net.WebSockets.WebSocketState]::Open){throw 'public_ws_handshake_failed'}
 $r.handshake_ok=$true
 $pay=[System.Text.Encoding]::UTF8.GetBytes('{"op":"subscribe","args":["kline.1.BTCUSDT"]}')
 $sendCts=[System.Threading.CancellationTokenSource]::new([TimeSpan]::FromSeconds(5))
 try{[void]$ws.SendAsync([ArraySegment[byte]]::new($pay),[System.Net.WebSockets.WebSocketMessageType]::Text,$true,$sendCts.Token).GetAwaiter().GetResult()}
 finally{$sendCts.Dispose()}
 $deadline=[DateTimeOffset]::UtcNow.AddSeconds(95)
 while([DateTimeOffset]::UtcNow -lt $deadline -and $r.received_topic_frames -lt 24 -and $r.confirmed_valid_minute_count -eq 0){
     $remain=($deadline-[DateTimeOffset]::UtcNow).TotalSeconds
     if($remain -le 0){break}
     $buff=New-Object byte[] 65536
     $recvCts=[System.Threading.CancellationTokenSource]::new([TimeSpan]::FromSeconds([Math]::Max(1,[Math]::Min(10,$remain))))
     try{
         $resp=$ws.ReceiveAsync([ArraySegment[byte]]::new($buff),$recvCts.Token).GetAwaiter().GetResult()
     }catch [System.OperationCanceledException] {
         if([DateTimeOffset]::UtcNow -lt $deadline -and $ws.State -eq [System.Net.WebSockets.WebSocketState]::Open){continue}
         break
     }catch{
         if($_.Exception.ToString().Contains('canceled') -and $r.received_topic_frames -gt 0){break}
         throw
     }finally{$recvCts.Dispose()}
     if($resp.MessageType -eq [System.Net.WebSockets.WebSocketMessageType]::Close){break}
     if($resp.MessageType -ne [System.Net.WebSockets.WebSocketMessageType]::Text){continue}
     if(-not $resp.EndOfMessage){throw 'fragmented_ws_payload_fails_closed'}
     $txt=[System.Text.Encoding]::UTF8.GetString($buff,0,$resp.Count)
     $obj=$txt|ConvertFrom-Json
     if($obj.op -eq 'subscribe'){
         if($obj.success -eq $true){$r.subscribe_ack=$true}
         elseif($obj.success -eq $false){throw 'spot_one_minute_subscription_rejected'}
     }
     if($obj.topic -ne 'kline.1.BTCUSDT'){continue}
     $r.received_topic_frames++
     foreach($bar in @($obj.data)){
         if($null -eq $bar){continue}
         if($bar.confirm -isnot [bool] -or [string]$bar.interval -ne '1'){throw 'invalid_confirm_or_interval'}
         $start=[long]$bar.start
         $end=[long]$bar.end
         $ms=[long]$obj.ts
         $traded=[long]$bar.timestamp
         $received=[DateTimeOffset]::UtcNow
         $vals=@([decimal]::Parse([string]$bar.open,[System.Globalization.CultureInfo]::InvariantCulture),
                 [decimal]::Parse([string]$bar.high,[System.Globalization.CultureInfo]::InvariantCulture),
                 [decimal]::Parse([string]$bar.low,[System.Globalization.CultureInfo]::InvariantCulture),
                 [decimal]::Parse([string]$bar.close,[System.Globalization.CultureInfo]::InvariantCulture),
                 [decimal]::Parse([string]$bar.volume,[System.Globalization.CultureInfo]::InvariantCulture))
         if($start -le 0 -or $start%60000 -ne 0 -or $end -ne $start+59999 -or
           $ms -lt $start -or $traded -lt $start -or $traded -gt $end -or
           $vals[0] -le 0 -or $vals[1] -le 0 -or $vals[2] -le 0 -or $vals[3] -le 0 -or $vals[4] -lt 0 -or
           $vals[1] -lt [Math]::Max($vals[0],$vals[3]) -or $vals[2] -gt [Math]::Min($vals[0],$vals[3])){
             throw 'invalid_public_spot_minute_market_payload'
         }
         $snapshot=[ordered]@{
           received_utc=$received.ToString('o')
           topic=$obj.topic
           bybit_message_ms=$ms
           last_trade_ms=$traded
           start_ms=$start
           end_ms=$end
           open=[string]$bar.open;high=[string]$bar.high;low=[string]$bar.low;close=[string]$bar.close;volume=[string]$bar.volume
           confirmed=[bool]$bar.confirm
         }
         if($bar.confirm -eq $true){
             if($ms -lt $start+60000 -or $received.ToUnixTimeMilliseconds() -lt $start+60000){throw 'premature_confirm_true'}
             if(-not $r.subscribe_ack){throw 'confirmed_data_without_subscription_ack'}
             $r.confirmations+= $snapshot
             $r.confirmed_valid_minute_count++
         }else{
             $r.observed_unconfirmed_count++
             if($r.first_unconfirmed.Count -lt 3){$r.first_unconfirmed+= $snapshot}
         }
     }
 }
}catch{
 $r.error_kind=$_.Exception.GetType().Name
 $r.error_text=($_.Exception.Message -replace '[\r\n]+',' ')
 if($r.error_text.Length -gt 450){$r.error_text=$r.error_text.Substring(0,450)}
}finally{
 if($null -ne $ws){try{$ws.Dispose()}catch{}}
}
$r.finish_utc=[DateTimeOffset]::UtcNow.ToString('o')
$dir=Split-Path -Parent $Output
if(-not (Test-Path $dir)){New-Item -ItemType Directory -Path $dir -Force|Out-Null}
$r|ConvertTo-Json -Depth 10|Set-Content -LiteralPath $Output -Encoding UTF8 -NoNewline
$r|ConvertTo-Json -Depth 10
