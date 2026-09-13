[CmdletBinding()]
param([string]$RepositoryRoot=(Join-Path $PSScriptRoot '..'))

$ErrorActionPreference='Stop'
Set-StrictMode -Version 2.0
$RepositoryRoot=[IO.Path]::GetFullPath($RepositoryRoot).TrimEnd('\')

function Assert([bool]$Condition,[string]$Message){if(-not$Condition){throw $Message}}
function Get-FunctionAst([string]$Path,[string]$Name){
    $tokens=$null;$errors=$null
    $ast=[Management.Automation.Language.Parser]::ParseFile($Path,[ref]$tokens,[ref]$errors)
    if(@($errors).Count){throw('Parser failed for '+$Path+': '+([string]::Join(' | ',@($errors|ForEach-Object{$_.Message}))))}
    $rows=@($ast.FindAll({param($node)$node-is[Management.Automation.Language.FunctionDefinitionAst]},$true)|Where-Object{$_.Name-ceq$Name})
    if($rows.Count-ne1){throw('function '+$Name+' count='+$rows.Count)}
    return $rows[0]
}
function Get-FunctionText([string]$Path,[string]$Name){return [string](Get-FunctionAst $Path $Name).Extent.Text}
function Get-CommandAsts($FunctionAst,[string]$CommandName){
    return @($FunctionAst.Body.FindAll({param($node)
        if($node-isnot[Management.Automation.Language.CommandAst]){return $false}
        return [string]::Equals([string]$node.GetCommandName(),$CommandName,[StringComparison]::OrdinalIgnoreCase)
    },$true))
}
function Assert-OrderedCommands($FunctionAst,[string[]]$Names,[string]$Message){
    $previous=-1
    foreach($name in $Names){
        $rows=@(Get-CommandAsts $FunctionAst $name)
        Assert ($rows.Count-ge1) ($Message+' Missing command: '+$name)
        $candidate=@($rows|Where-Object{[int]$_.Extent.StartOffset-gt$previous}|Sort-Object{[int]$_.Extent.StartOffset}|Select-Object -First 1)
        Assert ($candidate.Count-eq1) ($Message+' Command order failed at: '+$name)
        $previous=[int]$candidate[0].Extent.StartOffset
    }
}
function Pass([string]$Id,[string]$Text){Write-Host ('  PASS '+$Id+' '+$Text)}

$p=Join-Path $PSHOME 'powershell.exe'
& $p -NoProfile -NonInteractive -ExecutionPolicy Bypass -File (Join-Path $RepositoryRoot 'tools\Invoke-Manager4178ReviewRegression.ps1') -RepositoryRoot $RepositoryRoot
if($LASTEXITCODE-ne0){throw 'Inherited Manager 4.17.8 regression failed.'}
Write-Host '  PASS inherited Manager 4.17.8 regression chain'

$runtimePath=Join-Path $RepositoryRoot 'manager\product\runtime\Keelaryn__Manager.ps1'
$runtime=[IO.File]::ReadAllText($runtimePath,[Text.Encoding]::UTF8)

# Recovery entry points must remain callable when registry document is valid but
# active selection / active Hub resolution is not. This is deliberately checked
# at the early-dispatch boundary as well as inside the target-driven operations.
Assert ($runtime -match '\$allowRegistryUnresolved\s*=([^\r\n]*\$SwitchInstanceId[^\r\n]*\$BindInstancePath|[^\r\n]*\$BindInstancePath[^\r\n]*\$SwitchInstanceId)') 'A02/A03/A04/A05: early unresolved-registry allowlist does not include SwitchInstanceId and BindInstancePath.'

$listText=Get-FunctionText $runtimePath 'Invoke-ListInstances'
Assert ($listText.Contains('Read-ActiveInstanceEarly')) 'A01: ListInstances no longer reads active metadata for display/diagnostic status.'
Assert ($listText -match 'try\s*\{[^}]*Read-ActiveInstanceEarly') 'A01: ListInstances requires valid active metadata instead of treating it as diagnostic-only.'
Assert (-not$listText.Contains('Get-ManagerActiveInstance')) 'A01: ListInstances depends on a fully resolved active Hub.'
Pass 'A01' 'registry remains listable when active metadata is invalid'

$switchAst=Get-FunctionAst $runtimePath 'Invoke-SwitchRegisteredInstance'
$switchText=[string]$switchAst.Extent.Text
Assert (-not$switchText.Contains('$previous=Get-ManagerActiveInstance')) 'A02-A04: SwitchInstance still requires a valid previous active Hub.'
Assert ($switchText.Contains('Assert-RegisteredInstanceActivationEligible')) 'A12/A20: SwitchInstance lacks full target activation eligibility validation.'
$shadowCalls=@(Get-CommandAsts $switchAst 'Publish-CompatibilityShadowFromRegisteredInstance')
$activationCalls=@(Get-CommandAsts $switchAst 'Assert-RegisteredInstanceActivationEligible')
$activeWrites=@(Get-CommandAsts $switchAst 'Write-ManagerActiveInstance')
Assert ($shadowCalls.Count-ge1-and$activationCalls.Count-ge1-and$activeWrites.Count-eq1) 'A12: switch transaction commands are incomplete.'
$prepare=@($shadowCalls|Where-Object{$_.Extent.Text -match 'multi_hub_switch_prepare'}|Select-Object -First 1)
Assert ($prepare.Count-eq1) 'A12: switch compatibility preparation call is missing.'
$finalGuard=@($activationCalls|Where-Object{[int]$_.Extent.StartOffset-gt[int]$prepare[0].Extent.StartOffset-and[int]$_.Extent.StartOffset-lt[int]$activeWrites[0].Extent.StartOffset})
Assert ($finalGuard.Count-ge1) 'A12: full activation eligibility is not revalidated after compatibility preparation and before active commit.'
Assert ($switchText -match 'ambiguous|durable commit|commit status') 'A14: switch failure handling does not distinguish ambiguous/durable commit outcomes.'
Assert ($switchText -notmatch 'rollback also failed[^\r\n]*Primary') 'A14: switch recovery still makes restoration of the broken previous Hub a required success condition.'
Pass 'A02-A04/A12/A14/A20' 'switch is target-driven with fresh commit-boundary eligibility and explicit outcomes'

$bindText=Get-FunctionText $runtimePath 'Invoke-BindInstance'
Assert ($bindText.Contains('Invoke-RebindRegisteredInstance')) 'A05/A06/A19: BindInstance does not route registered identities through an explicit rebind transaction.'
$rebindAst=Get-FunctionAst $runtimePath 'Invoke-RebindRegisteredInstance'
$rebindText=[string]$rebindAst.Extent.Text
Assert ($rebindText.Contains('Assert-RegisteredInstanceActivationEligible')) 'A05/A06/A19: rebind lacks full activation eligibility validation.'
Assert ($rebindText.Contains('Write-ManagerInstanceRegistry')) 'A05/A06: rebind does not atomically publish the registered path change through instances.json.'
Assert (-not$rebindText.Contains('New-RegisteredInstanceStateFromVault')) 'A05/A06: rebind must preserve existing per-instance state rather than cloning/regenerating it.'
Assert ($rebindText -match 'same.*instance_id|instance_id.*same|identity') 'A05/A06: rebind does not explicitly enforce immutable identity.'
Pass 'A05/A06/A19' 'BindInstance performs identity-preserving rebind with full eligibility validation'

$globalClassify=Get-FunctionText $runtimePath 'Get-GlobalHubOwnedInboxObjects'
Assert ($globalClassify.Contains('Keelaryn__Hub')) 'A07-A11: global Hub-input classifier does not recognize Keelaryn Hub objects.'
Assert ($globalClassify.Contains('CANDIDATE_TRANSPORT')) 'A07/A11: global Hub-input classifier omits candidate transport JSON.'
Assert ($globalClassify.Contains('Keelaryn__Manager') -or $globalClassify.Contains('ManagerGlobal')) 'A07: classifier does not explicitly separate Manager-global inputs from Hub-owned inputs.'

$stageAst=Get-FunctionAst $runtimePath 'Stage-GlobalHubInputsForRegistryActivation'
$stageText=[string]$stageAst.Extent.Text
Assert ($stageText.Contains('instance_id') -or $stageText.Contains('InstanceId')) 'A07: bootstrap Hub-input staging does not validate instance ownership.'
Assert ((@(Get-CommandAsts $stageAst 'Copy-Item').Count-ge1) -or $stageText -match 'File\.Copy') 'A07: pending inputs are not copied/staged before registry commit.'
Assert (@(Get-CommandAsts $stageAst 'Move-Item').Count-eq0) 'A07: bootstrap staging moves the only reachable pending input before registry commit.'
Assert ($stageText -match 'collision|already exists|Test-Path') 'A07: bootstrap staging lacks destination collision handling.'

$completeText=Get-FunctionText $runtimePath 'Complete-GlobalHubInputActivationHandoff'
Assert ($completeText -match 'Remove-Item') 'A07: post-commit handoff never removes proven duplicate global sources.'
Assert ($completeText -match 'hash|SHA|Get-FileHash') 'A07: post-commit cleanup does not revalidate source/destination identity.'

$initAst=Get-FunctionAst $runtimePath 'Invoke-InitializeInstanceRegistry'
$initText=[string]$initAst.Extent.Text
Assert ($initText.Contains('Stage-GlobalHubInputsForRegistryActivation')) 'A07: registry bootstrap does not account for pending global Hub inputs before commit.'
Assert ($initText.Contains('Complete-GlobalHubInputActivationHandoff')) 'A07: registry bootstrap lacks safe post-commit pending-input cleanup.'
$initShadow=@(Get-CommandAsts $initAst 'Publish-CompatibilityShadowFromRegisteredInstance'|Select-Object -First 1)
$initGuards=@(Get-CommandAsts $initAst 'Assert-RegisteredInstanceActivationEligible')
$initActive=@(Get-CommandAsts $initAst 'Write-ManagerActiveInstance')
$initRegistry=@(Get-CommandAsts $initAst 'Write-ManagerInstanceRegistry')
Assert ($initShadow.Count-eq1-and$initActive.Count-eq1-and$initRegistry.Count-eq1) 'A13: registry-bootstrap commit sequence is incomplete.'
$guardAfterShadowBeforeActive=@($initGuards|Where-Object{[int]$_.Extent.StartOffset-gt[int]$initShadow[0].Extent.StartOffset-and[int]$_.Extent.StartOffset-lt[int]$initActive[0].Extent.StartOffset})
$guardAfterActiveBeforeRegistry=@($initGuards|Where-Object{[int]$_.Extent.StartOffset-gt[int]$initActive[0].Extent.StartOffset-and[int]$_.Extent.StartOffset-lt[int]$initRegistry[0].Extent.StartOffset})
Assert ($guardAfterShadowBeforeActive.Count-ge1-and$guardAfterActiveBeforeRegistry.Count-ge1) 'A13: registry bootstrap does not freshly enforce full activation eligibility at both authoritative commit boundaries.'
Pass 'A07/A13' 'registry activation preserves pending-input reachability and full commit predicates'

$globalGuardText=Get-FunctionText $runtimePath 'Assert-NoStrandedGlobalHubInputs'
Assert ($globalGuardText.Contains('Get-GlobalHubOwnedInboxObjects')) 'A08-A11: stranded-global guard does not use the canonical classifier.'
foreach($fn in @('Invoke-BuildCandidateTransport','Invoke-RestoreCandidateTransport')){
    $text=Get-FunctionText $runtimePath $fn
    Assert ($text.Contains('Assert-NoStrandedGlobalHubInputs')) ('A10/A11: '+$fn+' can silently ignore global Hub-owned input.')
}
$hubDecisionText=Get-FunctionText $runtimePath 'Find-HubUpdateDecision'
Assert ($hubDecisionText.Contains('Assert-NoStrandedGlobalHubInputs') -or $runtime -match 'Assert-NoStrandedGlobalHubInputs[^\r\n]*(UpdateHub|hub update)') 'A09: Hub update path can silently ignore global Hub-owned inputs.'
$doctorText=Get-FunctionText $runtimePath 'Invoke-Doctor'
Assert ($doctorText.Contains('Get-GlobalHubOwnedInboxObjects')) 'A08: Doctor does not inspect stranded global Hub-owned inputs.'
Assert ($doctorText -match 'hub_global|global.*Hub|stranded') 'A08: Doctor does not emit a distinct global-Hub-input diagnostic.'
Pass 'A08-A11' 'steady-state global Hub-owned inputs are diagnosed and block Hub/candidate operations'

# A15/A16 are pre-existing diagnostic behavior but remain in this permanent convergence
# suite so future recovery work cannot accidentally require every inactive vault to be healthy.
Assert ($doctorText.Contains('Get-ManagerInstanceRegistry')) 'A15/A16: Doctor no longer inspects registry rows.'
Assert ($doctorText.Contains('Assert-RegisteredInstanceBaseline') -or $doctorText.Contains('Get-CompatibilityShadowAssessment')) 'A15/A16: Doctor lacks registered-instance health assessment.'
Assert (-not$doctorText.Contains('throw ''Inactive registered Hub')) 'A15/A16: Doctor aborts rather than reporting inactive-Hub findings.'
Pass 'A15/A16' 'Doctor retains inactive missing/corrupt Hub diagnostics without disabling healthy active use'

# These contracts are inherited from the 4.17.7/4.17.8 chain; retaining explicit checks here
# binds the convergence release to the original audit scenarios.
Assert ($runtime.Contains('Assert-UpdateAllContextSafe')) 'A17: UpdateAll restart/context guard is missing.'
$registerText=Get-FunctionText $runtimePath 'Invoke-RegisterExistingInstance'
Assert ($registerText.Contains('Assert-RegisteredInstanceActivationEligible')) 'A18: registration no longer rejects non-approved CURRENT before commit.'
Pass 'A17/A18' 'UpdateAll context and non-approved registration guards remain inherited'

Write-Host 'MANAGER 4.17.9 CONVERGENCE REGRESSION: PASS' -ForegroundColor Green
