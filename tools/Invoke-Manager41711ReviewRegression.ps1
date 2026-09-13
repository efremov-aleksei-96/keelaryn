[CmdletBinding()]
param([string]$RepositoryRoot=(Join-Path $PSScriptRoot '..'))

$ErrorActionPreference='Stop'
Set-StrictMode -Version 2.0
$RepositoryRoot=[IO.Path]::GetFullPath($RepositoryRoot).TrimEnd('\')
$Utf8NoBom=New-Object Text.UTF8Encoding($false)
Add-Type -AssemblyName System.IO.Compression.FileSystem
Add-Type -AssemblyName System.IO.Compression

function Fail([string]$Message){throw $Message}
function Assert([bool]$Condition,[string]$Message){if(-not$Condition){Fail $Message}}
function Write-Utf8NoBom([string]$Path,[string]$Text){
    $parent=Split-Path -Parent $Path
    if($parent-and-not(Test-Path -LiteralPath $parent -PathType Container)){New-Item -ItemType Directory -Force -Path $parent|Out-Null}
    [IO.File]::WriteAllText($Path,$Text,$Utf8NoBom)
}
function Invoke-Captured([string]$Script,[string[]]$Arguments,[string]$Purpose){
    $exe=Join-Path $PSHOME 'powershell.exe'
    $old=$ErrorActionPreference
    try{
        $ErrorActionPreference='Continue'
        $output=@(& $exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $Script @Arguments 2>&1|ForEach-Object{[string]$_})
        $exit=[int]$LASTEXITCODE
    }finally{$ErrorActionPreference=$old}
    foreach($line in $output){Write-Host $line}
    if($exit-ne0){Fail($Purpose+' failed with exit='+$exit+'; output='+([string]::Join(' | ',$output)))}
    return @($output)
}
function Copy-ManagedManager([string]$SourceManager,[string]$DestinationManager){
    $install=Get-Content -LiteralPath (Join-Path $SourceManager 'product\install\INSTALLATION.json') -Raw -Encoding UTF8|ConvertFrom-Json
    Assert ([string]$install.schema-ceq'keelaryn.manager.installation.v2') 'Unsupported Manager installation schema in regression source.'
    Assert ([string]$install.manager_version-ceq'4.17.11') ('Regression requires Manager 4.17.11 source; observed '+[string]$install.manager_version)
    New-Item -ItemType Directory -Force -Path $DestinationManager|Out-Null
    foreach($raw in @($install.managed_files)){
        $rel=([string]$raw).Replace('/','\')
        $src=Join-Path $SourceManager $rel
        $dst=Join-Path $DestinationManager $rel
        if(-not(Test-Path -LiteralPath $src -PathType Leaf)){Fail('Managed regression source missing: '+$rel)}
        $parent=Split-Path -Parent $dst
        if(-not(Test-Path -LiteralPath $parent -PathType Container)){New-Item -ItemType Directory -Force -Path $parent|Out-Null}
        Copy-Item -LiteralPath $src -Destination $dst -Force
    }
}
function Get-TreeHash([string]$Root){
    $rows=New-Object Collections.Generic.List[string]
    foreach($file in @(Get-ChildItem -LiteralPath $Root -File -Recurse -Force|Sort-Object FullName)){
        $rel=$file.FullName.Substring($Root.Length).TrimStart('\').Replace('\','/')
        $hash=(Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        $rows.Add($rel+"`0"+$hash)
    }
    $sha=[Security.Cryptography.SHA256]::Create()
    try{$bytes=[Text.Encoding]::UTF8.GetBytes([string]::Join("`n",$rows));return ([BitConverter]::ToString($sha.ComputeHash($bytes))).Replace('-','').ToLowerInvariant()}finally{$sha.Dispose()}
}
function New-CandidateLikeZip([string]$Path){
    if(Test-Path -LiteralPath $Path){Remove-Item -LiteralPath $Path -Force}
    $stream=[IO.File]::Open($Path,[IO.FileMode]::CreateNew,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None)
    try{
        $archive=New-Object IO.Compression.ZipArchive($stream,[IO.Compression.ZipArchiveMode]::Create,$true)
        try{
            $entry=$archive.CreateEntry('regression-marker.txt',[IO.Compression.CompressionLevel]::Optimal)
            $writer=New-Object IO.StreamWriter($entry.Open(),$Utf8NoBom)
            try{$writer.Write('candidate-only active-instance inbox routing regression')}finally{$writer.Dispose()}
        }finally{$archive.Dispose()}
    }finally{$stream.Dispose()}
}
function Get-FunctionText([string]$Path,[string]$Name){
    $tokens=$null;$errors=$null
    $ast=[Management.Automation.Language.Parser]::ParseFile($Path,[ref]$tokens,[ref]$errors)
    if(@($errors).Count){Fail('Parser failed: '+([string]::Join(' | ',@($errors|ForEach-Object{$_.Message}))))}
    $fn=@($ast.FindAll({param($n)$n-is[Management.Automation.Language.FunctionDefinitionAst]},$true)|Where-Object{$_.Name-ceq$Name})
    if($fn.Count-ne1){Fail('Function '+$Name+' count='+$fn.Count)}
    return [string]$fn[0].Extent.Text
}

$inherited=Join-Path $RepositoryRoot 'tools\Invoke-Manager4179ConvergenceRegression.ps1'
$null=Invoke-Captured $inherited @('-RepositoryRoot',$RepositoryRoot) 'Inherited Manager 4.17.9 convergence regression'
Write-Host '  PASS inherited multi-Hub convergence regression chain'

$sourceManager=Join-Path $RepositoryRoot 'manager'
$tempRoot=Join-Path ([IO.Path]::GetTempPath()) ('keelaryn-manager-41711-review-'+[guid]::NewGuid().ToString('N'))
$keelarynRoot=Join-Path $tempRoot 'keelaryn'
$managerRoot=Join-Path $keelarynRoot 'manager'
$config=Join-Path $tempRoot 'genesis.json'
try{
    New-Item -ItemType Directory -Force -Path $keelarynRoot|Out-Null
    Copy-ManagedManager $sourceManager $managerRoot
    $runtime=Join-Path $managerRoot 'product\runtime\Keelaryn__Manager.ps1'

    $updateText=Get-FunctionText $runtime 'Invoke-Update'
    $pending=[regex]::Matches($updateText,'(?m)^\s*\$pendingCandidates=@\(Get-ChildItem -LiteralPath \$(?<inbox>\w+) -File -Filter ''\*\.zip''')
    Assert ($pending.Count-eq1) ('MGR-DEF-0024: Invoke-Update pendingCandidates inventory count='+$pending.Count)
    Assert ($pending[0].Groups['inbox'].Value-ceq'HubInbox') ('MGR-DEF-0024: Invoke-Update pendingCandidates still routes through $'+$pending[0].Groups['inbox'].Value)

    $genesis=[ordered]@{schema='keelaryn.genesis-input.v1';language='en';purpose='mixed';timezone='UTC';areas=@('Qualification');projects=@('Manager 4.17.11 registry CANDIDATE outcome')}
    Write-Utf8NoBom $config ((($genesis|ConvertTo-Json -Depth 6).Replace("`r`n","`n"))+"`n")
    $null=Invoke-Captured $runtime @('-Genesis','-GenesisConfigPath',$config,'-GenesisConfirmed') 'Disposable Genesis'
    $null=Invoke-Captured $runtime @('-InitializeInstanceRegistry','-RegisterInstanceName','Primary') 'Disposable registry activation'

    $activePath=Join-Path $managerRoot 'state\active_instance.json'
    Assert (Test-Path -LiteralPath $activePath -PathType Leaf) 'Registry activation did not publish active_instance.json.'
    $active=Get-Content -LiteralPath $activePath -Raw -Encoding UTF8|ConvertFrom-Json
    Assert ([string]$active.schema-ceq'keelaryn.manager.active-instance.v1') 'Unexpected active-instance schema.'
    $instanceId=([string]$active.instance_id).Trim().ToLowerInvariant()
    Assert ($instanceId-match'^[0-9a-f-]{36}$') ('Invalid active instance_id: '+$instanceId)
    $instanceInbox=Join-Path $managerRoot ('state\instances\'+$instanceId+'\inbox')
    Assert (Test-Path -LiteralPath $instanceInbox -PathType Container) 'Active instance inbox is missing.'
    $globalInbox=Join-Path $managerRoot 'state\inbox'
    Assert (Test-Path -LiteralPath $globalInbox -PathType Container) 'Manager-global inbox is missing.'

    $candidate=Join-Path $instanceInbox 'Keelaryn__Hub_CANDIDATE_regression.zip'
    New-CandidateLikeZip $candidate
    Assert (Test-Path -LiteralPath $candidate -PathType Leaf) 'Candidate-only regression input was not created.'
    Assert (@(Get-ChildItem -LiteralPath $globalInbox -File -Filter 'Keelaryn__Hub_CANDIDATE_*.zip' -ErrorAction SilentlyContinue).Count-eq0) 'Regression precondition violated: global inbox contains a CANDIDATE.'

    $hubRoot=Join-Path $keelarynRoot 'hub'
    Assert (Test-Path -LiteralPath $hubRoot -PathType Container) 'Disposable Hub missing before UpdateHub.'
    $before=Get-TreeHash $hubRoot
    $output=@(Invoke-Captured $runtime @('-UpdateHub','-ExpectedInstanceId',$instanceId) 'Registry-active CANDIDATE-only UpdateHub')
    $text=[string]::Join("`n",$output)
    $after=Get-TreeHash $hubRoot

    Assert ($before-ceq$after) 'CANDIDATE-only UpdateHub mutated disposable Hub bytes.'
    Assert (Test-Path -LiteralPath $candidate -PathType Leaf) 'CANDIDATE-only UpdateHub removed the pending instance input.'
    Assert ($text.Contains('1 CANDIDATE package(s) left pending for Chat Manager.')) ('MGR-DEF-0024: active-instance CANDIDATE was not surfaced. output='+$text)
    Assert (-not$text.Contains('No installable APPROVED Hub package found; Hub remains unchanged.')) 'MGR-DEF-0024: UpdateHub incorrectly emitted the green no-pending-CANDIDATE outcome.'
    Write-Host '  PASS A21 real registry-active UpdateHub surfaces CANDIDATE from active instance inbox and leaves Hub immutable' -ForegroundColor Green

    $doctor=@(Invoke-Captured $runtime @('-Doctor') 'Registry-active Doctor inheritance')
    $doctorText=[string]::Join("`n",$doctor)
    Assert $doctorText.Contains('Keelaryn Doctor - Manager 4.17.11') 'Inherited registry Doctor regression did not execute on 4.17.11.'
    Assert $doctorText.Contains('[OK] instances.registry:') 'Inherited registry Doctor regression lost registry diagnostics.'
    Write-Host '  PASS inherited registry-active Doctor path on 4.17.11' -ForegroundColor Green
}
finally{
    if(Test-Path -LiteralPath $tempRoot){Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue}
}

Write-Host 'MANAGER 4.17.11 REVIEW REGRESSION: PASS' -ForegroundColor Green
