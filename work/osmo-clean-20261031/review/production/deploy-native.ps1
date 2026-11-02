param([switch]$Execute)
$ErrorActionPreference = 'Stop'
$rumahStageRoot = $PSScriptRoot
$rumahWorkspace = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../../../..'))
$rumahPython = 'C:/Users/bombe/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe'
$rumahRemote = Join-Path $rumahWorkspace 'work/hosting/remote.py'
$rumahPackage = Join-Path $rumahStageRoot 'deployment'
if (-not $Execute) {
    Write-Output 'Prepared only. No remote connections or changes were made.'
    Write-Output 'After root approves the exact new release, package it with prepare-deploy.py --approval release-approval.json, then invoke this runner with -Execute.'
    exit 0
}
$rumahInfo = Get-Content -LiteralPath (Join-Path $rumahPackage 'deployment-manifest.json') -Raw | ConvertFrom-Json
foreach ($rumahTarget in @($rumahInfo.release, $rumahInfo.previous)) {
    if ($rumahTarget -notmatch '^/var/www/rumah/releases/20\d{6}-[a-z0-9-]+$') { throw 'Unsafe release path' }
}
if ($rumahInfo.staging -notmatch '^/var/lib/vz/rumah-deploy/20\d{6}-[a-z0-9-]+$' -or $rumahInfo.container -ne 710) { throw 'Unexpected deployment target' }
if ($rumahInfo.remote_archive -ne ($rumahInfo.staging + '/native-site-' + $rumahInfo.archive_sha256 + '.tar.partial')) { throw 'Unexpected upload path' }
foreach ($rumahFile in @(@('native-site.tar',$rumahInfo.archive_sha256), @('deploy-native.sh',$rumahInfo.runner_sha256), @('rollback-native.sh',$rumahInfo.rollback_sha256))) {
    if ((Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $rumahPackage $rumahFile[0])).Hash.ToLowerInvariant() -ne $rumahFile[1]) { throw 'Package changed after local review' }
}
function Invoke-RumahRemote([string[]]$RemoteArguments) {
    & $rumahPython $rumahRemote @RemoteArguments
    if ($LASTEXITCODE -ne 0) { throw 'Remote step failed. Inspect current release and receipt files before any rerun.' }
}
# This read-only guard runs before upload or mutation and refuses a stale baseline.
$rumahPreflight = "test `"`$(pct exec 710 -- readlink -f /var/www/rumah/current)`" = '$($rumahInfo.previous)' && pct exec 710 -- systemctl is-active nginx cloudflared && pct exec 710 -- nginx -t"
Invoke-RumahRemote @('--command',$rumahPreflight,'--limit','45')
$rumahStageCommand = "install -d -m 0700 '{0}'" -f $rumahInfo.staging
# Existing SFTP uses put -a (resume); create empty targets without truncating a partial upload.
foreach ($rumahUploadTarget in @($rumahInfo.remote_archive,($rumahInfo.staging + '/deploy-native.sh'),($rumahInfo.staging + '/rollback-native.sh'))) {
    $rumahStageCommand += " && test ! -L '{0}' && {{ test -f '{0}' || install -m 0600 /dev/null '{0}'; }}" -f $rumahUploadTarget
}
Invoke-RumahRemote @('--command',$rumahStageCommand,'--limit','45')
Invoke-RumahRemote @('--put',(Join-Path $rumahPackage 'native-site.tar'),$rumahInfo.remote_archive,'--limit','600')
foreach ($rumahScript in @('deploy-native.sh','rollback-native.sh')) {
    Invoke-RumahRemote @('--put',(Join-Path $rumahPackage $rumahScript),($rumahInfo.staging + '/' + $rumahScript),'--limit','60')
}
# Use --command intentionally: --script stops the remote run at --limit minus 5 s, too short here.
$rumahRun = "printf '%s\n' '{0}  {1}/deploy-native.sh' | sha256sum -c - && timeout -s TERM 180 bash '{1}/deploy-native.sh'" -f $rumahInfo.runner_sha256,$rumahInfo.staging
Invoke-RumahRemote @('--command',$rumahRun,'--limit','195')
& $rumahPython (Join-Path $rumahStageRoot 'verify-public-native.py')
if ($LASTEXITCODE -ne 0) {
    $rumahRollback = "printf '%s\n' '{0}  {1}/rollback-native.sh' | sha256sum -c - && timeout -s TERM 45 bash '{1}/rollback-native.sh'" -f $rumahInfo.rollback_sha256,$rumahInfo.staging
    Invoke-RumahRemote @('--command',$rumahRollback,'--limit','60')
    throw 'Public verification failed. Previous release was restored; review local evidence before retrying.'
}
Write-Output 'Atomic release and bounded public checks passed. Confirm the chooser in Chrome; physical phone verification remains separately reported.'
