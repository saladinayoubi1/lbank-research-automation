param([Parameter(Mandatory=$true)][string]$ScriptPath)
$ErrorActionPreference = 'Stop'
$errors=$null; $tokens=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($ScriptPath,[ref]$tokens,[ref]$errors)
if ($errors.Count) { throw 'PowerShell parse errors' }
$function=$ast.Find({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Run-Watchdog'},$true)
. ([scriptblock]::Create($function.Extent.Text))
$stateRoot=Join-Path ([IO.Path]::GetTempPath()) ('nexus-cold-logon-test-'+[guid]::NewGuid())
$script:probes=0; $script:launches=0; $script:sleeps=0
function Get-WatchdogMutexName { return 'Local\NEXUS-Regression-'+[guid]::NewGuid() }
function Test-ExistingRegistration { throw 'WSL_NOT_READY_AT_LOGON' }
function Write-Log { param($Message) }
function Get-RunnerProcessState {
    $script:probes++
    return @{known=($script:probes -gt 1);worker=$false;listener=$false}
}
function Start-ManagedRunnerProcess { $script:launches++; return $null }
function Start-Sleep {
    param($Seconds)
    $script:sleeps++
    if ($script:sleeps -eq 1 -and $script:launches -ne 0) { throw 'unknown state launched runner' }
    if ($script:sleeps -ge 2) { throw 'TEST_COMPLETE' }
}
try {
    try { Run-Watchdog } catch { if ($_.Exception.Message -ne 'TEST_COMPLETE') { throw } }
    if ($script:probes -ne 2 -or $script:launches -ne 1) { throw 'watchdog did not retry after cold logon' }
    'PASS: unknown WSL state preserved; watchdog retried and reached guarded launch'
} finally { if(Test-Path $stateRoot) { Remove-Item $stateRoot -Recurse -Force } }
