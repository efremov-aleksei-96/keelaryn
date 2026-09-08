[CmdletBinding()]
param(
    [string]$HubRoot,
    [string]$Scope,
    [string]$Subscope,
    [string]$CheckoutPath,
    [switch]$SelfTest
)

$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest

function Fail([string]$Message){throw $Message}
function Get-FrontmatterValue([string]$Text,[string]$Name){
    $normalized=$Text.Replace("`r`n","`n")
    if(-not$normalized.StartsWith("---`n",[System.StringComparison]::Ordinal)){return $null}
    $end=$normalized.IndexOf("`n---`n",4,[System.StringComparison]::Ordinal)
    if($end-lt0){return $null}
    $front=$normalized.Substring(4,$end-4)
    $m=[regex]::Match($front,'(?m)^'+[regex]::Escape($Name)+':\s*(.+?)\s*$')
    if(-not$m.Success){return $null}
    return ([string]$m.Groups[1].Value).Trim()
}
function Get-CanonicalH1([string]$Text,[string]$Path){
    $m=[regex]::Match($Text,'(?m)^#\s+(.+?)\s*$')
    if(-not$m.Success){Fail('Canonical project Markdown is missing an H1 title: '+$Path)}
    $title=([string]$m.Groups[1].Value).Trim()
    if(-not$title-or$title-match'[\x00-\x1F]'){Fail('Canonical project H1 is invalid: '+$Path)}
    return $title
}
function Normalize-WorkspaceKey([string]$Value){
    if($null-eq$Value){return ''}
    $value=$Value.Trim().Normalize([System.Text.NormalizationForm]::FormC).ToLowerInvariant()
    $value=[regex]::Replace($value,'[^\p{L}\p{Nd}]+',' ')
    return ([regex]::Replace($value,'\s+',' ')).Trim()
}
function Get-WorkspaceProjectRows([string]$Root){
    if([string]::IsNullOrWhiteSpace($Root)){Fail 'HubRoot is required.'}
    $full=[System.IO.Path]::GetFullPath($Root).TrimEnd('\')
    $projects=Join-Path $full 'Projects'
    if(-not(Test-Path -LiteralPath $projects -PathType Container)){Fail('Hub Projects directory is missing: '+$projects)}
    $projectsItem=Get-Item -LiteralPath $projects -Force -ErrorAction Stop
    if(($projectsItem.Attributes-band[System.IO.FileAttributes]::ReparsePoint)-ne0){Fail('Hub Projects directory must not be a reparse point: '+$projects)}
    $rows=New-Object System.Collections.ArrayList
    foreach($file in @(Get-ChildItem -LiteralPath $projects -File -Recurse -Force -Filter '*.md' -ErrorAction Stop)){
        if(($file.Attributes-band[System.IO.FileAttributes]::ReparsePoint)-ne0){Fail('Project Markdown must not be a reparse point: '+$file.FullName)}
        if($file.Length-gt4MB){Fail('Project Markdown exceeds 4 MiB: '+$file.FullName)}
        $text=[System.IO.File]::ReadAllText($file.FullName,[System.Text.Encoding]::UTF8)
        $type=Get-FrontmatterValue $text 'type'
        if(([string]$type).Trim().ToLowerInvariant()-ne'project'){continue}
        $id=(Get-FrontmatterValue $text 'id')
        if([string]::IsNullOrWhiteSpace($id)){Fail('Canonical project Markdown is missing id: '+$file.FullName)}
        $title=Get-CanonicalH1 $text $file.FullName
        $relative='Projects/'+$file.FullName.Substring($projects.Length).TrimStart('\').Replace('\','/')
        [void]$rows.Add([pscustomobject]@{
            Id=$id.Trim();Title=$title;Path=$relative;Stem=[System.IO.Path]::GetFileNameWithoutExtension($file.Name)
            IdKey=(Normalize-WorkspaceKey $id);TitleKey=(Normalize-WorkspaceKey $title);PathKey=(Normalize-WorkspaceKey $relative);StemKey=(Normalize-WorkspaceKey ([System.IO.Path]::GetFileNameWithoutExtension($file.Name)))
        })
    }
    if($rows.Count-eq0){Fail 'No canonical project Markdown entities were found.'}
    return @($rows)
}
function Test-RowKeyExact($Row,[string]$Key){
    return @($Row.IdKey,$Row.TitleKey,$Row.PathKey,$Row.StemKey)-contains$Key
}
function Test-RowKeyAlias($Row,[string]$Key){
    foreach($candidate in @($Row.IdKey,$Row.TitleKey,$Row.PathKey,$Row.StemKey)){
        if($candidate-and$candidate.Contains($Key)){return $true}
    }
    return $false
}
function Get-RouterLocatorPaths([string]$Root,[string]$Key){
    $routerPath=Join-Path ([System.IO.Path]::GetFullPath($Root)) '_System\ROUTER.json'
    if(-not(Test-Path -LiteralPath $routerPath -PathType Leaf)){return @()}
    $item=Get-Item -LiteralPath $routerPath -Force -ErrorAction Stop
    if(($item.Attributes-band[System.IO.FileAttributes]::ReparsePoint)-ne0-or$item.Length-gt4MB){Fail('ROUTER locator is unsafe: '+$routerPath)}
    try{$router=([System.IO.File]::ReadAllText($routerPath,[System.Text.Encoding]::UTF8)|ConvertFrom-Json)}catch{Fail('ROUTER locator JSON is invalid: '+$_.Exception.Message)}
    $paths=New-Object System.Collections.ArrayList
    foreach($route in @($router.routes)){
        $a=@($route)
        if($a.Count-ne4){continue}
        if(([string]$a[0]).Trim().ToLowerInvariant()-ne'project'){continue}
        $path=([string]$a[2]).Replace('\','/').Trim()
        $title=([string]$a[3]).Trim()
        $pathKey=Normalize-WorkspaceKey $path
        $titleKey=Normalize-WorkspaceKey $title
        if($Key-eq$pathKey-or$Key-eq$titleKey-or($Key.Length-ge3-and(($pathKey-and$pathKey.Contains($Key))-or($titleKey-and$titleKey.Contains($Key))))){
            if($paths-notcontains$path){[void]$paths.Add($path)}
        }
    }
    return @($paths)
}
function Resolve-WorkspaceProject([string]$Root,[string]$RequestedScope,[string]$RequestedSubscope){
    $key=Normalize-WorkspaceKey $RequestedScope
    if(-not$key){Fail 'Scope is required.'}
    $rows=@(Get-WorkspaceProjectRows $Root)
    $matches=@($rows|Where-Object{Test-RowKeyExact $_ $key})
    $method='canonical_exact'
    if($matches.Count-eq0-and$key.Length-ge3){$matches=@($rows|Where-Object{Test-RowKeyAlias $_ $key});$method='canonical_alias'}
    if($matches.Count-eq0){
        $routerPaths=@(Get-RouterLocatorPaths $Root $key)
        if($routerPaths.Count-gt0){
            $matches=@($rows|Where-Object{$routerPaths-contains([string]$_.Path)})
            $method='router_locator_canonical_markdown_authority'
        }
    }
    if($matches.Count-eq0){Fail('Scope does not resolve to one canonical project: '+$RequestedScope)}
    if($matches.Count-ne1){Fail('Scope is ambiguous across '+$matches.Count+' canonical projects: '+$RequestedScope)}
    $row=$matches[0]
    $sub=([string]$RequestedSubscope).Trim()
    if($sub-match'[\x00-\x1F]'){Fail 'Subscope contains a control character.'}
    if($sub.Length-gt120){Fail 'Subscope is too long (max 120 characters).'}
    $suggested=[string]$row.Title
    if($sub){$suggested=$suggested+' '+([string][char]0x2014)+' '+$sub}
    return [pscustomobject][ordered]@{
        source_entity_id=[string]$row.Id
        source_entity_title=[string]$row.Title
        suggested_chat_title=$suggested
        source_entity_path=[string]$row.Path
        resolution=$method
    }
}
function Get-CheckoutField([string]$Text,[string]$Name){
    $m=[regex]::Match($Text,'(?m)^'+[regex]::Escape($Name)+':\s*(.*?)\s*$')
    if(-not$m.Success){return $null}
    return ([string]$m.Groups[1].Value).Trim()
}
function Test-WorkspaceCheckoutPacketText([string]$Text){
    if([string]::IsNullOrWhiteSpace($Text)){return $false}
    if($Text.IndexOf('KEELARYN__HUB WORKSPACE CHECKOUT',[System.StringComparison]::Ordinal)-lt0){return $false}
    if((Get-CheckoutField $Text 'schema')-cne'keelaryn.workspace.v1'){return $false}
    if((Get-CheckoutField $Text 'packet_role')-cne'checkout'){return $false}
    $id=Get-CheckoutField $Text 'source_entity_id'
    $title=Get-CheckoutField $Text 'source_entity_title'
    $suggested=Get-CheckoutField $Text 'suggested_chat_title'
    $present=0
    foreach($value in @($id,$title,$suggested)){if(-not[string]::IsNullOrWhiteSpace([string]$value)){$present++}}
    if($present-eq0){return $true}
    if($present-ne3-or[string]::IsNullOrWhiteSpace($id)-or[string]::IsNullOrWhiteSpace($title)-or[string]::IsNullOrWhiteSpace($suggested)){return $false}
    if($suggested-ceq$title){return $true}
    $prefix=$title+' '+([string][char]0x2014)+' '
    return $suggested.StartsWith($prefix,[System.StringComparison]::Ordinal)-and$suggested.Length-gt$prefix.Length
}
function Invoke-WorkspaceResolverSelfTest{
    $temp=Join-Path ([System.IO.Path]::GetTempPath()) ('Keelaryn_workspace_title_'+[guid]::NewGuid().ToString('N'))
    try{
        $projects=Join-Path $temp 'Projects';$system=Join-Path $temp '_System'
        New-Item -ItemType Directory -Force -Path $projects,$system|Out-Null
        $p1=@('---','id: project.personal-bankruptcy-assessment','type: project','status: active','updated: 2030-01-01','---','','# Personal Bankruptcy Assessment & Preparation','','Fixture.')-join"`n"
        $p2=@('---','id: project.home-budget','type: project','status: active','updated: 2030-01-01','---','','# Home Budget','','Fixture.')-join"`n"
        [System.IO.File]::WriteAllText((Join-Path $projects 'Personal Bankruptcy Assessment.md'),$p1,(New-Object System.Text.UTF8Encoding($false)))
        [System.IO.File]::WriteAllText((Join-Path $projects 'Home Budget.md'),$p2,(New-Object System.Text.UTF8Encoding($false)))
        $router=[ordered]@{schema='keelaryn.router.v2';routes=@(,@('project','active','Projects/Personal Bankruptcy Assessment.md','Bankruptcy short alias'))}
        [System.IO.File]::WriteAllText((Join-Path $system 'ROUTER.json'),(($router|ConvertTo-Json -Depth 6)+"`n"),(New-Object System.Text.UTF8Encoding($false)))

        $a=Resolve-WorkspaceProject $temp 'Personal Bankruptcy Assessment' ''
        if($a.source_entity_id-cne'project.personal-bankruptcy-assessment'-or$a.source_entity_title-cne'Personal Bankruptcy Assessment & Preparation'-or$a.suggested_chat_title-cne$a.source_entity_title){Fail 'SelfTest: filename/H1 authority contract failed.'}
        $b=Resolve-WorkspaceProject $temp 'bankruptcy' ''
        if($b.source_entity_title-cne'Personal Bankruptcy Assessment & Preparation'){Fail 'SelfTest: shortened alias resolution failed.'}
        $c=Resolve-WorkspaceProject $temp 'project.personal-bankruptcy-assessment' 'Evidence review'
        $expected='Personal Bankruptcy Assessment & Preparation '+([string][char]0x2014)+' Evidence review'
        if($c.suggested_chat_title-cne$expected){Fail 'SelfTest: explicit subscope suffix contract failed.'}
        $d=Resolve-WorkspaceProject $temp 'Bankruptcy short alias' ''
        if($d.resolution-cne'router_locator_canonical_markdown_authority'-or$d.source_entity_title-cne'Personal Bankruptcy Assessment & Preparation'){Fail 'SelfTest: ROUTER locator overrode canonical Markdown title.'}

        $legacy=@('KEELARYN__HUB WORKSPACE CHECKOUT','schema: keelaryn.workspace.v1','packet_role: checkout','created: 2030-01-01','scope: bankruptcy')-join"`n"
        if(-not(Test-WorkspaceCheckoutPacketText $legacy)){Fail 'SelfTest: legacy workspace.v1 checkout was rejected.'}
        $modern=$legacy+"`nsource_entity_id: project.personal-bankruptcy-assessment`nsource_entity_title: Personal Bankruptcy Assessment & Preparation`nsuggested_chat_title: "+$expected
        if(-not(Test-WorkspaceCheckoutPacketText $modern)){Fail 'SelfTest: metadata-bearing workspace.v1 checkout was rejected.'}
        if(Test-WorkspaceCheckoutPacketText ($legacy+"`nsource_entity_id: project.personal-bankruptcy-assessment")){Fail 'SelfTest: incomplete entity metadata was accepted.'}

        $p3=@('---','id: project.bankruptcy-secondary','type: project','status: active','updated: 2030-01-01','---','','# Bankruptcy Secondary','','Fixture.')-join"`n"
        [System.IO.File]::WriteAllText((Join-Path $projects 'Bankruptcy Secondary.md'),$p3,(New-Object System.Text.UTF8Encoding($false)))
        $ambiguous=$false
        try{$null=Resolve-WorkspaceProject $temp 'bankruptcy' ''}catch{$ambiguous=$_.Exception.Message-match'ambiguous'}
        if(-not$ambiguous){Fail 'SelfTest: ambiguous alias did not fail closed.'}
        return $true
    }finally{if(Test-Path -LiteralPath $temp){Remove-Item -LiteralPath $temp -Recurse -Force -ErrorAction SilentlyContinue}}
}

if($SelfTest){
    if(-not(Invoke-WorkspaceResolverSelfTest)){exit 1}
    Write-Host 'Workspace checkout canonical-title contract: PASS'
    exit 0
}
if(-not[string]::IsNullOrWhiteSpace($CheckoutPath)){
    $full=[System.IO.Path]::GetFullPath($CheckoutPath)
    if(-not(Test-Path -LiteralPath $full -PathType Leaf)){Fail('Checkout file not found: '+$full)}
    $text=[System.IO.File]::ReadAllText($full,[System.Text.Encoding]::UTF8)
    if(-not(Test-WorkspaceCheckoutPacketText $text)){Fail('Workspace checkout packet failed compatibility validation: '+$full)}
    Write-Host 'Workspace checkout packet compatibility: PASS'
    exit 0
}
$result=Resolve-WorkspaceProject $HubRoot $Scope $Subscope
[Console]::Out.WriteLine(($result|ConvertTo-Json -Depth 4))
