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

$conditional=$policy.conditional_compatibility_shadow_bypass
if($null-eq$conditional){Fail 'Entry policy is missing conditional_compatibility_shadow_bypass.'}
if([string]$conditional.parameter-cne'UpdateAll'){Fail 'Conditional compatibility-shadow bypass must be owned by UpdateAll.'}
if([string]$conditional.entry_action-cne'UpdateAll'){Fail 'Conditional compatibility-shadow bypass must map to UpdateAll entry evidence.'}
if(-not[bool]$conditional.requires_nonblank_expected_instance_id){Fail 'Conditional UpdateAll bypass must require a nonblank ExpectedInstanceId.'}
if(-not[bool]$conditional.requires_preserved_binding_resolution_error){Fail 'Conditional UpdateAll bypass must require a preserved BindingResolutionError.'}
if([bool]$conditional.generic_unresolved_registry_bypass_permitted){Fail 'Conditional UpdateAll bypass must not permit generic unresolved-registry dispatch.'}
$updateAllPolicy=@($rows|Where-Object{[string]$_.parameter-ceq'UpdateAll'});if($updateAllPolicy.Count-ne1){Fail('UpdateAll policy row count='+$updateAllPolicy.Count)}
if([string]$updateAllPolicy[0].old_active_current-cne'reconcile_required'-or[string]$updateAllPolicy[0].unresolved_registry-cne'fail_closed'){Fail 'Generic UpdateAll policy must remain reconcile_required/fail_closed.'}

$func=@($ast.FindAll({param($n)$n-is[Management.Automation.Language.FunctionDefinitionAst]-and$n.Name-ceq'Test-ActiveCompatibilityShadowReconciliationRequired'},$true));if($func.Count-ne1){Fail('Central reconciliation policy function count='+$func.Count)}
$falseClauses=New-Object System.Collections.ArrayList
$ifAsts=@($func[0].Body.FindAll({param($n)$n-is[Management.Automation.Language.IfStatementAst]},$true))
foreach($ifAst in $ifAsts){
    foreach($clause in @($ifAst.Clauses)){
        $bodyText=[string]$clause.Item2.Extent.Text
        if($bodyText-notmatch'(?i)\breturn\s+\$false\b'){continue}
        $condition=$clause.Item1
        $vars=@($condition.FindAll({param($n)$n-is[Management.Automation.Language.VariableExpressionAst]},$true)|ForEach-Object{$_.VariablePath.UserPath}|Sort-Object -Unique)
        [void]$falseClauses.Add([pscustomobject]@{Condition=$condition;Variables=@($vars)})
    }
}
$special=@($falseClauses|Where-Object{$_.Variables-ccontains'UpdateAll'-or$_.Variables-ccontains'ExpectedInstanceId'-or$_.Variables-ccontains'script:BindingResolutionError'})
if($special.Count-ne1){Fail('Conditional UpdateAll compatibility-shadow clause count='+$special.Count)}
Same-Set @('UpdateAll','ExpectedInstanceId','script:BindingResolutionError') @($special[0].Variables) 'Conditional UpdateAll compatibility-shadow variables'
$specialCondition=(([string]$special[0].Condition.Extent.Text)-replace'\s','')
$expectedSpecial='$UpdateAll-and-not[string]::IsNullOrWhiteSpace([string]$ExpectedInstanceId)-and-not[string]::IsNullOrWhiteSpace([string]$script:BindingResolutionError)'
if($specialCondition-cne$expectedSpecial){Fail('Conditional UpdateAll compatibility-shadow predicate drifted. expected='+$expectedSpecial+' actual='+$specialCondition)}

$genericCandidates=@($falseClauses|Where-Object{
    $_-ne$special[0] -and
    $_.Variables-cnotcontains'script:InstanceRegistryActive' -and
    @($_.Variables).Count-gt1
})
if($genericCandidates.Count-ne1){Fail('Generic compatibility-shadow bypass clause count='+$genericCandidates.Count)}
$expectedBypass=@($rows|Where-Object{[string]$_.old_active_current-ceq'bypass'}|ForEach-Object{[string]$_.parameter});Same-Set $expectedBypass @($genericCandidates[0].Variables) 'Compatibility-shadow generic bypass set'
if(@($genericCandidates[0].Variables)-ccontains'UpdateAll'){Fail 'Generic compatibility-shadow bypass must not include UpdateAll.'}

$allow=@($assignments|Where-Object{$_.Left-is[Management.Automation.Language.VariableExpressionAst]-and$_.Left.VariablePath.UserPath-ceq'allowRegistryUnresolved'});if($allow.Count-ne1){Fail('allowRegistryUnresolved assignment count='+$allow.Count)}
$allowVars=@($allow[0].Right.FindAll({param($n)$n-is[Management.Automation.Language.VariableExpressionAst]},$true)|ForEach-Object{$_.VariablePath.UserPath}|Sort-Object -Unique)
$expectedAllow=@($rows|Where-Object{[string]$_.unresolved_registry-ceq'allow_dispatch'}|ForEach-Object{[string]$_.parameter});Same-Set $expectedAllow $allowVars 'Unresolved-registry pre-dispatch allowlist'
if($allowVars-ccontains'UpdateAll'){Fail 'Generic unresolved-registry pre-dispatch allowlist must not include UpdateAll.'}
$entryIds=@($entry.actions|ForEach-Object{[string]$_.id});foreach($r in @($rows|Where-Object{[string]$_.old_active_current-ceq'bypass'})){if([string]::IsNullOrWhiteSpace([string]$r.entry_action)){Fail([string]$r.parameter+' bypass lacks entry_action evidence mapping.')};if($entryIds-cnotcontains[string]$r.entry_action){Fail([string]$r.parameter+' bypass references missing entry action '+[string]$r.entry_action)}}
if($entryIds-cnotcontains[string]$conditional.entry_action){Fail('Conditional UpdateAll bypass references missing entry action '+[string]$conditional.entry_action)}
Write-Host 'Manager entry-policy completeness: PASS' -ForegroundColor Green
Write-Host ('  primary modes: '+$primaryVars.Count)
Write-Host ('  compatibility-shadow generic bypass: '+$expectedBypass.Count)
Write-Host '  conditional token-bound UpdateAll shadow bypass: 1'
Write-Host ('  unresolved-registry allow-dispatch: '+$expectedAllow.Count)
