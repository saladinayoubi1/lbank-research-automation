[CmdletBinding()]
param(
 [Parameter(Mandatory=$true)][string]$InputStageProof,
 [Parameter(Mandatory=$true)][ValidatePattern('^[a-f0-9]{64}$')][string]$ExpectedInputStageProofSha256
)
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
if($env:COMPUTERNAME -cne 'DESKTOP-1R1081M'){throw 'Wrong rollout host'}
$private='E:\NEXUS\NEXUS_OWNER_PAPER_PRIVATE'
$statusPath=Join-Path $private 'rollout-3c3461c4-fixed-20261123-status.json'
if(Test-Path -LiteralPath $statusPath){throw 'Existing rollout receipt: inspect before retry'}
$helper=Join-Path $private 'activation-helper-26c35eed.ps1'
$wrapper=Join-Path $private 'ops_private_clone_20261121.ps1'
$helperHash='26c35eed16d56ecd93f67664c7412ab18f36a0adb434008e1bd434fdb1007086'
$wrapperHash='2da011980c8f0fa0a846ad0df7d21dded6091fa09248c8278955854108e6efd7'
$source='3c3461c4e39801232b64f1016cc48edc0ae6b0c5'
$candidate='C:\Users\afaq\AppData\Local\Programs\NEXUS Personal Pro\5.1.0-3c3461c4'
$owner='E:\NEXUS-Applications\profiles\lbank-research-e3f11c53'
$journal=Join-Path $owner 'product-data\product_runtime\paper-events.jsonl'
$journalHash='d7b5f4ffefa7ac14d21f51755c42659de72f8f3c0046c97e3a8b999e48310a98'
$innerHash='c777deafe75154f163ef0eed19e1526c051e40d6a3817cdf007d39305a2b478d'
$stageInput=[IO.Path]::GetFullPath($InputStageProof)
$stageProof=Join-Path $private 'official-stage-3c3461c4-45183878518-attempt2.json'
$cloneProof=Join-Path $private 'private-clone-3c3461c4-20261123-v2.json'
$rehearsalProof=Join-Path $private 'device-rehearsal-3c3461c4-20261123-v2.json'
$zip='C:\Users\afaq\AppData\Local\NEXUS\artifact-cache\nexus-windows-persistent-unpacked-14715106625\NEXUS_Personal_Pro_Unpacked_5.1.0_x64.zip'
function Get-RolloutPinnedFileSha256([string]$p){(Get-FileHash -LiteralPath $p -Algorithm SHA256).Hash.ToLowerInvariant()}
function Require([bool]$ok,[string]$message){if(!$ok){throw $message}}
function ReadJson([string]$p){[IO.File]::ReadAllText($p)|ConvertFrom-Json}
function SaveStatus([string]$phase,[string]$decision,[string]$errorText=''){
 $out=[ordered]@{source_sha=$source;phase=$phase;status=$decision;updated_utc=[DateTime]::UtcNow.ToString('o');error=$errorText;owner_profile=$owner;candidate_install_root=$candidate;stage_proof=$stageProof;clone_proof=$cloneProof;rehearsal_proof=$rehearsalProof;owner_journal_unchanged=((Test-Path -LiteralPath $journal) -and (Get-RolloutPinnedFileSha256 $journal) -ceq $journalHash);paper_only=$true;live_trading_authority=$false}
 $temp=$statusPath+'.tmp';[IO.File]::WriteAllText($temp,($out|ConvertTo-Json -Depth 5),(New-Object Text.UTF8Encoding($false)));Move-Item -LiteralPath $temp -Destination $statusPath -Force
}
$phase='PRECHECK'
try{
 Require ((Split-Path -Parent $stageInput).Equals($private,[StringComparison]::OrdinalIgnoreCase) -and (Split-Path -Leaf $stageInput) -ceq ('captured-stage-3c3461c4-45183878518-attempt2-'+$ExpectedInputStageProofSha256+'.json')) 'Actual captured stage input path is not bound'
 Require ((Get-RolloutPinnedFileSha256 $stageInput) -ceq $ExpectedInputStageProofSha256) 'Actual captured stage input hash changed'
 Require (!(Test-Path -LiteralPath (Join-Path $private 'rollout-3c3461c4-status.json'))) 'An earlier owner protocol receipt requires inspection'
 Require ((Get-RolloutPinnedFileSha256 $helper) -ceq $helperHash -and (Get-RolloutPinnedFileSha256 $wrapper) -ceq $wrapperHash) 'Frozen rollout helper changed'
 Require ((Get-RolloutPinnedFileSha256 $journal) -ceq $journalHash) 'Original financial journal changed; refusing cutover'
 foreach($p in @($stageProof,$cloneProof,$rehearsalProof)){Require (!(Test-Path -LiteralPath $p)) 'Proof exists; inspect prior rollout before any new action'}
 $a=ReadJson $stageInput
 Require ($a.decision -ceq 'PASS' -and $a.source_sha -ceq $source -and [long]$a.artifact_id -eq 14715106625 -and [long]$a.artifact_run_id -eq 44924381327 -and $a.package.unpacked_sha256 -ceq $innerHash -and $a.final_launch.status -ceq 'STAGED_ONLY_OWNER_PRESERVED' -and $a.final_launch.activation_requested -eq $false) 'Official stage proof is not accepted'
 Copy-Item -LiteralPath $stageInput -Destination $stageProof
 Require ((Get-RolloutPinnedFileSha256 $stageInput) -ceq (Get-RolloutPinnedFileSha256 $stageProof)) 'Stage proof changed during private capture'
 $stageHash=Get-RolloutPinnedFileSha256 $stageProof
 SaveStatus $phase 'RUNNING'
 $cloneParams=@{TransactionScript=$helper;ExpectedTransactionSha256=$helperHash;ExpectedSourceSha=$source;CandidateInstallRoot=$candidate;StageProof=$stageProof;ExpectedStageProofSha256=$stageHash;ExpectedArtifactId=14715106625;ExpectedArtifactRunId=44924381327;ExpectedUnpackedSha256=$innerHash;ProofPath=$cloneProof;VerifiedUnpackedZip=$zip;JournalPython='C:\Users\afaq\AppData\Local\Programs\Python\Python312\python.exe'}
 $phase='PRIVATE_CLONE';SaveStatus $phase 'RUNNING'
 & $wrapper @cloneParams *> (Join-Path $private 'private-clone-3c3461c4.log')
 Require ((ReadJson $cloneProof).decision -ceq 'PASS_NO_OWNER_ACTIVATION') 'Private clone did not pass'
 $cloneHash=Get-RolloutPinnedFileSha256 $cloneProof
 $transactionParams=@{AccountSurface='DeviceJournal';ExpectedSourceSha=$source;CandidateInstallRoot=$candidate;PriorInstallRoot='E:\NEXUS-Applications\5.1.0-demo-v2-1d8b7f08';PriorSourceSha='1d8b7f08c11ce1b55f3b1f9432899d81ab62b28d';OwnerProfileRoot=$owner;ExpectedJournalSha256=$journalHash;ExpectedArtifactId=14715106625;ExpectedArtifactRunId=44924381327;ExpectedUnpackedSha256=$innerHash;StageProof=$stageProof;ExpectedStageProofSha256=$stageHash;CloneProof=$cloneProof;ExpectedCloneProofSha256=$cloneHash;PrivateRoot=$private;RehearsalProof=$rehearsalProof;JournalPython='C:\Users\afaq\AppData\Local\Programs\Python\Python312\python.exe'}
 $phase='PHYSICAL_REHEARSAL';SaveStatus $phase 'RUNNING'
 # The production script exits on completion, so isolate each Mode invocation in its own native process.
 $invokePath=Join-Path $private 'invoke-device-3c3461c4.ps1'
 $parameterPath=Join-Path $private 'device-3c3461c4-parameters.json'
 [IO.File]::WriteAllText($parameterPath,($transactionParams|ConvertTo-Json -Depth 5),(New-Object Text.UTF8Encoding($false)))
 $invoke=@'
param([ValidateSet('Rehearse','Preflight','Activate')][string]$Step)
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
$h='E:\NEXUS\NEXUS_OWNER_PAPER_PRIVATE\activation-helper-26c35eed.ps1'
if((Get-FileHash -LiteralPath $h -Algorithm SHA256).Hash.ToLowerInvariant() -cne '26c35eed16d56ecd93f67664c7412ab18f36a0adb434008e1bd434fdb1007086'){throw 'Helper changed'}
$o=[IO.File]::ReadAllText('E:\NEXUS\NEXUS_OWNER_PAPER_PRIVATE\device-3c3461c4-parameters.json')|ConvertFrom-Json
$p=@{};foreach($property in $o.PSObject.Properties){$p[$property.Name]=$property.Value}
& $h -Mode $Step @p
'@
 [IO.File]::WriteAllText($invokePath,$invoke,(New-Object Text.UTF8Encoding($false)))
 & powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $invokePath -Step Rehearse *> (Join-Path $private 'device-rehearsal-3c3461c4.log')
 Require ($LASTEXITCODE -eq 0 -and (ReadJson $rehearsalProof).decision -ceq 'PASS_DEVICE_JOURNAL_REHEARSAL') 'Physical rehearsal failed'
 $transactionParams.ExpectedRehearsalProofSha256=Get-RolloutPinnedFileSha256 $rehearsalProof
 [IO.File]::WriteAllText($parameterPath,($transactionParams|ConvertTo-Json -Depth 5),(New-Object Text.UTF8Encoding($false)))
 $phase='READ_ONLY_PREFLIGHT';SaveStatus $phase 'RUNNING'
 & powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $invokePath -Step Preflight *> (Join-Path $private 'device-preflight-3c3461c4.log')
 Require ($LASTEXITCODE -eq 0) 'Original-profile preflight failed'
 $phase='TRANSACTIONAL_ACTIVATION';SaveStatus $phase 'RUNNING'
 & powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $invokePath -Step Activate *> (Join-Path $private 'device-activation-3c3461c4.log')
 Require ($LASTEXITCODE -eq 0) 'Transactional cutover failed; inspect its recovery receipt'
 Require ((Get-RolloutPinnedFileSha256 $journal) -ceq $journalHash) 'Post-cutover journal changed'
 SaveStatus 'POST_ACTIVATION' 'ACTIVATED_PENDING_VISUAL_CHECKS'
}catch{SaveStatus $phase 'FAILED_CLOSED' $_.Exception.Message;throw}

