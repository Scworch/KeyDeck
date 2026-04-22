$repoRootLong = Split-Path -Parent $MyInvocation.MyCommand.Path

$fso = New-Object -ComObject Scripting.FileSystemObject
$repoRootShort = $fso.GetFolder($repoRootLong).ShortPath

$targetPathShort = Join-Path $repoRootShort "run_keydeck.cmd"
$shortcutPathShort = Join-Path $repoRootShort "KeyDeck.lnk"

if (-not (Test-Path $targetPathShort)) {
    throw "run_keydeck.cmd not found: $targetPathShort"
}

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPathShort)
$shortcut.TargetPath = $targetPathShort
$shortcut.WorkingDirectory = $repoRootShort
$shortcut.WindowStyle = 1
$shortcut.Description = "Launch KeyDeck via project virtual environment"
$shortcut.Save()

$shortcutPathLong = Join-Path $repoRootLong "KeyDeck.lnk"
Write-Host "Shortcut created: $shortcutPathLong"
