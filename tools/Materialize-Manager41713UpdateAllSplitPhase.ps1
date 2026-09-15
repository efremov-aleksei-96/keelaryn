[CmdletBinding()]
param(
    [string]$RepositoryRoot='D:\0\0__Core\keelaryn'
)

$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest

$Branch='dev/manager-4.17.13'
$RepositoryFullName='efremov-aleksei-96/keelaryn'
$ExpectedBaseRuntimeBlob='f4b46f185ae51f1763980a8149d8388771cc1e4b'
$ExpectedProofHelperBlob='6bef1ce4fa918c14633a2cab7e4cdf130f42676e'
$ExpectedPatchedRuntimeSha256='4e34b45924de4f50b6c29cf2d9d90a9454f9278cd0c7ed682b67b4e2e368083f'
$ExpectedPatchedRuntimeBytes=576076L
$RuntimeRelative='manager/product/runtime/Keelaryn__Manager.ps1'
$ManifestRelative='PUBLIC_FILE_MANIFEST.json'
$ProofHelperRelative='tools/Apply-Manager41713UpdateAllSplitPhaseProofPatch.ps1'
$WorkRoot=Join-Path $RepositoryRoot 'tests\work\manager-4.17.13-mgr-def-0035-materialize'
$Succeeded=$false

function Fail([string]$Message){ throw $Message }
function Invoke-Git([string]$WorkingDirectory,[string[]]$Arguments,[switch]$AllowMany){
    $old=$ErrorActionPreference
    try{
        $ErrorActionPreference='Continue'
        $out=@(& git.exe -C $WorkingDirectory @Arguments 2>&1 | ForEach-Object {[string]$_})
        $code=[int]$LASTEXITCODE
    }finally{$ErrorActionPreference=$old}
    if($code-ne0){Fail('git '+($Arguments-join' ')+' failed: '+([string]::Join(' | ',$out)))}
    if(-not$AllowMany-and$out.Count-ne1){Fail('git '+($Arguments-join' ')+' returned '+$out.Count+' lines; expected exactly one.')}
    if($AllowMany){return @($out)}
    return ([string]$out[0]).Trim()
}
function Get-RemoteHead([string]$Repo,[string]$Remote,[string]$Ref){
    $rows=@(Invoke-Git $Repo @('ls-remote',$Remote,$Ref) -AllowMany)
    if($rows.Count-ne1-or$rows[0]-notmatch'^([0-9a-fA-F]{40})\s+'){
        Fail('Unable to resolve exact remote ref '+$Ref+'. Output: '+([string]::Join(' | ',$rows)))
    }
    return $Matches[1].ToLowerInvariant()
}
function Get-GitBlob([string]$Repo,[string]$Spec){
    $value=(Invoke-Git $Repo @('rev-parse','--verify',$Spec)).ToLowerInvariant()
    if($value-notmatch'^[0-9a-f]{40}$'){Fail('Invalid blob identity for '+$Spec+': '+$value)}
    return $value
}
function Get-Sha256([string]$Path){return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()}

$RepositoryRoot=[IO.Path]::GetFullPath($RepositoryRoot).TrimEnd('\')
if(-not(Test-Path -LiteralPath $RepositoryRoot -PathType Container)){Fail('Repository root missing: '+$RepositoryRoot)}
if(-not(Test-Path -LiteralPath (Join-Path $RepositoryRoot '.git'))){Fail('Repository root is not a Git checkout: '+$RepositoryRoot)}
$origin=Invoke-Git $RepositoryRoot @('remote','get-url','origin')
if($origin-notmatch'(?i)(?:github\.com[:/])efremov-aleksei-96/keelaryn(?:\.git)?$'){
    Fail('Unexpected origin URL: '+$origin)
}
if(Test-Path -LiteralPath $WorkRoot){Fail('Disposable materialization path already exists: '+$WorkRoot)}
$workParent=Split-Path -Parent $WorkRoot
if(-not(Test-Path -LiteralPath $workParent -PathType Container)){[void](New-Item -ItemType Directory -Force -Path $workParent)}

$remoteRef='refs/heads/'+$Branch
$remoteBefore=Get-RemoteHead $RepositoryRoot 'origin' $remoteRef
Write-Host ('Authoritative remote before: '+$remoteBefore)
Write-Host ('Cloning disposable materialization checkout: '+$WorkRoot)

try{
    $old=$ErrorActionPreference
    try{
        $ErrorActionPreference='Continue'
        $cloneOut=@(& git.exe clone --no-tags --single-branch --branch $Branch $origin $WorkRoot 2>&1 | ForEach-Object {[string]$_})
        $cloneCode=[int]$LASTEXITCODE
    }finally{$ErrorActionPreference=$old}
    if($cloneCode-ne0){Fail('Disposable clone failed: '+([string]::Join(' | ',$cloneOut)))}

    $head=(Invoke-Git $WorkRoot @('rev-parse','--verify','HEAD^{commit}')).ToLowerInvariant()
    if($head-cne$remoteBefore){Fail('Disposable clone HEAD drifted. expected='+$remoteBefore+' actual='+$head)}

    $runtimeBlob=Get-GitBlob $WorkRoot ('HEAD:'+$RuntimeRelative)
    if($runtimeBlob-cne$ExpectedBaseRuntimeBlob){Fail('Base runtime blob changed; refusing materialization. expected='+$ExpectedBaseRuntimeBlob+' actual='+$runtimeBlob)}
    $helperBlob=Get-GitBlob $WorkRoot ('HEAD:'+$ProofHelperRelative)
    if($helperBlob-cne$ExpectedProofHelperBlob){Fail('Proof helper blob changed; refusing materialization. expected='+$ExpectedProofHelperBlob+' actual='+$helperBlob)}

    $helper=Join-Path $WorkRoot $ProofHelperRelative.Replace('/','\')
    & powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $helper -RepositoryRoot $WorkRoot
    if($LASTEXITCODE-ne0){Fail('Exact proven proof helper failed; exit='+$LASTEXITCODE)}

    $runtime=Join-Path $WorkRoot $RuntimeRelative.Replace('/','\')
    $runtimeItem=Get-Item -LiteralPath $runtime -Force
    $runtimeSha=Get-Sha256 $runtime
    if([long]$runtimeItem.Length-ne$ExpectedPatchedRuntimeBytes){Fail('Patched runtime byte count mismatch. expected='+$ExpectedPatchedRuntimeBytes+' actual='+$runtimeItem.Length)}
    if($runtimeSha-cne$ExpectedPatchedRuntimeSha256){Fail('Patched runtime SHA-256 mismatch. expected='+$ExpectedPatchedRuntimeSha256+' actual='+$runtimeSha)}
    Write-Host ('Patched runtime identity: PASS; bytes='+$runtimeItem.Length+'; sha256='+$runtimeSha) -ForegroundColor Green

    $manifestBuilder=Join-Path $WorkRoot 'tools\Build-PublicFileManifest.ps1'
    & powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $manifestBuilder -RepositoryRoot $WorkRoot -Write
    if($LASTEXITCODE-ne0){Fail('PUBLIC_FILE_MANIFEST generation failed; exit='+$LASTEXITCODE)}
    & powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $manifestBuilder -RepositoryRoot $WorkRoot -Check
    if($LASTEXITCODE-ne0){Fail('PUBLIC_FILE_MANIFEST reproducibility check failed; exit='+$LASTEXITCODE)}

    $manifestPath=Join-Path $WorkRoot $ManifestRelative
    $manifest=Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8|ConvertFrom-Json
    $runtimeRow=@($manifest.manager.files|Where-Object{[string]$_.path-ceq'product/runtime/Keelaryn__Manager.ps1'})
    if($runtimeRow.Count-ne1){Fail('Generated manifest has no unique runtime row.')}
    if([long]$runtimeRow[0].size_bytes-ne$ExpectedPatchedRuntimeBytes-or[string]$runtimeRow[0].sha256-cne$ExpectedPatchedRuntimeSha256){Fail('Generated manifest runtime identity does not match proven runtime.')}
    $managedDigest=([string]$manifest.manager.gate_managed_content_sha256).ToLowerInvariant()
    if($managedDigest-notmatch'^[0-9a-f]{64}$'){Fail('Generated managed-content digest is invalid: '+$managedDigest)}

    $status=@(Invoke-Git $WorkRoot @('status','--porcelain=v1') -AllowMany)
    $changed=@($status|ForEach-Object{if($_.Length-ge4){$_.Substring(3).Replace('\','/')}else{''}}|Where-Object{$_})
    $expected=@($ManifestRelative,$RuntimeRelative)|Sort-Object
    $actual=@($changed|Sort-Object)
    if(([string]::Join('|',$actual))-cne([string]::Join('|',$expected))){Fail('Unexpected materialization diff set. expected='+($expected-join',')+' actual='+($actual-join','))}
    [void](Invoke-Git $WorkRoot @('diff','--check') -AllowMany)

    [void](Invoke-Git $WorkRoot @('add','--',$RuntimeRelative,$ManifestRelative) -AllowMany)
    $staged=@(Invoke-Git $WorkRoot @('diff','--cached','--name-only') -AllowMany|ForEach-Object{$_.Replace('\','/')}|Sort-Object)
    if(([string]::Join('|',$staged))-cne([string]::Join('|',$expected))){Fail('Unexpected staged diff set: '+($staged-join','))}

    $name=(Invoke-Git $RepositoryRoot @('config','user.name')).Trim()
    $email=(Invoke-Git $RepositoryRoot @('config','user.email')).Trim()
    if([string]::IsNullOrWhiteSpace($name)-or[string]::IsNullOrWhiteSpace($email)){Fail('Local Git user.name/user.email must already be configured; refusing to invent commit identity.')}
    [void](Invoke-Git $WorkRoot @('config','user.name',$name) -AllowMany)
    [void](Invoke-Git $WorkRoot @('config','user.email',$email) -AllowMany)

    [void](Invoke-Git $WorkRoot @('commit','-m','Manager 4.17.13: materialize token-bound UpdateAll split phase') -AllowMany)
    $commit=(Invoke-Git $WorkRoot @('rev-parse','--verify','HEAD^{commit}')).ToLowerInvariant()
    $tree=(Invoke-Git $WorkRoot @('rev-parse','--verify','HEAD^{tree}')).ToLowerInvariant()

    $remoteAtCommit=Get-RemoteHead $RepositoryRoot 'origin' $remoteRef
    if($remoteAtCommit-cne$remoteBefore){Fail('Authoritative remote advanced during materialization; refusing push. before='+$remoteBefore+' now='+$remoteAtCommit)}

    Write-Host ('Pushing non-force commit '+$commit+' to '+$Branch+' ...')
    [void](Invoke-Git $WorkRoot @('push','origin','HEAD:'+ $remoteRef) -AllowMany)
    $remoteAfter=Get-RemoteHead $RepositoryRoot 'origin' $remoteRef
    if($remoteAfter-cne$commit){Fail('Remote post-push identity mismatch. expected='+$commit+' actual='+$remoteAfter)}

    Write-Host ''
    Write-Host 'MGR-DEF-0035 MANAGED-BYTE MATERIALIZATION: PASS' -ForegroundColor Green
    Write-Host ('remote_before='+$remoteBefore)
    Write-Host ('commit='+$commit)
    Write-Host ('tree='+$tree)
    Write-Host ('runtime_sha256='+$runtimeSha)
    Write-Host ('runtime_bytes='+$runtimeItem.Length)
    Write-Host ('managed_content_sha256='+$managedDigest)
    Write-Host 'candidate_frozen=false'
    Write-Host 'production_mutated=false'
    $Succeeded=$true
}
finally{
    if($Succeeded-and(Test-Path -LiteralPath $WorkRoot)){
        Remove-Item -LiteralPath $WorkRoot -Recurse -Force
        Write-Host ('Disposable materialization checkout removed: '+$WorkRoot)
    }elseif(Test-Path -LiteralPath $WorkRoot){
        Write-Warning ('Materialization did not complete; disposable checkout retained for diagnosis: '+$WorkRoot)
    }
}
