param(
    [string]$Distribution = 'Ubuntu',
    [string]$OutputPath = 'build\bybit-wsl-package-diagnostic\evidence.json',
    [string]$RunnerVersion = '2.336.0',
    [string]$RunnerSha256 = '04cf0be1aff4c3ec3554466c39124ca250e3effd8873bb7e8d68535aa9505d5d'
)

$ErrorActionPreference = 'Stop'
$wsl = Join-Path $env:SystemRoot 'System32\wsl.exe'
$packageName = "actions-runner-linux-x64-$RunnerVersion.tar.gz"
$packageUrl = "https://github.com/actions/runner/releases/download/v$RunnerVersion/$packageName"
$outputDir = Split-Path -Parent $OutputPath
if ($outputDir) {
    New-Item -ItemType Directory -Force -Path $outputDir | Out-Null
}

$probe = @"
archive='/tmp/$packageName'
extract_root='/tmp/nexus-runner-package-diagnostic'
rm -f -- "`$archive"
rm -rf -- "`$extract_root"
printf 'kernel='; uname -a
printf 'curl_path='; command -v curl || true
printf 'sha256sum_path='; command -v sha256sum || true
printf 'tar_path='; command -v tar || true
printf 'gzip_path='; command -v gzip || true
curl --version | head -n 2
printf 'download_url=%s\n' '$packageUrl'
curl --fail --location --retry 1 --connect-timeout 20 --max-time 240 --output "`$archive" '$packageUrl'
curl_exit=`$?
printf 'curl_exit=%s\n' "`$curl_exit"
if [ -f "`$archive" ]; then
  printf 'archive_bytes='; wc -c < "`$archive"
  printf 'archive_sha256='; sha256sum "`$archive" | awk '{print `$1}'
  printf '%s  %s\n' '$RunnerSha256' "`$archive" | sha256sum --check
  checksum_exit=`$?
  printf 'checksum_exit=%s\n' "`$checksum_exit"
  tar --list --gzip --file "`$archive" >/tmp/nexus-runner-package-list.txt 2>/tmp/nexus-runner-package-list.err
  list_exit=`$?
  printf 'tar_list_exit=%s\n' "`$list_exit"
  head -n 8 /tmp/nexus-runner-package-list.txt 2>/dev/null || true
  cat /tmp/nexus-runner-package-list.err 2>/dev/null || true
  mkdir -p "`$extract_root"
  tar --extract --gzip --file "`$archive" --directory "`$extract_root"
  extract_exit=`$?
  printf 'tar_extract_exit=%s\n' "`$extract_exit"
  if [ -d "`$extract_root" ]; then
    find "`$extract_root" -maxdepth 1 -type f -printf 'extracted_file=%f\n' 2>/dev/null | head -n 12 || true
  fi
else
  printf 'archive_present=false\n'
fi
rm -f -- "`$archive"
rm -rf -- "`$extract_root"
exit 0
"@

$previousErrorActionPreference = $ErrorActionPreference
try {
    # Windows PowerShell 5.1 can surface native stderr as NativeCommandError.
    # Capture merged native streams under Continue so the diagnostic itself
    # cannot terminate before $LASTEXITCODE and the output are recorded.
    $ErrorActionPreference = 'Continue'
    $raw = @(& $wsl -d $Distribution -u root -- bash -lc $probe 2>&1)
    $wslExitCode = $LASTEXITCODE
}
catch {
    $raw = @($_.Exception.ToString())
    $wslExitCode = -1
}
finally {
    $ErrorActionPreference = $previousErrorActionPreference
}

$text = (($raw | ForEach-Object { $_.ToString() }) | Out-String)
$text = ($text -replace "`0", '').Trim()
if ($text.Length -gt 12000) {
    $text = $text.Substring(0, 12000)
}

$evidence = [ordered]@{
    schema_version = 1
    generated_at_utc = [DateTime]::UtcNow.ToString('o')
    source_sha = $env:GITHUB_SHA
    run_id = $env:GITHUB_RUN_ID
    distribution = $Distribution
    runner_version = $RunnerVersion
    runner_package_url = $packageUrl
    expected_runner_package_sha256 = $RunnerSha256
    wsl_invocation_exit_code = if ($null -eq $wslExitCode) { -1 } else { [int]$wslExitCode }
    diagnostic_output = $text
    windows_runner_paths_modified = $false
    windows_runner_service_modified = $false
    automatic_restart_performed = $false
    firmware_setting_modified = $false
    bybit_private_credentials_used = $false
    github_registration_token_used = $false
    decision = 'PACKAGE_DIAGNOSTIC_CAPTURED'
}

$evidence | ConvertTo-Json -Depth 6 | Set-Content -Path $OutputPath -Encoding UTF8
Write-Host 'bybit_runner_package_diagnostic_decision=PACKAGE_DIAGNOSTIC_CAPTURED'
Write-Host "wsl_invocation_exit_code=$($evidence.wsl_invocation_exit_code)"
Write-Host "evidence_path=$OutputPath"
exit 0
