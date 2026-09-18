[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$ManagerRoot,
    [Parameter(Mandatory=$true)][string]$OutputDirectory
)
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
$script:Utf8NoBom=New-Object System.Text.UTF8Encoding($false)
function Write-Utf8NoBom{param([string]$Path,[string]$Text);$parent=[System.IO.Path]::GetDirectoryName($Path);if($parent -and -not [System.IO.Directory]::Exists($parent)){[void][System.IO.Directory]::CreateDirectory($parent)};[System.IO.File]::WriteAllText($Path,$Text,$script:Utf8NoBom)}
function Get-TextSha256{param([string]$Text);$bytes=[System.Text.Encoding]::UTF8.GetBytes($Text);$sha=[System.Security.Cryptography.SHA256]::Create();try{return([BitConverter]::ToString($sha.ComputeHash($bytes)).Replace('-','').ToLowerInvariant())}finally{$sha.Dispose()}}
function Get-FileSha256{param([string]$Path);$stream=[System.IO.File]::OpenRead($Path);$sha=[System.Security.Cryptography.SHA256]::Create();try{return([BitConverter]::ToString($sha.ComputeHash($stream)).Replace('-','').ToLowerInvariant())}finally{$sha.Dispose();$stream.Dispose()}}
function Get-ManagedSourceItem{param([string]$Path);$item=Get-Item -LiteralPath $Path -Force -ErrorAction Stop;if($item.PSIsContainer-or($item.Attributes-band[System.IO.FileAttributes]::ReparsePoint)-ne0){throw('Unsafe managed source item: '+$Path)};return $item}
function ConvertTo-StableJson{param($Value,[int]$Depth=20);return(($Value|ConvertTo-Json -Depth $Depth).Replace("`r`n","`n")+"`n")}
function Write-ValidatedMarkdown{param([string]$Path,$Lines,[int]$MinimumLineFeeds);$sb=New-Object System.Text.StringBuilder;$lineCount=0;foreach($line in @($Lines)){$s=[string]$line;if($s.Contains([string][char]10)-or$s.Contains([string][char]13)){throw('AI context Markdown line record contains embedded newline: '+$Path)};[void]$sb.Append($s);[void]$sb.Append([char]10);$lineCount++};if($lineCount-lt$MinimumLineFeeds){throw('AI context Markdown has too few explicit line records: '+$Path+'; line_count='+$lineCount)};$text=$sb.ToString();$lfCount=0;foreach($ch in $text.ToCharArray()){if([int]$ch-eq10){$lfCount++}};if($lfCount-ne$lineCount){throw('AI context Markdown line-feed invariant failed: '+$Path+'; lines='+$lineCount+' lf_count='+$lfCount)};if($text.Contains([string][char]13)){throw('AI context Markdown must use deterministic LF line endings: '+$Path)};Write-Utf8NoBom $Path $text;$roundTrip=[System.IO.File]::ReadAllText($Path,[System.Text.Encoding]::UTF8);if($roundTrip-cne$text){throw('AI context Markdown round-trip mismatch: '+$Path)}}
function Test-IsNestedFunctionAst{param($FunctionAst);$p=$FunctionAst.Parent;while($p){if($p -is [System.Management.Automation.Language.FunctionDefinitionAst]){return $true};$p=$p.Parent};return $false}
function Get-NestedFunctionNames{param($FunctionAst);$r=@();foreach($n in @($FunctionAst.FindAll({param($node)$node -is [System.Management.Automation.Language.FunctionDefinitionAst]},$true))){if($n-ne$FunctionAst){$r+=[string]$n.Name}};return @($r|Sort-Object -Unique)}
function Test-IsWindowsReservedSegment{param([string]$Segment);if(-not$Segment){return $false};$trimmed=([string]$Segment).TrimEnd([char[]]@(' ','.'));$dot=$trimmed.IndexOf('.');$stem=if($dot-ge0){$trimmed.Substring(0,$dot)}else{$trimmed};$stem=$stem.ToUpperInvariant().Replace([string][char]0x00B9,'1').Replace([string][char]0x00B2,'2').Replace([string][char]0x00B3,'3');if(@('CON','PRN','AUX','NUL','CLOCK$','CONIN$','CONOUT$')-contains$stem){return $true};return $stem-match'^COM[1-9]$'-or$stem-match'^LPT[1-9]$'}
function Test-SafeManagedRelativePath{param([string]$RelativePath);if([System.IO.Path]::IsPathRooted($RelativePath)){return $false};$rel=$RelativePath.Replace('\','/').Trim('/');if(-not$rel-or$rel.Contains(':')-or$rel.Length-gt512){return $false};foreach($seg in @($rel-split'/')){if(-not$seg-or$seg-eq'.'-or$seg-eq'..'-or$seg.Length-gt180-or$seg.EndsWith(' ')-or$seg.EndsWith('.')-or$seg-match'[<>"|?*\x00-\x1F]'-or(Test-IsWindowsReservedSegment $seg)){return $false}};return $true}

$root=(Resolve-Path -LiteralPath $ManagerRoot).Path.TrimEnd('\');$scriptPath=Join-Path $root 'product\runtime\Keelaryn__Manager.ps1';$installPath=Join-Path $root 'product\install\INSTALLATION.json';$policyPath=Join-Path $root 'product\manager_release.json';$releasePath=Join-Path $root 'product\release.json';$readmePath=Join-Path $root 'README_FIRST.md'
foreach($q in @($scriptPath,$installPath,$policyPath,$releasePath,$readmePath)){if(-not(Test-Path -LiteralPath $q -PathType Leaf)){throw('AI context preflight missing source: '+$q)}}
$im=(Get-Content -LiteralPath $installPath -Raw -Encoding UTF8)|ConvertFrom-Json;$version=([string]$im.manager_version).Trim();$runtimeHash=Get-FileSha256 $scriptPath;$source=[System.IO.File]::ReadAllText($scriptPath,[System.Text.Encoding]::UTF8);$runtimeTextHash=Get-TextSha256 $source;if($runtimeTextHash-cne$runtimeHash){throw('AI context runtime source/hash binding mismatch. file='+$runtimeHash+' decoded='+$runtimeTextHash)};$tokens=$null;$errors=$null;$ast=[System.Management.Automation.Language.Parser]::ParseInput($source,[ref]$tokens,[ref]$errors);if(@($errors).Count){throw(($errors|ForEach-Object{$_.Message})-join'; ')}
$policy=(Get-Content -LiteralPath $policyPath -Raw -Encoding UTF8)|ConvertFrom-Json;$release=(Get-Content -LiteralPath $releasePath -Raw -Encoding UTF8)|ConvertFrom-Json;$readme=[System.IO.File]::ReadAllText($readmePath,[System.Text.Encoding]::UTF8);$sm=[regex]::Match($source,'(?m)^\$ManagerVersion\s*=\s*"([^"]+)"\s*$');$rm=[regex]::Match($readme,'(?m)^# Keelaryn Manager\s+([^\s]+)\s*$')
if(-not$sm.Success-or-not$rm.Success-or$sm.Groups[1].Value-ne$version-or$rm.Groups[1].Value-ne$version){throw 'AI context preflight found inconsistent runtime/README version markers.'};if([string]$im.schema-ne'keelaryn.manager.installation.v2'-or[string]$im.manager_version-ne$version-or[int]$im.layout_version-ne2){throw 'AI context preflight found inconsistent canonical installation manifest.'};if([string]$policy.schema-ne'keelaryn.manager.release-policy.v1'-or[string]$policy.manager_version-ne$version-or[string]$policy.native_update_schema-ne'keelaryn.manager.update.v2'){throw 'AI context preflight found inconsistent Manager release policy.'};try{if([version]([string]$policy.update_min_version)-gt[version]$version){throw 'impossible'}}catch{throw 'AI context preflight found invalid update floor.'};if([string]$release.schema-ne'keelaryn.system-release.v1'){throw 'AI context preflight found inconsistent system release.'}
$managed=@($im.managed_files|ForEach-Object{([string]$_).Replace('\','/')});$seen=@{};$managedItems=@{};$prefix=[System.IO.Path]::GetFullPath($root).TrimEnd('\')+'\';foreach($rel in $managed){if(-not(Test-SafeManagedRelativePath $rel)){throw('Unsafe managed path: '+$rel)};$key=$rel.Normalize([System.Text.NormalizationForm]::FormC).ToLowerInvariant();if($seen.ContainsKey($key)){throw('Duplicate/Unicode-colliding managed path: '+$rel)};$seen[$key]=$true;$full=[System.IO.Path]::GetFullPath((Join-Path $root $rel.Replace('/','\')));if(-not$full.StartsWith($prefix,[System.StringComparison]::OrdinalIgnoreCase)-or-not(Test-Path -LiteralPath $full -PathType Leaf)){throw('Managed source unavailable: '+$rel)};$item=Get-ManagedSourceItem $full;if($item.Length-gt64MB){throw('Unsafe managed source: '+$rel)};$managedItems[$key]=$item}
$preflightSourceHashes=@{}
$managedCanonicalPaths=@{}
foreach($rel in $managed){
    $key=$rel.Normalize([System.Text.NormalizationForm]::FormC).ToLowerInvariant()
    $preflightSourceHashes[$key]=Get-FileSha256 $managedItems[$key].FullName
    $managedCanonicalPaths[$key]=$rel
}
$runtimeKey='product/runtime/Keelaryn__Manager.ps1'.Normalize([System.Text.NormalizationForm]::FormC).ToLowerInvariant()
if([string]$preflightSourceHashes[$runtimeKey]-cne$runtimeHash){throw('Canonical runtime changed between initial SHA binding and managed-source preflight. expected='+$runtimeHash+' actual='+[string]$preflightSourceHashes[$runtimeKey])}
$badKeywordAdjacencyPattern='\b(?:return|throw|exit|break|continue)[$@\[]';$badBooleanGluePattern='\)-and-not\(';foreach($rel in $managed){if([System.IO.Path]::GetExtension($rel)-ieq'.ps1'){$managedPsText=if($rel-eq'product/runtime/Keelaryn__Manager.ps1'){$source}else{[System.IO.File]::ReadAllText((Join-Path $root $rel.Replace('/','\')),[System.Text.Encoding]::UTF8)};if($managedPsText-match'[^\x00-\x7F]'){throw('Windows PowerShell 5.1-compatible managed .ps1 source must be ASCII-only: '+$rel)};if($managedPsText-match$badKeywordAdjacencyPattern-or$managedPsText-match$badBooleanGluePattern){throw('Unsafe PowerShell lexical adjacency in managed source: '+$rel)}}}
if(Test-Path -LiteralPath $OutputDirectory){Remove-Item -LiteralPath $OutputDirectory -Recurse -Force};New-Item -ItemType Directory -Force -Path $OutputDirectory|Out-Null;$functionsDir=Join-Path $OutputDirectory 'functions';$runtimeDir=Join-Path $OutputDirectory 'runtime';$routesDir=Join-Path $OutputDirectory 'routes';$managedDir=Join-Path $OutputDirectory 'managed';New-Item -ItemType Directory -Force -Path $functionsDir,$runtimeDir,$routesDir,$managedDir|Out-Null
foreach($rel in @($managed|Sort-Object)){if($rel-eq'product/runtime/Keelaryn__Manager.ps1'){continue};$src=Join-Path $root $rel.Replace('/','\');$dst=Join-Path $managedDir $rel.Replace('/','\');$parent=[System.IO.Path]::GetDirectoryName($dst);if($parent -and -not [System.IO.Directory]::Exists($parent)){[void][System.IO.Directory]::CreateDirectory($parent)};[System.IO.File]::Copy($src,$dst,$true)}
# Runtime slice invariant: AST and slicing use the same explicitly decoded UTF-8 string; each slice must exactly equal Extent.Text.
$all=@($ast.FindAll({param($node)$node -is [System.Management.Automation.Language.FunctionDefinitionAst]},$true));$top=@($all|Where-Object{-not(Test-IsNestedFunctionAst $_)}|Sort-Object{$_.Extent.StartOffset});if(-not$top){throw 'No top-level functions.'};$nameSet=@{};foreach($f in $top){$nameSet[[string]$f.Name]=[string]$f.Name};$raw=@{};$functionByteSizes=@{}
foreach($f in $top){$name=[string]$f.Name;$startOffset=[int]$f.Extent.StartOffset;$endOffset=[int]$f.Extent.EndOffset;if($startOffset-lt0-or$endOffset-lt$startOffset-or$endOffset-gt$source.Length){throw('Invalid AST extent for function: '+$name)};$text=$source.Substring($startOffset,$endOffset-$startOffset);if($text-cne[string]$f.Extent.Text){throw('AI context AST extent/text mismatch for function: '+$name)};$calls=New-Object System.Collections.ArrayList;$nested=New-Object System.Collections.ArrayList;foreach($node in @($f.FindAll({param($n)($n -is [System.Management.Automation.Language.CommandAst])-or($n -is [System.Management.Automation.Language.FunctionDefinitionAst])},$true))){if($node -is [System.Management.Automation.Language.FunctionDefinitionAst]){if($node-ne$f){[void]$nested.Add([string]$node.Name)};continue};$called=$node.GetCommandName();if($called-and$called-ne$name-and$nameSet.ContainsKey([string]$called)){[void]$calls.Add([string]$nameSet[[string]$called])}};$calls=@($calls|Sort-Object -Unique);$nested=@($nested|Sort-Object -Unique);$slice='functions/'+$name+'.ps1';Write-Utf8NoBom (Join-Path $OutputDirectory $slice.Replace('/','\')) $text;$raw[$name]=[ordered]@{name=$name;start_line=[int]$f.Extent.StartLineNumber;end_line=[int]$f.Extent.EndLineNumber;line_count=[int]$f.Extent.EndLineNumber-[int]$f.Extent.StartLineNumber+1;sha256=Get-TextSha256 $text;slice=$slice;calls=$calls;called_by=@();nested_functions=@($nested)};$functionByteSizes[$name]=[long][System.Text.Encoding]::UTF8.GetByteCount($text)}
foreach($name in @($raw.Keys)){foreach($called in @($raw[$name].calls)){if($raw.ContainsKey($called)){$raw[$called].called_by+=$name}}};$rows=New-Object System.Collections.ArrayList;foreach($f in $top){$r=$raw[[string]$f.Name];$r.called_by=@($r.called_by|Sort-Object -Unique);[void]$rows.Add([pscustomobject]$r)}
$first=$top[0];$last=$top[-1];$preamble=$source.Substring(0,[int]$first.Extent.StartOffset);$dispatch=$source.Substring([int]$last.Extent.EndOffset);Write-Utf8NoBom (Join-Path $runtimeDir 'PREAMBLE.ps1') $preamble;Write-Utf8NoBom (Join-Path $runtimeDir 'DISPATCH.ps1') $dispatch;$segments=New-Object System.Collections.ArrayList;[void]$segments.Add([ordered]@{kind='preamble';slice='runtime/PREAMBLE.ps1';sha256=Get-TextSha256 $preamble})
for($i=0;$i-lt$top.Count;$i++){$f=$top[$i];$name=[string]$f.Name;[void]$segments.Add([ordered]@{kind='function';name=$name;slice='functions/'+$name+'.ps1';sha256=[string]$raw[$name].sha256});if($i-lt$top.Count-1){$next=$top[$i+1];$start=[int]$f.Extent.EndOffset;$len=[int]$next.Extent.StartOffset-$start;if($len-gt0){$gap=$source.Substring($start,$len);$g=('runtime/GLOBAL_GAP_{0:D3}.ps1'-f($i+1));Write-Utf8NoBom (Join-Path $OutputDirectory $g.Replace('/','\')) $gap;[void]$segments.Add([ordered]@{kind='global_gap';slice=$g;sha256=Get-TextSha256 $gap})}}};[void]$segments.Add([ordered]@{kind='dispatch';slice='runtime/DISPATCH.ps1';sha256=Get-TextSha256 $dispatch});$sb=New-Object System.Text.StringBuilder;foreach($seg in @($segments)){[void]$sb.Append([System.IO.File]::ReadAllText((Join-Path $OutputDirectory ([string]$seg.slice).Replace('/','\')),[System.Text.Encoding]::UTF8))};$rebuiltRuntime=$sb.ToString();$rebuiltRuntimeHash=Get-TextSha256 $rebuiltRuntime;if($rebuiltRuntimeHash-ne$runtimeTextHash){throw('AI context runtime segmentation is not lossless. expected='+$runtimeTextHash+' actual='+$rebuiltRuntimeHash+' source_chars='+$source.Length+' rebuilt_chars='+$rebuiltRuntime.Length)}
$routes=[ordered]@{manager_update=@('Read-ManagerUpdatePackage','Find-ManagerUpdateDecision','Install-ManagerPackage','Restore-ManagerSnapshot','Invoke-Update','Complete-PendingFilesystemLogHandoff');hub_update=@('Get-ValidHubPackages','Find-HubUpdateDecision','Install-HubPackage','Invoke-Update');candidate_transport=@('Invoke-BuildCandidateTransport','Invoke-RestoreCandidateTransport','New-CandidateTransportDocument','Read-CandidateTransportDocument','Restore-CandidateTransportDocument','New-CandidateTransportOperations','Apply-CandidateTransportOperations','Assert-CandidateTransportRelativePath','Assert-CandidateTransportInboxOutputPath','Read-HubZipEntryBytes','Expand-HubZipPortableToDirectory','Get-ValidatedHubTransportIdentity','Write-CandidateTransportJsonAtomic');package_security=@('Assert-KeelarynArchiveEntrySafety','Test-ZipEnvelope','Read-ManagerUpdatePackage','Get-HubZipEnvelope');hub_integrity=@('Test-CanonicalBaselineConsistent','Get-ZipHashPair','Get-VaultHashPairAt','New-PortableSourceManifest');release_build=@('Invoke-BuildRelease','Invoke-BuildDistribution','Write-DeterministicZip','Get-TransitionRootBootstrapText','Test-TransitionRootBootstrapSelfTest','Get-ManagerReleaseSourceSnapshot','Write-ManagerReleaseSnapshotFile','Convert-ManagerReleaseBytesToText');doctor=@('Invoke-Doctor','Get-VaultManifestDiagnostic');genesis=@('Invoke-Genesis','New-GenesisItemPlan','Assert-GenesisPlanDoesNotCollideWithTemplates','Expand-GenesisTemplate');migrations=@('Resolve-MigrationChain','Invoke-OneRegisteredMigration','Invoke-CheckMigrations','Invoke-ApplyMigrations','Invoke-AdoptInstanceIdentity','Invoke-MigrateLegacyNamespace','Invoke-MigrateLayout','Invoke-FinalizeLayout');ai_context=@('Invoke-BuildAIContext','Invoke-BuildRelease');transaction_safety=@('Publish-CompletedFileAtomically','Assert-CurrentHubSnapshotUnchanged','Install-HubPackage','Restore-ManagerSnapshot','Install-ManagerPackage');lock_diagnostics=@('Test-IsTransientFileLockException','Initialize-RestartManagerInterop','Get-RestartManagerLockOwners','Format-FileLockOwnerDiagnostic','New-FileLockDiagnosticException','Wait-FileReadyForAtomicReplace','Write-ManagerLogLine','Publish-CompletedFileAtomically');performance_hashing=@('Get-TextHashHex','Get-StreamHashHex','Get-BytesHashHex','Get-SafeTreeFileInventory','Get-PortableVaultFileInventory','Get-ZipHashPair','Get-VaultHashPairAt','Add-HubContentHashes','Invoke-Doctor');path_safety=@('Test-IsWindowsReservedPathSegment','Get-SafeTreeFileInventory','Test-ManagerManagedPath','Test-ZipEnvelope');tests_workspace=@('Initialize-TestsWorkspaceAt','Invoke-PrepareTests','Test-TestsWorkspaceSelfTest');user_interface=@('Initialize-ManagerPresentationState','Set-ManagerOperationalPaths','Assert-ManagerOperationalPathsReady','Complete-PendingFilesystemLogHandoff','Invoke-FinalizeFilesystemLayout','Get-GeneratedCompatibilityCommandText','Get-GeneratedLayoutRootLauncherText','Ensure-LayoutRootLauncherBestEffort');repository_model=@('Set-ManagerOperationalPaths','Assert-ManagerOperationalPathsReady','Complete-PendingFilesystemLogHandoff','Invoke-FinalizeFilesystemLayout','Test-FinalFilesystemLayout','Test-ManagerManagedPath','Get-InstalledManagedPaths','Invoke-BuildDistribution','Invoke-BuildRelease')}
$routeFiles=[ordered]@{manager_update=@('product/install/INSTALLATION.json','product/manager_release.json','product/docs/OPERATIONS.md');hub_update=@('product/docs/OPERATIONS.md','product/governance/hub/_System/PROTOCOL.md');candidate_transport=@('product/docs/CANDIDATE_TRANSPORT.md','product/docs/PRIVACY_AND_RELEASE.md','product/docs/ARCHITECTURE.md','product/docs/OPERATIONS.md','product/docs/AI_DEVELOPMENT.md');package_security=@('product/docs/PRIVACY_AND_RELEASE.md');hub_integrity=@('product/governance/hub/_System/PROTOCOL.md');release_build=@('product/install/INSTALLATION.json','product/manager_release.json','product/release.json','product/docs/RELEASE_BUILD.md');doctor=@('product/docs/OPERATIONS.md');genesis=@('product/docs/GENESIS_AND_ONBOARDING.md','product/docs/ARCHITECTURE.md','product/release.json','product/starter/hub/_System/GENESIS.md','product/governance/hub/_System/BOOTSTRAP.md');migrations=@('product/docs/MIGRATIONS.md','product/docs/LAYOUT.md','product/migrations/index.json','product/migrations/README.md');ai_context=@('product/docs/AI_DEVELOPMENT.md','product/tools/New-KeelarynAIContext.ps1');transaction_safety=@('product/docs/ARCHITECTURE.md','product/docs/OPERATIONS.md');lock_diagnostics=@('product/docs/ARCHITECTURE.md','product/docs/OPERATIONS.md','product/docs/AI_DEVELOPMENT.md');performance_hashing=@('product/docs/ARCHITECTURE.md','product/tools/New-KeelarynAIContext.ps1');path_safety=@('product/docs/PRIVACY_AND_RELEASE.md');tests_workspace=@('product/docs/TESTING.md','product/docs/LAYOUT.md','product/docs/AI_DEVELOPMENT.md','product/tools/Unpack-KeelarynTestArchive.ps1');user_interface=@('KEELARYN.cmd','product/tools/KeelarynMenu.ps1','product/tools/Unpack-KeelarynTestArchive.ps1','product/docs/USER_INTERFACE.md','product/docs/OPERATIONS.md');repository_model=@('product/docs/REPOSITORY_MODEL.md','product/docs/ARCHITECTURE.md','product/docs/PRIVACY_AND_RELEASE.md')}
$routeRows=[ordered]@{}
foreach($route in $routes.Keys){
    $configuredEntries=@($routes[$route]|ForEach-Object{[string]$_})
    if($configuredEntries.Count-eq0){throw('AI context route has no entry functions: '+$route)}
    $entrySet=New-Object 'System.Collections.Generic.HashSet[string]' ([System.StringComparer]::Ordinal)
    $entryList=New-Object 'System.Collections.Generic.List[string]'
    foreach($entry in $configuredEntries){
        if(-not ($raw.ContainsKey($entry))){throw('AI context route entry function missing: route='+$route+' function='+$entry)}
        $canonicalEntry=[string]$raw[$entry].name
        if(-not ($entrySet.Add($canonicalEntry))){throw('AI context route entry function duplicated after canonicalization: route='+$route+' function='+$entry)}
        [void]$entryList.Add($canonicalEntry)
    }
    $entries=@($entryList)

    $directSet=New-Object 'System.Collections.Generic.HashSet[string]' ([System.StringComparer]::Ordinal)
    foreach($entry in $entries){
        foreach($called in @($raw[$entry].calls)){
            if(-not ($raw.ContainsKey([string]$called))){throw('AI context route direct dependency is absent from function map: route='+$route+' function='+[string]$called)}
            if(-not ($entrySet.Contains([string]$called))){[void]$directSet.Add([string]$called)}
        }
    }

    $closureSet=New-Object 'System.Collections.Generic.HashSet[string]' ([System.StringComparer]::Ordinal)
    $queue=New-Object 'System.Collections.Generic.Queue[string]'
    foreach($entry in $entries){if($closureSet.Add($entry)){$queue.Enqueue($entry)}}
    while($queue.Count-gt0){
        $current=$queue.Dequeue()
        foreach($called in @($raw[$current].calls)){
            $dependency=[string]$called
            if(-not ($raw.ContainsKey($dependency))){throw('AI context route dependency is absent from function map: route='+$route+' caller='+$current+' dependency='+$dependency)}
            if($closureSet.Add($dependency)){$queue.Enqueue($dependency)}
        }
    }

    foreach($fn in @($closureSet)){
        foreach($called in @($raw[[string]$fn].calls)){
            if(-not ($closureSet.Contains([string]$called))){throw('AI context route transitive closure invariant failed: route='+$route+' caller='+[string]$fn+' missing='+[string]$called)}
        }
    }

    $recommendedList=New-Object 'System.Collections.Generic.List[string]'
    foreach($fn in @($closureSet)){[void]$recommendedList.Add([string]$fn)}
    $recommendedList.Sort([System.StringComparer]::Ordinal)
    $recommended=@($recommendedList)

    $directList=New-Object 'System.Collections.Generic.List[string]'
    foreach($fn in @($directSet)){[void]$directList.Add([string]$fn)}
    $directList.Sort([System.StringComparer]::Ordinal)
    $directDependencies=@($directList)

    $transitiveList=New-Object 'System.Collections.Generic.List[string]'
    foreach($fn in $recommended){
        if((-not ($entrySet.Contains($fn)))-and(-not ($directSet.Contains($fn)))){[void]$transitiveList.Add($fn)}
    }
    $transitiveDependencies=@($transitiveList)

    if($recommended.Count-ne($entries.Count+$directDependencies.Count+$transitiveDependencies.Count)){
        throw('AI context route closure accounting mismatch: route='+$route)
    }

    $configuredRelated=@($routeFiles[$route]|ForEach-Object{[string]$_})
    $related=New-Object System.Collections.ArrayList
    $relatedKeys=New-Object 'System.Collections.Generic.HashSet[string]' ([System.StringComparer]::Ordinal)
    foreach($rel in $configuredRelated){
        $key=$rel.Normalize([System.Text.NormalizationForm]::FormC).ToLowerInvariant()
        if(-not ($seen.ContainsKey($key))){throw('AI context route related managed file missing: route='+$route+' file='+$rel)}
        if(-not ($relatedKeys.Add($key))){throw('AI context route related managed file duplicated: route='+$route+' file='+$rel)}
        $canonicalRel=[string]$managedCanonicalPaths[$key]
        if($canonicalRel-cne$rel){throw('AI context route related managed file casing/path mismatch: route='+$route+' configured='+$rel+' canonical='+$canonicalRel)}
        [void]$related.Add($canonicalRel)
    }

    $runtimeBytes=0
    foreach($fn in $recommended){$runtimeBytes += [long]$functionByteSizes[$fn]}

    $routeRows[$route]=[ordered]@{
        entry_functions=$entries
        entry_function_count=$entries.Count
        direct_dependencies=$directDependencies
        direct_dependency_count=$directDependencies.Count
        transitive_dependencies=$transitiveDependencies
        transitive_dependency_count=$transitiveDependencies.Count
        recommended_functions=$recommended
        recommended_function_count=$recommended.Count
        related_managed_files=@($related)
        recommended_runtime_bytes=$runtimeBytes
    }

    $bundle=New-Object System.Collections.ArrayList
    [void]$bundle.Add('# Keelaryn Manager '+$version+' - route: '+$route)
    [void]$bundle.Add('')
    [void]$bundle.Add('Runtime SHA-256: `'+$runtimeHash+'`.')
    [void]$bundle.Add('')
    [void]$bundle.Add('This route is an index, not a duplicate code bundle. Load the complete transitive internal dependency closure listed below plus the referenced managed files.')
    [void]$bundle.Add('')
    [void]$bundle.Add('Entry function slices:')
    foreach($entry in $entries){[void]$bundle.Add('- `functions/'+$entry+'.ps1`')}
    [void]$bundle.Add('')
    [void]$bundle.Add('Recommended function slices (complete transitive closure):')
    foreach($fn in $recommended){[void]$bundle.Add('- `functions/'+$fn+'.ps1`')}
    [void]$bundle.Add('')
    [void]$bundle.Add('Related managed files:')
    foreach($rel in @($related)){[void]$bundle.Add('- `managed/'+$rel+'`')}
    [void]$bundle.Add('')
    [void]$bundle.Add('Closure counts: entry='+$entries.Count+'; direct_dependencies='+$directDependencies.Count+'; deeper_transitive_dependencies='+$transitiveDependencies.Count+'; recommended_total='+$recommended.Count+'.')
    [void]$bundle.Add('Approximate recommended runtime bytes: '+$runtimeBytes+'.')
    Write-ValidatedMarkdown (Join-Path $routesDir ($route+'.md')) $bundle 10
}
$paramRows=@()
if($ast.ParamBlock){foreach($q in @($ast.ParamBlock.Parameters)){$paramRows += [ordered]@{name=[string]$q.Name.VariablePath.UserPath;text=[string]$q.Extent.Text}}}
$fm=[ordered]@{schema='keelaryn.ai-context.function-map.v4';manager_version=$version;runtime_sha256=$runtimeHash;function_count=$rows.Count;functions=$rows}
$rs=[ordered]@{schema='keelaryn.ai-context.runtime-surface.v1';manager_version=$version;runtime_sha256=$runtimeHash;runtime_text_sha256=$runtimeTextHash;parameters=$paramRows;segments=@($segments)}
$tr=[ordered]@{schema='keelaryn.ai-context.task-router.v5';manager_version=$version;runtime_sha256=$runtimeHash;routes=$routeRows}

$managedRows=@()
foreach($rel in @($managed|Sort-Object)){
    $key=$rel.Normalize([System.Text.NormalizationForm]::FormC).ToLowerInvariant()
    $f=$managedItems[$key]
    $f.Refresh()
    if((-not$f.Exists)-or($f.Attributes-band[System.IO.FileAttributes]::ReparsePoint)-ne0-or$f.Length-gt64MB){throw('Managed source changed during AI context build: '+$rel)}
    $managedRows += [ordered]@{
        path=$rel
        size_bytes=[long]$f.Length
        sha256=[string]$preflightSourceHashes[$key]
        context_path=$(if($rel-eq'product/runtime/Keelaryn__Manager.ps1'){'runtime segments + functions/'}else{'managed/'+$rel})
    }
}
$mm=[ordered]@{schema='keelaryn.ai-context.managed-file-map.v2';manager_version=$version;runtime_sha256=$runtimeHash;file_count=$managedRows.Count;files=$managedRows}
Write-Utf8NoBom (Join-Path $OutputDirectory 'FUNCTION_MAP.json') (ConvertTo-StableJson $fm)
Write-Utf8NoBom (Join-Path $OutputDirectory 'RUNTIME_SURFACE.json') (ConvertTo-StableJson $rs)
Write-Utf8NoBom (Join-Path $OutputDirectory 'TASK_ROUTER.json') (ConvertTo-StableJson $tr)
Write-Utf8NoBom (Join-Path $OutputDirectory 'MANAGED_FILE_MAP.json') (ConvertTo-StableJson $mm)
$start=New-Object System.Collections.ArrayList
[void]$start.Add('# Keelaryn Manager '+$version+' - compact development context')
[void]$start.Add('')
[void]$start.Add('Canonical runtime SHA-256: `'+$runtimeHash+'`.')
[void]$start.Add('')
[void]$start.Add('Start with `TASK_ROUTER.json`; route Markdown files are compact indexes only, then load exact function slices and files under `managed/`. Runtime segments reconstruct the canonical runtime text losslessly.')
[void]$start.Add('')
[void]$start.Add('Key invariants:')
[void]$start.Add('- Canonical installed layout is `keelaryn/manager`, `keelaryn/hub`, `keelaryn/tests`; the public repository adds scaffolding around the same managed Manager tree.')
[void]$start.Add('- UPDATE payload, outer manifest and all active version surfaces must agree.')
[void]$start.Add('- Never extract/apply an unvalidated ZIP.')
[void]$start.Add('- Manager/Hub updates remain rollback-oriented and preserve local deployment state.')
[void]$start.Add('- Context reduction must never remove runtime capability or weaken validation.')
Write-ValidatedMarkdown (Join-Path $OutputDirectory 'START_HERE.md') $start 12
$manifestRows=New-Object System.Collections.ArrayList
$contextHashes=@{}
$base=[System.IO.Path]::GetFullPath($OutputDirectory).TrimEnd('\')+'\'
foreach($f in @(Get-ChildItem -LiteralPath $OutputDirectory -File -Recurse -Force|Where-Object{$_.Name-ne'CONTEXT_MANIFEST.json'}|Sort-Object FullName)){
    $rel=$f.FullName.Substring($base.Length).Replace('\','/')
    $hash=Get-FileSha256 $f.FullName
    if($contextHashes.ContainsKey($rel)){throw('Duplicate AI context output path while hashing manifest: '+$rel)}
    $contextHashes[$rel]=$hash
    [void]$manifestRows.Add([ordered]@{path=$rel;size_bytes=[long]$f.Length;sha256=$hash})
}
foreach($row in @($managedRows)){
    $managedPath=[string]$row.path
    $key=$managedPath.Normalize([System.Text.NormalizationForm]::FormC).ToLowerInvariant()
    $sourceItem=$managedItems[$key]
    $sourceItem.Refresh()
    if((-not$sourceItem.Exists)-or($sourceItem.Attributes-band[System.IO.FileAttributes]::ReparsePoint)-ne0-or$sourceItem.Length-gt64MB){throw('Managed source became unsafe at AI context transaction boundary: '+$managedPath)}
    $finalSourceHash=Get-FileSha256 $sourceItem.FullName
    if($finalSourceHash-cne[string]$row.sha256){throw('Managed source mutated during AI context build: '+$managedPath+' preflight='+[string]$row.sha256+' final='+$finalSourceHash)}
    if($managedPath-eq'product/runtime/Keelaryn__Manager.ps1'){
        if($finalSourceHash-cne$runtimeHash){throw('Canonical runtime changed during AI context build. expected='+$runtimeHash+' actual='+$finalSourceHash)}
        continue
    }
    $contextPath='managed/'+$managedPath
    if(-not ($contextHashes.ContainsKey($contextPath))){throw('AI context copied managed file missing from final manifest scan: '+$managedPath)}
    if([string]$contextHashes[$contextPath]-cne[string]$row.sha256){throw('AI context copied managed file differs from final source snapshot: '+$managedPath+' source='+[string]$row.sha256+' context='+[string]$contextHashes[$contextPath])}
}
$cm=[ordered]@{schema='keelaryn.ai-context.manifest.v1';manager_version=$version;runtime_sha256=$runtimeHash;files=$manifestRows}
Write-Utf8NoBom (Join-Path $OutputDirectory 'CONTEXT_MANIFEST.json') (ConvertTo-StableJson $cm)
Write-Host('AI context generated: '+[System.IO.Path]::GetFullPath($OutputDirectory))-ForegroundColor Green
