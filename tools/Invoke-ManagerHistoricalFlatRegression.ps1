[CmdletBinding()]
param([string]$RepositoryRoot=(Join-Path $PSScriptRoot '..'))

$ErrorActionPreference='Stop'
Set-StrictMode -Version 2.0
$RepositoryRoot=[IO.Path]::GetFullPath($RepositoryRoot).TrimEnd('\')
$Utf8NoBom=New-Object Text.UTF8Encoding($false)

function Fail([string]$Message){throw $Message}
function Invoke-Proof([string]$Script,[string]$Purpose){
    $powershell=Join-Path $PSHOME 'powershell.exe'
    $old=$ErrorActionPreference
    try{
        $ErrorActionPreference='Continue'
        $output=@(& $powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $Script -RepositoryRoot $RepositoryRoot 2>&1)
        $code=[int]$LASTEXITCODE
    }finally{$ErrorActionPreference=$old}
    foreach($line in @($output)){Write-Host ([string]$line)}
    if($code-ne0){Fail($Purpose+' failed with exit '+$code+'.')}
}
function Assert-Parse([string]$Path){
    $tokens=$null;$errors=$null
    [void][Management.Automation.Language.Parser]::ParseFile($Path,[ref]$tokens,[ref]$errors)
    if(@($errors).Count-ne0){Fail('Flattened historical proof parser failed: '+$Path+'; '+([string]::Join(' | ',@($errors|ForEach-Object{$_.Message}))))}
}
function New-LeafCopy([string]$SourcePath,[string]$DestinationPath,[string]$EndToken,[string]$ExpectedReference){
    $lines=@([IO.File]::ReadAllLines($SourcePath,[Text.Encoding]::UTF8))
    $endMatches=New-Object System.Collections.ArrayList
    for($i=0;$i-lt$lines.Count;$i++){
        if(([string]$lines[$i]).Contains($EndToken)){[void]$endMatches.Add($i)}
    }
    if($endMatches.Count-ne1){Fail('Historical proof inherited-end marker count must be one: '+[IO.Path]::GetFileName($SourcePath)+' token='+$EndToken+' actual='+$endMatches.Count)}
    $end=[int]$endMatches[0]
    $startCandidates=New-Object System.Collections.ArrayList
    for($i=[Math]::Max(0,$end-8);$i-le$end;$i++){
        if(([string]$lines[$i])-match '^\$(?:p|powershell)=Join-Path \$PSHOME ''powershell\.exe'''){[void]$startCandidates.Add($i)}
    }
    if($startCandidates.Count-ne1){Fail('Historical proof inherited-start marker count must be one near end marker: '+[IO.Path]::GetFileName($SourcePath)+' actual='+$startCandidates.Count)}
    $start=[int]$startCandidates[0]
    if($start-gt$end){Fail('Historical proof inherited orchestration range is reversed: '+[IO.Path]::GetFileName($SourcePath))}
    $removed=[string]::Join("`n",@($lines[$start..$end]))
    if(-not$removed.Contains('-File')){Fail('Historical proof inherited orchestration range lacks child -File invocation: '+[IO.Path]::GetFileName($SourcePath))}
    if(-not$removed.Contains($ExpectedReference)){Fail('Historical proof inherited orchestration range does not bind expected predecessor reference '+$ExpectedReference+': '+[IO.Path]::GetFileName($SourcePath))}
    $kept=New-Object System.Collections.Generic.List[string]
    for($i=0;$i-lt$lines.Count;$i++){
        if($i-lt$start-or$i-gt$end){$kept.Add([string]$lines[$i])}
    }
    $text=[string]::Join("`r`n",$kept)+"`r`n"
    if($text.Contains($EndToken)){Fail('Historical proof inherited orchestration marker survived flattening: '+[IO.Path]::GetFileName($SourcePath))}
    [IO.File]::WriteAllText($DestinationPath,$text,$Utf8NoBom)
    Assert-Parse $DestinationPath
}

$specs=@(
    [pscustomobject]@{Path='tools/Invoke-Manager4172ReviewRegression.ps1';Mode='direct';End='';Reference=''},
    [pscustomobject]@{Path='tools/Invoke-Manager4173ReviewRegression.ps1';Mode='strip';End='PASS inherited Manager 4.17.2 review regressions';Reference='$legacyRegression'},
    [pscustomobject]@{Path='tools/Invoke-Manager4174ReviewRegression.ps1';Mode='strip';End='PASS inherited Manager 4.17.3 review regressions';Reference='$legacyRegression'},
    [pscustomobject]@{Path='tools/Invoke-Manager4174BootstrapRegression.ps1';Mode='direct';End='';Reference=''},
    [pscustomobject]@{Path='tools/Invoke-Manager4175ReviewRegression.ps1';Mode='strip';End='PASS inherited Manager 4.17.4 regressions';Reference='Invoke-Manager4174ReviewRegression.ps1'},
    [pscustomobject]@{Path='tools/Invoke-Manager4176ReviewRegression.ps1';Mode='strip';End='PASS inherited Manager 4.17.5 regression chain';Reference='Invoke-Manager4175ReviewRegression.ps1'},
    [pscustomobject]@{Path='tools/Invoke-Manager4177ReviewRegression.ps1';Mode='strip';End='PASS inherited Manager 4.17.6 regression chain';Reference='Invoke-Manager4176ReviewRegression.ps1'},
    [pscustomobject]@{Path='tools/Invoke-Manager4178ReviewRegression.ps1';Mode='strip';End='PASS inherited Manager 4.17.7 regression chain';Reference='Invoke-Manager4177ReviewRegression.ps1'},
    [pscustomobject]@{Path='tools/Invoke-Manager4179ConvergenceRegression.ps1';Mode='strip';End='PASS inherited Manager 4.17.8 regression chain';Reference='Invoke-Manager4178ReviewRegression.ps1'}
)

$temp=Join-Path ([IO.Path]::GetTempPath()) ('keelaryn-historical-flat-'+[guid]::NewGuid().ToString('N'))
[void][IO.Directory]::CreateDirectory($temp)
try{
    $seen=New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::Ordinal)
    foreach($spec in $specs){
        $relative=([string]$spec.Path).Replace('\','/')
        if(-not$seen.Add($relative)){Fail('Duplicate historical flat proof path: '+$relative)}
        $source=Join-Path $RepositoryRoot ($relative.Replace('/','\'))
        if(-not(Test-Path -LiteralPath $source -PathType Leaf)){Fail('Historical flat proof source missing: '+$relative)}
        if([string]$spec.Mode-ceq'direct'){
            Write-Host ('--- historical leaf direct :: '+$relative+' ---')
            Invoke-Proof $source $relative
        }elseif([string]$spec.Mode-ceq'strip'){
            $leaf=Join-Path $temp ([IO.Path]::GetFileName($source))
            New-LeafCopy $source $leaf ([string]$spec.End) ([string]$spec.Reference)
            Write-Host ('--- historical leaf flattened :: '+$relative+' ---')
            Invoke-Proof $leaf $relative
        }else{
            Fail('Unsupported historical flat proof mode: '+[string]$spec.Mode)
        }
    }
    Write-Host ('MANAGER HISTORICAL FLAT REGRESSION: PASS; unique_leaf_proofs='+$seen.Count) -ForegroundColor Green
}finally{
    if(Test-Path -LiteralPath $temp){Remove-Item -LiteralPath $temp -Recurse -Force -ErrorAction SilentlyContinue}
}
exit 0
