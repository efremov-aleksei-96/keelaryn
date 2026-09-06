[CmdletBinding()]
param(
    [string]$CandidateRoot=(Split-Path $PSScriptRoot -Parent),
    [string]$ProductionRoot=''
)

$ErrorActionPreference='Stop'
if($PSVersionTable.PSVersion.Major-ne5-or[string]$PSVersionTable.PSEdition-ne'Desktop'){
    throw 'Run with Windows PowerShell 5.1 Desktop.'
}

Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem

function Sha([string]$Path){
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

$CandidateRoot=[System.IO.Path]::GetFullPath($CandidateRoot).TrimEnd('\')
$gateSupportRoot=Join-Path $CandidateRoot 'gate'
$specPath=Join-Path $gateSupportRoot 'GATE_SPEC.json'
if(-not(Test-Path -LiteralPath $specPath -PathType Leaf)){throw('Gate spec missing: '+$specPath)}
$gateSpec=(Get-Content -LiteralPath $specPath -Raw -Encoding UTF8)|ConvertFrom-Json
if([string]$gateSpec.schema-ne'keelaryn.manager-gate-spec.v1'-or[string]$gateSpec.framework_version-ne'2.0'){throw('Unsupported gate spec/framework: '+[string]$gateSpec.schema+' / '+[string]$gateSpec.framework_version)}
$version=[string]$gateSpec.candidate_version
$baseline=[string]$gateSpec.baseline_manager_version
$gateRevision=[int]$gateSpec.gate_revision
$frameworkRevision=[int]$gateSpec.framework_revision
if([string]::IsNullOrWhiteSpace($version)-or[string]::IsNullOrWhiteSpace($baseline)-or$gateRevision-lt1-or$frameworkRevision-lt1){throw 'Gate spec candidate/baseline/gate/framework revision is invalid.'}
$frameworkRevisionPath=Join-Path $gateSupportRoot 'FRAMEWORK_REVISION.txt'
$frameworkRevisionMarker=0
if(-not(Test-Path -LiteralPath $frameworkRevisionPath -PathType Leaf)-or-not[int]::TryParse((Get-Content -LiteralPath $frameworkRevisionPath -Raw -Encoding UTF8).Trim(),[ref]$frameworkRevisionMarker)-or$frameworkRevisionMarker-ne$frameworkRevision){throw 'Framework revision marker/spec mismatch.'}
$gateRevisionPath=Join-Path $gateSupportRoot 'GATE_REVISION.txt'
if(-not(Test-Path -LiteralPath $gateRevisionPath -PathType Leaf)){throw('Gate revision marker missing: '+$gateRevisionPath)}
$gateRevisionMarker=0
if(-not[int]::TryParse((Get-Content -LiteralPath $gateRevisionPath -Raw -Encoding UTF8).Trim(),[ref]$gateRevisionMarker)-or$gateRevisionMarker-ne$gateRevision){throw 'Gate revision marker/spec mismatch.'}
$candidateParent=Split-Path $CandidateRoot -Parent
$testsRoot=Split-Path $candidateParent -Parent
$expectedLeaf='manager-'+$version
if((Split-Path $candidateParent -Leaf)-ine'work'-or
   (Split-Path $testsRoot -Leaf)-ine'tests'-or
   (Split-Path $CandidateRoot -Leaf)-ine$expectedLeaf){
    throw('CandidateRoot must be exactly under keelaryn\tests\work\'+$expectedLeaf+': '+$CandidateRoot)
}
if([string]::IsNullOrWhiteSpace($ProductionRoot)){$ProductionRoot=Split-Path $testsRoot -Parent}
$ProductionRoot=[System.IO.Path]::GetFullPath($ProductionRoot).TrimEnd('\')

$exe=Join-Path $PSHOME 'powershell.exe'
$prodManager=Join-Path $ProductionRoot 'manager'
$prodHub=Join-Path $ProductionRoot 'hub'
$prodCurrent=Join-Path $prodManager 'state\baseline\Keelaryn__Hub_CURRENT.zip'
$resultsRoot=Join-Path $testsRoot ('results\manager-'+$version)
$doctorRoot=Join-Path $resultsRoot 'doctor_reports'
$runtime=Join-Path $CandidateRoot '_runtime'
$summaryPath=Join-Path $resultsRoot 'GATE_SUMMARY.json'
$transcriptPath=Join-Path $resultsRoot 'FULL_GATE.log'
$candidateInstallPath=Join-Path $CandidateRoot 'product\install\INSTALLATION.json'
if(-not(Test-Path -LiteralPath $candidateInstallPath -PathType Leaf)){throw('Candidate installation manifest missing: '+$candidateInstallPath)}
$candidateInstall=(Get-Content -LiteralPath $candidateInstallPath -Raw -Encoding UTF8)|ConvertFrom-Json
if([string]$candidateInstall.schema-ne'keelaryn.manager.installation.v2'-or[string]$candidateInstall.manager_version-ne$version){throw 'Candidate installation manifest/spec mismatch.'}
$candidateManagedCount=@($candidateInstall.managed_files).Count
if($candidateManagedCount-lt1){throw 'Candidate installation manifest has no managed files.'}

foreach($dir in @((Join-Path $testsRoot 'results'),$resultsRoot,$doctorRoot)){
    if(-not(Test-Path -LiteralPath $dir)){New-Item -ItemType Directory -Force -Path $dir|Out-Null}
    $item=Get-Item -LiteralPath $dir -Force
    if(-not$item.PSIsContainer-or($item.Attributes-band[System.IO.FileAttributes]::ReparsePoint)-ne0){
        throw('Unsafe results directory: '+$dir)
    }
}

$summary=[ordered]@{
    schema='keelaryn.manager.windows-gate-summary.v16'
    manager_version=$version
    baseline_version=$baseline
    gate_revision=$gateRevision
    framework_revision=$frameworkRevision
    gate_spec_sha256=(Sha $specPath)
    candidate_installation_sha256=[string]$gateSpec.candidate_installation_sha256
    candidate_managed_content_sha256=[string]$gateSpec.candidate_managed_content_sha256
    started=(Get-Date).ToUniversalTime().ToString('o')
    completed=$null
    status='running'
    failure=$null
    phases=[ordered]@{
        production_preflight=$false
        source_release=$false
        disposable_baseline=$false
        rollback_fault_injection=$false
        native_update=$false
        doctor_migrations=$false
        ui_orchestration=$false
        archive_orchestration=$false
        candidate_transport=$false
        current_repair=$false
        ai_context_performance=$false
        installed_release_distribution=$false
        genesis=$false
        production_immutability=$false
    }
    update=[ordered]@{snapshot_verified=$false;rollback_verified=$false;state_preserved=$false;hub_preserved=$false}
    ux=[ordered]@{
        frontend_selftest=$false;archive_tool_selftest=$false;menu_render=$false
        interactive_doctor=$false;interactive_update_all=$false;interactive_installation_info=$false;submenu_navigation=$false
        full_gate_frontend_delegation=$false;migration_noop=$false;migration_preview_decline=$false;migration_apply=$false;binding_preview_cancel=$false
        archive_fresh=$false;archive_child_noninteractive=$false;archive_decline=$false;archive_replace=$false;archive_traversal_rejected=$false
        candidate_no_input=$false;candidate_invalid_rejected=$false;candidate_multi_build=$false;candidate_restore=$false
        generic_distribution=$false;generic_distribution_smoke=$false;genesis_direct_decline=$false;genesis=$false;genesis_existing_target_rejected=$false
    }
    ai_context_performance=$null
    disposable_hub_source='production_current_zip'
    production_unchanged=$false
    production_execution_isolated=$false
    production_hub_observed_change=$null
    tested_artifacts=$null
    workspace=[ordered]@{tests=$testsRoot;work=$candidateParent;candidate=$CandidateRoot;results=$resultsRoot;runtime=$runtime}
}
$script:CurrentPhase='initialization'
$transcriptStarted=$false
$desktopSnapshot=$null

function TextSha([string]$Text){
    $enc=New-Object System.Text.UTF8Encoding($false)
    $sha=[System.Security.Cryptography.SHA256]::Create()
    try{return [BitConverter]::ToString($sha.ComputeHash($enc.GetBytes($Text))).Replace('-','').ToLowerInvariant()}
    finally{$sha.Dispose()}
}

function TreeDigest([string]$RootPath){
    if(-not(Test-Path -LiteralPath $RootPath -PathType Container)){return '<missing>'}
    $root=(Get-Item -LiteralPath $RootPath -Force).FullName.TrimEnd('\')
    $rows=New-Object System.Collections.ArrayList
    foreach($f in @(Get-ChildItem -LiteralPath $RootPath -File -Recurse -Force|Sort-Object FullName)){
        $rel=$f.FullName.Substring($root.Length).TrimStart('\').Replace('\','/')
        [void]$rows.Add($rel+"`0"+(Sha $f.FullName))
    }
    return TextSha([string]::Join("`n",@($rows)))
}

function PortableHubDigest([string]$RootPath){
    $root=(Get-Item -LiteralPath $RootPath -Force).FullName.TrimEnd('\')
    $rows=New-Object System.Collections.ArrayList
    foreach($f in @(Get-ChildItem -LiteralPath $RootPath -File -Recurse -Force|Sort-Object FullName)){
        $rel=$f.FullName.Substring($root.Length).TrimStart('\').Replace('\','/')
        $low=$rel.ToLowerInvariant()
        $leaf=[System.IO.Path]::GetFileName($low)
        if($low-eq'.git'-or$low.StartsWith('.git/')-or
           $low-eq'.obsidian'-or$low.StartsWith('.obsidian/')-or
           @('.ds_store','thumbs.db','desktop.ini')-contains$leaf){continue}
        [void]$rows.Add($rel+"`0"+(Sha $f.FullName))
    }
    return TextSha([string]::Join("`n",@($rows)))
}

function PortableHubSnapshot([string]$RootPath){
    $root=(Get-Item -LiteralPath $RootPath -Force).FullName.TrimEnd('\')
    $files=@{}
    $rows=New-Object System.Collections.ArrayList
    foreach($f in @(Get-ChildItem -LiteralPath $RootPath -File -Recurse -Force|Sort-Object FullName)){
        $rel=$f.FullName.Substring($root.Length).TrimStart('\').Replace('\','/')
        $low=$rel.ToLowerInvariant()
        $leaf=[System.IO.Path]::GetFileName($low)
        if($low-eq'.git'-or$low.StartsWith('.git/')-or
           $low-eq'.obsidian'-or$low.StartsWith('.obsidian/')-or
           @('.ds_store','thumbs.db','desktop.ini')-contains$leaf){continue}
        $hash=Sha $f.FullName
        $files[$rel]=$hash
        [void]$rows.Add($rel+"`0"+$hash)
    }
    return [pscustomobject]@{Digest=(TextSha([string]::Join("`n",@($rows))));Files=$files}
}

function Compare-PortableHubSnapshots($Before,$After){
    $changed=New-Object System.Collections.ArrayList
    $keys=@(@($Before.Files.Keys)+@($After.Files.Keys)|Sort-Object -Unique)
    foreach($key in $keys){
        $beforeHash=if($Before.Files.ContainsKey($key)){[string]$Before.Files[$key]}else{$null}
        $afterHash=if($After.Files.ContainsKey($key)){[string]$After.Files[$key]}else{$null}
        if($beforeHash-ne$afterHash){
            $kind=if($null-eq$beforeHash){'added'}elseif($null-eq$afterHash){'removed'}else{'changed'}
            [void]$changed.Add([pscustomobject]@{path=[string]$key;kind=$kind;before=$beforeHash;after=$afterHash})
        }
    }
    return @($changed)
}

function Assert-NotProductionExecutionPath([string]$Path,[string]$Context){
    $full=[System.IO.Path]::GetFullPath($Path).TrimEnd('\')
    $prod=[System.IO.Path]::GetFullPath($prodManager).TrimEnd('\')
    if($full.Equals($prod,[System.StringComparison]::OrdinalIgnoreCase)-or
       $full.StartsWith($prod+'\',[System.StringComparison]::OrdinalIgnoreCase)){
        throw('Disposable gate attempted to execute production Manager/tool path in '+$Context+': '+$full)
    }
}

function Read-InstalledManifest([string]$ManagerRoot){
    $path=Join-Path $ManagerRoot 'product\install\INSTALLATION.json'
    if(-not(Test-Path -LiteralPath $path -PathType Leaf)){throw('Canonical installation manifest missing: '+$path)}
    $m=(Get-Content -LiteralPath $path -Raw -Encoding UTF8)|ConvertFrom-Json
    if([string]$m.schema-ne'keelaryn.manager.installation.v2'-or[int]$m.layout_version-ne2){throw('Unsupported canonical installation manifest: '+$path)}
    return $m
}

function ManagedDigest([string]$ManagerRoot){
    $m=Read-InstalledManifest $ManagerRoot
    $rows=New-Object System.Collections.ArrayList
    foreach($rel in @($m.managed_files|ForEach-Object{([string]$_).Replace('\','/')}|Sort-Object)){
        $p=Join-Path $ManagerRoot $rel.Replace('/','\')
        if(-not(Test-Path -LiteralPath $p -PathType Leaf)){throw('Managed file missing while hashing: '+$p)}
        [void]$rows.Add($rel+"`0"+(Sha $p))
    }
    return TextSha([string]::Join("`n",@($rows)))
}

function GateSpecManagedDigest([string]$ManagerRoot){
    $m=Read-InstalledManifest $ManagerRoot
    $managed=New-Object 'System.Collections.Generic.List[string]'
    foreach($raw in @($m.managed_files)){[void]$managed.Add(([string]$raw).Replace('\','/'))}
    $managed.Sort([System.StringComparer]::Ordinal)
    $rows=New-Object System.Collections.ArrayList
    foreach($rel in $managed){
        $p=Join-Path $ManagerRoot $rel.Replace('/','\')
        if(-not(Test-Path -LiteralPath $p -PathType Leaf)){throw('Managed file missing while gate-spec hashing: '+$p)}
        [void]$rows.Add($rel+"`0"+(Sha $p))
    }
    return TextSha([string]::Join("`n",@($rows)))
}

function Copy-ManagedTree([string]$Source,[string]$Destination){
    $m=Read-InstalledManifest $Source
    if(Test-Path -LiteralPath $Destination){Remove-Item -LiteralPath $Destination -Recurse -Force}
    New-Item -ItemType Directory -Force -Path $Destination|Out-Null
    foreach($raw in @($m.managed_files)){
        $rel=([string]$raw).Replace('/','\')
        $src=Join-Path $Source $rel;$dst=Join-Path $Destination $rel
        $parent=Split-Path -Parent $dst;if($parent){New-Item -ItemType Directory -Force -Path $parent|Out-Null}
        Copy-Item -LiteralPath $src -Destination $dst -Force
    }
    return $m
}

$commandLogRoot=Join-Path $resultsRoot 'command_logs\full'
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
    [bool]$Show=$true,
    [AllowNull()][string]$InputText=$null
){
    $script:CommandSequence++
    $safeLabel=($Label-replace'[^A-Za-z0-9_.-]','_')
    $prefix=('{0:D3}_{1}'-f$script:CommandSequence,$safeLabel)
    $stdout=Join-Path $commandLogRoot ($prefix+'.stdout.txt')
    $stderr=Join-Path $commandLogRoot ($prefix+'.stderr.txt')
    $specPath=Join-Path $commandLogRoot ($prefix+'.spec.json')
    $exitCodePath=Join-Path $commandLogRoot ($prefix+'.exitcode.txt')
    $stdinPath=Join-Path $commandLogRoot ($prefix+'.stdin.txt')
    Remove-Item -LiteralPath $stdout,$stderr,$specPath,$exitCodePath,$stdinPath -Force -ErrorAction SilentlyContinue
    if($null-ne$InputText){
        [System.IO.File]::WriteAllText($stdinPath,$InputText,(New-Object System.Text.UTF8Encoding($false)))
    }

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

    $startArgs=@{
        FilePath=$exe
        ArgumentList=$argLine
        PassThru=$true
        WindowStyle='Hidden'
        RedirectStandardOutput=$stdout
        RedirectStandardError=$stderr
    }
    if($null-ne$InputText){$startArgs['RedirectStandardInput']=$stdinPath}
    $p=Start-Process @startArgs
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

function Invoke-ManagerCapture([string]$ManagerRoot,[string[]]$ManagerArgs){
    Assert-NotProductionExecutionPath $ManagerRoot 'Manager invocation'
    $managerScript=Join-Path $ManagerRoot 'product\runtime\Keelaryn__Manager.ps1'
    if(-not(Test-Path -LiteralPath $managerScript -PathType Leaf)){$managerScript=Join-Path $ManagerRoot 'Keelaryn__Manager.ps1'}
    $childArgs=@('-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',$managerScript)+@($ManagerArgs)
    return Invoke-SafeProcess $exe $childArgs ('Manager '+($ManagerArgs-join' ')) (Get-ManagerTimeout $ManagerArgs) $false
}

function Run-Manager([string]$ManagerRoot,[string[]]$ManagerArgs,[bool]$Show=$true){
    $r=Invoke-ManagerCapture $ManagerRoot $ManagerArgs
    if($Show){
        if($r.StdOut){Write-Host $r.StdOut.TrimEnd([char[]]"`r`n")}
        if($r.StdErr){Write-Host $r.StdErr.TrimEnd([char[]]"`r`n") -ForegroundColor Yellow}
    }
    if($r.ExitCode-ne0){$detail=if($r.StdErr){[string]$r.StdErr}else{[string]$r.StdOut};$detail=$detail.Trim();if($detail.Length-gt1200){$detail=$detail.Substring($detail.Length-1200)};throw('Manager command failed: '+($ManagerArgs-join' ')+'; exit='+$r.ExitCode+'; detail='+$detail+'; stdout='+$r.StdOutPath+'; stderr='+$r.StdErrPath)}
    return $r
}

function Invoke-ToolCapture([string]$ToolPath,[string[]]$ToolArgs){
    Assert-NotProductionExecutionPath $ToolPath 'tool invocation'
    $childArgs=@('-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',$ToolPath)+@($ToolArgs)
    return Invoke-SafeProcess $exe $childArgs ('Tool '+[System.IO.Path]::GetFileName($ToolPath)+' '+($ToolArgs-join' ')) 180 $false
}

function Run-Tool([string]$ToolPath,[string[]]$ToolArgs,[bool]$Show=$true){
    $r=Invoke-ToolCapture $ToolPath $ToolArgs
    if($Show){
        if($r.StdOut){Write-Host $r.StdOut.TrimEnd([char[]]"`r`n")}
        if($r.StdErr){Write-Host $r.StdErr.TrimEnd([char[]]"`r`n") -ForegroundColor Yellow}
    }
    if($r.ExitCode-ne0){$detail=if($r.StdErr){[string]$r.StdErr}else{[string]$r.StdOut};$detail=$detail.Trim();if($detail.Length-gt1200){$detail=$detail.Substring($detail.Length-1200)};throw('Tool failed: '+$ToolPath+'; exit='+$r.ExitCode+'; detail='+$detail+'; stdout='+$r.StdOutPath+'; stderr='+$r.StdErrPath)}
    return $r
}

function Get-ManagerStatePath([string]$ManagerRoot,[string]$LegacyRelative,[string]$StateRelative){
    $receipt=Join-Path $ManagerRoot 'state\layout.json'
    if(Test-Path -LiteralPath $receipt -PathType Leaf){return Join-Path $ManagerRoot ('state\'+$StateRelative)}
    return Join-Path $ManagerRoot $LegacyRelative
}

function Get-DoctorReport([string]$ManagerRoot){
    $p=Get-ManagerStatePath $ManagerRoot '_logs\DOCTOR_REPORT.json' 'logs\DOCTOR_REPORT.json'
    if(-not(Test-Path -LiteralPath $p -PathType Leaf)){throw('Doctor report missing: '+$p)}
    return (Get-Content -LiteralPath $p -Raw -Encoding UTF8)|ConvertFrom-Json
}

function Normalize-DoctorFindingMessage([string]$Code,[string]$Message){
    if($Code-eq'hub.state'){
        $m=[regex]::Match($Message,'^STATE identifies Hub v(?<version>[0-9]+(?:\.[0-9]+){1,3})(?: r[0-9]+| \| revision [0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2})\.$')
        if($m.Success){return('STATE identifies Hub v'+$m.Groups['version'].Value+' | revision <display>.')}
    }
    elseif($Code-eq'hub.metadata'){
        $m=[regex]::Match($Message,'^Hub v(?<version>[0-9]+(?:\.[0-9]+){1,3})(?: r[0-9]+| \| revision [0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}) metadata is valid\.$')
        if($m.Success){return('Hub v'+$m.Groups['version'].Value+' | revision <display> metadata is valid.')}
    }
    return $Message
}

function FindingSignature($Report){
    return [string]::Join("`n",@(
        $Report.findings|
        Where-Object{[string]$_.Code-notlike'manager.*'}|
        ForEach-Object{
            $code=[string]$_.Code
            [string]$_.Severity+'|'+$code+'|'+(Normalize-DoctorFindingMessage $code ([string]$_.Message))
        }
    ))
}

function Median([double[]]$Values){
    $s=@($Values|Sort-Object)
    if($s.Count-eq0){return 0.0}
    $mid=[int][math]::Floor($s.Count/2)
    if(($s.Count%2)-eq1){return [double]$s[$mid]}
    return ([double]$s[$mid-1]+[double]$s[$mid])/2.0
}

function Measure-AIContextCoreOnce([string]$ManagerRoot,[string]$OutputDirectory){
    $tool=Join-Path $ManagerRoot 'product\tools\New-KeelarynAIContext.ps1'
    if(-not(Test-Path -LiteralPath $tool -PathType Leaf)){throw('AI_CONTEXT benchmark tool missing: '+$tool)}
    $sw=[System.Diagnostics.Stopwatch]::StartNew()
    & $tool -ManagerRoot $ManagerRoot -OutputDirectory $OutputDirectory 6>$null | Out-Null
    $sw.Stop()
    if(-not(Test-Path -LiteralPath (Join-Path $OutputDirectory 'CONTEXT_MANIFEST.json') -PathType Leaf)){
        throw('AI_CONTEXT core benchmark did not produce CONTEXT_MANIFEST.json: '+$OutputDirectory)
    }
    return [double]$sw.Elapsed.TotalMilliseconds
}

function Median-AbsoluteDeviation([double[]]$Values){
    if(@($Values).Count-eq0){return 0.0}
    $m=Median $Values
    $d=@($Values|ForEach-Object{[math]::Abs([double]$_-$m)})
    return [double](Median $d)
}

function Measure-AIContextCoreRobust([string]$BaselineRoot,[string]$CandidateManagerRoot,[string]$ScratchRoot){
    if(Test-Path -LiteralPath $ScratchRoot){Remove-Item -LiteralPath $ScratchRoot -Recurse -Force}
    New-Item -ItemType Directory -Force -Path $ScratchRoot|Out-Null
    $baseOut=Join-Path $ScratchRoot 'baseline'
    $candOut=Join-Path $ScratchRoot 'candidate'

    # Warm both implementations twice inside this already-running PowerShell host.
    # The release decision therefore excludes powershell.exe startup noise.
    for($w=0;$w-lt2;$w++){
        $null=Measure-AIContextCoreOnce $BaselineRoot $baseOut
        $null=Measure-AIContextCoreOnce $CandidateManagerRoot $candOut
    }

    $baselineValues=New-Object System.Collections.ArrayList
    $candidateValues=New-Object System.Collections.ArrayList
    $blockDeltas=New-Object System.Collections.ArrayList

    $targetBlocks=9
    $maxBlocks=15
    $i=0
    while($i-lt$targetBlocks){
        $block=$i+1
        if(($i%2)-eq0){
            Write-Host ('  AI_CONTEXT ABBA block {0}/{1}: baseline -> candidate -> candidate -> baseline' -f$block,$targetBlocks) -ForegroundColor DarkGray
            $b1=Measure-AIContextCoreOnce $BaselineRoot $baseOut
            $c1=Measure-AIContextCoreOnce $CandidateManagerRoot $candOut
            $c2=Measure-AIContextCoreOnce $CandidateManagerRoot $candOut
            $b2=Measure-AIContextCoreOnce $BaselineRoot $baseOut
        }else{
            Write-Host ('  AI_CONTEXT ABBA block {0}/{1}: candidate -> baseline -> baseline -> candidate' -f$block,$targetBlocks) -ForegroundColor DarkGray
            $c1=Measure-AIContextCoreOnce $CandidateManagerRoot $candOut
            $b1=Measure-AIContextCoreOnce $BaselineRoot $baseOut
            $b2=Measure-AIContextCoreOnce $BaselineRoot $baseOut
            $c2=Measure-AIContextCoreOnce $CandidateManagerRoot $candOut
        }
        [void]$baselineValues.Add([double]$b1);[void]$baselineValues.Add([double]$b2)
        [void]$candidateValues.Add([double]$c1);[void]$candidateValues.Add([double]$c2)
        # Geometric means make the comparison multiplicative and symmetric.
        $b=[math]::Sqrt([double]$b1*[double]$b2)
        $c=[math]::Sqrt([double]$c1*[double]$c2)
        $d=if($b-gt0){(($c/$b)-1.0)*100.0}else{0.0}
        [void]$blockDeltas.Add([double]$d)
        Write-Host ('    baseline_geo={0:N1} ms; candidate_geo={1:N1} ms; block_delta={2:N1}%' -f$b,$c,$d) -ForegroundColor DarkGray
        $i++

        # After nine blocks, extend not only for high dispersion but also when
        # the estimated regression is too close to the +5% release threshold
        # to distinguish from ordinary block-to-block variation.  This avoids
        # treating a few tenths of a percentage point as a deterministic fail.
        if($i-eq9){
            $mad=Median-AbsoluteDeviation @($blockDeltas)
            $medianNow=Median @($blockDeltas)
            $decisionMargin=if($i-gt0){3.1*[double]$mad/[math]::Sqrt([double]$i)}else{0.0}
            $thresholdDistance=[math]::Abs([double]$medianNow-5.0)
            if($mad-gt5.0-or$thresholdDistance-le$decisionMargin){
                $targetBlocks=$maxBlocks
                Write-Host ('  AI_CONTEXT benchmark needs more evidence after 9 blocks (median={0:N2}%; MAD={1:N2} pp; decision_margin={2:N2} pp); extending automatically to {3} blocks.' -f$medianNow,$mad,$decisionMargin,$maxBlocks) -ForegroundColor Yellow
            }
        }
    }

    $medianDelta=Median @($blockDeltas)
    $mad=Median-AbsoluteDeviation @($blockDeltas)
    $decisionMargin=if($blockDeltas.Count-gt0){3.1*[double]$mad/[math]::Sqrt([double]$blockDeltas.Count)}else{0.0}
    return [pscustomobject]@{
        Methodology='in-process generator core; 2 warmups/tree; ABBA/BAAB blocks; geometric within-block means; median block delta; auto-extend 9->15 for high dispersion or threshold ambiguity; conservative MAD/sqrt(n) decision margin'
        Blocks=$blockDeltas.Count
        BaselineMedian=(Median @($baselineValues))
        CandidateMedian=(Median @($candidateValues))
        BlockDeltaMedian=[double]$medianDelta
        BlockDeltaMad=[double]$mad
        DecisionMargin=[double]$decisionMargin
        BaselineValues=@($baselineValues)
        CandidateValues=@($candidateValues)
        BlockDeltas=@($blockDeltas)
    }
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

function Assert-ZipContains([string]$ZipPath,[string[]]$Expected,[string]$Prefix=''){
    $archive=[System.IO.Compression.ZipFile]::OpenRead($ZipPath)
    try{
        $names=@($archive.Entries|ForEach-Object{$_.FullName.Replace('\','/')})
        foreach($rel in $Expected){
            $name=$Prefix+$rel
            if($names-notcontains$name){throw('Release ZIP missing expected path: '+$name)}
        }
    }finally{$archive.Dispose()}
}

function Get-DesktopSnapshot{
    $desktop=[Environment]::GetFolderPath([Environment+SpecialFolder]::DesktopDirectory)
    $snap=Join-Path $runtime '_desktop_shortcut_snapshot'
    if(Test-Path -LiteralPath $snap){Remove-Item -LiteralPath $snap -Recurse -Force}
    New-Item -ItemType Directory -Force -Path $snap|Out-Null
    $rows=New-Object System.Collections.ArrayList
    foreach($name in @('Keelaryn Hub.lnk','Core__Hub.lnk')){
        $src=Join-Path $desktop $name
        $exists=Test-Path -LiteralPath $src -PathType Leaf
        if($exists){Copy-Item -LiteralPath $src -Destination (Join-Path $snap $name) -Force}
        [void]$rows.Add([pscustomobject]@{Name=$name;Existed=$exists})
    }
    return [pscustomobject]@{Desktop=$desktop;Snapshot=$snap;Rows=@($rows)}
}

function Restore-DesktopSnapshot($Snapshot){
    if(-not$Snapshot){return}
    foreach($row in @($Snapshot.Rows)){
        $dst=Join-Path $Snapshot.Desktop ([string]$row.Name)
        if([bool]$row.Existed){
            Copy-Item -LiteralPath (Join-Path $Snapshot.Snapshot ([string]$row.Name)) -Destination $dst -Force
        }elseif(Test-Path -LiteralPath $dst){
            Remove-Item -LiteralPath $dst -Force -ErrorAction SilentlyContinue
        }
    }
}

function New-TestZip([string]$Path,[hashtable]$Entries){
    if(Test-Path -LiteralPath $Path){Remove-Item -LiteralPath $Path -Force}
    $parent=Split-Path -Parent $Path
    if($parent){New-Item -ItemType Directory -Force -Path $parent|Out-Null}
    $stream=New-Object System.IO.FileStream($Path,[System.IO.FileMode]::CreateNew,[System.IO.FileAccess]::ReadWrite,[System.IO.FileShare]::None)
    try{
        $archive=New-Object System.IO.Compression.ZipArchive($stream,[System.IO.Compression.ZipArchiveMode]::Create,$true)
        try{
            foreach($name in @($Entries.Keys|Sort-Object)){
                $entry=$archive.CreateEntry([string]$name,[System.IO.Compression.CompressionLevel]::Optimal)
                $writer=New-Object System.IO.StreamWriter($entry.Open(),(New-Object System.Text.UTF8Encoding($false)))
                try{$writer.Write([string]$Entries[$name])}finally{$writer.Dispose()}
            }
        }finally{$archive.Dispose()}
    }finally{$stream.Dispose()}
}


function Expand-CurrentHubBaseline([string]$CurrentZip,[string]$Destination){
    if(-not(Test-Path -LiteralPath $CurrentZip -PathType Leaf)){throw('CURRENT baseline missing: '+$CurrentZip)}
    $zipItem=Get-Item -LiteralPath $CurrentZip -Force
    if($zipItem.Length-gt50MB){throw 'CURRENT baseline exceeds the Manager Hub ZIP size limit.'}
    if(Test-Path -LiteralPath $Destination){Remove-Item -LiteralPath $Destination -Recurse -Force}
    New-Item -ItemType Directory -Force -Path $Destination|Out-Null
    $destRoot=(Get-Item -LiteralPath $Destination -Force).FullName.TrimEnd('\')+'\'
    $archive=$null
    try{
        $archive=[System.IO.Compression.ZipFile]::OpenRead($CurrentZip)
        if($archive.Entries.Count-gt10000){throw 'CURRENT baseline exceeds the Manager Hub entry limit.'}
        $root=$null
        foreach($candidateRoot in @('Keelaryn__Hub/','Core__Hub/')){
            $stateName=$candidateRoot+'_System/STATE.md'
            if(@($archive.Entries|Where-Object{$_.FullName.Replace('\','/')-ceq$stateName}).Count-eq1){$root=$candidateRoot;break}
        }
        if(-not$root){throw 'CURRENT baseline has an unsupported or ambiguous Hub ZIP root.'}

        $seen=@{}
        [long]$expanded=0
        foreach($entry in $archive.Entries){
            $name=$entry.FullName.Replace('\','/')
            if(-not$name.StartsWith($root,[System.StringComparison]::Ordinal)){
                throw('CURRENT baseline contains an entry outside the Hub root: '+$name)
            }
            $rel=$name.Substring($root.Length).TrimEnd('/')
            if(-not$rel){continue}
            $parts=@($rel.Split('/'))
            if(@($parts|Where-Object{$_-eq''-or$_-eq'.'-or$_-eq'..'-or$_.Contains(':')}).Count-gt0){
                throw('CURRENT baseline contains an unsafe relative path: '+$rel)
            }
            $low=$rel.ToLowerInvariant()
            $leaf=[System.IO.Path]::GetFileName($low)
            if($low-eq'.git'-or$low.StartsWith('.git/')-or
               $low-eq'.obsidian'-or$low.StartsWith('.obsidian/')-or
               @('.ds_store','thumbs.db','desktop.ini')-contains$leaf){continue}
            if($name.EndsWith('/')){continue}

            $expanded+=[long]$entry.Length
            if($expanded-gt250MB){throw 'CURRENT baseline exceeds the Manager Hub expanded-size limit.'}
            $key=$rel.ToLowerInvariant()
            if($seen.ContainsKey($key)){throw('CURRENT baseline contains a duplicate portable path: '+$rel)}
            $seen[$key]=$true

            $target=[System.IO.Path]::GetFullPath((Join-Path $Destination $rel.Replace('/','\')))
            if(-not$target.StartsWith($destRoot,[System.StringComparison]::OrdinalIgnoreCase)){
                throw('CURRENT baseline extraction escaped the disposable Hub root: '+$rel)
            }
            $parent=Split-Path -Parent $target
            if($parent){New-Item -ItemType Directory -Force -Path $parent|Out-Null}
            $input=$entry.Open()
            try{
                $output=New-Object System.IO.FileStream($target,[System.IO.FileMode]::CreateNew,[System.IO.FileAccess]::Write,[System.IO.FileShare]::None)
                try{$input.CopyTo($output)}finally{$output.Dispose()}
            }finally{$input.Dispose()}
        }
    }finally{if($archive){$archive.Dispose()}}
    if(-not(Test-Path -LiteralPath (Join-Path $Destination '_System\STATE.md') -PathType Leaf)){throw 'Extracted CURRENT baseline is missing _System\STATE.md.'}
    return [pscustomobject]@{Root=$root;FileCount=$seen.Count;ExpandedBytes=$expanded}
}


function Assert-TextContains([string]$Text,[string[]]$Tokens,[string]$Context){
    foreach($token in $Tokens){if($Text-notmatch[regex]::Escape($token)){throw($Context+' omitted token: '+$token)}}
}

function Get-UpdateManifest([string]$ZipPath){
    $za=[System.IO.Compression.ZipFile]::OpenRead($ZipPath)
    try{
        $e=@($za.Entries|Where-Object{$_.FullName.Replace('\','/')-ieq'Keelaryn__Manager_Update/manifest.json'})[0]
        if(-not$e){throw 'UPDATE manifest entry missing.'}
        $r=New-Object System.IO.StreamReader($e.Open(),[System.Text.Encoding]::UTF8,$true)
        try{return ($r.ReadToEnd()|ConvertFrom-Json)}finally{$r.Dispose()}
    }finally{$za.Dispose()}
}

function Write-DirectoryZip([string]$SourceRoot,[string]$ZipPath){
    if(Test-Path -LiteralPath $ZipPath){Remove-Item -LiteralPath $ZipPath -Force}
    $root=(Get-Item -LiteralPath $SourceRoot -Force).FullName.TrimEnd('\')
    $fs=New-Object System.IO.FileStream($ZipPath,[System.IO.FileMode]::CreateNew,[System.IO.FileAccess]::ReadWrite,[System.IO.FileShare]::None)
    try{
        $za=New-Object System.IO.Compression.ZipArchive($fs,[System.IO.Compression.ZipArchiveMode]::Create,$true)
        try{
            foreach($f in @(Get-ChildItem -LiteralPath $root -File -Recurse -Force|Sort-Object FullName)){
                $rel=$f.FullName.Substring($root.Length).TrimStart('\').Replace('\','/')
                $entry=$za.CreateEntry($rel,[System.IO.Compression.CompressionLevel]::Optimal)
                $input=[System.IO.File]::OpenRead($f.FullName);$output=$entry.Open()
                try{$input.CopyTo($output)}finally{$output.Dispose();$input.Dispose()}
            }
        }finally{$za.Dispose()}
    }finally{$fs.Dispose()}
}

function New-RollbackFaultUpdate([string]$SourceUpdate,[string]$Destination,[string]$Scratch){
    if(Test-Path -LiteralPath $Scratch){Remove-Item -LiteralPath $Scratch -Recurse -Force}
    New-Item -ItemType Directory -Force -Path $Scratch|Out-Null
    Expand-Archive -LiteralPath $SourceUpdate -DestinationPath $Scratch -Force
    $base=Join-Path $Scratch 'Keelaryn__Manager_Update'
    $install=Join-Path $base 'payload\product\install\INSTALLATION.json'
    $im=(Get-Content -LiteralPath $install -Raw -Encoding UTF8)|ConvertFrom-Json
    $im.manager_version='9.9.9'
    [System.IO.File]::WriteAllText($install,(($im|ConvertTo-Json -Depth 12)+"`n"),(New-Object System.Text.UTF8Encoding($false)))
    $manifestPath=Join-Path $base 'manifest.json'
    $um=(Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8)|ConvertFrom-Json
    $row=@($um.files|Where-Object{([string]$_.path).Replace('\','/')-eq'product/install/INSTALLATION.json'})
    if($row.Count-ne1){throw 'Fault UPDATE installation row missing.'}
    $item=Get-Item -LiteralPath $install -Force
    $row[0].sha256=Sha $install;$row[0].size_bytes=[long]$item.Length
    $hashMap=@{};foreach($r in @($um.files)){$hashMap[([string]$r.path).Replace('\','/').ToLowerInvariant()]=([string]$r.sha256).ToLowerInvariant()}
    $rows=New-Object System.Collections.ArrayList
    foreach($rel in @($um.final_managed_files|ForEach-Object{([string]$_).Replace('\','/')}|Sort-Object)){
        $key=$rel.ToLowerInvariant();if(-not$hashMap.ContainsKey($key)){throw('Fault UPDATE final path missing from transport rows: '+$rel)}
        [void]$rows.Add($rel+"`0"+$hashMap[$key])
    }
    $um.final_content_hash=TextSha([string]::Join("`n",@($rows)))
    [System.IO.File]::WriteAllText($manifestPath,(($um|ConvertTo-Json -Depth 16)+"`n"),(New-Object System.Text.UTF8Encoding($false)))
    Write-DirectoryZip $Scratch $Destination
    return $Destination
}

function Test-IsLocalRelative([string]$Rel){
    $low=$Rel.Replace('\','/').ToLowerInvariant();$leaf=[System.IO.Path]::GetFileName($low)
    return ($low-eq'.git'-or$low.StartsWith('.git/')-or$low-eq'.obsidian'-or$low.StartsWith('.obsidian/')-or@('.ds_store','thumbs.db','desktop.ini')-contains$leaf)
}

function Get-ZipContentDigest([string]$ZipPath){
    $za=[System.IO.Compression.ZipFile]::OpenRead($ZipPath)
    try{
        $rows=New-Object System.Collections.ArrayList;$seen=@{}
        foreach($e in @($za.Entries|Where-Object{-not$_.FullName.EndsWith('/')-and-not$_.FullName.EndsWith('\')})){
            $name=$e.FullName.Replace('\','/').TrimStart('/')
            $slash=$name.IndexOf('/')
            if($slash-lt1-or$slash-ge($name.Length-1)){throw('Candidate fixture ZIP entry lacks a single Hub root: '+$name)}
            $rel=$name.Substring($slash+1)
            if(Test-IsLocalRelative $rel){continue}
            $key=$rel.Normalize([System.Text.NormalizationForm]::FormC).ToLowerInvariant()
            if($seen.ContainsKey($key)){throw('Candidate fixture ZIP contains a duplicate portable path: '+$rel)};$seen[$key]=$true
            $stream=$e.Open();$sha=[System.Security.Cryptography.SHA256]::Create()
            try{$h=[BitConverter]::ToString($sha.ComputeHash($stream)).Replace('-','').ToLowerInvariant()}finally{$sha.Dispose();$stream.Dispose()}
            [void]$rows.Add($rel+"`0"+$h)
        }
        return TextSha([string]::Join("`n",@($rows|Sort-Object)))
    }finally{$za.Dispose()}
}

function New-CandidateFixture([string]$CurrentZip,[string]$Destination,[string]$ArtifactId,[string]$Scratch){
    if(Test-Path -LiteralPath $Scratch){Remove-Item -LiteralPath $Scratch -Recurse -Force}
    $hubDir=Join-Path $Scratch 'Keelaryn__Hub'
    New-Item -ItemType Directory -Force -Path $Scratch|Out-Null
    $null=Expand-CurrentHubBaseline $CurrentZip $hubDir

    # Build a valid alternate worker CANDIDATE for the same Hub revision as CURRENT.
    # ARTIFACT is excluded from the portable payload hash, so changing only ARTIFACT
    # preserves the already-validated STATE / INDEX / ROUTER / VALIDATION / MANIFEST set.
    # This avoids hand-regenerating derived Hub metadata inside the gate fixture while
    # still exercising real candidate transport build, collision and restore contracts.
    $artifactPath=Join-Path $hubDir '_System\ARTIFACT.json'
    $art=(Get-Content -LiteralPath $artifactPath -Raw -Encoding UTF8)|ConvertFrom-Json
    if ([string]$art.schema -ne 'keelaryn.artifact.v3' -or [string]$art.artifact_status -ne 'approved') { throw 'Candidate fixture requires an APPROVED keelaryn.artifact.v3 CURRENT baseline.' }
    if ([int]$art.data_revision -lt 2 -or [int]$art.base_data_revision -ne ([int]$art.data_revision - 1)) { throw 'Candidate fixture CURRENT lineage is not a normal non-genesis revision.' }
    if (-not ([regex]::IsMatch($ArtifactId,'^[A-Za-z0-9][A-Za-z0-9._-]{5,127}$'))) { throw 'Candidate fixture artifact_id is invalid.' }

    $created=(Get-Date).ToUniversalTime().ToString('o')
    $art.artifact_status='candidate'
    $art.artifact_id=$ArtifactId
    $art.producer_role='worker_chat'
    $art.created=$created
    $art|Add-Member -NotePropertyName revision_time_utc -NotePropertyValue $created -Force
    if ($art.PSObject.Properties['accepted_candidates']) { $art.PSObject.Properties.Remove('accepted_candidates') }
    [System.IO.File]::WriteAllText($artifactPath,(($art|ConvertTo-Json -Depth 40)+"`n"),(New-Object System.Text.UTF8Encoding($false)))

    Write-DirectoryZip $Scratch $Destination
    return [pscustomobject]@{Path=$Destination;ArtifactId=$ArtifactId;Revision=[int]$art.data_revision;RevisionTimeUtc=$created;Digest=(Get-ZipContentDigest $Destination)}
}

function Assert-NoArchiveStaging([string]$WorkRoot){
    $left=@(Get-ChildItem -LiteralPath $WorkRoot -Force -ErrorAction SilentlyContinue|Where-Object{$_.Name-like'._unpack_*'-or$_.Name-like'._old_*'})
    if($left.Count-gt0){throw('Archive staging residue remains: '+($left.Name-join', '))}
}

function New-FakeManagerGateArchive([string]$ZipPath,[string]$VersionText){
    $folder='manager-'+$VersionText;$digits=$VersionText.Replace('.','')
    $runner=@"
[CmdletBinding()]
param([string]`$CandidateRoot,[string]`$ProductionRoot)
Write-Host ('FAKE_GATE_CANDIDATE_ROOT='+`$CandidateRoot)
Write-Host ('FAKE_GATE_PRODUCTION_ROOT='+`$ProductionRoot)
Write-Host 'FAKE_GATE_OK'
exit 0
"@
    $entries=@{}
    $entries[$folder+'/Keelaryn__Manager.ps1']='$ManagerVersion = "'+$VersionText+'"'
    $entries[$folder+'/_manager_version.txt']=$VersionText
    $entries[$folder+'/RUN_'+$digits+'_FULL_GATE.cmd']='@echo off'
    $entries[$folder+'/gate/Run-KeelarynManagerFullGate.ps1']=$runner
    New-TestZip $ZipPath $entries
}

try{
    try{Start-Transcript -LiteralPath $transcriptPath -Force|Out-Null;$transcriptStarted=$true}catch{Write-Host ('WARNING: transcript unavailable: '+$_.Exception.Message) -ForegroundColor Yellow}

    $script:CurrentPhase='gate/candidate binding preflight'
    $declaredInstallSha=([string]$gateSpec.candidate_installation_sha256).ToLowerInvariant();$declaredManagedSha=([string]$gateSpec.candidate_managed_content_sha256).ToLowerInvariant()
    if($declaredInstallSha-notmatch'^[0-9a-f]{64}$'-or$declaredManagedSha-notmatch'^[0-9a-f]{64}$'){throw 'Gate spec candidate hash binding is missing or invalid.'}
    if((Sha $candidateInstallPath)-ne$declaredInstallSha){throw 'Gate spec installation-manifest hash does not match candidate bytes.'}
    if((GateSpecManagedDigest $CandidateRoot)-ne$declaredManagedSha){throw 'Gate spec managed-content hash does not match candidate bytes.'}
    if([int]$gateSpec.final_managed_count-ne$candidateManagedCount){throw 'Gate spec final_managed_count does not match candidate installation manifest.'}
    Write-Host ('Gate revision: '+$gateRevision+' (Manager '+$version+' managed='+$declaredManagedSha.Substring(0,12)+')') -ForegroundColor DarkGray

    $script:CurrentPhase='production read-only preflight'
    Write-Host 'Full Gate 0: production read-only preflight' -ForegroundColor Cyan
    foreach($p in @($CandidateRoot,$prodManager,$prodHub,$prodCurrent)){if(-not(Test-Path -LiteralPath $p)){throw('Required path missing: '+$p)}}
    $prodInstall=Read-InstalledManifest $prodManager
    if([string]$prodInstall.manager_version-ne$baseline){throw('Expected production Manager '+$baseline+', found '+[string]$prodInstall.manager_version+'.')}
    if(-not(Test-Path -LiteralPath (Join-Path $prodManager 'state\layout.json') -PathType Leaf)){throw ('Production '+$baseline+' state/layout.json is missing; canonical filesystem baseline is not complete.')}
    $prodManagedBefore=ManagedDigest $prodManager
    $prodCurrentBefore=Sha $prodCurrent
    $prodHubBefore=PortableHubSnapshot $prodHub
    $prodReleasesBefore=TreeDigest (Join-Path $prodManager 'state\releases')
    $prodHistoryBefore=TreeDigest (Join-Path $prodManager 'state\history\manager_releases')
    $prodBindingBefore=TreeDigest (Join-Path $prodManager 'state')
    $summary.phases.production_preflight=$true

    if(Test-Path -LiteralPath $runtime){Remove-Item -LiteralPath $runtime -Recurse -Force}
    New-Item -ItemType Directory -Force -Path $runtime|Out-Null
    $desktopSnapshot=Get-DesktopSnapshot

    $script:CurrentPhase='source / SelfTests / AI_CONTEXT / deterministic release'
    Write-Host 'Full Gate A-C: source / SelfTests / AI_CONTEXT / deterministic release' -ForegroundColor Cyan
    $sourceGate=Join-Path $CandidateRoot 'gate\Run-KeelarynManagerSourceGate.ps1'
    $sourceResult=Invoke-SafeProcess $exe @('-NoProfile','-ExecutionPolicy','Bypass','-File',$sourceGate,'-ManagerRoot',$CandidateRoot) 'SourceGate' 1800 $true
    if($sourceResult.ExitCode-ne0){throw('Source gate failed: '+$sourceResult.ExitCode+'; stderr='+$sourceResult.StdErrPath)}
    $sourceGateResultPath=Join-Path $resultsRoot 'SOURCE_GATE_RESULT.json'
    if(-not(Test-Path -LiteralPath $sourceGateResultPath -PathType Leaf)){throw('SourceGate result missing: '+$sourceGateResultPath)}
    $sourceGateResult=(Get-Content -LiteralPath $sourceGateResultPath -Raw -Encoding UTF8)|ConvertFrom-Json
    if([string]$sourceGateResult.schema-ne'keelaryn.manager-source-gate-result.v1'-or[string]$sourceGateResult.status-ne'passed'){throw 'SourceGate result is not PASS v1.'}
    if([string]$sourceGateResult.candidate_version-ne$version-or[int]$sourceGateResult.gate_revision-ne$gateRevision-or[int]$sourceGateResult.framework_revision-ne$frameworkRevision){throw 'SourceGate result version/revision mismatch.'}
    if([string]$sourceGateResult.gate_spec_sha256-ne(Sha $specPath)){throw 'SourceGate result GATE_SPEC binding mismatch.'}
    if([string]$sourceGateResult.candidate_installation_sha256-ne[string]$gateSpec.candidate_installation_sha256-or[string]$sourceGateResult.candidate_managed_content_sha256-ne[string]$gateSpec.candidate_managed_content_sha256){throw 'SourceGate result candidate binding mismatch.'}
    if([string]$sourceGateResult.release.root_relative-cne'_releases'){throw 'Unsupported SourceGate release-root contract.'}
    $candidateReleases=Join-Path $CandidateRoot ([string]$sourceGateResult.release.root_relative)
    $manifestRel=[string]$sourceGateResult.release.manifest_relative
    if([string]::IsNullOrWhiteSpace($manifestRel)-or[System.IO.Path]::IsPathRooted($manifestRel)-or$manifestRel.Contains('..')){throw 'SourceGate manifest relative path is unsafe.'}
    $candidateManifest=Join-Path $candidateReleases $manifestRel
    if(-not(Test-Path -LiteralPath $candidateManifest -PathType Leaf)-or(Sha $candidateManifest)-ne([string]$sourceGateResult.release.manifest_sha256).ToLowerInvariant()){throw 'SourceGate release manifest evidence mismatch.'}
    $candidateRelease=Read-Release $candidateReleases $version
    foreach($artifactEvidence in @($sourceGateResult.release.artifacts)){
        $rows=@($candidateRelease.artifacts|Where-Object{[string]$_.role-eq[string]$artifactEvidence.role})
        if($rows.Count-ne1-or[string]$rows[0].path-cne[string]$artifactEvidence.path-or[string]$rows[0].sha256-ne[string]$artifactEvidence.sha256){throw('SourceGate/release artifact evidence mismatch: '+[string]$artifactEvidence.role)}
        $artifactPath=Join-Path $candidateReleases ([string]$artifactEvidence.path)
        if(-not(Test-Path -LiteralPath $artifactPath -PathType Leaf)-or(Sha $artifactPath)-ne([string]$artifactEvidence.sha256).ToLowerInvariant()-or[int64](Get-Item -LiteralPath $artifactPath -Force).Length-ne[int64]$artifactEvidence.bytes){throw('SourceGate artifact bytes mismatch: '+[string]$artifactEvidence.role)}
    }
    $updateRows=@($sourceGateResult.release.artifacts|Where-Object{[string]$_.role-eq'update'});if($updateRows.Count-ne1){throw 'SourceGate result UPDATE role missing.'}
    $update=Join-Path $candidateReleases ([string]$updateRows[0].path)
    $updateManifest=Get-UpdateManifest $update
    $summary.phases.source_release=$true

    $script:CurrentPhase='CURRENT-backed disposable '+$baseline+' baseline'
    Write-Host ('Full Gate D: CURRENT-backed disposable baseline '+$baseline) -ForegroundColor Cyan
    Write-Host '  Production Manager/Hub are read-only. All mutable targets are under tests.' -ForegroundColor DarkGray
    $layout=Join-Path $runtime 'keelaryn';$mgr=Join-Path $layout 'manager';$hub=Join-Path $layout 'hub';$disposableTests=Join-Path $layout 'tests'
    New-Item -ItemType Directory -Force -Path $layout,$disposableTests|Out-Null
    $null=Copy-ManagedTree $prodManager $mgr
    $null=Run-Manager $mgr @('-InitializePresentation') $false
    $stateRoot=Join-Path $mgr 'state';$stateInbox=Join-Path $stateRoot 'inbox';$stateCurrent=Join-Path $stateRoot 'baseline\Keelaryn__Hub_CURRENT.zip';$stateReleases=Join-Path $stateRoot 'releases'
    Copy-Item -LiteralPath $prodCurrent -Destination $stateCurrent -Force
    $currentBaseline=Expand-CurrentHubBaseline $prodCurrent $hub
    Write-Host ('  CURRENT baseline: files={0}; expanded={1} bytes' -f$currentBaseline.FileCount,$currentBaseline.ExpandedBytes) -ForegroundColor DarkGray
    $hubBefore=PortableHubDigest $hub;$currentBefore=Sha $stateCurrent
    $null=Run-Manager $mgr @('-BindInstancePath',$hub) $false
    $bindingPath=Join-Path $stateRoot 'binding.json';if(-not(Test-Path -LiteralPath $bindingPath -PathType Leaf)){throw 'Disposable binding was not persisted.'}
    $bindingHashBefore=Sha $bindingPath
    $null=Run-Manager $mgr @('-SelfTest') $true
    $null=Run-Manager $mgr @('-Doctor') $true
    $baselineReport=Get-DoctorReport $mgr
    Copy-Item -LiteralPath (Join-Path $stateRoot 'logs\DOCTOR_REPORT.json') -Destination (Join-Path $doctorRoot ('baseline_'+$baseline+'.json')) -Force
    $baselinePerfMgr=Join-Path $runtime ('baseline_perf_manager_'+$baseline);$null=Copy-ManagedTree $mgr $baselinePerfMgr
    $baselineDigest=ManagedDigest $mgr
    $summary.phases.disposable_baseline=$true

    $script:CurrentPhase='Manager update rollback fault injection'
    Write-Host 'Full Gate D1: transactional Manager update rollback fault injection' -ForegroundColor Cyan
    $probeLayout=Join-Path $runtime 'rollback-probe\keelaryn';$probeMgr=Join-Path $probeLayout 'manager'
    New-Item -ItemType Directory -Force -Path $probeLayout|Out-Null;$null=Copy-ManagedTree $prodManager $probeMgr;$null=Run-Manager $probeMgr @('-InitializePresentation') $false
    $probeBefore=ManagedDigest $probeMgr
    $faultUpdate=Join-Path $runtime ('Keelaryn__Manager_Update_FAULT_v'+$version+'.zip')
    $null=New-RollbackFaultUpdate $update $faultUpdate (Join-Path $runtime 'fault-update-source')
    $faultInbox=Join-Path $probeMgr 'state\inbox';Copy-Item -LiteralPath $faultUpdate -Destination (Join-Path $faultInbox ([System.IO.Path]::GetFileName($faultUpdate))) -Force
    $faultResult=Invoke-ManagerCapture $probeMgr @('-UpdateManager')
    if($faultResult.ExitCode-eq0){throw 'Fault-injection Manager UPDATE unexpectedly succeeded.'}
    if((ManagedDigest $probeMgr)-ne$probeBefore){throw 'Fault-injection rollback did not restore exact baseline managed content.'}
    $probeInstall=Read-InstalledManifest $probeMgr
    if([string]$probeInstall.manager_version -ne $baseline){throw ('Fault-injection rollback did not restore Manager '+$baseline+' version marker.')}
    $probeSnaps=@(Get-ChildItem -LiteralPath (Join-Path $probeMgr 'state\history\manager_updates') -Directory -Force -ErrorAction SilentlyContinue|Sort-Object LastWriteTime -Descending)
    if($probeSnaps.Count-lt1){throw 'Fault-injection update did not create rollback snapshot.'}
    $probeMeta=(Get-Content -LiteralPath (Join-Path $probeSnaps[0].FullName '_snapshot_manifest.json') -Raw -Encoding UTF8)|ConvertFrom-Json
    if([string]$probeMeta.schema-ne'keelaryn.manager.rollback-snapshot.v2'-or[string]$probeMeta.manager_version-ne$baseline){throw 'Fault-injection rollback snapshot schema/version mismatch.'}
    $null=Run-Manager $probeMgr @('-SelfTest') $false
    $summary.update.rollback_verified=$true;$summary.phases.rollback_fault_injection=$true

    $script:CurrentPhase='native Manager update '+$baseline+' -> '+$version
    Write-Host ('Full Gate D2: native disposable update '+$baseline+' -> '+$version) -ForegroundColor Cyan
    $updateDest=Join-Path $stateInbox ([System.IO.Path]::GetFileName($update));Copy-Item -LiteralPath $update -Destination $updateDest -Force
    if((Sha $updateDest)-ne(Sha $update)){throw 'Copied UPDATE hash mismatch.'}
    try{$null=Run-Manager $mgr @('-UpdateManager') $true}finally{Restore-DesktopSnapshot $desktopSnapshot}
    $installed=Read-InstalledManifest $mgr
    if([string]$installed.manager_version -ne $version -or @($installed.managed_files).Count -ne $candidateManagedCount){throw ('Disposable native update did not install canonical Manager '+$version+' managed set.')}
    if((ManagedDigest $mgr)-ne([string]$updateManifest.final_content_hash).ToLowerInvariant()){throw ('Installed '+$version+' managed content differs from UPDATE final_content_hash.')}
    foreach($legacyRoot in @('Keelaryn__Manager.ps1','_manager_manifest.json','_manager_version.txt')){if(Test-Path -LiteralPath (Join-Path $mgr $legacyRoot)){throw('Transition root file leaked into final '+$version+' installation: '+$legacyRoot)}}
    if((PortableHubDigest $hub)-ne$hubBefore){throw 'Manager native update changed disposable Hub.'}
    if((Sha $stateCurrent)-ne$currentBefore){throw 'Manager native update changed disposable CURRENT.'}
    if((Sha $bindingPath)-ne$bindingHashBefore){throw 'Manager native update changed disposable binding.'}
    $normalSnaps=@(Get-ChildItem -LiteralPath (Join-Path $stateRoot 'history\manager_updates') -Directory -Force -ErrorAction Stop|Sort-Object LastWriteTime -Descending)
    if($normalSnaps.Count-lt1){throw 'Native update rollback snapshot missing.'}
    $snapshot=$normalSnaps[0].FullName;$snapshotMeta=(Get-Content -LiteralPath (Join-Path $snapshot '_snapshot_manifest.json') -Raw -Encoding UTF8)|ConvertFrom-Json
    if([string]$snapshotMeta.schema-ne'keelaryn.manager.rollback-snapshot.v2'-or[string]$snapshotMeta.manager_version-ne$baseline){throw 'Native update rollback snapshot schema/version mismatch.'}
    foreach($row in @($snapshotMeta.files)){
        $src=Join-Path $baselinePerfMgr ([string]$row.path).Replace('/','\');if(-not(Test-Path -LiteralPath $src -PathType Leaf)){throw('Snapshot baseline source missing: '+[string]$row.path)}
        if(([string]$row.sha256).ToLowerInvariant()-ne(Sha $src)){throw('Rollback snapshot hash differs from '+$baseline+' baseline: '+[string]$row.path)}
    }
    $summary.update.snapshot_verified=$true;$summary.update.state_preserved=$true;$summary.update.hub_preserved=$true;$summary.phases.native_update=$true

    $script:CurrentPhase='Doctor / migration compatibility'
    Write-Host 'Full Gate D3: SelfTest / Doctor / migration compatibility' -ForegroundColor Cyan
    $null=Run-Manager $mgr @('-SelfTest') $true
    $null=Run-Manager $mgr @('-Doctor') $true
    $candidateReport=Get-DoctorReport $mgr
    if([int]$candidateReport.errors-ne0){throw ('Disposable Manager '+$version+' Doctor reports errors.')}
    Copy-Item -LiteralPath (Join-Path $stateRoot 'logs\DOCTOR_REPORT.json') -Destination (Join-Path $doctorRoot ('candidate_'+$version+'.json')) -Force
    $revisionPattern='\| revision [0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}'
    foreach($code in @('hub.state','hub.metadata')){
        $finding=@($candidateReport.findings|Where-Object{[string]$_.Code-eq$code})
        if($finding.Count-ne1-or[string]$finding[0].Severity-ne'OK'){throw('Candidate Doctor revision finding missing or unhealthy: '+$code)}
        if(([string]$finding[0].Message)-notmatch$revisionPattern){throw('Candidate Doctor did not render immutable revision time for legacy Hub: '+$code+' -> '+[string]$finding[0].Message)}
        if(([string]$finding[0].Message)-match'\br[0-9]+\b'){throw('Candidate Doctor leaked legacy rNNNN as the primary revision display: '+$code)}
    }
    if((FindingSignature $baselineReport)-cne(FindingSignature $candidateReport)){throw ('Stable non-Manager Doctor findings changed across '+$baseline+' -> '+$version+'.')}
    $mig=Run-Manager $mgr @('-CheckMigrations') $false
    if($mig.Text-notmatch'Migration status: up_to_date'){throw 'Disposable production-compatible Hub is not migration up_to_date.'}
    $summary.phases.doctor_migrations=$true

    $script:CurrentPhase='interactive UI / semantic results'
    Write-Host 'Full Gate E: UI / semantic result / submenu contracts' -ForegroundColor Cyan
    $menuTool=Join-Path $mgr 'product\tools\KeelarynMenu.ps1';$archiveTool=Join-Path $mgr 'product\tools\Unpack-KeelarynTestArchive.ps1'
    $null=Run-Tool $menuTool @('-SelfTest','-NoRootLauncher') $false;$summary.ux.frontend_selftest=$true
    $null=Run-Tool $archiveTool @('-SelfTest') $false;$summary.ux.archive_tool_selftest=$true
    $render=Invoke-ToolCapture $menuTool @('-Action','RenderMain','-NoRootLauncher');if($render.ExitCode-ne0){throw 'RenderMain failed.'}
    Assert-TextContains $render.Text @(('Keelaryn Manager '+$version),'Everyday','[5] Installation info','[7] Development','[0] Exit') 'RenderMain';$summary.ux.menu_render=$true
    $doctorUi=Invoke-SafeProcess $exe @('-NoProfile','-ExecutionPolicy','Bypass','-File',$menuTool,'-NoRootLauncher') 'Interactive Doctor' 300 $false "2`r`n`r`n0`r`n"
    if($doctorUi.ExitCode-ne0){throw 'Interactive Doctor path failed.'};Assert-TextContains $doctorUi.Text @(('Keelaryn Doctor - Manager '+$version),'COMPLETED','[Enter] Back') 'Interactive Doctor';$summary.ux.interactive_doctor=$true
    $infoUi=Invoke-SafeProcess $exe @('-NoProfile','-ExecutionPolicy','Bypass','-File',$menuTool,'-NoRootLauncher') 'Interactive InstallationInfo' 180 $false "5`r`n`r`n0`r`n"
    if($infoUi.ExitCode-ne0){throw 'Interactive Installation info path failed.'};Assert-TextContains $infoUi.Text @('Keelaryn installation',('Version: '+$version),'Revision:','Revision UTC:','Legacy sequence:','Binding source:','Instance ID:','COMPLETED') 'Installation info';$summary.ux.interactive_installation_info=$true
    $updateUi=Invoke-SafeProcess $exe @('-NoProfile','-ExecutionPolicy','Bypass','-File',$menuTool,'-NoRootLauncher') 'Interactive UpdateAll no-op' 180 $false "4`r`n`r`n0`r`n"
    if($updateUi.ExitCode-ne0){throw 'Interactive UpdateAll no-op path failed.'};Assert-TextContains $updateUi.Text @('Manager: no pending update.','Hub: no APPROVED update.','NO CHANGES REQUIRED') 'UpdateAll no-op';$summary.ux.interactive_update_all=$true
    $subUi=Invoke-SafeProcess $exe @('-NoProfile','-ExecutionPolicy','Bypass','-File',$menuTool,'-NoRootLauncher') 'Interactive submenus' 180 $false "6`r`n0`r`n7`r`n0`r`n8`r`n0`r`n0`r`n"
    if($subUi.ExitCode-ne0){throw 'Interactive submenu navigation failed.'};Assert-TextContains $subUi.Text @('Repair Hub CURRENT','Check migrations','Run Full Gate...','Run test package...','Compatibility / legacy migration...','Repair root launcher') 'Submenu navigation';$summary.ux.submenu_navigation=$true
    $summary.phases.ui_orchestration=$true

    $script:CurrentPhase='archive planning / hidden-prompt / Full Gate frontend'
    Write-Host 'Full Gate E2: archive orchestration / hidden-prompt regression' -ForegroundColor Cyan
    $profileLeaf='ux-profile-'+$version;$profileLauncher='RUN_UX_PROFILE_'+$version.Replace('.','')+'.cmd';$profileZip=Join-Path $runtime ($profileLeaf+'.zip')
    $profileEntries=@{};$profileEntries[$profileLeaf+'/'+$profileLauncher]='@echo off';$profileEntries[$profileLeaf+'/data.txt']='Keelaryn UX profile fixture';New-TestZip $profileZip $profileEntries
    $fresh=Invoke-ToolCapture $archiveTool @('-ZipPath',$profileZip,'-TestsRoot',$disposableTests,'-NonInteractive','-NoAutoRun');if($fresh.ExitCode-ne0){throw 'Fresh non-interactive archive unpack failed.'}
    $profileOut=Join-Path $disposableTests ('work\'+$profileLeaf);if(-not(Test-Path -LiteralPath (Join-Path $profileOut $profileLauncher) -PathType Leaf)){throw 'Fresh archive destination missing launcher.'};Assert-NoArchiveStaging (Join-Path $disposableTests 'work');$summary.ux.archive_fresh=$true
    $profileDigest=TreeDigest $profileOut
    $hidden=Invoke-ToolCapture $archiveTool @('-ZipPath',$profileZip,'-TestsRoot',$disposableTests,'-NonInteractive','-NoAutoRun');if($hidden.ExitCode-ne3){throw('Existing destination non-interactive child returned '+$hidden.ExitCode+' instead of 3.')};Assert-TextContains $hidden.Text @('Existing work folder requires explicit replacement.') 'Non-interactive archive child';if((TreeDigest $profileOut)-ne$profileDigest){throw 'Non-interactive decline changed existing workspace.'};Assert-NoArchiveStaging (Join-Path $disposableTests 'work');$summary.ux.archive_child_noninteractive=$true
    $decline=Invoke-ToolCapture $menuTool @('-Action','UnpackTest','-Path',$profileZip,'-NoRootLauncher')
    if($decline.ExitCode-ne3){throw('Frontend archive direct-action decline exit mismatch: '+$decline.ExitCode+'; output='+$decline.Text)};Assert-TextContains $decline.Text @('Cancelled. Existing work folder left untouched.') 'Frontend archive direct-action decline';if((TreeDigest $profileOut)-ne$profileDigest){throw 'Frontend direct-action decline changed existing workspace.'};Assert-NoArchiveStaging (Join-Path $disposableTests 'work');$summary.ux.archive_decline=$true
    $replace=Invoke-ToolCapture $menuTool @('-Action','UnpackTest','-Path',$profileZip,'-Replace','-NoRootLauncher')
    if($replace.ExitCode-ne0){throw('Frontend archive explicit replace failed: '+$replace.ExitCode+'; output='+$replace.Text)};Assert-NoArchiveStaging (Join-Path $disposableTests 'work');$summary.ux.archive_replace=$true
    $badZip=Join-Path $runtime ('unsafe-profile-'+$version+'.zip');New-TestZip $badZip @{'../escape.txt'='blocked'}
    $bad=Invoke-ToolCapture $archiveTool @('-ZipPath',$badZip,'-TestsRoot',$disposableTests,'-NonInteractive','-NoAutoRun');if($bad.ExitCode-eq0){throw 'Archive tool accepted ZIP traversal.'};if(Test-Path -LiteralPath (Join-Path $disposableTests 'escape.txt')){throw 'Traversal fixture escaped tests/work.'};Assert-NoArchiveStaging (Join-Path $disposableTests 'work');$summary.ux.archive_traversal_rejected=$true
    $fakeZip=Join-Path $runtime 'manager-9.9.9.zip';New-FakeManagerGateArchive $fakeZip '9.9.9';$fakeDest=Join-Path $disposableTests 'work\manager-9.9.9';if(Test-Path -LiteralPath $fakeDest){Remove-Item -LiteralPath $fakeDest -Recurse -Force}
    $fake=Invoke-ToolCapture $menuTool @('-Action','RunFullGate','-Path',$fakeZip,'-NoRootLauncher');if($fake.ExitCode-ne0){throw('Manager-driven Full Gate delegation failed: '+$fake.ExitCode)}
    Assert-TextContains $fake.Text @('FAKE_GATE_OK',('FAKE_GATE_CANDIDATE_ROOT='+$fakeDest),('FAKE_GATE_PRODUCTION_ROOT='+$layout)) 'Manager-driven Full Gate delegation';$summary.ux.full_gate_frontend_delegation=$true
    $summary.phases.archive_orchestration=$true

    $script:CurrentPhase='migration no-op / binding preview / candidate transport'
    Write-Host 'Full Gate E3: applicability preflight / candidate transport' -ForegroundColor Cyan
    $migUi=Invoke-ToolCapture $menuTool @('-Action','ApplyMigrations','-NoRootLauncher');if($migUi.ExitCode-ne0){throw('ApplyMigrations up-to-date frontend failed: '+$migUi.ExitCode)};Assert-TextContains $migUi.Text @('No migrations required.') 'Migration no-op';if($migUi.Text-match'Apply these migrations\?'){throw 'Zero-pending migration frontend asked for confirmation.'};$summary.ux.migration_noop=$true

    # Build a disposable manager-safe migration probe. Its copy suppresses global Obsidian shutdown so the gate never disturbs production applications.
    $migLayout=Join-Path $runtime 'migration-probe\keelaryn';$migMgr=Join-Path $migLayout 'manager';$migHub=Join-Path $migLayout 'hub';$migTests=Join-Path $migLayout 'tests'
    New-Item -ItemType Directory -Force -Path $migLayout,$migTests|Out-Null;$null=Copy-ManagedTree $mgr $migMgr;$null=Run-Manager $migMgr @('-InitializePresentation') $false
    $migState=Join-Path $migMgr 'state';$migCurrent=Join-Path $migState 'baseline\Keelaryn__Hub_CURRENT.zip';Copy-Item -LiteralPath $stateCurrent -Destination $migCurrent -Force
    $null=Expand-CurrentHubBaseline $stateCurrent $migHub;$null=Run-Manager $migMgr @('-BindInstancePath',$migHub) $false
    $migRuntime=Join-Path $migMgr 'product\runtime\Keelaryn__Manager.ps1';$migRuntimeText=[System.IO.File]::ReadAllText($migRuntime,[System.Text.Encoding]::ASCII)
    $closePattern='(?s)function Close-ObsidianIfNeeded \{.*?\r?\n\}\r?\n\r?\nfunction Assert-FreeSpace'
    if(([regex]::Matches($migRuntimeText,$closePattern)).Count-ne1){throw 'Migration probe could not isolate Close-ObsidianIfNeeded.'}
    $migRuntimeText=[regex]::Replace($migRuntimeText,$closePattern,"function Close-ObsidianIfNeeded { return `$true }`r`n`r`nfunction Assert-FreeSpace",1)
    [System.IO.File]::WriteAllText($migRuntime,$migRuntimeText,[System.Text.Encoding]::ASCII)
    $migStateBefore=[System.IO.File]::ReadAllText((Join-Path $migHub '_System\STATE.md'),[System.Text.Encoding]::UTF8)
    $migSystemMatch=[regex]::Match($migStateBefore,'(?m)^system_version:\s*([0-9]+\.[0-9]+\.[0-9]+)\s*$')
    if(-not$migSystemMatch.Success){throw 'Migration probe could not resolve Hub system_version.'}
    $fromSystem=[version]$migSystemMatch.Groups[1].Value;$fromSystemText=$fromSystem.ToString(3);$targetSystemText=($fromSystem.Major.ToString()+'.'+($fromSystem.Minor+1).ToString()+'.0')
    $probeMigrationId='gate-system-'+$fromSystemText+'-to-'+$targetSystemText;$probeSpecLeaf='gate_'+$fromSystemText+'_to_'+$targetSystemText+'.json'
    $releasePath=Join-Path $migMgr 'product\release.json';$probeRelease=(Get-Content -LiteralPath $releasePath -Raw -Encoding UTF8)|ConvertFrom-Json
    if(-not$probeRelease.PSObject.Properties['system_version']-or-not$probeRelease.PSObject.Properties['release_id']){throw 'Migration probe release metadata lacks required system_version/release_id properties.'}
    $probeRelease.system_version=$targetSystemText;$probeRelease.release_id='keelaryn-system-'+$targetSystemText;[System.IO.File]::WriteAllText($releasePath,(($probeRelease|ConvertTo-Json -Depth 20)+"`n"),(New-Object System.Text.UTF8Encoding($false)))
    $registryPath=Join-Path $migMgr 'product\migrations\index.json';$probeRegistry=(Get-Content -LiteralPath $registryPath -Raw -Encoding UTF8)|ConvertFrom-Json
    if(-not$probeRegistry.PSObject.Properties['system_version']-or-not$probeRegistry.PSObject.Properties['migrations']){throw 'Migration probe registry lacks required system_version/migrations properties.'}
    $probeStep=[pscustomobject]@{id=$probeMigrationId;from_system_version=$fromSystemText;to_system_version=$targetSystemText;apply_mode='manager_safe';spec=$probeSpecLeaf};$probeRegistry.system_version=$targetSystemText;$probeRegistry.migrations=@($probeStep);[System.IO.File]::WriteAllText($registryPath,(($probeRegistry|ConvertTo-Json -Depth 20)+"`n"),(New-Object System.Text.UTF8Encoding($false)))
    $probeSpec=[ordered]@{schema='keelaryn.migration.v1';id=$probeMigrationId;from_system_version=$fromSystemText;to_system_version=$targetSystemText;apply_mode='manager_safe';requires_full_reconciliation=$false;reason='Disposable Full Gate manager-safe migration fixture.';operations=@()};$probeSpecPath=Join-Path $migMgr ('product\migrations\'+$probeSpecLeaf);[System.IO.File]::WriteAllText($probeSpecPath,(($probeSpec|ConvertTo-Json -Depth 20)+"`n"),(New-Object System.Text.UTF8Encoding($false)))
    $migMenu=Join-Path $migMgr 'product\tools\KeelarynMenu.ps1';$migHubBefore=PortableHubDigest $migHub;$migCurrentBefore=Sha $migCurrent
    $migDecline=Invoke-ToolCapture $migMenu @('-Action','ApplyMigrations','-NoRootLauncher')
    if($migDecline.ExitCode-ne2){throw('Pending migration direct-action decline exit mismatch: '+$migDecline.ExitCode+'; output='+$migDecline.Text)};Assert-TextContains $migDecline.Text @('Pending migrations: 1',($probeMigrationId+': '+$fromSystemText+' -> '+$targetSystemText),'Explicit confirmation is required for direct migration apply.','Cancelled. No changes made.') 'Pending migration direct-action preview';if((PortableHubDigest $migHub)-ne$migHubBefore-or(Sha $migCurrent)-ne$migCurrentBefore){throw 'Declined migration changed disposable Hub/CURRENT.'};$summary.ux.migration_preview_decline=$true
    $migApply=Invoke-ToolCapture $migMenu @('-Action','ApplyMigrations','-ConfirmChanges','-NoRootLauncher')
    if($migApply.ExitCode-ne0){throw('Disposable manager-safe migration failed: '+$migApply.ExitCode+' '+$migApply.Text)};Assert-TextContains $migApply.Text @('Pending migrations: 1','Registered system migration chain applied.') 'Migration apply'
    $migStateText=[System.IO.File]::ReadAllText((Join-Path $migHub '_System\STATE.md'),[System.Text.Encoding]::UTF8);$targetPattern='(?m)^system_version:\s*'+[regex]::Escape($targetSystemText)+'\s*$';if($migStateText-notmatch$targetPattern){throw('Disposable migration did not advance Hub system_version to '+$targetSystemText+'.')};$migArt=(Get-Content -LiteralPath (Join-Path $migHub '_System\ARTIFACT.json') -Raw -Encoding UTF8)|ConvertFrom-Json;if(-not$migArt.revision_time_utc){throw 'Disposable migration did not emit revision_time_utc.'};$migRt=[DateTimeOffset]::Parse([string]$migArt.revision_time_utc);if($migRt.Offset-ne[TimeSpan]::Zero){throw 'Disposable migration revision_time_utc is not UTC.'};$summary.ux.migration_apply=$true

    $bindingBefore=Sha $bindingPath;$bindUi=Invoke-ToolCapture $menuTool @('-Action','BindInstance','-Path',$hub,'-NoRootLauncher')
    if($bindUi.ExitCode-ne2){throw('Binding direct-action decline exit mismatch: '+$bindUi.ExitCode+'; output='+$bindUi.Text)};Assert-TextContains $bindUi.Text @('Current Hub:','New Hub:','Explicit confirmation is required for direct binding changes.','Cancelled. Binding unchanged.') 'Binding preview';if((Sha $bindingPath)-ne$bindingBefore){throw 'Binding decline changed binding bytes.'};$summary.ux.binding_preview_cancel=$true
    foreach($f in @(Get-ChildItem -LiteralPath $stateInbox -File -Force -ErrorAction SilentlyContinue)){Remove-Item -LiteralPath $f.FullName -Force}
    $none1=Invoke-ToolCapture $menuTool @('-Action','BuildCandidateTransport','-NoRootLauncher');$none2=Invoke-ToolCapture $menuTool @('-Action','RestoreCandidateTransport','-NoRootLauncher')
    if($none1.ExitCode-ne0-or$none2.ExitCode-ne0){throw 'Candidate transport no-input frontend is not a no-op.'};Assert-TextContains $none1.Text @('No Hub CANDIDATE is available. Nothing to build.') 'Candidate no-input';Assert-TextContains $none2.Text @('No Hub CANDIDATE transport is available. Nothing to restore.') 'Transport no-input';$summary.ux.candidate_no_input=$true
    $invalid=Join-Path $stateInbox 'Keelaryn__Hub_CANDIDATE_invalid.zip';[System.IO.File]::WriteAllBytes($invalid,[byte[]](1,2,3,4));$invalidResult=Invoke-ManagerCapture $mgr @('-BuildCandidateTransport');if($invalidResult.ExitCode-eq0){throw 'Invalid Hub CANDIDATE unexpectedly built a transport.'};if(-not(Test-Path -LiteralPath $invalid -PathType Leaf)){throw 'Invalid CANDIDATE rejection removed source unexpectedly.'};Remove-Item -LiteralPath $invalid -Force;$summary.ux.candidate_invalid_rejected=$true
    $candA=New-CandidateFixture $stateCurrent (Join-Path $stateInbox 'Keelaryn__Hub_CANDIDATE_gate-a.zip') ('cand-gate-a-'+$version.Replace('.','')+'000') (Join-Path $runtime 'candidate-a-src')
    Start-Sleep -Milliseconds 20
    $candB=New-CandidateFixture $stateCurrent (Join-Path $stateInbox 'Keelaryn__Hub_CANDIDATE_gate-b.zip') ('cand-gate-b-'+$version.Replace('.','')+'000') (Join-Path $runtime 'candidate-b-src')
    $buildCand=Run-Manager $mgr @('-BuildCandidateTransport') $true
    $transportFiles=@(Get-ChildItem -LiteralPath $stateInbox -File -Filter 'Keelaryn__Hub_CANDIDATE_TRANSPORT_*.json'|Sort-Object Name);if($transportFiles.Count-ne2){throw('Expected two candidate transport JSONs, got '+$transportFiles.Count)};$summary.ux.candidate_multi_build=$true
    $savedCand=Join-Path $runtime 'saved-candidates';New-Item -ItemType Directory -Force -Path $savedCand|Out-Null
    Move-Item -LiteralPath $candA.Path -Destination (Join-Path $savedCand 'a.zip');Move-Item -LiteralPath $candB.Path -Destination (Join-Path $savedCand 'b.zip')
    $destA=Join-Path $stateInbox ('Keelaryn__Hub_CANDIDATE_RECONSTRUCTED_'+$candA.ArtifactId+'.zip');[System.IO.File]::WriteAllText($destA,'collision',(New-Object System.Text.UTF8Encoding($false)))
    $collision=Invoke-ManagerCapture $mgr @('-RestoreCandidateTransport');if($collision.ExitCode-eq0){throw 'Candidate restore collision unexpectedly succeeded.'};if([System.IO.File]::ReadAllText($destA)-ne'collision'){throw 'Candidate restore collision modified existing destination.'};Remove-Item -LiteralPath $destA -Force
    $restoreCand=Run-Manager $mgr @('-RestoreCandidateTransport') $true
    $destB=Join-Path $stateInbox ('Keelaryn__Hub_CANDIDATE_RECONSTRUCTED_'+$candB.ArtifactId+'.zip')
    if(-not(Test-Path -LiteralPath $destA -PathType Leaf)-or-not(Test-Path -LiteralPath $destB -PathType Leaf)){throw 'Candidate restore did not reconstruct both candidate ZIPs.'}
    if((Get-ZipContentDigest $destA) -ne [string]$candA.Digest -or (Get-ZipContentDigest $destB) -ne [string]$candB.Digest){throw 'Reconstructed candidate ZIP content differs from source fixture.'}
    $summary.ux.candidate_restore=$true;$summary.phases.candidate_transport=$true
    foreach($f in @(Get-ChildItem -LiteralPath $stateInbox -File -Force -ErrorAction SilentlyContinue)){Remove-Item -LiteralPath $f.FullName -Force}

    $script:CurrentPhase='CURRENT repair contract'
    Write-Host 'Full Gate E4: disposable CURRENT repair contract' -ForegroundColor Cyan
    $za=[System.IO.Compression.ZipFile]::Open($stateCurrent,[System.IO.Compression.ZipArchiveMode]::Update)
    try{$entry=$za.CreateEntry('Keelaryn__Hub/.obsidian/keelaryn-gate-local-state.txt',[System.IO.Compression.CompressionLevel]::Optimal);$writer=New-Object System.IO.StreamWriter($entry.Open(),(New-Object System.Text.UTF8Encoding($false)));try{$writer.Write('disposable gate local state')}finally{$writer.Dispose()}}finally{$za.Dispose()}
    $null=Run-Manager $mgr @('-RepairCurrentTransport') $true
    $checkArchive=[System.IO.Compression.ZipFile]::OpenRead($stateCurrent);try{if(@($checkArchive.Entries|Where-Object{$_.FullName.Replace('\','/').StartsWith('Keelaryn__Hub/.obsidian/',[System.StringComparison]::OrdinalIgnoreCase)}).Count-ne0){throw 'RepairCurrentTransport left local deployment state in CURRENT.'}}finally{$checkArchive.Dispose()}
    $null=Run-Manager $mgr @('-Doctor') $false;$repairedReport=Get-DoctorReport $mgr;if((FindingSignature $candidateReport)-cne(FindingSignature $repairedReport)){throw 'CURRENT repair changed Doctor findings.'}
    $summary.phases.current_repair=$true

    $script:CurrentPhase='AI_CONTEXT performance control'
    Write-Host 'Full Gate F: BUILD_AI_CONTEXT robust paired performance control' -ForegroundColor Cyan
    $benchScratch=Join-Path $runtime 'ai_context_core_benchmark';$robustAI=Measure-AIContextCoreRobust $baselinePerfMgr $mgr $benchScratch
    $aggregateDelta=if($robustAI.BaselineMedian-gt0){(($robustAI.CandidateMedian/$robustAI.BaselineMedian)-1.0)*100.0}else{0.0}
    Write-Host ('  baseline={0:N1} ms; candidate={1:N1} ms; robust_delta={2:N1}%; MAD={3:N1} pp; margin={4:N1} pp' -f$robustAI.BaselineMedian,$robustAI.CandidateMedian,$robustAI.BlockDeltaMedian,$robustAI.BlockDeltaMad,$robustAI.DecisionMargin)
    $summary.ai_context_performance=[ordered]@{methodology=$robustAI.Methodology;blocks=$robustAI.Blocks;baseline_ms=[math]::Round($robustAI.BaselineMedian,1);candidate_ms=[math]::Round($robustAI.CandidateMedian,1);raw_sample_delta_pct=[math]::Round($aggregateDelta,2);robust_block_delta_median_pct=[math]::Round($robustAI.BlockDeltaMedian,2);block_delta_mad_pp=[math]::Round($robustAI.BlockDeltaMad,2);decision_margin_pp=[math]::Round($robustAI.DecisionMargin,2)}
    if($robustAI.BlockDeltaMad-gt8.0){throw('AI_CONTEXT benchmark inconclusive: MAD='+[math]::Round($robustAI.BlockDeltaMad,2)+' pp.')}
    $perfLower=[double]$robustAI.BlockDeltaMedian-[double]$robustAI.DecisionMargin;$perfUpper=[double]$robustAI.BlockDeltaMedian+[double]$robustAI.DecisionMargin
    if($perfLower-gt5.0){throw('AI_CONTEXT regression credibly exceeds 5%: '+[math]::Round($robustAI.BlockDeltaMedian,2)+'%.')}
    if($perfUpper-gt5.0){throw('AI_CONTEXT benchmark threshold remains ambiguous around +5%.')}
    $summary.phases.ai_context_performance=$true

    $script:CurrentPhase='installed release / generic distribution / Genesis'
    Write-Host 'Full Gate G: installed release / generic distribution contracts' -ForegroundColor Cyan
    $null=Run-Manager $mgr @('-BuildRelease') $true
    $installedRelease=Read-Release $stateReleases $version
    $sourceRow=@($installedRelease.artifacts|Where-Object{[string]$_.role-eq'source'})[0];$distRow=@($installedRelease.artifacts|Where-Object{[string]$_.role-eq'distribution'})[0];$installedUpdateRow=@($installedRelease.artifacts|Where-Object{[string]$_.role-eq'update'})[0]
    $expected=@('KEELARYN.cmd','product/install/INSTALLATION.json','product/runtime/Keelaryn__Manager.ps1','compat/commands/DOCTOR.cmd','product/tools/KeelarynMenu.ps1','product/tools/Unpack-KeelarynTestArchive.ps1','product/docs/USER_INTERFACE.md')
    Assert-ZipContains (Join-Path $stateReleases ([string]$sourceRow.path)) $expected 'keelaryn/manager/'
    Assert-ZipContains (Join-Path $stateReleases ([string]$installedUpdateRow.path)) $expected 'Keelaryn__Manager_Update/payload/'
    Assert-ZipContains (Join-Path $stateReleases ([string]$installedUpdateRow.path)) @('Keelaryn__Manager.ps1','_manager_manifest.json','_manager_version.txt') 'Keelaryn__Manager_Update/payload/'
    $null=Run-Manager $mgr @('-BuildDistribution') $true
    $genericDist=Join-Path $stateReleases ('Keelaryn__Manager_Distribution_v'+$version+'.zip');if(-not(Test-Path -LiteralPath $genericDist -PathType Leaf)){throw 'Generic distribution ZIP missing.'};Assert-ZipContains $genericDist @('Keelaryn.cmd') 'keelaryn/';$summary.ux.generic_distribution=$true
    $distSmoke=Join-Path $runtime 'generic-distribution-smoke';if(Test-Path -LiteralPath $distSmoke){Remove-Item -LiteralPath $distSmoke -Recurse -Force};New-Item -ItemType Directory -Force -Path $distSmoke|Out-Null;Expand-Archive -LiteralPath $genericDist -DestinationPath $distSmoke -Force
    $freshLayout=Join-Path $distSmoke 'keelaryn';$freshMgr=Join-Path $freshLayout 'manager';$null=Run-Manager $freshMgr @('-SelfTest') $false;$null=Run-Manager $freshMgr @('-InitializePresentation') $false
    $freshVisible=@(Get-ChildItem -LiteralPath $freshMgr -Force|Where-Object{($_.Attributes-band[System.IO.FileAttributes]::Hidden)-eq0}|ForEach-Object{$_.Name}|Sort-Object);$freshExpected=@(@('compat','KEELARYN.cmd','product','README_FIRST.md','state')|Sort-Object)
    if([string]::Join('|',$freshVisible)-cne[string]::Join('|',$freshExpected)){throw('Fresh distribution root view mismatch: '+($freshVisible-join', '))};$summary.ux.generic_distribution_smoke=$true
    Write-Host 'Full Gate G2: disposable Genesis / explicit-confirmation / existing-target rejection' -ForegroundColor Cyan
    $freshMenu=Join-Path $freshMgr 'product\tools\KeelarynMenu.ps1'
    $genConfig=Join-Path $runtime ('genesis-config-'+$version+'.json')
    $genConfigDoc=[ordered]@{schema='keelaryn.genesis-input.v1';language='en';purpose='mixed';timezone='UTC';areas=@();projects=@()}
    [System.IO.File]::WriteAllText($genConfig,(($genConfigDoc|ConvertTo-Json -Depth 6)+"`n"),(New-Object System.Text.UTF8Encoding($false)))
    $freshHub=Join-Path $freshLayout 'hub';$freshCurrent=Join-Path $freshMgr 'state\baseline\Keelaryn__Hub_CURRENT.zip'
    $genDecline=Invoke-ToolCapture $freshMenu @('-Action','Genesis','-Path',$genConfig,'-NoRootLauncher')
    if($genDecline.ExitCode-ne2){throw('Direct Genesis decline exit mismatch: '+$genDecline.ExitCode+'; output='+$genDecline.Text)}
    Assert-TextContains $genDecline.Text @('Target Hub:','CURRENT transport:','Explicit confirmation is required for direct Genesis.','Cancelled. No changes made.') 'Direct Genesis decline'
    if((Test-Path -LiteralPath $freshHub)-or(Test-Path -LiteralPath $freshCurrent)){throw 'Declined direct Genesis created Hub or CURRENT.'}
    $summary.ux.genesis_direct_decline=$true
    $gen=Invoke-ToolCapture $freshMenu @('-Action','Genesis','-Path',$genConfig,'-ConfirmChanges','-NoRootLauncher')
    if($gen.ExitCode-ne0){throw('Disposable Genesis failed: '+$gen.ExitCode+'; output='+$gen.Text)}
    Assert-TextContains $gen.Text @('Target Hub:','CURRENT transport:','Genesis complete.') 'Disposable Genesis'
    $freshArt=(Get-Content -LiteralPath (Join-Path $freshHub '_System\ARTIFACT.json') -Raw -Encoding UTF8)|ConvertFrom-Json
    if([int]$freshArt.data_revision-ne1-or-not$freshArt.revision_time_utc){throw 'Genesis did not create revision 1 with revision_time_utc.'};$rt=[DateTimeOffset]::Parse([string]$freshArt.revision_time_utc);if($rt.Offset-ne[TimeSpan]::Zero){throw 'Genesis revision_time_utc is not UTC.'}
    $null=Run-Manager $freshMgr @('-Doctor') $false;$freshHubDigest=PortableHubDigest $freshHub
    $genAgain=Invoke-ToolCapture $freshMenu @('-Action','Genesis','-Path',$genConfig,'-ConfirmChanges','-NoRootLauncher')
    if($genAgain.ExitCode-eq0){throw 'Genesis existing-target rejection unexpectedly succeeded.'};Assert-TextContains $genAgain.Text @('Target Hub:','CURRENT transport:','Genesis refused:') 'Genesis existing-target rejection';if((PortableHubDigest $freshHub)-ne$freshHubDigest){throw 'Rejected Genesis changed existing Hub.'}
    $summary.ux.genesis=$true;$summary.ux.genesis_existing_target_rejected=$true;$summary.phases.genesis=$true;$summary.phases.installed_release_distribution=$true

    $script:CurrentPhase='production immutability'
    Write-Host 'Full Gate H: production unchanged' -ForegroundColor Cyan
    Restore-DesktopSnapshot $desktopSnapshot
    if((ManagedDigest $prodManager)-ne$prodManagedBefore){throw 'Production Manager managed content changed during disposable gate.'}
    if((Sha $prodCurrent)-ne$prodCurrentBefore){throw 'Production CURRENT changed during disposable gate.'}
    if((TreeDigest (Join-Path $prodManager 'state\releases'))-ne$prodReleasesBefore){throw 'Production Manager releases changed during disposable gate.'}
    if((TreeDigest (Join-Path $prodManager 'state\history\manager_releases'))-ne$prodHistoryBefore){throw 'Production Manager release history changed during disposable gate.'}
    $prodHubAfter=PortableHubSnapshot $prodHub
    if($prodHubAfter.Digest-ne$prodHubBefore.Digest){
        $hubChanges=@(Compare-PortableHubSnapshots $prodHubBefore $prodHubAfter);$summary.production_hub_observed_change=[ordered]@{before_digest=$prodHubBefore.Digest;after_digest=$prodHubAfter.Digest;changed_count=$hubChanges.Count;changes=@($hubChanges)}
        Write-Host 'WARNING: production Hub changed concurrently; gate did not execute or mutate it.' -ForegroundColor Yellow
    }else{$summary.production_hub_observed_change=[ordered]@{before_digest=$prodHubBefore.Digest;after_digest=$prodHubAfter.Digest;changed_count=0;changes=@()}}
    $summary.production_execution_isolated=$true;$summary.production_unchanged=$true;$summary.phases.production_immutability=$true

    $summary.status='passed'
    if(-not$summary.completed){$summary.completed=(Get-Date).ToUniversalTime().ToString('o')}
    [System.IO.File]::WriteAllText($summaryPath,($summary|ConvertTo-Json -Depth 12),(New-Object System.Text.UTF8Encoding($false)))
    $publisher=Join-Path $gateSupportRoot 'Publish-KeelarynTestedArtifacts.ps1'
    if(-not(Test-Path -LiteralPath $publisher -PathType Leaf)){throw('Tested-artifact publisher missing: '+$publisher)}
    & $publisher -CandidateRoot $CandidateRoot -ResultsRoot $resultsRoot -SourceGateResultPath $sourceGateResultPath -GateSummaryPath $summaryPath | ForEach-Object{Write-Host ([string]$_)}
    $testedReleasePath=Join-Path $resultsRoot 'artifacts\TESTED_RELEASE.json'
    $testedInstallerPath=Join-Path $resultsRoot 'artifacts\INSTALL_TESTED_MANAGER_UPDATE.cmd'
    $testedUpdateRows=@($sourceGateResult.release.artifacts|Where-Object{[string]$_.role-eq'update'})
    $testedUpdatePath=Join-Path (Join-Path $resultsRoot 'artifacts') (Split-Path ([string]$testedUpdateRows[0].path) -Leaf)
    foreach($required in @($testedReleasePath,$testedInstallerPath,$testedUpdatePath)){if(-not(Test-Path -LiteralPath $required -PathType Leaf)){throw('Tested artifact publication incomplete: '+$required)}}
    $summary.tested_artifacts=[ordered]@{update=$testedUpdatePath;metadata=$testedReleasePath;installer=$testedInstallerPath}
    [System.IO.File]::WriteAllText($summaryPath,($summary|ConvertTo-Json -Depth 12),(New-Object System.Text.UTF8Encoding($false)))
    Write-Host ''
    foreach($p in @($summary.phases.Keys)){Write-Host ('{0,-30} PASS' -f$p)}
    Write-Host ''
    Write-Host 'FULL GATE: PASS' -ForegroundColor Green
    Write-Host ('Candidate: Manager '+$version)
    Write-Host ('Workspace: '+$CandidateRoot)
    Write-Host ('Results: '+$resultsRoot)
    Write-Host ('Production install package: '+$testedUpdatePath) -ForegroundColor Green
    Write-Host ('One-click production installer: '+$testedInstallerPath) -ForegroundColor Green
    Write-Host 'Production Manager: unchanged' -ForegroundColor Green
    Write-Host 'Production Hub: not used as a mutable test target' -ForegroundColor Green
}
catch{
    $summary.status='failed';$summary.failure=[ordered]@{phase=$script:CurrentPhase;check=$_.Exception.Message}
    Write-Host ''
    Write-Host 'FULL GATE: FAIL' -ForegroundColor Red
    Write-Host ('Failed phase: '+$script:CurrentPhase) -ForegroundColor Red
    Write-Host ('Failed check: '+$_.Exception.Message) -ForegroundColor Red
    Write-Host 'Production Manager: gate uses read-only production paths only.' -ForegroundColor Yellow
    Write-Host 'Production Hub: gate never uses the live Hub as a mutable test target.' -ForegroundColor Yellow
    Write-Host ('Results: '+$resultsRoot)
    throw
}
finally{
    $summary.completed=(Get-Date).ToUniversalTime().ToString('o')
    try{[System.IO.File]::WriteAllText($summaryPath,($summary|ConvertTo-Json -Depth 12),(New-Object System.Text.UTF8Encoding($false)))}catch{}
    if($desktopSnapshot){Restore-DesktopSnapshot $desktopSnapshot}
    if($summary.status-eq'passed'-and(Test-Path -LiteralPath $runtime)){Remove-Item -LiteralPath $runtime -Recurse -Force -ErrorAction SilentlyContinue}
    if($transcriptStarted){try{Stop-Transcript|Out-Null}catch{}}
}
