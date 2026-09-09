[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$ManagerRoot)

$ErrorActionPreference='Stop'
if($PSVersionTable.PSVersion.Major-ne5-or[string]$PSVersionTable.PSEdition-ne'Desktop'){
    throw 'Run this gate with Windows PowerShell 5.1 Desktop.'
}
Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem

$ManagerRoot=[System.IO.Path]::GetFullPath($ManagerRoot).TrimEnd('\')
$gateSupportRoot=Join-Path $ManagerRoot 'gate'
$specPath=Join-Path $gateSupportRoot 'GATE_SPEC.json'
if(-not(Test-Path -LiteralPath $specPath -PathType Leaf)){throw('Gate spec missing: '+$specPath)}
$gateSpec=(Get-Content -LiteralPath $specPath -Raw -Encoding UTF8)|ConvertFrom-Json
if([string]$gateSpec.schema-ne'keelaryn.manager-gate-spec.v1'-or[string]$gateSpec.framework_version-ne'2.0'){throw('Unsupported gate spec/framework: '+[string]$gateSpec.schema+' / '+[string]$gateSpec.framework_version)}
$frameworkRevision=[int]$gateSpec.framework_revision
$frameworkRevisionPath=Join-Path $gateSupportRoot 'FRAMEWORK_REVISION.txt'
$frameworkRevisionMarker=0
if($frameworkRevision-lt1-or-not(Test-Path -LiteralPath $frameworkRevisionPath -PathType Leaf)-or-not[int]::TryParse((Get-Content -LiteralPath $frameworkRevisionPath -Raw -Encoding UTF8).Trim(),[ref]$frameworkRevisionMarker)-or$frameworkRevisionMarker-ne$frameworkRevision){throw 'Framework revision marker/spec mismatch.'}
$version=[string]$gateSpec.candidate_version
if([string]::IsNullOrWhiteSpace($version)){throw 'Gate spec candidate_version is empty.'}
$workRoot=Split-Path $ManagerRoot -Parent
$testsRoot=Split-Path $workRoot -Parent
$expectedLeaf='manager-'+$version
if((Split-Path $workRoot -Leaf)-ine'work'-or
   (Split-Path $testsRoot -Leaf)-ine'tests'-or
   (Split-Path $ManagerRoot -Leaf)-ine$expectedLeaf){
    throw('ManagerRoot must be exactly under keelaryn\tests\work\'+$expectedLeaf+': '+$ManagerRoot)
}

$exe=Join-Path $PSHOME 'powershell.exe'
$entryPath=Join-Path $ManagerRoot 'Keelaryn__Manager.ps1'
$scriptPath=Join-Path $ManagerRoot 'product\runtime\Keelaryn__Manager.ps1'
$manifestPath=Join-Path $ManagerRoot 'product\install\INSTALLATION.json'
$transitionManifestPath=Join-Path $ManagerRoot '_manager_manifest.json'
$versionPath=Join-Path $ManagerRoot '_manager_version.txt'

function Sha([string]$Path){
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function TextSha([string]$Text){
    $enc=New-Object System.Text.UTF8Encoding($false);$sha=[System.Security.Cryptography.SHA256]::Create()
    try{return [BitConverter]::ToString($sha.ComputeHash($enc.GetBytes($Text))).Replace('-','').ToLowerInvariant()}finally{$sha.Dispose()}
}

$resultsRoot=Join-Path $testsRoot ('results\manager-'+$version)
$commandLogRoot=Join-Path $resultsRoot 'command_logs\source'
New-Item -ItemType Directory -Force -Path $commandLogRoot|Out-Null
$script:CommandSequence=0

function Quote-ProcessArg([string]$Value){
    if($null-eq$Value){return '""'}
    if($Value.Length-gt0-and$Value-notmatch'[\s"]'){return $Value}
    $sb=New-Object System.Text.StringBuilder
    [void]$sb.Append('"')
    $slashes=0
    foreach($ch in $Value.ToCharArray()){
        if($ch-eq'\'){$slashes++;continue}
        if($ch-eq'"'){
            if($slashes-gt0){[void]$sb.Append(('\'*(2*$slashes)))}
            [void]$sb.Append('\"')
            $slashes=0
            continue
        }
        if($slashes-gt0){[void]$sb.Append(('\'*$slashes));$slashes=0}
        [void]$sb.Append($ch)
    }
    if($slashes-gt0){[void]$sb.Append(('\'*(2*$slashes)))}
    [void]$sb.Append('"')
    return $sb.ToString()
}

function Invoke-SafeProcess(
    [string]$FilePath,
    [string[]]$ProcessArgs,
    [string]$Label,
    [int]$TimeoutSeconds=180,
    [bool]$Show=$true
){
    $script:CommandSequence++
    $safeLabel=($Label-replace'[^A-Za-z0-9_.-]','_')
    $labelHash=(TextSha $Label).Substring(0,12)
    if($safeLabel.Length-gt80){$safeLabel=$safeLabel.Substring(0,80)}
    $prefix=('{0:D3}_{1}_{2}'-f$script:CommandSequence,$safeLabel,$labelHash)
    $stdout=Join-Path $commandLogRoot ($prefix+'.stdout.txt')
    $stderr=Join-Path $commandLogRoot ($prefix+'.stderr.txt')
    $specPath=Join-Path $commandLogRoot ($prefix+'.spec.json')
    $exitCodePath=Join-Path $commandLogRoot ($prefix+'.exitcode.txt')
    Remove-Item -LiteralPath $stdout,$stderr,$specPath,$exitCodePath -Force -ErrorAction SilentlyContinue

    $spec=[ordered]@{
        file_path=$FilePath
        arguments=@($ProcessArgs|ForEach-Object{[string]$_})
        exit_code_path=$exitCodePath
    }
    [System.IO.File]::WriteAllText($specPath,($spec|ConvertTo-Json -Depth 4),(New-Object System.Text.UTF8Encoding($false)))

    $runner=Join-Path $gateSupportRoot 'Invoke-KeelarynGateChild.ps1'
    if(-not(Test-Path -LiteralPath $runner -PathType Leaf)){throw('Gate child runner missing: '+$runner)}

    $runnerArgs=@('-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',$runner,'-SpecPath',$specPath)
    $argLine=[string]::Join(' ',@($runnerArgs|ForEach-Object{Quote-ProcessArg ([string]$_)}))
    Write-Host ('  RUN {0} (timeout {1}s)' -f$Label,$TimeoutSeconds) -ForegroundColor DarkGray

    $p=Start-Process -FilePath $exe -ArgumentList $argLine -PassThru -WindowStyle Hidden -RedirectStandardOutput $stdout -RedirectStandardError $stderr
    $sw=[System.Diagnostics.Stopwatch]::StartNew()
    $nextNotice=15
    try{
        while(-not$p.HasExited){
            Start-Sleep -Milliseconds 200
            if($sw.Elapsed.TotalSeconds-ge$TimeoutSeconds){
                try{& (Join-Path $env:SystemRoot 'System32\taskkill.exe') /PID $p.Id /T /F 2>$null|Out-Null}catch{}
                try{[void]$p.WaitForExit(3000)}catch{}
                throw('TIMEOUT: '+$Label+' exceeded '+$TimeoutSeconds+'s; pid='+$p.Id+'; stdout='+$stdout+'; stderr='+$stderr)
            }
            if($sw.Elapsed.TotalSeconds-ge$nextNotice){
                $lastLine=$null
                if(Test-Path -LiteralPath $stdout){
                    try{$lastLine=Get-Content -LiteralPath $stdout -Tail 1 -ErrorAction SilentlyContinue}catch{}
                }
                if($lastLine){
                    Write-Host ('    still running: {0} ({1:N0}s); last: {2}' -f$Label,$sw.Elapsed.TotalSeconds,[string]$lastLine) -ForegroundColor DarkGray
                }else{
                    Write-Host ('    still running: {0} ({1:N0}s)' -f$Label,$sw.Elapsed.TotalSeconds) -ForegroundColor DarkGray
                }
                $nextNotice+=15
            }
        }
        if(-not$p.WaitForExit(3000)){throw('Process exit finalization timeout: '+$Label+'; pid='+$p.Id)}
    }finally{
        $sw.Stop()
    }

    if(-not(Test-Path -LiteralPath $exitCodePath -PathType Leaf)){
        throw('Exit-code sidecar missing for '+$Label+'; pid='+$p.Id+'; stdout='+$stdout+'; stderr='+$stderr)
    }
    $exitText=(Get-Content -LiteralPath $exitCodePath -Raw -Encoding UTF8).Trim()
    $exitCode=0
    if(-not[int]::TryParse($exitText,[ref]$exitCode)){
        throw('Invalid exit-code sidecar for '+$Label+': '+$exitText+'; path='+$exitCodePath)
    }

    $outText=if(Test-Path -LiteralPath $stdout){[System.IO.File]::ReadAllText($stdout)}else{''}
    $errText=if(Test-Path -LiteralPath $stderr){[System.IO.File]::ReadAllText($stderr)}else{''}
    if($Show){
        if($outText){Write-Host $outText.TrimEnd([char[]]"`r`n")}
        if($errText){Write-Host $errText.TrimEnd([char[]]"`r`n") -ForegroundColor Yellow}
    }
    Write-Host ('  DONE {0}: exit={1}; {2:N1}s' -f$Label,$exitCode,$sw.Elapsed.TotalSeconds) -ForegroundColor DarkGray
    return [pscustomobject]@{ExitCode=$exitCode;Text=($outText+$errText);StdOut=$outText;StdErr=$errText;StdOutPath=$stdout;StdErrPath=$stderr;ExitCodePath=$exitCodePath;Seconds=$sw.Elapsed.TotalSeconds}
}

function Get-ManagerTimeout([string[]]$ManagerArgs){
    if($ManagerArgs.Count-gt0){
        switch([string]$ManagerArgs[0]){
            '-BuildRelease'{return 600}
            '-BuildAIContext'{return 300}
            '-UpdateManager'{return 300}
            '-Doctor'{return 300}
        }
    }
    return 180
}

function Invoke-ManagerAt([string]$Root,[string[]]$ManagerArgs,[bool]$Show=$true,[string]$LabelPrefix='Manager'){
    $runtimePath=Join-Path $Root 'product\runtime\Keelaryn__Manager.ps1'
    if(-not(Test-Path -LiteralPath $runtimePath -PathType Leaf)){throw('Manager runtime missing: '+$runtimePath)}
    $childArgs=@('-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',$runtimePath)+@($ManagerArgs)
    $r=Invoke-SafeProcess $exe $childArgs ($LabelPrefix+' '+($ManagerArgs-join' ')) (Get-ManagerTimeout $ManagerArgs) $Show
    if($r.ExitCode-ne0){$detail=if($r.StdErr){[string]$r.StdErr}else{[string]$r.StdOut};$detail=$detail.Trim();if($detail.Length-gt1200){$detail=$detail.Substring($detail.Length-1200)};throw($LabelPrefix+' command failed: '+($ManagerArgs-join' ')+'; exit='+$r.ExitCode+'; detail='+$detail+'; stdout='+$r.StdOutPath+'; stderr='+$r.StdErrPath)}
    return $r
}

function Invoke-Manager([string[]]$ManagerArgs,[bool]$Show=$true){
    return Invoke-ManagerAt $ManagerRoot $ManagerArgs $Show 'Manager'
}

function Invoke-Tool([string]$Path,[string[]]$ToolArgs){
    $childArgs=@('-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',$Path)+@($ToolArgs)
    $r=Invoke-SafeProcess $exe $childArgs ('Tool '+[System.IO.Path]::GetFileName($Path)+' '+($ToolArgs-join' ')) 180 $true
    if($r.ExitCode-ne0){throw('Tool failed: '+$Path+'; exit='+$r.ExitCode+'; stderr='+$r.StdErrPath)}
    return $r
}

function Invoke-ToolCapture([string]$Path,[string[]]$ToolArgs){
    $childArgs=@('-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',$Path)+@($ToolArgs)
    return Invoke-SafeProcess $exe $childArgs ('ToolCapture '+[System.IO.Path]::GetFileName($Path)+' '+($ToolArgs-join' ')) 180 $false
}

function Read-Release([string]$Base,[string]$VersionText){
    $mp=Join-Path $Base ('Keelaryn__Manager_RELEASE_v'+$VersionText+'.json')
    if(-not(Test-Path -LiteralPath $mp -PathType Leaf)){throw('Release manifest missing: '+$mp)}
    $m=(Get-Content -LiteralPath $mp -Raw -Encoding UTF8)|ConvertFrom-Json
    if([string]$m.schema-ne'keelaryn.manager.release-bundle.v1'-or[string]$m.manager_version-ne$VersionText){
        throw('Release manifest invalid: '+$mp)
    }
    $arts=@($m.artifacts)
    if($arts.Count-ne4){throw('Expected modern four-artifact release: '+$VersionText)}
    foreach($role in @('source','distribution','update','ai_context')){
        $rows=@($arts|Where-Object{[string]$_.role-eq$role})
        if($rows.Count-ne1){throw('Release role mismatch: '+$role)}
        $p=Join-Path $Base ([string]$rows[0].path)
        if(-not(Test-Path -LiteralPath $p -PathType Leaf)){throw('Release artifact missing: '+$p)}
        if((Sha $p)-ne([string]$rows[0].sha256).ToLowerInvariant()){throw('Release artifact hash mismatch: '+$role)}
    }
    return $m
}

function Release-Hashes([string]$Base,$Release){
    $h=[ordered]@{}
    foreach($a in @($Release.artifacts)){
        $h[[string]$a.role]=Sha (Join-Path $Base ([string]$a.path))
    }
    $h['manifest']=Sha (Join-Path $Base ('Keelaryn__Manager_RELEASE_v'+[string]$Release.manager_version+'.json'))
    return $h
}

function Get-ZipEntryHashMap([string]$ZipPath){
    $map=@{};$za=[System.IO.Compression.ZipFile]::OpenRead($ZipPath)
    try{
        foreach($entry in @($za.Entries|Where-Object{-not$_.FullName.EndsWith('/')})){
            $name=$entry.FullName.Replace('\','/')
            if($map.ContainsKey($name)){throw('Duplicate ZIP entry while comparing deterministic artifacts: '+$name)}
            $stream=$entry.Open();$sha=[System.Security.Cryptography.SHA256]::Create()
            try{$hash=[BitConverter]::ToString($sha.ComputeHash($stream)).Replace('-','').ToLowerInvariant()}finally{$sha.Dispose();$stream.Dispose()}
            $map[$name]=$hash
        }
    }finally{$za.Dispose()}
    return $map
}

function Compare-ZipEntries([string]$Left,[string]$Right){
    $a=Get-ZipEntryHashMap $Left;$b=Get-ZipEntryHashMap $Right
    $keys=@(Get-OrdinalUniqueStrings @(@($a.Keys)+@($b.Keys)))
    $diff=New-Object System.Collections.ArrayList
    foreach($k in $keys){
        $ah=if($a.ContainsKey($k)){[string]$a[$k]}else{$null}
        $bh=if($b.ContainsKey($k)){[string]$b[$k]}else{$null}
        if($ah-ne$bh){
            $kind=if($null-eq$ah){'added'}elseif($null-eq$bh){'removed'}else{'changed'}
            [void]$diff.Add([pscustomobject]@{path=$k;kind=$kind;left=$ah;right=$bh})
        }
    }
    return @($diff)
}

function Get-ReleaseArtifactPath([string]$Base,$Release,[string]$Role){
    $rows=@($Release.artifacts|Where-Object{[string]$_.role-eq$Role})
    if($rows.Count-ne1){throw('Release role missing while comparing deterministic artifacts: '+$Role)}
    return (Join-Path $Base ([string]$rows[0].path))
}

function Assert-DeterministicRelease([string]$BaseA,$ReleaseA,[string]$BaseB,$ReleaseB){
    foreach($role in @('source','distribution','update','ai_context')){
        $left=Get-ReleaseArtifactPath $BaseA $ReleaseA $role
        $right=Get-ReleaseArtifactPath $BaseB $ReleaseB $role
        $leftSha=Sha $left;$rightSha=Sha $right
        if($leftSha-ne$rightSha){
            $diff=@(Compare-ZipEntries $left $right)
            if($diff.Count-eq0){
                throw('Deterministic BUILD_RELEASE container hash changed but ZIP entry names/content are identical: '+$role+'; left='+$leftSha+'; right='+$rightSha)
            }
            $preview=@($diff|Select-Object -First 8|ForEach-Object{([string]$_.kind)+':'+([string]$_.path)})
            throw('Deterministic BUILD_RELEASE content changed: '+$role+'; differing_entries='+$diff.Count+'; first='+([string]::Join(', ',@($preview))))
        }
    }
    $manifestA=Join-Path $BaseA ('Keelaryn__Manager_RELEASE_v'+[string]$ReleaseA.manager_version+'.json')
    $manifestB=Join-Path $BaseB ('Keelaryn__Manager_RELEASE_v'+[string]$ReleaseB.manager_version+'.json')
    if((Sha $manifestA)-ne(Sha $manifestB)){throw 'Deterministic BUILD_RELEASE release manifest changed despite identical artifact ZIPs.'}
}

function Get-OrdinalUniqueStrings([object[]]$Values){
    $list=New-Object 'System.Collections.Generic.List[string]'
    foreach($raw in @($Values)){if($null-ne$raw){[void]$list.Add([string]$raw)}}
    $list.Sort([System.StringComparer]::Ordinal)
    $out=New-Object System.Collections.ArrayList
    $haveLast=$false;$last=''
    foreach($item in $list){
        if ((-not $haveLast) -or (-not [string]::Equals($last,$item,[System.StringComparison]::Ordinal))) {
            [void]$out.Add($item);$last=$item;$haveLast=$true
        }
    }
    return @($out)
}

Write-Host 'Gate A: parser / ASCII / managed-set / SelfTests' -ForegroundColor Cyan
foreach($p in @($entryPath,$scriptPath,$manifestPath,$versionPath)){
    if(-not(Test-Path -LiteralPath $p -PathType Leaf)){throw('Missing candidate source: '+$p)}
}
if((Get-Content -LiteralPath $versionPath -Raw -Encoding UTF8).Trim()-ne$version){throw 'Candidate version mismatch.'}
$manifest=(Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8)|ConvertFrom-Json
if([string]$manifest.manager_version-ne$version){throw 'Canonical installation manifest version mismatch.'}
if([string]$manifest.schema-ne'keelaryn.manager.installation.v2'-or[int]$manifest.layout_version-ne2){throw 'Canonical installation manifest schema/layout mismatch.'}
if(@($manifest.managed_files).Count-lt1){throw 'Canonical installation manifest has no managed files.'}
$transitionManifest=(Get-Content -LiteralPath $transitionManifestPath -Raw -Encoding UTF8)|ConvertFrom-Json
if([string]$transitionManifest.schema-ne'keelaryn.manager.installation.v1'-or[string]$transitionManifest.manager_version-ne$version){throw 'Transition installation manifest schema/version mismatch.'}
$transitionOnly=@('Keelaryn__Manager.ps1','_manager_manifest.json','_manager_version.txt')
function Get-UpdateTransportCompatibilityContract {
    param([string[]]$FinalPaths,[string[]]$TransitionOnly,$ReleasePolicy)

    $normalize={
        param([string]$Value,[string]$Label)
        $path=([string]$Value).Replace('\','/').Trim()
        if([string]::IsNullOrWhiteSpace($path)-or$path.StartsWith('/')-or$path-match'^[A-Za-z]:'){
            throw($Label+' must be a relative Manager path: '+$path)
        }
        $segments=@($path.Split('/'))
        if($segments.Count-eq0){throw($Label+' is empty.')}
        foreach($segment in $segments){
            if([string]::IsNullOrWhiteSpace($segment)-or$segment-eq'.'-or$segment-eq'..'){
                throw($Label+' contains an unsafe path segment: '+$path)
            }
            if($segment.EndsWith('.')-or$segment.EndsWith(' ')-or$segment.IndexOfAny([char[]]'<>:"|?*')-ge0){
                throw($Label+' contains a Windows-unsafe path segment: '+$path)
            }
            foreach($ch in $segment.ToCharArray()){if([int]$ch-lt32){throw($Label+' contains a control character: '+$path)}}
        }
        return [pscustomobject]@{
            Path=$path
            Key=$path.Normalize([System.Text.NormalizationForm]::FormC).ToLowerInvariant()
        }
    }
    $sortUnique={
        param([string[]]$Values,[string]$Label)
        $seen=New-Object 'System.Collections.Generic.HashSet[string]' ([System.StringComparer]::Ordinal)
        $items=New-Object System.Collections.ArrayList
        foreach($value in @($Values)){
            $v=[string]$value
            if(-not$seen.Add($v)){throw($Label+' contains an exact duplicate path: '+$v)}
            [void]$items.Add($v)
        }
        [string[]]$ordered=@($items)
        [Array]::Sort($ordered,[System.StringComparer]::Ordinal)
        return @($ordered)
    }

    $finalMap=@{};$finalCanonical=New-Object System.Collections.ArrayList
    foreach($raw in @($FinalPaths)){
        $n=&$normalize ([string]$raw) 'final managed path'
        if($finalMap.ContainsKey($n.Key)){throw('Final managed paths collide by Windows/Unicode identity: '+$n.Path)}
        $finalMap[$n.Key]=$n.Path;[void]$finalCanonical.Add($n.Path)
    }
    $transitionMap=@{};$transitionCanonical=New-Object System.Collections.ArrayList
    foreach($raw in @($TransitionOnly)){
        $n=&$normalize ([string]$raw) 'transition compatibility path'
        if($finalMap.ContainsKey($n.Key)-or$transitionMap.ContainsKey($n.Key)){throw('Transition compatibility path collides with another transport path: '+$n.Path)}
        $transitionMap[$n.Key]=$n.Path;[void]$transitionCanonical.Add($n.Path)
    }

    $aliasRows=New-Object System.Collections.ArrayList
    $aliasMap=@{}
    $declaredAliases=@()
    if($null-ne$ReleasePolicy-and$null-ne$ReleasePolicy.PSObject.Properties['transition_compatibility_aliases']){
        $declaredAliases=@($ReleasePolicy.transition_compatibility_aliases)
    }
    foreach($row in $declaredAliases){
        if($null-eq$row-or$null-eq$row.PSObject.Properties['path']-or$null-eq$row.PSObject.Properties['source_path']){
            throw 'Transition compatibility alias must declare path and source_path.'
        }
        $alias=&$normalize ([string]$row.path) 'transition alias path'
        $source=&$normalize ([string]$row.source_path) 'transition alias source_path'
        if($finalMap.ContainsKey($alias.Key)-or$transitionMap.ContainsKey($alias.Key)){throw('Transition alias collides with canonical/transition path: '+$alias.Path)}
        if($aliasMap.ContainsKey($alias.Key)){throw('Duplicate transition alias path: '+$alias.Path)}
        if(-not$finalMap.ContainsKey($source.Key)){throw('Transition alias source_path is not a canonical final managed path: '+$source.Path)}
        $aliasMap[$alias.Key]=$alias.Path
        [void]$aliasRows.Add([pscustomobject]@{
            Path=$alias.Path
            SourcePath=[string]$finalMap[$source.Key]
        })
    }

    $expected=@($finalCanonical)+@($transitionCanonical)+@($aliasRows|ForEach-Object{[string]$_.Path})
    $ordered=&$sortUnique ([string[]]$expected) 'expected UPDATE transport'
    return [pscustomobject]@{
        ExpectedPackagePaths=@($ordered)
        Aliases=@($aliasRows|Sort-Object Path)
    }
}

$finalPaths=@(Get-OrdinalUniqueStrings @($manifest.managed_files|ForEach-Object{([string]$_).Replace('\','/')}))
$transitionPaths=@(Get-OrdinalUniqueStrings @($transitionManifest.managed_files|ForEach-Object{([string]$_).Replace('\','/')}))
$expectedTransition=@(Get-OrdinalUniqueStrings @($finalPaths+$transitionOnly))
if($transitionPaths.Count-ne$expectedTransition.Count-or[string]::Join('|',$transitionPaths)-cne[string]::Join('|',$expectedTransition)){throw 'Transition installation manifest is not exactly final managed files plus the three compatibility transport paths.'}
$releasePolicyPath=Join-Path $ManagerRoot 'product\manager_release.json'
if(-not(Test-Path -LiteralPath $releasePolicyPath -PathType Leaf)){throw 'Manager release policy is missing from candidate source.'}
$releasePolicy=(Get-Content -LiteralPath $releasePolicyPath -Raw -Encoding UTF8)|ConvertFrom-Json
$updateTransportContract=Get-UpdateTransportCompatibilityContract -FinalPaths $finalPaths -TransitionOnly $transitionOnly -ReleasePolicy $releasePolicy
$expectedUpdateTransport=@($updateTransportContract.ExpectedPackagePaths)
$updateAliases=@($updateTransportContract.Aliases)

foreach($legacyRoot in $transitionOnly){if($finalPaths-contains$legacyRoot){throw('Canonical final manifest contains transition-only root path: '+$legacyRoot)}}
foreach($legacyRoot in $transitionOnly){if(-not(Test-Path -LiteralPath (Join-Path $ManagerRoot $legacyRoot) -PathType Leaf)){throw('Transition envelope file missing from gate source: '+$legacyRoot)}}
$declaredInstallSha=([string]$gateSpec.candidate_installation_sha256).ToLowerInvariant();$declaredManagedSha=([string]$gateSpec.candidate_managed_content_sha256).ToLowerInvariant()
if($declaredInstallSha-notmatch'^[0-9a-f]{64}$'-or$declaredManagedSha-notmatch'^[0-9a-f]{64}$'){throw 'Gate spec candidate hash binding is missing or invalid.'}
if((Sha $manifestPath)-ne$declaredInstallSha){throw 'Gate spec installation-manifest hash does not match source candidate.'}
$managedRows=New-Object System.Collections.ArrayList
foreach($rel in $finalPaths){$p=Join-Path $ManagerRoot $rel.Replace('/','\');if(-not(Test-Path -LiteralPath $p -PathType Leaf)){throw('Managed candidate file missing: '+$rel)};[void]$managedRows.Add($rel+"`0"+(Sha $p))}
if((TextSha([string]::Join("`n",@($managedRows))))-ne$declaredManagedSha){throw 'Gate spec managed-content hash does not match source candidate.'}
if([int]$gateSpec.final_managed_count-ne$finalPaths.Count){throw 'Gate spec final_managed_count does not match source candidate.'}

$asciiEncoding=[System.Text.Encoding]::GetEncoding(28591)
$lexicalPatterns=[ordered]@{
    'return glue'='\bret'+'urn[$@[]'
    'throw glue'='\bthr'+'ow[$@[]'
    'exit glue'='\bex'+'it[$@[]'
    'break glue'='\bbre'+'ak[$@[]'
    'continue glue'='\bcont'+'inue[$@[]'
    'boolean operator glue'='\)-and-not\('
}
$managedRows=@($manifest.managed_files)
$managedDone=0
foreach($rel in $managedRows){
    $p=Join-Path $ManagerRoot ([string]$rel).Replace('/','\')
    if(-not(Test-Path -LiteralPath $p -PathType Leaf)){throw('Managed file missing: '+$rel)}
    $ext=[System.IO.Path]::GetExtension([string]$rel)
    if($ext-ieq'.ps1'-or$ext-ieq'.cmd'){
        $bytes=[System.IO.File]::ReadAllBytes($p)
        $source=$asciiEncoding.GetString($bytes)
        if($source-match'[^\x00-\x7F]'){throw('Non-ASCII managed executable source: '+$rel)}
        if($ext-ieq'.ps1'){
            $tokens=$null;$errors=$null
            [void][System.Management.Automation.Language.Parser]::ParseInput($source,[ref]$tokens,[ref]$errors)
            if(@($errors).Count-ne0){throw('Parser failure in '+$rel+': '+((@($errors)|ForEach-Object{$_.Message})-join'; '))}
            foreach($rule in @($lexicalPatterns.GetEnumerator())){
                if($source-match[string]$rule.Value){throw('Lexical source-contract failure in '+$rel+': '+[string]$rule.Key)}
            }
        }
    }
    $managedDone++
    if($managedDone-eq1-or($managedDone%10)-eq0-or$managedDone-eq$managedRows.Count){
        Write-Host ('  static {0}/{1}: {2}' -f $managedDone,$managedRows.Count,$rel) -ForegroundColor DarkGray
    }
}
foreach($rel in @('Keelaryn__Manager.ps1')){
    $p=Join-Path $ManagerRoot $rel
    $bytes=[System.IO.File]::ReadAllBytes($p)
    $source=$asciiEncoding.GetString($bytes)
    if($source-match'[^\x00-\x7F]'){throw('Non-ASCII transition executable source: '+$rel)}
    $tokens=$null;$errors=$null
    [void][System.Management.Automation.Language.Parser]::ParseInput($source,[ref]$tokens,[ref]$errors)
    if(@($errors).Count-ne0){throw('Parser failure in transition source '+$rel+': '+((@($errors)|ForEach-Object{$_.Message})-join'; '))}
}
Write-Host 'Gate A static parser / ASCII / final-managed + transition-envelope PASS.' -ForegroundColor Green
foreach($required in @(
    'KEELARYN.cmd',
    'product/runtime/Keelaryn__Manager.ps1',
    'product/install/INSTALLATION.json',
    'compat/commands/DOCTOR.cmd',
    'product/tools/KeelarynMenu.ps1',
    'product/tools/Unpack-KeelarynTestArchive.ps1',
    'product/docs/USER_INTERFACE.md',
    'product/docs/REPOSITORY_MODEL.md'
)){
    if(@($manifest.managed_files)-notcontains$required){throw('Final managed file missing from manifest: '+$required)}
}
$launcher=[System.IO.File]::ReadAllText((Join-Path $ManagerRoot 'KEELARYN.cmd'),[System.Text.Encoding]::ASCII)
if($launcher-notmatch'(?i)product\\tools\\KeelarynMenu\.ps1'){throw 'KEELARYN.cmd does not delegate to the canonical frontend tool.'}
if($launcher-notmatch'(?im)^title\s+Keelaryn Manager\s*$'){throw 'KEELARYN.cmd does not set a readable console title.'}
$menuText=[System.IO.File]::ReadAllText((Join-Path $ManagerRoot 'product\tools\KeelarynMenu.ps1'),[System.Text.Encoding]::UTF8)
foreach($token in @('[Console]::WriteLine','[Console]::ReadLine','function Show-MainMenuScreen','''RenderMain''')){
    if(-not$menuText.Contains($token)){throw('Direct console frontend contract missing token: '+$token)}
}
if($menuText-match'(?m)^\s*Clear-Host\b'){throw 'Frontend still depends on Clear-Host for menu rendering.'}
$archiveToolText=[System.IO.File]::ReadAllText((Join-Path $ManagerRoot 'product\tools\Unpack-KeelarynTestArchive.ps1'),[System.Text.Encoding]::UTF8)
if(-not$archiveToolText.Contains('[Console]::WriteLine')){throw 'Integrated archive tool does not use direct console output.'}
$runtimeText=[System.IO.File]::ReadAllText($scriptPath,[System.Text.Encoding]::UTF8)
foreach($token in @('revision_time_utc','RevisionTimeUtc','function Test-RevisionTimestampParserSelfTest','Create the canonical initial Hub revision? [y/N]','ToLocalTime().ToString(''yyyy-MM-dd HH:mm'')',' | revision ')){
    if(-not$runtimeText.Contains($token)){throw('Hub revision timestamp compatibility contract missing token: '+$token)}
}
foreach($docRel in @('product/governance/hub/_System/PROTOCOL.md','product/governance/hub/_System/CHAT_MANAGER.md','product/starter/hub/Resources/Prompts/WORKER_CHAT.md')){
    $docText=[System.IO.File]::ReadAllText((Join-Path $ManagerRoot $docRel.Replace('/','\')),[System.Text.Encoding]::UTF8)
    if(-not$docText.Contains('revision_time_utc')-or-not$docText.Contains('data_revision')){throw('Hub revision governance contract missing in '+$docRel)}
}
$entryText=[System.IO.File]::ReadAllText($entryPath,[System.Text.Encoding]::UTF8)
if($entryText.Length-gt4096){throw 'Root Keelaryn__Manager.ps1 bootstrap is unexpectedly large; canonical runtime did not migrate physically.'}
$rootVersionMatch=[regex]::Match($entryText,'(?m)^\$ManagerVersion\s*=\s*"([^"]+)"\s*$')
if(-not$rootVersionMatch.Success-or[string]$rootVersionMatch.Groups[1].Value-ne$version){throw('Root Manager bootstrap version mismatch: expected '+$version+'.')}
foreach($token in @('product\runtime\Keelaryn__Manager.ps1','@args')){if(-not$entryText.Contains($token)){throw('Root Manager bootstrap contract missing token: '+$token)}}
foreach($required in @('product/runtime/Keelaryn__Manager.ps1')){if(@($manifest.managed_files)-notcontains$required){throw('Physical runtime managed path missing: '+$required)}}
$compatNames=@('APPLY_MIGRATIONS.cmd','BIND_INSTANCE.cmd','BUILD_AI_CONTEXT.cmd','BUILD_CANDIDATE_TRANSPORT.cmd','BUILD_GENERIC_DISTRIBUTION.cmd','BUILD_RELEASE.cmd','CHECK_MIGRATIONS.cmd','DOCTOR.cmd','FINALIZE_LAYOUT.cmd','GENESIS_KEELARYN__HUB.cmd','MIGRATE_INSTANCE_IDENTITY.cmd','MIGRATE_LAYOUT.cmd','MIGRATE_TO_KEELARYN.cmd','OPEN_KEELARYN__HUB.cmd','PREPARE_TESTS.cmd','REPAIR_CURRENT_TRANSPORT.cmd','RESTORE_CANDIDATE_TRANSPORT.cmd','SHOW_INSTANCE_INFO.cmd','UPDATE_ALL.cmd','UPDATE_HUB.cmd','UPDATE_MANAGER.cmd')
foreach($name in $compatNames){
    if(@($manifest.managed_files)-contains$name){throw('Historical root wrapper remains managed: '+$name)}
    $rel='compat/commands/'+$name
    if(@($manifest.managed_files)-notcontains$rel){throw('Managed compatibility command missing: '+$rel)}
    if(-not(Test-Path -LiteralPath (Join-Path $ManagerRoot $rel.Replace('/','\')) -PathType Leaf)){throw('Compatibility command file missing: '+$rel)}
}
$rootManagedCmd=@($manifest.managed_files|Where-Object{([string]$_)-notmatch'/'-and([string]$_)-match'\.cmd$'})
if($rootManagedCmd.Count-ne1-or$rootManagedCmd[0]-ne'KEELARYN.cmd'){throw('Physical-layout source root must manage only KEELARYN.cmd as a root CMD. Found: '+($rootManagedCmd-join', '))}
if(-not$menuText.Contains('Open compatibility commands')){throw 'Advanced menu omits compatibility-command access.'}
$requiredMenuTokens=@(
    'function Invoke-MenuAction',
    '2>&1 | ForEach-Object { Write-UiHost ([string]$_) }',
    '[Enter] Back',
    'product\runtime\Keelaryn__Manager.ps1'
)
foreach($token in $requiredMenuTokens){
    if(-not$menuText.Contains($token)){
        throw('Visible interactive UI contract missing token: '+$token)
    }
}

# Candidate frontend owns all user interaction before redirected children and direct actions require explicit commit switches.
foreach($token in @(
    'function Resolve-PickerSelection','function Select-File','function Select-Folder','GUI unavailable; enter full path or leave blank to cancel',
    'Picker GUI-success state-machine failed.','Picker GUI-Cancel incorrectly fell through to manual selection.','Picker GUI-unavailable manual fallback failed.',
    'function Get-TestArchivePlan','-PlanOnly','function Invoke-TestArchiveTool','-NonInteractive','function Resolve-ExplicitConfirmation','function Request-CommitConfirmation','ConfirmChanges',
    'Cancelled. Existing work folder left untouched.','function Invoke-FullGate','gate\Run-KeelarynManagerFullGate.ps1',
    "'-ProductionRoot',$LayoutRoot",'COMPLETED','NO CHANGES REQUIRED','CANCELLED. No changes made.','FAILED',
    'No migrations required.','Pending migrations:','Apply these migrations?','Explicit confirmation is required for direct migration apply.','Current Hub:','New Hub:','Explicit confirmation is required for direct binding changes.',
    'function Invoke-GenesisUi','GenesisConfigPath','GenesisConfirmed','Explicit confirmation is required for direct Genesis.','keelaryn.genesis-input.v1'
)){
    if(-not$menuText.Contains($token)){throw('Frontend orchestration contract missing token: '+$token)}
}
if($menuText.Contains('Press Enter to continue...')){throw 'Legacy unconditional pause wording remains in frontend.'}
$invokeManagerStart=$menuText.IndexOf('function Invoke-Manager')
$openFolderStart=$menuText.IndexOf('function Open-Folder')
if($invokeManagerStart-lt0-or$openFolderStart-le$invokeManagerStart){throw 'Invoke-Manager frontend function boundaries are unavailable.'}
$invokeManagerBody=$menuText.Substring($invokeManagerStart,$openFolderStart-$invokeManagerStart)
if(-not$invokeManagerBody.Contains('-NoProfile -NonInteractive -ExecutionPolicy Bypass -File $ManagerScript')){throw 'Frontend runtime child invocation is not engine-level non-interactive.'}
foreach($token in @('[string]$GenesisConfigPath','[switch]$GenesisConfirmed','function Read-GenesisInputConfig','keelaryn.genesis-input.v1','Target Hub:','CURRENT transport:','Non-interactive Genesis requires explicit confirmation.')){
    if(-not$runtimeText.Contains($token)){throw('Genesis non-interactive runtime contract missing token: '+$token)}
}
$pickerStart=$menuText.IndexOf('function Resolve-PickerSelection')
$selectFileStart=$menuText.IndexOf('function Select-File')
$selectFolderStart=$menuText.IndexOf('function Select-Folder')
$confirmStart=$menuText.IndexOf('function Confirm')
if($pickerStart-lt0-or$selectFileStart-le$pickerStart-or$selectFolderStart-le$selectFileStart-or$confirmStart-le$selectFolderStart){throw 'Picker function boundaries are unavailable.'}
$pickerBody=$menuText.Substring($pickerStart,$selectFileStart-$pickerStart)
$selectFileBody=$menuText.Substring($selectFileStart,$selectFolderStart-$selectFileStart)
$selectFolderBody=$menuText.Substring($selectFolderStart,$confirmStart-$selectFolderStart)
foreach($token in @('if($GuiAvailable)','if($Accepted){return [string]$SelectedPath}','return $null','if([string]::IsNullOrWhiteSpace($ManualPath)){return $null}')){
    if(-not$pickerBody.Contains($token)){throw('Picker state-machine source contract missing token: '+$token)}
}
foreach($body in @($selectFileBody,$selectFolderBody)){
    $gui=$body.IndexOf('return Resolve-PickerSelection $true')
    $manualPrompt=$body.IndexOf('GUI unavailable; enter full path or leave blank to cancel')
    $manual=$body.IndexOf('return Resolve-PickerSelection $false',$manualPrompt)
    if($gui-lt0-or$manualPrompt-lt0-or$manual-lt0-or$gui-gt$manualPrompt){throw 'Picker GUI/Cancel/manual fallback flow is malformed.'}
}
$fullStart=$menuText.IndexOf('function Invoke-FullGate')
$applyStart=$menuText.IndexOf('function Invoke-ApplyMigrationsUi')
if($fullStart-lt0-or$applyStart-le$fullStart){throw 'Full Gate frontend function boundaries are unavailable.'}
$fullBody=$menuText.Substring($fullStart,$applyStart-$fullStart)
if(-not$fullBody.Contains('gate\Run-KeelarynManagerFullGate.ps1')-or-not$fullBody.Contains("'-ProductionRoot',$LayoutRoot")-or$fullBody-match'(?i)cmd\.exe|RUN_.*FULL_GATE\.cmd'){
    throw 'Manager Full Gate frontend must delegate directly to the canonical PowerShell runner and pass the active layout as ProductionRoot.'
}
foreach($token in @('[switch]$PlanOnly','[switch]$NonInteractive','KEELARYN_PLAN_JSON:','Existing work folder requires explicit replacement.')){
    if(-not$archiveToolText.Contains($token)){throw('Archive non-interactive planning contract missing token: '+$token)}
}
$frontendPathCapturePattern='(?m)^\$script:FrontendScriptPath\s*=\s*\[string\]\$MyInvocation\.MyCommand\.Path\s*$'
if($menuText-notmatch$frontendPathCapturePattern){
    throw 'Frontend stable script-path capture contract is missing.'
}
$frontendReadPattern='\[System\.IO\.File\]::ReadAllText\(\s*\$script:FrontendScriptPath\s*(?:,|\))'
if($menuText-notmatch$frontendReadPattern){
    throw 'Frontend SelfTest does not read its captured stable script path.'
}

if($menuText-match'(?m)^\s*\$null\s*=\s*Invoke-Action\b'){throw 'Interactive menu still suppresses action output.'}
if($runtimeText-notmatch'(?m)^\$script:UserInterfaceToolSourceSelfTestReason='){throw 'Detailed UI source SelfTest reason contract is missing.'}
foreach($token in @('function Invoke-WithExistingHiddenFileWritable','function Set-ManagerMutablePresentationHidden','function Write-ManagerBindingDocument','Invoke-WithExistingHiddenFileWritable $CurrentZip','Invoke-WithExistingHiddenFileWritable $dest')){if(-not$runtimeText.Contains($token)){throw('Hidden mutable-file safety contract missing token: '+$token)}}
foreach($token in @('function Initialize-ManagerPresentationState','function Set-ManagerPathVisibleBestEffort','function Get-GeneratedCompatibilityCommandText','function Get-GeneratedRootCompatibilityAliasText','function Get-GeneratedLayoutRootLauncherText','function Ensure-LayoutRootLauncherBestEffort','function Invoke-FinalizeFilesystemLayout','function Set-ManagerOperationalPaths','function Assert-ManagerOperationalPathsReady','function Complete-PendingFilesystemLogHandoff','legacy_log_handoff_pending','KEELARYN_FILESYSTEM_HANDOFF_ACTIVE','Restarting Manager after filesystem finalization to activate canonical state paths...','return (Restart-UpdatedManager)','state\baseline\Keelaryn__Hub_CURRENT.zip','product\install\INSTALLATION.json','compat/commands/','InitializePresentation','FinalizeFilesystemLayout')){if(-not$runtimeText.Contains($token)){throw('Physical productization runtime contract missing token: '+$token)}}
if($runtimeText.Contains('Set-Content $BindingFile -Encoding UTF8')){throw 'Direct binding Set-Content bypasses hidden-safe writer.'}
if($runtimeText-match"@\('ImportPackage','UnpackTest','BuildRelease','EnsureRootLauncher','Get-QuickHubBinding','Doctor','UpdateAll'\)"){throw 'Rejected 4.5.0 UI SelfTest action/function conflation is still present.'}
foreach($token in @('function Get-InstalledManagedFileItem','Get-InstalledManagedFileItem $rel')){if(-not$runtimeText.Contains($token)){throw('Hidden-safe managed source runtime contract missing token: '+$token)}}
foreach($token in @('function Get-ManagerSnapshotFileMetadata','function Test-ManagerSnapshotMetadataSelfTest')){if(-not$runtimeText.Contains($token)){throw('Hidden-safe rollback snapshot runtime contract missing token: '+$token)}}
$aiTool=[System.IO.File]::ReadAllText((Join-Path $ManagerRoot 'product\tools\New-KeelarynAIContext.ps1'),[System.Text.Encoding]::UTF8)
if($aiTool.Contains('Get-FileHash')){throw 'AI_CONTEXT generator still uses Get-FileHash.'}
if(-not$aiTool.Contains('function Get-FileSha256')){throw 'AI_CONTEXT generator direct file hash helper is missing.'}
foreach($token in @('product\runtime\Keelaryn__Manager.ps1','function Get-ManagedSourceItem','$script:Utf8NoBom','$managedItems=@{}','$f.Refresh()','$functionByteSizes[$fn]')){if(-not$aiTool.Contains($token)){throw('AI_CONTEXT physical-runtime/performance contract missing token: '+$token)}}
if($aiTool.Contains("Get-Item -LiteralPath (Join-Path $functionsDir ($fn+'.ps1'))")){throw 'AI_CONTEXT route sizing still reopens function slice files.'}

Write-Host 'Gate A0: root bootstrap SelfTest compatibility' -ForegroundColor Cyan
$bridgeResult=Invoke-SafeProcess $exe @('-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',$entryPath,'-SelfTest') 'Root bootstrap SelfTest' 180 $true
if($bridgeResult.ExitCode-ne0){throw('Root bootstrap SelfTest failed: '+$bridgeResult.ExitCode)}
Write-Host 'Gate A0: root bootstrap SelfTest PASS' -ForegroundColor Green

Write-Host 'Gate A1: Manager SelfTest' -ForegroundColor Cyan
$null=Invoke-Manager @('-SelfTest') $true
Write-Host 'Gate A1: Manager SelfTest PASS' -ForegroundColor Green
$menuTool=Join-Path $ManagerRoot 'product\tools\KeelarynMenu.ps1'
Write-Host 'Gate A1: Frontend SelfTest' -ForegroundColor Cyan
$null=Invoke-Tool $menuTool @('-SelfTest','-NoRootLauncher')
Write-Host 'Gate A1: Frontend SelfTest PASS' -ForegroundColor Green
Write-Host 'Gate A1: Archive-tool SelfTest' -ForegroundColor Cyan
$null=Invoke-Tool (Join-Path $ManagerRoot 'product\tools\Unpack-KeelarynTestArchive.ps1') @('-SelfTest')
Write-Host 'Gate A1: Archive-tool SelfTest PASS' -ForegroundColor Green

Write-Host 'Gate A2: non-interactive console render contract' -ForegroundColor Cyan
$render=Invoke-ToolCapture $menuTool @('-Action','RenderMain','-NoRootLauncher')
if($render.ExitCode-ne0){throw('RenderMain failed: '+$render.ExitCode)}
foreach($token in @(('Keelaryn Manager '+$version),'Everyday','[2] Doctor','[7] Development','[0] Exit')){
    if($render.Text-notmatch[regex]::Escape($token)){throw('Rendered main menu omitted token: '+$token)}
}
if(($render.Text-split"`n").Count-lt12){throw 'Rendered main menu is unexpectedly collapsed.'}

Write-Host 'Gate B: AI_CONTEXT UX/repository routes / lossless reconstruction' -ForegroundColor Cyan
$null=Invoke-Manager @('-BuildAIContext') $true
$aiZip=Join-Path $ManagerRoot ('_releases\Keelaryn__Manager_AI_CONTEXT_v'+$version+'.zip')
if(-not(Test-Path -LiteralPath $aiZip -PathType Leaf)){throw 'AI_CONTEXT ZIP missing.'}
$tmp=Join-Path ([System.IO.Path]::GetTempPath()) ('Keelaryn_ai_'+$version.Replace('.','')+'_'+[guid]::NewGuid().ToString('N'))
try{
    Expand-Archive -LiteralPath $aiZip -DestinationPath $tmp -Force
    $ctx=Join-Path $tmp 'Keelaryn__Manager_AI_CONTEXT'
    $fm=(Get-Content -LiteralPath (Join-Path $ctx 'FUNCTION_MAP.json') -Raw -Encoding UTF8)|ConvertFrom-Json
    $rs=(Get-Content -LiteralPath (Join-Path $ctx 'RUNTIME_SURFACE.json') -Raw -Encoding UTF8)|ConvertFrom-Json
    $tr=(Get-Content -LiteralPath (Join-Path $ctx 'TASK_ROUTER.json') -Raw -Encoding UTF8)|ConvertFrom-Json
    $mm=(Get-Content -LiteralPath (Join-Path $ctx 'MANAGED_FILE_MAP.json') -Raw -Encoding UTF8)|ConvertFrom-Json

    foreach($obj in @($fm,$rs,$tr,$mm)){
        if([string]$obj.manager_version-ne$version){throw 'AI_CONTEXT version mismatch.'}
    }
    if([int]$mm.file_count-ne$finalPaths.Count){throw('AI_CONTEXT final managed file count mismatch: '+[int]$mm.file_count+' expected='+$finalPaths.Count)}

    foreach($routeName in @('user_interface','repository_model','tests_workspace','performance_hashing','candidate_transport','doctor','release_build')){
        $route=$tr.routes.$routeName
        if(-not$route){throw('AI_CONTEXT route missing: '+$routeName)}
        if(-not(Test-Path -LiteralPath (Join-Path $ctx ('routes\'+$routeName+'.md')) -PathType Leaf)){
            throw('AI_CONTEXT route Markdown missing: '+$routeName)
        }
    }
    $uiFiles=@($tr.routes.user_interface.related_managed_files|ForEach-Object{[string]$_})
    foreach($rel in @('KEELARYN.cmd','product/tools/KeelarynMenu.ps1','product/tools/Unpack-KeelarynTestArchive.ps1','product/docs/USER_INTERFACE.md')){
        if($uiFiles-notcontains$rel){throw('user_interface route omitted managed file: '+$rel)}
    }
    $uiFunctions=@($tr.routes.user_interface.entry_functions|ForEach-Object{[string]$_})
    foreach($fn in @('Initialize-ManagerPresentationState','Get-GeneratedCompatibilityCommandText','Get-GeneratedLayoutRootLauncherText','Ensure-LayoutRootLauncherBestEffort','Invoke-FinalizeFilesystemLayout','Set-ManagerOperationalPaths','Assert-ManagerOperationalPathsReady','Complete-PendingFilesystemLogHandoff')){
        if($uiFunctions-notcontains$fn){throw('user_interface route omitted runtime entry function: '+$fn)}
    }
    $repoFiles=@($tr.routes.repository_model.related_managed_files|ForEach-Object{[string]$_})
    if($repoFiles-notcontains'product/docs/REPOSITORY_MODEL.md'){throw 'repository_model route omitted REPOSITORY_MODEL.md.'}
    $repoFunctions=@($tr.routes.repository_model.entry_functions|ForEach-Object{[string]$_})
    foreach($fn in @('Test-ManagerManagedPath','Get-InstalledManagedPaths','Invoke-BuildDistribution','Invoke-BuildRelease','Invoke-FinalizeFilesystemLayout','Set-ManagerOperationalPaths','Assert-ManagerOperationalPathsReady','Complete-PendingFilesystemLogHandoff')){
        if($repoFunctions-notcontains$fn){throw('repository_model route omitted runtime entry function: '+$fn)}
    }
    $testFiles=@($tr.routes.tests_workspace.related_managed_files|ForEach-Object{[string]$_})
    if($testFiles-notcontains'product/tools/Unpack-KeelarynTestArchive.ps1'){throw 'tests_workspace route omitted integrated test archive tool.'}

    # Optimized route byte sizing must remain byte-exact against materialized function slices.
    foreach($routeProp in @($tr.routes.PSObject.Properties)){
        $route=$routeProp.Value
        $actualBytes=[long]0
        foreach($fn in @($route.recommended_functions)){
            $slicePath=Join-Path $ctx ('functions\'+[string]$fn+'.ps1')
            $sliceItem=Get-Item -LiteralPath $slicePath -Force -ErrorAction Stop
            $actualBytes += [long]$sliceItem.Length
        }
        if([long]$route.recommended_runtime_bytes-ne$actualBytes){throw('AI_CONTEXT route byte total mismatch: '+[string]$routeProp.Name+' declared='+[long]$route.recommended_runtime_bytes+' actual='+$actualBytes)}
    }

    foreach($row in @($fm.functions)){
        $slice=Join-Path $ctx ([string]$row.slice).Replace('/','\')
        if(-not(Test-Path -LiteralPath $slice -PathType Leaf)){throw('Function slice missing: '+[string]$row.name)}
        if((Sha $slice)-ne([string]$row.sha256).ToLowerInvariant()){throw('Function slice hash mismatch: '+[string]$row.name)}
    }

    $sb=New-Object System.Text.StringBuilder
    foreach($seg in @($rs.segments)){
        [void]$sb.Append([System.IO.File]::ReadAllText((Join-Path $ctx ([string]$seg.slice).Replace('/','\')),[System.Text.Encoding]::UTF8))
    }
    $runtime=[System.IO.File]::ReadAllText($scriptPath,[System.Text.Encoding]::UTF8)
    if($sb.ToString()-cne$runtime){throw 'AI_CONTEXT runtime reconstruction differs from source.'}

    $cm=(Get-Content -LiteralPath (Join-Path $ctx 'CONTEXT_MANIFEST.json') -Raw -Encoding UTF8)|ConvertFrom-Json
    foreach($row in @($cm.files)){
        $p=Join-Path $ctx ([string]$row.path).Replace('/','\')
        if(-not(Test-Path -LiteralPath $p -PathType Leaf)){throw('CONTEXT_MANIFEST file missing: '+[string]$row.path)}
        if((Sha $p)-ne([string]$row.sha256).ToLowerInvariant()){throw('CONTEXT_MANIFEST hash mismatch: '+[string]$row.path)}
    }
}
finally{
    if(Test-Path -LiteralPath $tmp){Remove-Item -LiteralPath $tmp -Recurse -Force -ErrorAction SilentlyContinue}
}

function New-IsolatedManagerBuildRoot([string]$Path){
    if(Test-Path -LiteralPath $Path){Remove-Item -LiteralPath $Path -Recurse -Force}
    New-Item -ItemType Directory -Force -Path $Path|Out-Null
    foreach($rel in @($expectedTransition)){
        $src=Join-Path $ManagerRoot $rel.Replace('/','\')
        if(-not(Test-Path -LiteralPath $src -PathType Leaf)){throw('Isolated build source missing: '+$rel)}
        $dst=Join-Path $Path $rel.Replace('/','\');$parent=Split-Path -Parent $dst
        if($parent){New-Item -ItemType Directory -Force -Path $parent|Out-Null}
        Copy-Item -LiteralPath $src -Destination $dst -Force
    }
    return $Path
}

Write-Host 'Gate C: deterministic BUILD_RELEASE x2 (isolated outputs)' -ForegroundColor Cyan
$detRoot=Join-Path $ManagerRoot '_gate_determinism'
$buildA=New-IsolatedManagerBuildRoot (Join-Path $detRoot 'build-a')
$buildB=New-IsolatedManagerBuildRoot (Join-Path $detRoot 'build-b')
try{
    $null=Invoke-ManagerAt $buildA @('-BuildRelease') $true 'Manager build-A'
    $releasesA=Join-Path $buildA '_releases';$r1=Read-Release $releasesA $version;$h1=Release-Hashes $releasesA $r1
    $null=Invoke-ManagerAt $buildB @('-BuildRelease') $true 'Manager build-B'
    $releasesB=Join-Path $buildB '_releases';$r2=Read-Release $releasesB $version;$h2=Release-Hashes $releasesB $r2
    Assert-DeterministicRelease $releasesA $r1 $releasesB $r2

    Write-Host 'Gate C2: SOURCE / DISTRIBUTION / transition UPDATE boundary' -ForegroundColor Cyan
    $releaseBase=$releasesB
$sourceRow=@($r2.artifacts|Where-Object{[string]$_.role-eq'source'})[0]
$distRow=@($r2.artifacts|Where-Object{[string]$_.role-eq'distribution'})[0]
$updateRow=@($r2.artifacts|Where-Object{[string]$_.role-eq'update'})[0]
$sourceZip=Join-Path $releaseBase ([string]$sourceRow.path)
$distZip=Join-Path $releaseBase ([string]$distRow.path)
$updateZip=Join-Path $releaseBase ([string]$updateRow.path)
function Get-ZipNames([string]$ZipPath){
    $za=[System.IO.Compression.ZipFile]::OpenRead($ZipPath)
    try{return @($za.Entries|Where-Object{-not$_.FullName.EndsWith('/')}|ForEach-Object{$_.FullName.Replace('\','/')})}finally{$za.Dispose()}
}
$sourceNames=@(Get-ZipNames $sourceZip)
$distNames=@(Get-ZipNames $distZip)
foreach($legacyRoot in $transitionOnly){
    if($sourceNames-contains('keelaryn/manager/'+$legacyRoot)){throw('SOURCE leaked transition-only root file: '+$legacyRoot)}
    if($distNames-contains('keelaryn/manager/'+$legacyRoot)){throw('DISTRIBUTION leaked transition-only root file: '+$legacyRoot)}
}
foreach($required in @('keelaryn/manager/product/install/INSTALLATION.json','keelaryn/manager/product/runtime/Keelaryn__Manager.ps1','keelaryn/manager/compat/commands/DOCTOR.cmd')){
    if($sourceNames-notcontains$required){throw('SOURCE omitted canonical final file: '+$required)}
    if($distNames-notcontains$required){throw('DISTRIBUTION omitted canonical final file: '+$required)}
}
if($distNames-notcontains'keelaryn/manager/product/install/DISTRIBUTION_MANIFEST.json'){throw 'DISTRIBUTION omitted organized distribution provenance manifest.'}
if($distNames-contains'keelaryn/manager/DISTRIBUTION_MANIFEST.json'){throw 'DISTRIBUTION leaked distribution provenance manifest into Manager root.'}
if($sourceNames-contains'keelaryn/manager/product/install/DISTRIBUTION_MANIFEST.json'){throw 'SOURCE must not contain generated distribution provenance metadata.'}
$ua=[System.IO.Compression.ZipFile]::OpenRead($updateZip)
try{
    $index=@{};foreach($e in $ua.Entries){if(-not$e.FullName.EndsWith('/')){$index[$e.FullName.Replace('\','/').ToLowerInvariant()]=$e}}
    $manifestEntry=$index['keelaryn__manager_update/manifest.json'];if(-not$manifestEntry){throw 'UPDATE manifest missing.'}
    $reader=New-Object System.IO.StreamReader($manifestEntry.Open(),[System.Text.Encoding]::UTF8,$true);try{$updateManifest=$reader.ReadToEnd()|ConvertFrom-Json}finally{$reader.Dispose()}
    $finalDeclared=@(Get-OrdinalUniqueStrings @($updateManifest.final_managed_files|ForEach-Object{([string]$_).Replace('\','/')}))
    if($finalDeclared.Count-ne$finalPaths.Count-or[string]::Join('|',$finalDeclared)-cne[string]::Join('|',$finalPaths)){throw 'UPDATE final_managed_files does not equal canonical final manifest.'}
    if(-not([string]$updateManifest.final_content_hash-match'^[0-9a-fA-F]{64}$')){throw 'UPDATE final_content_hash missing/invalid.'}
    $packageRows=@($updateManifest.files)
    $packageDeclared=@(Get-OrdinalUniqueStrings @($packageRows|ForEach-Object{([string]$_.path).Replace('\','/')}))
    if($packageDeclared.Count-ne$packageRows.Count){throw 'UPDATE transport manifest contains duplicate file paths.'}
    if($packageDeclared.Count-ne$expectedUpdateTransport.Count-or[string]::Join('|',$packageDeclared)-cne[string]::Join('|',$expectedUpdateTransport)){throw('UPDATE transport path set mismatch: declared='+$packageDeclared.Count+' expected='+$expectedUpdateTransport.Count)}
    foreach($legacyRoot in $transitionOnly){if(-not$index.ContainsKey(('keelaryn__manager_update/payload/'+$legacyRoot).ToLowerInvariant())){throw('UPDATE transition payload file missing: '+$legacyRoot)}}
    foreach($alias in $updateAliases){
        $aliasPath=[string]$alias.Path;$sourcePath=[string]$alias.SourcePath
        $aliasRows=@($packageRows|Where-Object{([string]$_.path).Replace('\','/')-ceq$aliasPath})
        $sourceRows=@($packageRows|Where-Object{([string]$_.path).Replace('\','/')-ceq$sourcePath})
        if($aliasRows.Count-ne1-or$sourceRows.Count-ne1){throw('UPDATE transition alias/source row missing: '+$aliasPath+' -> '+$sourcePath)}
        if(([string]$aliasRows[0].sha256).ToLowerInvariant()-cne([string]$sourceRows[0].sha256).ToLowerInvariant()-or[int64]$aliasRows[0].size_bytes-ne[int64]$sourceRows[0].size_bytes){throw('UPDATE transition alias does not bind exact source bytes: '+$aliasPath+' -> '+$sourcePath)}
        if(-not$index.ContainsKey(('keelaryn__manager_update/payload/'+$aliasPath).ToLowerInvariant())){throw('UPDATE transition alias payload file missing: '+$aliasPath)}
        if($sourceNames-contains('keelaryn/manager/'+$aliasPath)){throw('SOURCE leaked UPDATE-only transition alias: '+$aliasPath)}
        if($distNames-contains('keelaryn/manager/'+$aliasPath)){throw('DISTRIBUTION leaked UPDATE-only transition alias: '+$aliasPath)}
    }
    if(-not$index.ContainsKey('keelaryn__manager_update/payload/product/install/installation.json')){throw 'UPDATE canonical installation manifest missing.'}

    $bootstrapEntry=$index['keelaryn__manager_update/payload/keelaryn__manager.ps1'];if(-not$bootstrapEntry){throw 'UPDATE transition bootstrap missing.'}
    $bootstrapReader=New-Object System.IO.StreamReader($bootstrapEntry.Open(),[System.Text.Encoding]::UTF8,$true)
    try{$bootstrapText=$bootstrapReader.ReadToEnd()}finally{$bootstrapReader.Dispose()}
    foreach($token in @('$runtime = Join-Path $PSScriptRoot ''product\runtime\Keelaryn__Manager.ps1''','$PSHOME','$runtime @args')){if(-not$bootstrapText.Contains($token)){throw('UPDATE transition bootstrap omitted literal runtime token: '+$token)}}
    if($bootstrapText-match'(?i)[A-Z]:\\'){throw('UPDATE transition bootstrap leaked an absolute Windows build path: '+$bootstrapText)}
    $bt=$null;$be=$null;[void][System.Management.Automation.Language.Parser]::ParseInput($bootstrapText,[ref]$bt,[ref]$be)
    if(@($be).Count-ne0){throw('UPDATE transition bootstrap parser failure: '+([string]::Join(' | ',@($be|ForEach-Object{$_.Message}))))}
}finally{$ua.Dispose()}
Write-Host 'Gate C2 SOURCE/DISTRIBUTION final-only and UPDATE transition-envelope PASS.' -ForegroundColor Green

    # Publish the already-validated build-B release set to the stable SourceGate -> FullGate handoff path.
    # This happens only after isolated build A/B determinism and C2 package validation have passed.
    $publishedReleases=Join-Path $ManagerRoot '_releases'
    if(-not(Test-Path -LiteralPath $publishedReleases -PathType Container)){
        New-Item -ItemType Directory -Force -Path $publishedReleases|Out-Null
    }
    foreach($artifact in @($r2.artifacts)){
        $src=Join-Path $releasesB ([string]$artifact.path)
        $dst=Join-Path $publishedReleases ([string]$artifact.path)
        $parent=Split-Path -Parent $dst
        if($parent){New-Item -ItemType Directory -Force -Path $parent|Out-Null}
        if(Test-Path -LiteralPath $dst -PathType Leaf){
            if((Sha $dst)-eq(Sha $src)){continue}
            Remove-Item -LiteralPath $dst -Force
        }
        Copy-Item -LiteralPath $src -Destination $dst -Force
    }
    $manifestName='Keelaryn__Manager_RELEASE_v'+$version+'.json'
    $manifestSrc=Join-Path $releasesB $manifestName
    $manifestDst=Join-Path $publishedReleases $manifestName
    if((-not(Test-Path -LiteralPath $manifestDst -PathType Leaf))-or(Sha $manifestDst)-ne(Sha $manifestSrc)){
        Copy-Item -LiteralPath $manifestSrc -Destination $manifestDst -Force
    }
    $publishedRelease=Read-Release $publishedReleases $version
    Assert-DeterministicRelease $releasesB $r2 $publishedReleases $publishedRelease
    $publishedManifestName='Keelaryn__Manager_RELEASE_v'+$version+'.json'
    $publishedManifestPath=Join-Path $publishedReleases $publishedManifestName
    $handoffArtifacts=New-Object System.Collections.ArrayList
    foreach($artifact in @($publishedRelease.artifacts)){
        $artifactPath=Join-Path $publishedReleases ([string]$artifact.path)
        if(-not(Test-Path -LiteralPath $artifactPath -PathType Leaf)){throw('Published release artifact missing while writing SourceGate result: '+$artifactPath)}
        $actualSha=Sha $artifactPath
        if($actualSha-ne([string]$artifact.sha256).ToLowerInvariant()){throw('Published release artifact hash mismatch while writing SourceGate result: '+[string]$artifact.role)}
        [void]$handoffArtifacts.Add([ordered]@{role=[string]$artifact.role;path=[string]$artifact.path;sha256=$actualSha;bytes=[int64](Get-Item -LiteralPath $artifactPath -Force).Length})
    }
    $sourceGateResult=[ordered]@{schema='keelaryn.manager-source-gate-result.v1';status='passed';framework_revision=$frameworkRevision;candidate_version=$version;gate_revision=[int]$gateSpec.gate_revision;gate_spec_sha256=(Sha $specPath);candidate_installation_sha256=[string]$gateSpec.candidate_installation_sha256;candidate_managed_content_sha256=[string]$gateSpec.candidate_managed_content_sha256;release=[ordered]@{root_relative='_releases';manifest_relative=$publishedManifestName;manifest_sha256=(Sha $publishedManifestPath);artifacts=@($handoffArtifacts)};completed_utc=(Get-Date).ToUniversalTime().ToString('o')}
    $sourceGateResultPath=Join-Path $resultsRoot 'SOURCE_GATE_RESULT.json'
    [System.IO.File]::WriteAllText($sourceGateResultPath,(($sourceGateResult|ConvertTo-Json -Depth 10).Replace("`r`n","`n")+"`n"),(New-Object System.Text.UTF8Encoding($false)))
    Write-Host ('Gate C3: validated release handoff: '+$sourceGateResultPath) -ForegroundColor Green
}finally{
    if(Test-Path -LiteralPath $detRoot){Remove-Item -LiteralPath $detRoot -Recurse -Force -ErrorAction SilentlyContinue}
}

Write-Host ''
Write-Host ('SOURCE/UI/ORCHESTRATION/AI-CONTEXT WINDOWS GATE PASSED for Manager '+$version+'.') -ForegroundColor Green
