param([Parameter(Mandatory=$true)][string]$RepositoryRoot)
$ErrorActionPreference='Stop'
$runtime=Join-Path ([System.IO.Path]::GetFullPath($RepositoryRoot)) 'manager\product\runtime\Keelaryn__Manager.ps1'
$text=[System.IO.File]::ReadAllText($runtime,[System.Text.Encoding]::UTF8)
$tokens=$null;$errors=$null
$ast=[System.Management.Automation.Language.Parser]::ParseInput($text,[ref]$tokens,[ref]$errors)
if(@($errors).Count-ne0){throw('Runtime parser failure: '+(@($errors|ForEach-Object{$_.Message})-join'; '))}
$names=@($ast.FindAll({param($n)$n-is[System.Management.Automation.Language.FunctionDefinitionAst]},$true)|ForEach-Object{$_.Name})
foreach($name in @('Get-CompatibilityBindingAssessment','Get-RegisteredVaultCheckpointIdentity','Get-CurrentCompatibilityAssessment','Publish-ExactManagerStateFile','Get-CompatibilityShadowAssessment','Publish-CompatibilityShadowFromRegisteredInstance','Invoke-ReconcileActiveCompatibilityShadow')){
    if($names-notcontains$name){throw('Missing compatibility-shadow function: '+$name)}
}
foreach($token in @("'multi_hub_switch_prepare'","'multi_hub_switch_rollback'","'multi_hub_shadow_reconciled_from_instance'","'multi_hub_shadow_adopted_to_instance'","'compatibility.shadow'",'Hub update durable commit succeeded, but compatibility shadow synchronization failed:','CURRENT sanitation durable commit succeeded, but compatibility shadow synchronization failed:')){
    if(-not$text.Contains($token)){throw('Missing compatibility-shadow source contract: '+$token)}
}
Write-Host 'Focused compatibility-shadow source contract: PASS'
