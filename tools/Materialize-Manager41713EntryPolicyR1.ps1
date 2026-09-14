[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$RepositoryRoot,
    [Parameter(Mandatory=$true)][string]$ExpectedBase,
    [string]$EvidenceRoot=''
)
$ErrorActionPreference='Stop'
Set-StrictMode -Version 2.0
$RepositoryRoot=[IO.Path]::GetFullPath($RepositoryRoot).TrimEnd('\')
$Utf8=New-Object Text.UTF8Encoding($false)
function Fail([string]$Message){throw $Message}
function Write-Utf8([string]$Path,[string]$Text){$parent=Split-Path -Parent $Path;if($parent-and-not(Test-Path -LiteralPath $parent -PathType Container)){New-Item -ItemType Directory -Force -Path $parent|Out-Null};[IO.File]::WriteAllText($Path,$Text,$Utf8)}
function Write-Json([string]$Path,$Object){Write-Utf8 $Path ((($Object|ConvertTo-Json -Depth 80).Replace("`r`n","`n"))+"`n")}
function Replace-Once([string]$Text,[string]$Old,[string]$New,[string]$Label){$i=$Text.IndexOf($Old,[StringComparison]::Ordinal);if($i-lt0){Fail($Label+': source token missing')};if($Text.IndexOf($Old,$i+$Old.Length,[StringComparison]::Ordinal)-ge0){Fail($Label+': source token occurs more than once')};return $Text.Substring(0,$i)+$New+$Text.Substring($i+$Old.Length)}
function Run([string]$Script,[string[]]$Arguments){$exe=Join-Path $PSHOME 'powershell.exe';$old=$ErrorActionPreference;try{$ErrorActionPreference='Continue';$out=@(& $exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $Script @Arguments 2>&1|ForEach-Object{[string]$_});$code=[int]$LASTEXITCODE}finally{$ErrorActionPreference=$old};foreach($line in $out){Write-Host $line};if($code-ne0){Fail('Command failed: '+$Script+' '+($Arguments-join' ')+' exit='+$code)};return @($out)}

$actual=(& git.exe -C $RepositoryRoot rev-parse HEAD).Trim().ToLowerInvariant()
if($actual-cne$ExpectedBase.ToLowerInvariant()){Fail('Authoritative dev head moved. expected='+$ExpectedBase+' actual='+$actual)}
git.exe -C $RepositoryRoot config user.name 'Aleksei Efremov'
git.exe -C $RepositoryRoot config user.email 'efremov.aleksei.96@gmail.com'
if([string]::IsNullOrWhiteSpace($EvidenceRoot)){$EvidenceRoot=Join-Path ([IO.Path]::GetTempPath()) ('keelaryn-41713-entry-policy-'+[guid]::NewGuid().ToString('N'))}
New-Item -ItemType Directory -Force -Path $EvidenceRoot|Out-Null

# 1. Canonical 29-mode entry policy. Active-context operations remain fail-closed;
# only Manager-global, diagnostics and explicit recovery bypass old-active CURRENT reconciliation.
$policy=[ordered]@{
 schema='keelaryn.manager-entry-policy.v1'
 purpose='Complete pre-dispatch classification for every top-level Manager mode. A new PrimaryModeCount member is a release blocker until explicitly classified.'
 actions=@(
  [ordered]@{parameter='OpenOnly';class='active_context_read';old_active_current='reconcile_required';unresolved_registry='fail_closed';entry_action=$null},
  [ordered]@{parameter='UpdateManager';class='manager_global';old_active_current='bypass';unresolved_registry='allow_dispatch';entry_action='UpdateManager'},
  [ordered]@{parameter='UpdateHub';class='active_context_mutation';old_active_current='reconcile_required';unresolved_registry='fail_closed';entry_action='UpdateHub'},
  [ordered]@{parameter='UpdateAll';class='mixed_manager_hub';old_active_current='reconcile_required';unresolved_registry='fail_closed';entry_action='UpdateAll'},
  [ordered]@{parameter='SelfTest';class='manager_global_diagnostic';old_active_current='bypass';unresolved_registry='allow_dispatch';entry_action='SelfTest'},
  [ordered]@{parameter='Genesis';class='active_context_genesis';old_active_current='reconcile_required';unresolved_registry='fail_closed';entry_action=$null},
  [ordered]@{parameter='BuildDistribution';class='manager_global';old_active_current='bypass';unresolved_registry='allow_dispatch';entry_action='BuildDistribution'},
  [ordered]@{parameter='InstanceInfo';class='active_context_diagnostic';old_active_current='reconcile_required';unresolved_registry='fail_closed';entry_action=$null},
  [ordered]@{parameter='CheckMigrations';class='active_context_diagnostic';old_active_current='reconcile_required';unresolved_registry='fail_closed';entry_action=$null},
  [ordered]@{parameter='AdoptInstanceIdentity';class='active_context_mutation';old_active_current='reconcile_required';unresolved_registry='fail_closed';entry_action=$null},
  [ordered]@{parameter='ApplyMigrations';class='active_context_mutation';old_active_current='reconcile_required';unresolved_registry='fail_closed';entry_action=$null},
  [ordered]@{parameter='MigrateLegacyNamespace';class='active_context_mutation';old_active_current='reconcile_required';unresolved_registry='fail_closed';entry_action=$null},
  [ordered]@{parameter='MigrateLayout';class='active_context_mutation';old_active_current='reconcile_required';unresolved_registry='fail_closed';entry_action=$null},
  [ordered]@{parameter='FinalizeLayout';class='active_context_mutation';old_active_current='reconcile_required';unresolved_registry='fail_closed';entry_action=$null},
  [ordered]@{parameter='Doctor';class='diagnostic';old_active_current='bypass';unresolved_registry='allow_dispatch';entry_action='Doctor'},
  [ordered]@{parameter='BuildRelease';class='manager_global';old_active_current='bypass';unresolved_registry='allow_dispatch';entry_action='BuildRelease'},
  [ordered]@{parameter='BuildAIContext';class='manager_global';old_active_current='bypass';unresolved_registry='allow_dispatch';entry_action='BuildAIContext'},
  [ordered]@{parameter='RepairCurrentTransport';class='active_context_transport_repair';old_active_current='reconcile_required';unresolved_registry='fail_closed';entry_action='RepairCurrent'},
  [ordered]@{parameter='PrepareTests';class='manager_global';old_active_current='bypass';unresolved_registry='allow_dispatch';entry_action='PrepareTests'},
  [ordered]@{parameter='BuildCandidateTransport';class='hub_bound';old_active_current='reconcile_required';unresolved_registry='fail_closed';entry_action='BuildCandidateTransport'},
  [ordered]@{parameter='RestoreCandidateTransport';class='hub_bound';old_active_current='reconcile_required';unresolved_registry='fail_closed';entry_action='RestoreCandidateTransport'},
  [ordered]@{parameter='InitializePresentation';class='manager_global';old_active_current='bypass';unresolved_registry='allow_dispatch';entry_action='InitializePresentation'},
  [ordered]@{parameter='FinalizeFilesystemLayout';class='manager_global';old_active_current='bypass';unresolved_registry='allow_dispatch';entry_action='FinalizeFilesystemLayout'},
  [ordered]@{parameter='BindInstancePath';class='target_driven_recovery';old_active_current='bypass';unresolved_registry='allow_dispatch';entry_action='BindInstance'},
  [ordered]@{parameter='InitializeInstanceRegistry';class='registry_recovery';old_active_current='bypass';unresolved_registry='allow_dispatch';entry_action='InitializeInstanceRegistry'},
  [ordered]@{parameter='ListInstances';class='diagnostic_recovery';old_active_current='bypass';unresolved_registry='allow_dispatch';entry_action='ListInstances'},
  [ordered]@{parameter='SwitchInstanceId';class='target_driven_recovery';old_active_current='bypass';unresolved_registry='allow_dispatch';entry_action='SwitchInstance'},
  [ordered]@{parameter='RegisterInstancePath';class='registry_target_mutation';old_active_current='reconcile_required';unresolved_registry='fail_closed';entry_action=$null},
  [ordered]@{parameter='GenesisInstancePath';class='registry_target_genesis';old_active_current='reconcile_required';unresolved_registry='fail_closed';entry_action=$null}
 )
 freeze_rule='PrimaryModeCount, centralized compatibility-shadow bypass and unresolved-registry pre-dispatch allowlist must exactly match this policy. Every bypass action requires real process-entry evidence.'
}
$policyPath=Join-Path $RepositoryRoot 'tests\knowledge\manager-entry-policy.json';Write-Json $policyPath $policy

# 2. Permanent AST completeness guard.
$validatorPath=Join-Path $RepositoryRoot 'tools\Test-ManagerEntryPolicyCompleteness.ps1'
$validator=@'
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
$funcVars=@($func[0].Body.FindAll({param($n)$n-is[Management.Automation.Language.VariableExpressionAst]},$true)|ForEach-Object{$_.VariablePath.UserPath}|Where-Object{$_-cne'script:InstanceRegistryActive'}|Sort-Object -Unique)
$expectedBypass=@($rows|Where-Object{[string]$_.old_active_current-ceq'bypass'}|ForEach-Object{[string]$_.parameter});Same-Set $expectedBypass $funcVars 'Compatibility-shadow bypass set'
$allow=@($assignments|Where-Object{$_.Left-is[Management.Automation.Language.VariableExpressionAst]-and$_.Left.VariablePath.UserPath-ceq'allowRegistryUnresolved'});if($allow.Count-ne1){Fail('allowRegistryUnresolved assignment count='+$allow.Count)}
$allowVars=@($allow[0].Right.FindAll({param($n)$n-is[Management.Automation.Language.VariableExpressionAst]},$true)|ForEach-Object{$_.VariablePath.UserPath}|Sort-Object -Unique)
$expectedAllow=@($rows|Where-Object{[string]$_.unresolved_registry-ceq'allow_dispatch'}|ForEach-Object{[string]$_.parameter});Same-Set $expectedAllow $allowVars 'Unresolved-registry pre-dispatch allowlist'
$entryIds=@($entry.actions|ForEach-Object{[string]$_.id});foreach($r in @($rows|Where-Object{[string]$_.old_active_current-ceq'bypass'})){if([string]::IsNullOrWhiteSpace([string]$r.entry_action)){Fail([string]$r.parameter+' bypass lacks entry_action evidence mapping.')};if($entryIds-cnotcontains[string]$r.entry_action){Fail([string]$r.parameter+' bypass references missing entry action '+[string]$r.entry_action)}}
Write-Host 'Manager entry-policy completeness: PASS' -ForegroundColor Green
Write-Host ('  primary modes: '+$primaryVars.Count)
Write-Host ('  compatibility-shadow bypass: '+$expectedBypass.Count)
Write-Host ('  unresolved-registry allow-dispatch: '+$expectedAllow.Count)
'@
Write-Utf8 $validatorPath (($validator.TrimEnd())+"`n")

# 3. Product pre-dispatch policy: add the missing Manager-global/recovery actions, while
# leaving all active-context operations on reconciliation/fail-closed behavior.
$runtimePath=Join-Path $RepositoryRoot 'manager\product\runtime\Keelaryn__Manager.ps1';$runtime=[IO.File]::ReadAllText($runtimePath,[Text.Encoding]::UTF8)
$oldShadow='if($Doctor-or$ListInstances-or$SwitchInstanceId-or$BindInstancePath-or$UpdateManager-or$BuildDistribution-or$BuildRelease-or$BuildAIContext){return $false}'
$newShadow='if($Doctor-or$SelfTest-or$ListInstances-or$SwitchInstanceId-or$BindInstancePath-or$InitializeInstanceRegistry-or$UpdateManager-or$BuildDistribution-or$BuildRelease-or$BuildAIContext-or$PrepareTests-or$InitializePresentation-or$FinalizeFilesystemLayout){return $false}'
$runtime=Replace-Once $runtime $oldShadow $newShadow 'compatibility-shadow bypass expansion'
$oldRegistry='$allowRegistryUnresolved=$Doctor-or$SelfTest-or$BuildDistribution-or$BuildRelease-or$BuildAIContext-or$UpdateManager-or$InitializeInstanceRegistry-or$ListInstances-or$SwitchInstanceId-or$BindInstancePath-or$FinalizeFilesystemLayout'
$newRegistry='$allowRegistryUnresolved=$Doctor-or$SelfTest-or$BuildDistribution-or$BuildRelease-or$BuildAIContext-or$UpdateManager-or$PrepareTests-or$InitializePresentation-or$InitializeInstanceRegistry-or$ListInstances-or$SwitchInstanceId-or$BindInstancePath-or$FinalizeFilesystemLayout'
$runtime=Replace-Once $runtime $oldRegistry $newRegistry 'unresolved-registry allowlist expansion'
$oldSkip='$SkipHubBindingResolution = (Test-Path -LiteralPath $script:InstanceRegistryFile -PathType Leaf) -or ((-not $BindInstancePath) -and ($SelfTest -or $BuildDistribution -or $BuildRelease -or $BuildAIContext -or $UpdateManager -or $BuildCandidateTransport -or $RestoreCandidateTransport -or $FinalizeFilesystemLayout -or $ListInstances -or $RegisterInstancePath -or $SwitchInstanceId -or $GenesisInstancePath))'
$newSkip='$SkipHubBindingResolution = (Test-Path -LiteralPath $script:InstanceRegistryFile -PathType Leaf) -or ((-not $BindInstancePath) -and ($SelfTest -or $BuildDistribution -or $BuildRelease -or $BuildAIContext -or $UpdateManager -or $PrepareTests -or $InitializePresentation -or $BuildCandidateTransport -or $RestoreCandidateTransport -or $FinalizeFilesystemLayout -or $ListInstances -or $RegisterInstancePath -or $SwitchInstanceId -or $GenesisInstancePath))'
$runtime=Replace-Once $runtime $oldSkip $newSkip 'single-instance binding skip expansion'
$oldUnresolved='$allowUnresolved = $Doctor -or $SelfTest -or $BuildDistribution -or $BuildRelease -or $BuildAIContext -or $BuildCandidateTransport -or $RestoreCandidateTransport -or $InitializePresentation -or $FinalizeFilesystemLayout -or $WantsManagerUpdate'
$newUnresolved='$allowUnresolved = $Doctor -or $SelfTest -or $BuildDistribution -or $BuildRelease -or $BuildAIContext -or $PrepareTests -or $BuildCandidateTransport -or $RestoreCandidateTransport -or $InitializePresentation -or $FinalizeFilesystemLayout -or $WantsManagerUpdate'
$runtime=Replace-Once $runtime $oldUnresolved $newUnresolved 'legacy binding allowlist expansion'
Write-Utf8 $runtimePath $runtime

# 4. Expand the executable process-entry matrix. Four Manager-global actions must work in
# all degraded states; registry initialization must bypass old CURRENT but may still reject
# invalid registry/active-Hub state through its own operation-level validation.
$entryPath=Join-Path $RepositoryRoot 'tests\knowledge\entry-reachability.json';$entry=Get-Content $entryPath -Raw -Encoding UTF8|ConvertFrom-Json
foreach($row in @(
 [pscustomobject]@{id='SelfTest';class='manager_global_diagnostic';expected_mode='global_success';invariants=@('MH-MANAGER-GLOBAL-001','MH-RECOVERY-001')},
 [pscustomobject]@{id='PrepareTests';class='manager_global';expected_mode='global_success';invariants=@('MH-MANAGER-GLOBAL-001','MH-RECOVERY-001')},
 [pscustomobject]@{id='InitializePresentation';class='manager_global';expected_mode='global_success';invariants=@('MH-MANAGER-GLOBAL-001','MH-RECOVERY-001')},
 [pscustomobject]@{id='FinalizeFilesystemLayout';class='manager_global';expected_mode='global_success';invariants=@('MH-MANAGER-GLOBAL-001','MH-RECOVERY-001')},
 [pscustomobject]@{id='InitializeInstanceRegistry';class='registry_recovery';expected_mode='global_success';invariants=@('MH-REGISTRY-001','MH-RECOVERY-001')}
)){if(@($entry.actions|Where-Object{[string]$_.id-ceq$row.id}).Count-eq0){$entry.actions=@($entry.actions)+@($row)}}
$all=@($entry.coverage_requirements|Where-Object{[string]$_.id-ceq'CR-ALL-DEGRADED-ENTRY'});if($all.Count-ne1){Fail 'CR-ALL-DEGRADED-ENTRY missing/ambiguous.'};foreach($a in @('SelfTest','PrepareTests','InitializePresentation','FinalizeFilesystemLayout')){if(@($all[0].actions)-notcontains$a){$all[0].actions=@($all[0].actions)+@($a)}}
$current=@($entry.coverage_requirements|Where-Object{[string]$_.id-ceq'CR-CURRENT-DEGRADED-BOUNDARIES'});if($current.Count-ne1){Fail 'CR-CURRENT-DEGRADED-BOUNDARIES missing/ambiguous.'};if(@($current[0].actions)-notcontains'InitializeInstanceRegistry'){$current[0].actions=@($current[0].actions)+@('InitializeInstanceRegistry')}
$entry.freeze_rule='Every pair generated by coverage_requirements must execute through the real Manager process entry on a disposable Windows installation. Every compatibility-shadow bypass action must have executable entry coverage. Any new PrimaryModeCount action absent from manager-entry-policy.json is a release blocker. A scenario harness may not restore state through the same runtime path under test and must publish a result record even when setup or cleanup fails.'
Write-Json $entryPath $entry

# 5. Teach matrix/knowledge validators the expanded action set.
$matrixPath=Join-Path $RepositoryRoot 'tools\Invoke-ManagerEntryReachabilityMatrix.ps1';$matrix=[IO.File]::ReadAllText($matrixPath,[Text.Encoding]::UTF8)
$matrix=Replace-Once $matrix "            'Doctor' {return @('-Doctor')}" ("            'Doctor' {return @('-Doctor')}`r`n            'SelfTest' {return @('-SelfTest')}`r`n            'PrepareTests' {return @('-PrepareTests')}`r`n            'InitializePresentation' {return @('-InitializePresentation')}`r`n            'FinalizeFilesystemLayout' {return @('-FinalizeFilesystemLayout')}`r`n            'InitializeInstanceRegistry' {return @('-InitializeInstanceRegistry')}") 'entry matrix action arguments'
Write-Utf8 $matrixPath $matrix
$entryValidatorPath=Join-Path $RepositoryRoot 'tools\Test-ManagerEntryReachabilityKnowledge.ps1';$ev=[IO.File]::ReadAllText($entryValidatorPath,[Text.Encoding]::UTF8)
$oldRequired="foreach(`$requiredAction in @('ListInstances','SwitchInstance','BindInstance','UpdateManager','BuildDistribution','BuildRelease','BuildAIContext','Doctor','UpdateHub','UpdateAll','RepairCurrent','BuildCandidateTransport','RestoreCandidateTransport'))"
$newRequired="foreach(`$requiredAction in @('ListInstances','SwitchInstance','BindInstance','UpdateManager','BuildDistribution','BuildRelease','BuildAIContext','Doctor','SelfTest','PrepareTests','InitializePresentation','FinalizeFilesystemLayout','InitializeInstanceRegistry','UpdateHub','UpdateAll','RepairCurrent','BuildCandidateTransport','RestoreCandidateTransport'))"
$ev=Replace-Once $ev $oldRequired $newRequired 'entry required-action inventory'
$oldAll="foreach(`$aid in @('ListInstances','SwitchInstance','BindInstance','UpdateManager','BuildDistribution','BuildRelease','BuildAIContext','Doctor','UpdateHub'))"
$newAll="foreach(`$aid in @('ListInstances','SwitchInstance','BindInstance','UpdateManager','BuildDistribution','BuildRelease','BuildAIContext','Doctor','SelfTest','PrepareTests','InitializePresentation','FinalizeFilesystemLayout','UpdateHub'))"
$ev=Replace-Once $ev $oldAll $newAll 'entry all-degraded action inventory'
$oldCurrent="foreach(`$aid in @('UpdateAll','RepairCurrent','BuildCandidateTransport','RestoreCandidateTransport'))"
$newCurrent="foreach(`$aid in @('UpdateAll','RepairCurrent','BuildCandidateTransport','RestoreCandidateTransport','InitializeInstanceRegistry'))"
$ev=Replace-Once $ev $oldCurrent $newCurrent 'entry current-degraded action inventory'
$ev=Replace-Once $ev "if(`$pairs.Count-lt53)" "if(`$pairs.Count-lt75)" 'entry minimum scenario count'
Write-Utf8 $entryValidatorPath $ev

# 6. Development Validation permanently owns the completeness guard and runs source SelfTests
# on a disposable managed copy so validation cannot contaminate authoritative source.
$devPath=Join-Path $RepositoryRoot 'tools\Invoke-DevelopmentValidation.ps1';$dev=[IO.File]::ReadAllText($devPath,[Text.Encoding]::UTF8)
$anchor="    'tools\Test-ManagerEntryReachabilityKnowledge.ps1',"
$dev=Replace-Once $dev $anchor ($anchor+"`r`n    'tools\Test-ManagerEntryPolicyCompleteness.ps1',") 'development policy tool inventory'
$entryRun='$entryModelValidator=Join-Path $RepositoryRoot ''tools\Test-ManagerEntryReachabilityKnowledge.ps1'''
$policyRun="$entryPolicyValidator=Join-Path `$RepositoryRoot 'tools\Test-ManagerEntryPolicyCompleteness.ps1'`r`nInvoke-Child `$entryPolicyValidator @('-RepositoryRoot',`$RepositoryRoot)`r`n"+$entryRun
$dev=Replace-Once $dev $entryRun $policyRun 'development policy execution'
$oldSelf="Invoke-Child `$runtime @('-SelfTest')`r`nInvoke-Child `$menu @('-SelfTest','-NoRootLauncher')"
$newSelf=@'
$selfTestRoot=Join-Path $OutputDirectory 'source-selftest\manager'
Copy-Managed $manager $selfTestRoot
Invoke-Child (Join-Path $selfTestRoot 'product\runtime\Keelaryn__Manager.ps1') @('-SelfTest')
Invoke-Child (Join-Path $selfTestRoot 'product\tools\KeelarynMenu.ps1') @('-SelfTest','-NoRootLauncher')
'@
$dev=Replace-Once $dev $oldSelf ($newSelf.TrimEnd()) 'development disposable source SelfTests'
$dev=Replace-Once $dev '    entry_reachability_pass=$true' "    entry_reachability_pass=`$true`r`n    entry_policy_completeness_pass=`$true" 'development evidence policy flag'
Write-Utf8 $devPath $dev

# Keep workflow triggering complete for future policy-only changes.
$workflowPath=Join-Path $RepositoryRoot '.github\workflows\development-validation.yml';$wf=[IO.File]::ReadAllText($workflowPath,[Text.Encoding]::UTF8)
$wf=Replace-Once $wf "      - 'tools/Invoke-Manager41712ReviewRegression.ps1'" "      - 'tools/Invoke-Manager41712ReviewRegression.ps1'`n      - 'tools/Invoke-ManagerRecoveryBehaviorRegression.ps1'`n      - 'tools/Invoke-Manager41713ReviewRegression.ps1'`n      - 'tools/Test-ManagerEntryReachabilityKnowledge.ps1'`n      - 'tools/Test-ManagerEntryPolicyCompleteness.ps1'`n      - 'tools/Invoke-ManagerEntryReachabilityMatrix.ps1'" 'development workflow policy paths'
Write-Utf8 $workflowPath $wf

# 7. Rebind public manifest/provenance to unqualified 4.17.13. Never inherit 4.17.12
# production qualification claims onto the successor.
Run (Join-Path $RepositoryRoot 'tools\Build-PublicFileManifest.ps1') @('-RepositoryRoot',$RepositoryRoot,'-Write')|Out-Null
$manifest=Get-Content (Join-Path $RepositoryRoot 'PUBLIC_FILE_MANIFEST.json') -Raw -Encoding UTF8|ConvertFrom-Json
$provPath=Join-Path $RepositoryRoot 'PUBLIC_PROVENANCE.json';$prov=Get-Content $provPath -Raw -Encoding UTF8|ConvertFrom-Json
$oldQualification=$prov.qualification_evidence
$prov.source_manager_version='4.17.13';$prov.source_gate_baseline_manager_version='4.17.12';$prov.source_manager_installation_sha256=[string]$manifest.manager.installation_sha256;$prov.source_manager_gate_managed_content_sha256=[string]$manifest.manager.gate_managed_content_sha256
$prov.candidate_identity.revision='development';$prov.candidate_identity.frozen_commit=$null;$prov.candidate_identity.frozen_tree=$null;$prov.candidate_identity.validated_development_parent=$ExpectedBase;$prov.candidate_identity.immutable=$false;$prov.candidate_identity.product_bytes_changed_after_freeze=$false
$prov.production_validation.full_gate_pass=$false;$prov.production_validation.gate_revision=$null;$prov.production_validation.framework_revision=24;$prov.production_validation.tested_update_sha256='';$prov.production_validation.production_doctor_pass=$false;$prov.production_validation.production_ux_smoke_pass=$false;$prov.production_validation.production_managed_content_prefix=''
$prov.qualification_evidence=[ordered]@{predecessor_4_17_12=$oldQualification;development_4_17_13=[ordered]@{status='unqualified_development';candidate_issued=$false;entry_policy_modes=29;entry_reachability_scenarios=75;exact_head_validation='required_before_freeze'}}
$prov.publication_status.status='unqualified_development';$prov.publication_status.public_release_approved=$false;$prov.publication_status.merged_to_main=$false;$prov.publication_status.multi_hub_activated=$false
$prov.gate_framework.frozen_for_manager_candidate=$false;$prov.public_candidate_revision=[int]$prov.public_candidate_revision+1
Write-Json $provPath $prov

$statePath=Join-Path $RepositoryRoot 'MANAGER_DEVELOPMENT_STATE.json';$state=Get-Content $statePath -Raw -Encoding UTF8|ConvertFrom-Json
$state.materialization.product_commit=$null;$state.materialization.product_tree=$null;$state.materialization.installation_sha256=[string]$manifest.manager.installation_sha256;$state.materialization.managed_content_sha256=[string]$manifest.manager.gate_managed_content_sha256;$state.materialization.status='materialized_unqualified_development_live_branch';$state.materialization.candidate_issued=$false
$state.qualification.successor_4_17_13.status='materialized_unqualified_development_entry_policy_hardening';$state.qualification.successor_4_17_13.process_entry_green_proof='R5 requires 75-scenario exact-entry PASS plus 29-mode completeness guard'
$req=@($state.qualification.successor_4_17_13.required_before_freeze);if($req-notcontains'entry_policy_completeness_pass'){$state.qualification.successor_4_17_13.required_before_freeze=@($req)+@('entry_policy_completeness_pass')}
if($null-eq$state.knowledge.PSObject.Properties['entry_policy_model']){$state.knowledge|Add-Member -NotePropertyName entry_policy_model -NotePropertyValue 'tests/knowledge/manager-entry-policy.json'}else{$state.knowledge.entry_policy_model='tests/knowledge/manager-entry-policy.json'}
if($null-eq$state.knowledge.PSObject.Properties['entry_policy_validator']){$state.knowledge|Add-Member -NotePropertyName entry_policy_validator -NotePropertyValue 'tools/Test-ManagerEntryPolicyCompleteness.ps1'}else{$state.knowledge.entry_policy_validator='tools/Test-ManagerEntryPolicyCompleteness.ps1'}
$state.next_exact_goal.id='MANAGER-41713-PREFREEZE-001';$state.next_exact_goal.description='Obtain exact-head Development Validation with 29-mode entry-policy completeness and 75-scenario process-entry PASS, then full-successor Risk/Defect Gate and semantic pre-freeze review.';$state.next_exact_goal.candidate_freeze_permitted=$false
Write-Json $statePath $state

# 8. Precommit coherence checks.
Run $validatorPath @('-RepositoryRoot',$RepositoryRoot)|Out-Null
Run $entryValidatorPath @('-RepositoryRoot',$RepositoryRoot)|Out-Null
$entryEvidence=Join-Path $EvidenceRoot 'ENTRY_REACHABILITY_RESULT.json';Run $matrixPath @('-RepositoryRoot',$RepositoryRoot,'-OutputPath',$entryEvidence)|Out-Null
Run (Join-Path $RepositoryRoot 'tools\Test-ManagerEngineeringKnowledge.ps1') @('-RepositoryRoot',$RepositoryRoot)|Out-Null
Run (Join-Path $RepositoryRoot 'tools\Verify-ManagerReleaseInstructions.ps1') @('-RepositoryRoot',$RepositoryRoot)|Out-Null
Run (Join-Path $RepositoryRoot 'tools\Build-PublicFileManifest.ps1') @('-RepositoryRoot',$RepositoryRoot,'-Check')|Out-Null
Run (Join-Path $RepositoryRoot 'tools\Verify-PublicCandidateMetadata.ps1') @('-RepositoryRoot',$RepositoryRoot)|Out-Null
Run (Join-Path $RepositoryRoot 'tools\Verify-PublicRepository.ps1') @('-RepositoryRoot',$RepositoryRoot)|Out-Null

# 9. Commit exact coherent dev revision, then validate the committed identity before push.
git.exe -C $RepositoryRoot add --all
$status=@(git.exe -C $RepositoryRoot status --porcelain);if($status.Count-eq0){Fail 'Entry-policy materializer produced no changes.'}
git.exe -C $RepositoryRoot commit -m 'Manager 4.17.13: complete process-entry policy coverage';if($LASTEXITCODE-ne0){Fail 'Could not commit entry-policy revision.'}
$head=(& git.exe -C $RepositoryRoot rev-parse HEAD).Trim().ToLowerInvariant();$tree=(& git.exe -C $RepositoryRoot rev-parse 'HEAD^{tree}').Trim().ToLowerInvariant()
$devOut=Join-Path $EvidenceRoot 'development-validation';Run (Join-Path $RepositoryRoot 'tools\Invoke-DevelopmentValidation.ps1') @('-RepositoryRoot',$RepositoryRoot,'-OutputDirectory',$devOut)|Out-Null
$dirty=@(git.exe -C $RepositoryRoot status --porcelain);if($dirty.Count-ne0){Fail('Committed Development Validation dirtied source: '+([string]::Join(' | ',$dirty)))}
Write-Host ('MANAGER 4.17.13 ENTRY POLICY MATERIALIZATION: PASS head='+$head+' tree='+$tree) -ForegroundColor Green
Write-Host ('ENTRY_EVIDENCE='+$entryEvidence)
Write-Host ('DEVELOPMENT_EVIDENCE='+$devOut)
