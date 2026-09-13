[CmdletBinding()]
param(
    [string]$RepositoryRoot=(Join-Path $PSScriptRoot '..'),
    [string]$BaseCommit='',
    [string]$HeadCommit='HEAD',
    [string]$OutputPath=''
)

$ErrorActionPreference='Stop'
Set-StrictMode -Version 2.0
$RepositoryRoot=[IO.Path]::GetFullPath($RepositoryRoot).TrimEnd('\')
$Utf8NoBom=New-Object Text.UTF8Encoding($false)
if([string]::IsNullOrWhiteSpace($OutputPath)){$OutputPath=Join-Path $RepositoryRoot 'MANAGER_RISK_CONTEXT.md'}
$OutputPath=[IO.Path]::GetFullPath($OutputPath)
$JsonOutputPath=[IO.Path]::ChangeExtension($OutputPath,'.json')

function Fail([string]$Message){throw $Message}
function Read-Json([string]$RelativePath){return (Get-Content -LiteralPath (Join-Path $RepositoryRoot ($RelativePath.Replace('/','\'))) -Raw -Encoding UTF8|ConvertFrom-Json)}
function Read-AllDefects {
    $dir=Join-Path $RepositoryRoot 'tests\knowledge\defects'
    $files=@(Get-ChildItem -LiteralPath $dir -File -Filter '*.json' -ErrorAction Stop|Sort-Object Name)
    if($files.Count-eq0){Fail 'No Manager defect knowledge files found.'}
    $rows=New-Object System.Collections.ArrayList
    foreach($file in $files){
        $doc=Get-Content -LiteralPath $file.FullName -Raw -Encoding UTF8|ConvertFrom-Json
        if([string]$doc.schema-cne'keelaryn.manager-defects.v1'){Fail('Unexpected defect schema in '+$file.Name+'.')}
        foreach($row in @($doc.defects)){[void]$rows.Add($row)}
    }
    return @($rows)
}
function Read-AllRiskAudits {
    $dir=Join-Path $RepositoryRoot 'tests\knowledge\audits'
    $files=@(Get-ChildItem -LiteralPath $dir -File -Filter '*.json' -ErrorAction Stop|Sort-Object Name)
    if($files.Count-eq0){return @()}
    $rows=New-Object System.Collections.ArrayList
    foreach($file in $files){
        $doc=Get-Content -LiteralPath $file.FullName -Raw -Encoding UTF8|ConvertFrom-Json
        if([string]$doc.schema-cne'keelaryn.manager-risk-audit.v1'){Fail('Unexpected risk-audit schema in '+$file.Name+'.')}
        [void]$rows.Add($doc)
    }
    return @($rows)
}
function Invoke-Git([string[]]$Arguments,[switch]$AllowEmpty){
    $old=$ErrorActionPreference
    try{$ErrorActionPreference='Continue';$lines=@(& git.exe -C $RepositoryRoot @Arguments 2>&1);$code=[int]$LASTEXITCODE}finally{$ErrorActionPreference=$old}
    if($code-ne0){Fail('git '+($Arguments-join' ')+' failed: '+([string]::Join(' | ',@($lines))))}
    if(-not$AllowEmpty -and $lines.Count-eq0){return @()}
    return @($lines|ForEach-Object{[string]$_})
}
function Resolve-Commit([string]$Ref){
    $rows=@(Invoke-Git @('rev-parse','--verify',($Ref+'^{commit}')))
    if($rows.Count-ne1){Fail('Could not resolve commit: '+$Ref)}
    return $rows[0].Trim().ToLowerInvariant()
}
function New-StringSet(){return New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)}
function Add-RangeSymbols([string]$Commit,[string]$Path,$Ranges,$Set){
    if(-not$Path.EndsWith('.ps1',[StringComparison]::OrdinalIgnoreCase)){return}
    $spec=('{0}:{1}' -f $Commit,$Path)
    $old=$ErrorActionPreference
    try{$ErrorActionPreference='Continue';$textRows=@(& git.exe -C $RepositoryRoot show $spec 2>&1);$code=[int]$LASTEXITCODE}finally{$ErrorActionPreference=$old}
    if($code-ne0){return}
    $temp=Join-Path ([IO.Path]::GetTempPath()) ('keelaryn-risk-'+[guid]::NewGuid().ToString('N')+'.ps1')
    try{
        [IO.File]::WriteAllText($temp,([string]::Join("`n",@($textRows))),$Utf8NoBom)
        $tokens=$null;$errors=$null
        $ast=[Management.Automation.Language.Parser]::ParseFile($temp,[ref]$tokens,[ref]$errors)
        if(@($errors).Count-ne0){Fail('Could not parse '+$Path+' at '+$Commit+' for risk-symbol mapping: '+([string]::Join(' | ',@($errors|ForEach-Object{$_.Message}))))}
        $functions=@($ast.FindAll({param($node)$node-is[Management.Automation.Language.FunctionDefinitionAst]},$true))
        foreach($range in @($Ranges)){
            $start=[int]$range.Start;$count=[int]$range.Count
            if($count-le0){continue}
            $end=$start+$count-1
            $hits=@($functions|Where-Object{[int]$_.Extent.StartLineNumber-le$end -and [int]$_.Extent.EndLineNumber-ge$start})
            if($hits.Count-eq0){[void]$Set.Add('__TOP_LEVEL__')}
            foreach($hit in $hits){[void]$Set.Add([string]$hit.Name)}
        }
    }finally{Remove-Item -LiteralPath $temp -Force -ErrorAction SilentlyContinue}
}
function Get-PathChange([string]$Path,[string]$Base,[string]$Head){
    $diff=@(Invoke-Git @('diff','--unified=0','--no-color',$Base,$Head,'--',$Path) -AllowEmpty)
    $oldRanges=New-Object System.Collections.ArrayList;$newRanges=New-Object System.Collections.ArrayList
    foreach($line in @($diff)){
        if($line-match'^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@'){
            $oldCount=if([string]::IsNullOrWhiteSpace($matches[2])){1}else{[int]$matches[2]};$newCount=if([string]::IsNullOrWhiteSpace($matches[4])){1}else{[int]$matches[4]}
            [void]$oldRanges.Add([pscustomobject]@{Start=[int]$matches[1];Count=$oldCount});[void]$newRanges.Add([pscustomobject]@{Start=[int]$matches[3];Count=$newCount})
        }
    }
    $symbols=New-StringSet;Add-RangeSymbols $Head $Path $newRanges $symbols;Add-RangeSymbols $Base $Path $oldRanges $symbols
    return [ordered]@{path=$Path;symbols=@($symbols|Sort-Object)}
}
function Test-WildcardPath([string]$Path,[string]$Pattern){
    $escaped=[regex]::Escape($Pattern.Replace('\','/'));$regex='^'+$escaped.Replace('\*\*','.*').Replace('\*','[^/]*').Replace('\?','.')+'$'
    return [regex]::IsMatch($Path.Replace('\','/'),$regex,[Text.RegularExpressions.RegexOptions]::IgnoreCase)
}
function Intersects($A,$B){foreach($x in @($A)){if(@($B)-contains$x){return $true}}return $false}
function Set-Intersects($Rows,$Set){foreach($row in @($Rows)){if($Set.Contains([string]$row)){return $true}}return $false}
function Add-UniqueIds($Set,$Rows){foreach($row in @($Rows)){if(-not[string]::IsNullOrWhiteSpace([string]$row)){[void]$Set.Add([string]$row)}}}
function Escape-Md([string]$Text){if($null-eq$Text){return''};return $Text.Replace('|','\|').Replace("`r",' ').Replace("`n",' ')}
function Get-OptionalText($Object,[string]$PropertyName){
    if($null-eq$Object){return''}
    if($Object.PSObject.Properties.Name -notcontains $PropertyName){return''}
    return [string]$Object.$PropertyName
}
function Get-WinningStateRule($Machine,[string]$State,[string]$Operation){
    $matches=@($Machine.rules|Where-Object{[string]$_.operation-ceq$Operation -and (@($_.states)-contains'*' -or @($_.states)-contains$State)})
    if($matches.Count-eq0){return $null}
    $max=($matches|Measure-Object -Property priority -Maximum).Maximum
    $winners=@($matches|Where-Object{[int]$_.priority-eq[int]$max})
    if($winners.Count-ne1){Fail('Ambiguous state-machine winner for '+$State+' x '+$Operation+'.')}
    return $winners[0]
}

$head=Resolve-Commit $HeadCommit;if([string]::IsNullOrWhiteSpace($BaseCommit)){$base=Resolve-Commit ($head+'^')}else{$base=Resolve-Commit $BaseCommit}
$risk=Read-Json 'tests/knowledge/risk-map.json';$invDoc=Read-Json 'tests/knowledge/invariants/multi-hub.json';$rootDoc=Read-Json 'tests/knowledge/root-causes.json';$allDefects=@(Read-AllDefects);$machine=Read-Json 'tests/knowledge/state-machines/multi-hub.json';$allAudits=@(Read-AllRiskAudits)

$changedPaths=@(Invoke-Git @('diff','--name-only','--diff-filter=ACDMRT',$base,$head,'--') -AllowEmpty|Where-Object{-not[string]::IsNullOrWhiteSpace($_)}|ForEach-Object{$_.Trim().Replace('\','/')}|Sort-Object -Unique)
$changes=New-Object System.Collections.ArrayList;foreach($path in $changedPaths){[void]$changes.Add((Get-PathChange $path $base $head))}

$matchedSurfaceIds=New-StringSet
foreach($surface in @($risk.surfaces)){
    $surfaceMatch=$false
    foreach($change in @($changes)){
        $pathMatch=$false;foreach($pattern in @($surface.paths)){if(Test-WildcardPath ([string]$change.path) ([string]$pattern)){$pathMatch=$true;break}}
        if(-not$pathMatch){continue}
        $surfaceSymbols=@($surface.symbols)
        if($surfaceSymbols.Count-eq0 -or -not([string]$change.path).EndsWith('.ps1',[StringComparison]::OrdinalIgnoreCase)){$surfaceMatch=$true;break}
        if(Intersects @($change.symbols) $surfaceSymbols){$surfaceMatch=$true;break}
    }
    if($surfaceMatch){[void]$matchedSurfaceIds.Add([string]$surface.id)}
}

$matchedSurfaces=@($risk.surfaces|Where-Object{$matchedSurfaceIds.Contains([string]$_.id)}|Sort-Object id)
$invariantIds=New-StringSet;$rootIds=New-StringSet;$regressions=New-StringSet;$planned=New-StringSet;$ruleIds=New-StringSet
foreach($surface in $matchedSurfaces){Add-UniqueIds $invariantIds @($surface.invariants);Add-UniqueIds $rootIds @($surface.root_cause_classes);Add-UniqueIds $regressions @($surface.regressions);Add-UniqueIds $planned @($surface.planned_regressions);Add-UniqueIds $ruleIds @($surface.state_machine_rules)}
$invariants=@($invDoc.invariants|Where-Object{$invariantIds.Contains([string]$_.id)}|Sort-Object id);$rootClasses=@($rootDoc.classes|Where-Object{$rootIds.Contains([string]$_.id)}|Sort-Object id);$stateRules=@($machine.rules|Where-Object{$ruleIds.Contains([string]$_.id)}|Sort-Object id)
$relatedDefects=@($allDefects|Where-Object{Set-Intersects @($_.affected_surfaces) $matchedSurfaceIds}|Sort-Object id);$openBlockers=@($allDefects|Where-Object{[string]$_.status-eq'open' -and [bool]$_.release_blocker}|Sort-Object id)

$applicableAudits=New-Object System.Collections.ArrayList
foreach($audit in @($allAudits)){
    $scenarios=New-Object System.Collections.ArrayList
    foreach($test in @($audit.required_pre_product_tests)){
        $winner=Get-WinningStateRule $machine ([string]$test.state) ([string]$test.operation)
        if($null-ne$winner -and $ruleIds.Contains([string]$winner.id)){
            $fault=Get-OptionalText $test 'fault'
            [void]$scenarios.Add([ordered]@{id=[string]$test.id;state=[string]$test.state;operation=[string]$test.operation;fault=$fault;expected=[string]$test.expected;state_machine_rule=[string]$winner.id})
        }
    }
    if($scenarios.Count-gt0){
        [void]$applicableAudits.Add([ordered]@{audit_id=[string]$audit.audit_id;title=[string]$audit.title;scenarios=@($scenarios);implementation_constraints=@($audit.implementation_constraints);freeze_criteria=@($audit.freeze_criteria)})
    }
}

$context=[ordered]@{schema='keelaryn.manager-risk-context.v1';base_commit=$base;head_commit=$head;changed_files=@($changes);matched_surfaces=@($matchedSurfaces|ForEach-Object{[ordered]@{id=[string]$_.id;subsystem=[string]$_.subsystem}});invariants=@($invariants|ForEach-Object{[ordered]@{id=[string]$_.id;title=[string]$_.title;rule=[string]$_.rule;coverage=@($_.coverage)}});root_cause_classes=@($rootClasses|ForEach-Object{[ordered]@{id=[string]$_.id;title=[string]$_.title}});related_defects=@($relatedDefects|ForEach-Object{[ordered]@{id=[string]$_.id;title=[string]$_.title;status=[string]$_.status;severity=[string]$_.severity;detected_in=[string]$_.detected_in;violated_invariants=@($_.violated_invariants)}});global_open_release_blockers=@($openBlockers|ForEach-Object{[ordered]@{id=[string]$_.id;title=[string]$_.title;severity=[string]$_.severity;affected_surfaces=@($_.affected_surfaces);violated_invariants=@($_.violated_invariants)}});applicable_regressions=@($regressions|Sort-Object);planned_regressions=@($planned|Sort-Object);state_machine_rules=@($stateRules|ForEach-Object{[ordered]@{id=[string]$_.id;states=@($_.states);operation=[string]$_.operation;outcome=[string]$_.outcome;reason=[string]$_.reason;invariants=@($_.invariants)}});applicable_audit_scenarios=@($applicableAudits)}

$parent=[IO.Path]::GetDirectoryName($OutputPath);if($parent-and-not(Test-Path -LiteralPath $parent -PathType Container)){[void][IO.Directory]::CreateDirectory($parent)}
[IO.File]::WriteAllText($JsonOutputPath,(($context|ConvertTo-Json -Depth 50).Replace("`r`n","`n"))+"`n",$Utf8NoBom)
$md=New-Object Text.StringBuilder
[void]$md.AppendLine('# Manager Task Risk Context');[void]$md.AppendLine();[void]$md.AppendLine(('Base: `'+$base+'`'));[void]$md.AppendLine(('Head: `'+$head+'`'));[void]$md.AppendLine();[void]$md.AppendLine('## Changed files / symbols')
if($changes.Count-eq0){[void]$md.AppendLine('- none')};foreach($change in @($changes)){$symbols=if(@($change.symbols).Count){' — '+([string]::Join(', ',@($change.symbols|ForEach-Object{'`'+$_+'`'})))}else{''};[void]$md.AppendLine(('- `'+[string]$change.path+'`'+$symbols))}
[void]$md.AppendLine();[void]$md.AppendLine('## Risk surfaces');if($matchedSurfaces.Count-eq0){[void]$md.AppendLine('- none mapped')};foreach($surface in $matchedSurfaces){[void]$md.AppendLine(('- `'+[string]$surface.id+'` — '+(Escape-Md ([string]$surface.subsystem))))}
[void]$md.AppendLine();[void]$md.AppendLine('## Applicable invariants');if($invariants.Count-eq0){[void]$md.AppendLine('- none')};foreach($inv in $invariants){[void]$md.AppendLine(('- **'+[string]$inv.id+'** — '+(Escape-Md ([string]$inv.rule))))}
[void]$md.AppendLine();[void]$md.AppendLine('## Historical defects on these surfaces');if($relatedDefects.Count-eq0){[void]$md.AppendLine('- none')};foreach($d in $relatedDefects){[void]$md.AppendLine(('- `'+[string]$d.id+'` ['+[string]$d.status+', '+[string]$d.severity+', detected '+[string]$d.detected_in+'] — '+(Escape-Md ([string]$d.title))))}
[void]$md.AppendLine();[void]$md.AppendLine('## Root-cause classes');if($rootClasses.Count-eq0){[void]$md.AppendLine('- none')};foreach($row in $rootClasses){[void]$md.AppendLine(('- `'+[string]$row.id+'` — '+(Escape-Md ([string]$row.title))))}
[void]$md.AppendLine();[void]$md.AppendLine('## Applicable permanent regressions');if($regressions.Count-eq0){[void]$md.AppendLine('- none')};foreach($reg in @($regressions|Sort-Object)){[void]$md.AppendLine(('- `'+$reg+'`'))};if($planned.Count){[void]$md.AppendLine();[void]$md.AppendLine('Planned coverage:');foreach($reg in @($planned|Sort-Object)){[void]$md.AppendLine(('- `'+$reg+'`'))}}
[void]$md.AppendLine();[void]$md.AppendLine('## Relevant state-machine rules');if($stateRules.Count-eq0){[void]$md.AppendLine('- none')};foreach($rule in $stateRules){[void]$md.AppendLine(('- `'+[string]$rule.id+'`: '+[string]$rule.operation+' / '+([string]::Join(',',@($rule.states)))+' -> **'+[string]$rule.outcome+'** — '+(Escape-Md ([string]$rule.reason))))}
[void]$md.AppendLine();[void]$md.AppendLine('## Applicable risk-audit scenarios');if($applicableAudits.Count-eq0){[void]$md.AppendLine('- none')};foreach($audit in @($applicableAudits)){[void]$md.AppendLine(('### `'+[string]$audit.audit_id+'` — '+(Escape-Md ([string]$audit.title))));foreach($scenario in @($audit.scenarios)){$fault=if([string]::IsNullOrWhiteSpace([string]$scenario.fault)){''}else{' | fault: '+(Escape-Md ([string]$scenario.fault))};[void]$md.AppendLine(('- `'+[string]$scenario.id+'` '+[string]$scenario.state+' x '+[string]$scenario.operation+' via `'+[string]$scenario.state_machine_rule+'`'+$fault+' -> '+(Escape-Md ([string]$scenario.expected))))};[void]$md.AppendLine();[void]$md.AppendLine('Implementation constraints:');foreach($constraint in @($audit.implementation_constraints)){[void]$md.AppendLine(('- '+(Escape-Md ([string]$constraint))))}}
[void]$md.AppendLine();[void]$md.AppendLine('## Global open release blockers');if($openBlockers.Count-eq0){[void]$md.AppendLine('- none')};foreach($d in $openBlockers){[void]$md.AppendLine(('- `'+[string]$d.id+'` ['+[string]$d.severity+'] — '+(Escape-Md ([string]$d.title))))}
[IO.File]::WriteAllText($OutputPath,$md.ToString().Replace("`r`n","`n"),$Utf8NoBom)
Write-Host 'Manager risk context generated.' -ForegroundColor Green;Write-Host ('  base: '+$base);Write-Host ('  head: '+$head);Write-Host ('  changed files: '+$changes.Count);Write-Host ('  risk surfaces: '+$matchedSurfaces.Count);Write-Host ('  invariants: '+$invariants.Count);Write-Host ('  historical defects: '+$relatedDefects.Count);Write-Host ('  audit groups: '+$applicableAudits.Count);Write-Host ('  open release blockers: '+$openBlockers.Count);Write-Host ('  markdown: '+$OutputPath);Write-Host ('  json: '+$JsonOutputPath)
