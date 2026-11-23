$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
if($env:COMPUTERNAME -cne 'DESKTOP-1R1081M'){throw 'Wrong native probe host'}
$root='E:\NEXUS\NEXUS_OWNER_PAPER_PRIVATE'
$path=Join-Path $root 'ops_rollout_3c3461c4_fixed_20261123.ps1'
$errors=$null;$tokens=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($path,[ref]$tokens,[ref]$errors)
if($errors.Count){throw ('Corrected driver parse failed: '+($errors|Out-String))}
$defs=@($ast.FindAll({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -ceq 'Get-RolloutPinnedFileSha256'},$false))
if($defs.Count -ne 1){throw 'Hash function is not unique'}
# Import this pure hash function only. Never run the release driver in a probe.
Invoke-Expression $defs[0].Extent.Text
$command=Get-Command Get-RolloutPinnedFileSha256 -ErrorAction Stop
if($command.CommandType -ne 'Function'){throw 'Corrected hash command resolution failed'}
$journal='E:\NEXUS-Applications\profiles\lbank-research-e3f11c53\product-data\product_runtime\paper-events.jsonl'
$actualJournal=Get-RolloutPinnedFileSha256 $journal
$actualHelper=Get-RolloutPinnedFileSha256 (Join-Path $root 'activation-helper-26c35eed.ps1')
if($actualJournal -cne 'd7b5f4ffefa7ac14d21f51755c42659de72f8f3c0046c97e3a8b999e48310a98'){throw 'Original journal pin changed'}
if($actualHelper -cne '26c35eed16d56ecd93f67664c7412ab18f36a0adb434008e1bd434fdb1007086'){throw 'Frozen activation helper changed'}
$out=[ordered]@{decision='PASS_NATIVE_HASH_FUNCTION_AND_PARSE';host=$env:COMPUTERNAME;old_h_alias=(Get-Alias h).Definition;resolved_command=$command.Name;resolved_command_type=[string]$command.CommandType;driver_sha256=(Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant();original_journal_sha256=$actualJournal;activation_helper_sha256=$actualHelper;owner_profile_mutated=$false;created_utc=[DateTime]::UtcNow.ToString('o')}
$json=$out|ConvertTo-Json -Depth 4 -Compress
[IO.File]::WriteAllText((Join-Path $root 'preflight-fixed-driver-20261123.json'),$json,(New-Object Text.UTF8Encoding($false)))
Write-Output $json
