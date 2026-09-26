[CmdletBinding()]
param(
  [Parameter(Mandatory=$true)][string]$BackupRoot,
  [Parameter(Mandatory=$true)][ValidatePattern('^[a-fA-F0-9]{64}$')][string]$ExpectedDataManifestSha256,
  [Parameter(Mandatory=$true)][ValidatePattern('^[a-fA-F0-9]{64}$')][string]$ExpectedShortcutManifestSha256,
  [Parameter(Mandatory=$true)][ValidatePattern('^[a-fA-F0-9]{64}$')][string]$ExpectedSyncManifestSha256
)
Set-StrictMode -Version 2
$ErrorActionPreference = 'Stop'
# Independent manifest digest check; NEVER an authorization or an activation.
if (-not (Test-Path -LiteralPath $BackupRoot -PathType Container)) { throw 'BACKUP_ROOT_MISSING' }
$root = [IO.Path]::GetFullPath($BackupRoot).TrimEnd('\')
if ((Get-Item -LiteralPath $root -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'BACKUP_ROOT_REPARSE_POINT' }
$pins = @(
  @{Name='product-data-sha256-manifest.json'; Expected=$ExpectedDataManifestSha256; ExpectedEntries=7},
  @{Name='shortcuts-manifest.json'; Expected=$ExpectedShortcutManifestSha256; ExpectedEntries=4},
  @{Name='global-paper-sync-manifest.json'; Expected=$ExpectedSyncManifestSha256; ExpectedEntries=2}
)
$observed = @{}
foreach ($pin in $pins) {
  $path = Join-Path $root $pin.Name
  if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw ('MANIFEST_MISSING_' + $pin.Name) }
  if ((Get-Item -LiteralPath $path -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'MANIFEST_REPARSE_POINT' }
  # Use intrinsic .NET SHA256 so the gate is independent of optional PowerShell cmdlet/module availability.
  $sha256 = [Security.Cryptography.SHA256]::Create()
  $stream = [IO.File]::OpenRead($path)
  try {
    $actual = [BitConverter]::ToString($sha256.ComputeHash($stream)).Replace('-', '').ToLowerInvariant()
  } finally {
    $stream.Dispose()
    $sha256.Dispose()
  }
  if ($actual -ne ([string]$pin.Expected).ToLowerInvariant()) { throw ('MANIFEST_PIN_MISMATCH_' + $pin.Name) }
  $items = Get-Content -LiteralPath $path -Raw | ConvertFrom-Json
  if (@($items).Count -ne $pin.ExpectedEntries) { throw ('MANIFEST_ENTRY_COUNT_MISMATCH_' + $pin.Name) }
  $observed[$pin.Name] = $actual
}
[ordered]@{
  schema='nexus.owner-backup-manifest-pins.v1'
  decision='MANIFEST_PIN_PASS_NOT_ACTIVATION'
  product_data_manifest_sha256=$observed['product-data-sha256-manifest.json']
  shortcut_manifest_sha256=$observed['shortcuts-manifest.json']
  global_sync_manifest_sha256=$observed['global-paper-sync-manifest.json']
  independent_source_for_expected_pins_verified=$false
  paired_bundle_preflight_required=$true
  rollback_tested=$false
  activation_authorized=$false
  owner_modified=$false
} | ConvertTo-Json -Depth 3
