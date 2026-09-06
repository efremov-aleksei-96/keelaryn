[CmdletBinding()]
param([string]$RepositoryRoot=(Join-Path $PSScriptRoot '..'))
$ErrorActionPreference='Stop'
$RepositoryRoot=[System.IO.Path]::GetFullPath($RepositoryRoot).TrimEnd('\')
$original=Join-Path $RepositoryRoot '.github\Verify-PublicRepository-original.ps1'
$target=Join-Path $RepositoryRoot 'tools\Verify-PublicRepository.ps1'
if(-not(Test-Path -LiteralPath $original -PathType Leaf)){throw('Temporary original verifier missing: '+$original)}
$temp=Join-Path ([System.IO.Path]::GetTempPath()) ('keelaryn_verify_public_'+[guid]::NewGuid().ToString('N')+'.ps1')
try{
    Copy-Item -LiteralPath $original -Destination $temp -Force
    Copy-Item -LiteralPath $original -Destination $target -Force
    Remove-Item -LiteralPath $original -Force
    $generatedState=Join-Path $RepositoryRoot 'manager\state'
    if(Test-Path -LiteralPath $generatedState){
        $layout=Join-Path $generatedState 'layout.json'
        if(-not(Test-Path -LiteralPath $layout -PathType Leaf)){throw('Refusing to clean unclassified Manager state during source bootstrap: '+$generatedState)}
        $unexpected=@(Get-ChildItem -LiteralPath $generatedState -File -Recurse -Force -ErrorAction Stop|Where-Object{$_.FullName -ne $layout})
        if($unexpected.Count-ne0){throw('Refusing to clean Manager state containing unexpected files: '+(($unexpected|ForEach-Object{$_.FullName})-join', '))}
        Remove-Item -LiteralPath $generatedState -Recurse -Force -ErrorAction Stop
        Write-Host 'Removed bootstrap-generated source-checkout Manager state before public verification.' -ForegroundColor DarkGray
    }
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $temp -RepositoryRoot $RepositoryRoot
    exit [int]$LASTEXITCODE
}
finally{
    if(Test-Path -LiteralPath $temp){Remove-Item -LiteralPath $temp -Force -ErrorAction SilentlyContinue}
}
