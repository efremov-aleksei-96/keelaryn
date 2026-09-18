Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$Runner = Join-Path $PSScriptRoot 'run_migration_disposable_read_only_finalizer.py'
if (-not (Test-Path -LiteralPath $Runner -PathType Leaf)) {
    throw 'Disposable migration read-only finalizer is missing.'
}

$Python = Get-Command python -CommandType Application -ErrorAction Stop |
    Select-Object -First 1

$StartInfo = New-Object System.Diagnostics.ProcessStartInfo
$StartInfo.FileName = $Python.Source
$StartInfo.Arguments = '-B "' + $Runner.Replace('"', '\"') + '"'
$StartInfo.UseShellExecute = $false
$StartInfo.RedirectStandardOutput = $true
$StartInfo.RedirectStandardError = $false
$StartInfo.CreateNoWindow = $false

$Process = New-Object System.Diagnostics.Process
$Process.StartInfo = $StartInfo

try {
    if (-not $Process.Start()) {
        throw 'Failed to start disposable migration read-only finalizer.'
    }

    # stdout is only the final compact sanitized PASS JSON. stderr is inherited
    # so progress/failure JSON remains visible without buffering.
    $Stdout = $Process.StandardOutput.ReadToEnd()
    $Process.WaitForExit()

    if ($Stdout.Length -gt 0) {
        [Console]::Out.Write($Stdout)
    }

    exit $Process.ExitCode
}
finally {
    $Process.Dispose()
}
