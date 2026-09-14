[CmdletBinding()]
param([string]$RepositoryRoot=(Join-Path $PSScriptRoot '..'))
$ErrorActionPreference='Stop';Set-StrictMode -Version 2.0
$RepositoryRoot=[IO.Path]::GetFullPath($RepositoryRoot).TrimEnd('\')
function Fail([string]$Message){throw $Message}
function New-Set(){return New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::Ordinal)}
function Same-Set($A,$B,[string]$Label){$aa=@($A|ForEach-Object{[string]$_}|Sort-Object -Unique);$bb=@($B|ForEach-Object{[string]$_}|Sort-Object -Unique);if(([string]::Join('|',$aa))-cne([string]::Join('|',$bb))){Fail($Label+' mismatch. expected='+([string]::Join(',',$aa))+' actual='+([string]::Join(',',$bb)))}}
$runtimePath=Join-Path $RepositoryRoot 'manager\product\runtime\Keelaryn__Manager.ps1';$policyPath=Join-Path $RepositoryRoot 'tests\knowledge\manager-entry-policy.json';$entryPath=Join-Path $RepositoryRoot 'tests\knowledge\entry-reachability.json'
foreach($p in @($runtimePath,$policyPath,$entryPath)){if(-not(Test-Path -LiteralPath $p -PathType Leaf)){Fail('Required entry-policy source missing: '+$p)}}
$policy=Get-Content $policyPath -Raw -Encoding UTF8|ConvertFrom-Json;$entry=Get-Content $entryPath -Raw -Encoding UTF8|ConvertFrom-Json
if([string]$policy.schema-cne'keelaryn.manager-entry-policy.v1'){Fail('Unexpected policy schema: '+[string]$policy.schema)}
$tokens=$null;$errors=$null;$ast=[Management.Automation.Language.Parser]::ParseFile($runtimePath,[ref]$tokens,[ref]$errors);if(@($errors).Count){Fail('Runtime parser failed: '+([string]::Join(' | ',@($errors|ForEach-Object{$_.Message}))))}
$assignments=@($ast.FindAll({param($n)$n-is[Management.Automation.Language.AssignmentStatementAst]},$true))
$primary=@($assignments|Where-Object{$_.Left-is[Management.Automation.Language.VariableExpressionAst]-and$_.Left.VariablePath.UserPath-ceq'PrimaryModeCount'});if($primary.Count-ne1){Fail('PrimaryModeCount assignment count='+$primary.Count)}
$primaryVars=@($primary[0].Right.FindAll({param($n)$n-is[Management.Automation.Language.VariableExpressionAst]},$true)|ForEach-Object{$_.VariablePath.UserPath}|Sort-Object -Unique)
$rows=@($policy.actions);if($rows.Count-ne29){Fail('Entry policy must classify exactly 29 modes; actual='+$rows.Count)}
$policyParams=@($rows|ForEach-Object{[string]$_.parameter});if(@($policyParams|Sort-Object -Unique).Count-ne$rows.Count){Fail 'Entry policy contains duplicate parameters.'};Same-Set $policyParams $primaryVars 'PrimaryModeCount policy coverage'
foreach($r in $rows){if([string]::IsNullOrWhiteSpace([string]$r.class)){Fail([string]$r.parameter+' class is empty.')};if(@('bypass','reconcile_required')-cnotcontains[string]$r.old_active_current){Fail([string]$r.parameter+' old_active_current policy unsupported.')};if(@('allow_dispatch','fail_closed')-cnotcontains[string]$r.unresolved_registry){Fail([string]$r.parameter+' unresolved_registry policy unsupported.')}}
$func=@($ast.FindAll({param($n)$n-is[Management.Automation.Language.FunctionDefinitionAst]-and$n.Name-ceq'Test-ActiveCompatibilityShadowReconciliationRequired'},$true));if($func.Count-ne1){Fail('Central reconciliation policy function count='+$func.Count)}
$funcVars=@($func[0].Body.FindAll({param($n)$n-is[Management.Automation.Language.VariableExpressionAst]},$true)|ForEach-Object{$_.VariablePath.UserPath}|Where-Object{$_-cne'script:InstanceRegistryActive'-and$_-cne'true'-and$_-cne'false'}|Sort-Object -Unique)
$expectedBypass=@($rows|Where-Object{[string]$_.old_active_current-ceq'bypass'}|ForEach-Object{[string]$_.parameter});Same-Set $expectedBypass $funcVars 'Compatibility-shadow bypass set'
$allow=@($assignments|Where-Object{$_.Left-is[Management.Automation.Language.VariableExpressionAst]-and$_.Left.VariablePath.UserPath-ceq'allowRegistryUnresolved'});if($allow.Count-ne1){Fail('allowRegistryUnresolved assignment count='+$allow.Count)}
$allowVars=@($allow[0].Right.FindAll({param($n)$n-is[Management.Automation.Language.VariableExpressionAst]},$true)|ForEach-Object{$_.VariablePath.UserPath}|Sort-Object -Unique)
$expectedAllow=@($rows|Where-Object{[string]$_.unresolved_registry-ceq'allow_dispatch'}|ForEach-Object{[string]$_.parameter});Same-Set $expectedAllow $allowVars 'Unresolved-registry pre-dispatch allowlist'
$entryIds=@($entry.actions|ForEach-Object{[string]$_.id});foreach($r in @($rows|Where-Object{[string]$_.old_active_current-ceq'bypass'})){if([string]::IsNullOrWhiteSpace([string]$r.entry_action)){Fail([string]$r.parameter+' bypass lacks entry_action evidence mapping.')};if($entryIds-cnotcontains[string]$r.entry_action){Fail([string]$r.parameter+' bypass references missing entry action '+[string]$r.entry_action)}}
Write-Host 'Manager entry-policy completeness: PASS' -ForegroundColor Green
Write-Host ('  primary modes: '+$primaryVars.Count)
Write-Host ('  compatibility-shadow bypass: '+$expectedBypass.Count)
Write-Host ('  unresolved-registry allow-dispatch: '+$expectedAllow.Count)
