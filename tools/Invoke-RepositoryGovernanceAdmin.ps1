[CmdletBinding()]
param(
    [ValidateSet('Plan','Apply')]
    [string]$Mode='Plan',
    [string]$Repository='efremov-aleksei-96/keelaryn',
    [string]$PolicyRef='main',
    [switch]$FreezePreservedBranches,
    [switch]$CleanupFrozenBranches,
    [string[]]$DeleteBranchNames=@()
)

$ErrorActionPreference='Stop'
Set-StrictMode -Version 2.0

function Fail([string]$Message){throw $Message}
function Invoke-GhJson([string[]]$Arguments){
    $raw=@(& gh @Arguments 2>&1)
    if($LASTEXITCODE-ne0){Fail('gh '+($Arguments-join' ')+' failed: '+($raw-join"`n"))}
    $text=($raw-join"`n").Trim()
    if([string]::IsNullOrWhiteSpace($text)){return $null}
    return $text|ConvertFrom-Json
}
function Invoke-Gh([string[]]$Arguments){
    $raw=@(& gh @Arguments 2>&1)
    if($LASTEXITCODE-ne0){Fail('gh '+($Arguments-join' ')+' failed: '+($raw-join"`n"))}
    return @($raw)
}
function Get-RemoteJsonFile([string]$Path){
    $encoded=[System.Uri]::EscapeDataString($PolicyRef)
    $doc=Invoke-GhJson @('api',('repos/'+$Repository+'/contents/'+$Path+'?ref='+$encoded))
    if([string]$doc.type-ne'file'-or[string]::IsNullOrWhiteSpace([string]$doc.content)){Fail('Could not fetch policy file: '+$Path+' @ '+$PolicyRef)}
    $bytes=[Convert]::FromBase64String(([string]$doc.content).Replace("`n",''))
    return [System.Text.Encoding]::UTF8.GetString($bytes)|ConvertFrom-Json
}
function Api-RefPath([string]$Ref){
    return ($Ref -split '/'|ForEach-Object{[System.Uri]::EscapeDataString($_)})-join'/'
}
function Get-ExistingTagSha([string]$Tag){
    $path='repos/'+$Repository+'/git/ref/tags/'+(Api-RefPath $Tag)
    $raw=@(& gh api $path 2>&1)
    if($LASTEXITCODE-eq0){
        $doc=($raw-join"`n")|ConvertFrom-Json
        if([string]$doc.object.type-ne'commit'){Fail('Expected lightweight provenance tag to point directly to commit: '+$Tag)}
        return [string]$doc.object.sha
    }
    $text=$raw-join"`n"
    if($text-match'404|Not Found'){return $null}
    Fail('Failed to query tag '+$Tag+': '+$text)
}
function Get-Branches(){
    $raw=@(& gh api ('repos/'+$Repository+'/branches?per_page=100') --paginate --slurp 2>&1)
    if($LASTEXITCODE-ne0){Fail('Failed to list branches: '+($raw-join"`n"))}
    $pages=($raw-join"`n")|ConvertFrom-Json
    $rows=New-Object System.Collections.ArrayList
    foreach($page in @($pages)){foreach($row in @($page)){[void]$rows.Add($row)}}
    return @($rows)
}
function Get-OpenPrHeads(){
    $raw=@(& gh api ('repos/'+$Repository+'/pulls?state=open&per_page=100') --paginate --slurp 2>&1)
    if($LASTEXITCODE-ne0){Fail('Failed to list open pull requests: '+($raw-join"`n"))}
    $pages=($raw-join"`n")|ConvertFrom-Json
    $heads=New-Object System.Collections.ArrayList
    foreach($page in @($pages)){foreach($pr in @($page)){if([string]$pr.head.repo.full_name-eq$Repository){[void]$heads.Add([string]$pr.head.ref)}}}
    return @($heads|Select-Object -Unique)
}
function Ensure-ProvenanceRuleset($Policy){
    $desired=$Policy.provenance_tag_ruleset
    $all=Invoke-GhJson @('api',('repos/'+$Repository+'/rulesets?per_page=100'))
    $matches=@($all|Where-Object{[string]$_.name-eq[string]$desired.name})
    if($matches.Count-gt1){Fail('Multiple provenance tag rulesets exist with the same name.')}
    $payload=[ordered]@{
        name=[string]$desired.name
        target='tag'
        enforcement='active'
        bypass_actors=@()
        conditions=[ordered]@{ref_name=[ordered]@{include=@($desired.include_refs);exclude=@()}}
        rules=@(
            [ordered]@{type='deletion'},
            [ordered]@{type='non_fast_forward'}
        )
    }
    $json=$payload|ConvertTo-Json -Depth 10 -Compress
    if($matches.Count-eq0){
        Write-Host ('Provenance tag ruleset: CREATE '+[string]$desired.name) -ForegroundColor Yellow
        if($Mode-eq'Apply'){
            $json|gh api --method POST ('repos/'+$Repository+'/rulesets') --input -|Out-Null
            if($LASTEXITCODE-ne0){Fail('Failed to create provenance tag ruleset.')}
        }
    }else{
        $id=[string]$matches[0].id
        Write-Host ('Provenance tag ruleset: UPDATE/VERIFY id='+$id) -ForegroundColor Yellow
        if($Mode-eq'Apply'){
            $json|gh api --method PUT ('repos/'+$Repository+'/rulesets/'+$id) --input -|Out-Null
            if($LASTEXITCODE-ne0){Fail('Failed to update provenance tag ruleset.')}
        }
    }
}
function Assert-ProvenanceRuleset($Policy){
    $desired=$Policy.provenance_tag_ruleset
    $all=Invoke-GhJson @('api',('repos/'+$Repository+'/rulesets?per_page=100'))
    $matches=@($all|Where-Object{[string]$_.name-eq[string]$desired.name})
    if($matches.Count-ne1){Fail('Expected exactly one active provenance tag ruleset after apply.')}
    $detail=Invoke-GhJson @('api',('repos/'+$Repository+'/rulesets/'+[string]$matches[0].id))
    if([string]$detail.target-ne'tag'){Fail('Provenance ruleset target mismatch after apply.')}
    if(([string]$detail.enforcement).ToLowerInvariant()-notin@('active','enabled')){Fail('Provenance ruleset is not active after apply.')}
    $include=@($detail.conditions.ref_name.include|ForEach-Object{[string]$_})
    foreach($expected in @($desired.include_refs)){if($include-cnotcontains[string]$expected){Fail('Provenance ruleset is missing include: '+[string]$expected)}}
    if($include.Count-ne@($desired.include_refs).Count){Fail('Provenance ruleset has unexpected include refs.')}
    if(@($detail.conditions.ref_name.exclude).Count-ne0){Fail('Provenance ruleset must not exclude refs.')}
    if(@($detail.bypass_actors).Count-ne0){Fail('Provenance ruleset bypass list must be empty.')}
    $types=@($detail.rules|ForEach-Object{[string]$_.type})
    foreach($type in @('deletion','non_fast_forward')){if($types-notcontains$type){Fail('Provenance ruleset is missing rule '+$type)}}
    Write-Host ('Provenance tag ruleset: PASS. id='+[string]$matches[0].id) -ForegroundColor Green
}

if($Repository-notmatch'^[^/]+/[^/]+$'){Fail('Repository must be owner/name.')}
if(-not(Get-Command gh -ErrorAction SilentlyContinue)){Fail('GitHub CLI gh.exe is required.')}
& gh auth status 2>&1|Out-Host
if($LASTEXITCODE-ne0){Fail('GitHub CLI is not authenticated.')}

$policy=Get-RemoteJsonFile 'REPOSITORY_GOVERNANCE.json'
if([string]$policy.schema-ne'keelaryn.repository-governance.v1'-or[int]$policy.revision-lt5){Fail('PolicyRef does not contain Repository Governance r5 or newer.')}
if([string]$policy.repository-ne$Repository){Fail('Policy repository mismatch.')}
$prefixes=@($policy.branch_hygiene.preserved_prefixes|ForEach-Object{([string]$_).Trim()}|Where-Object{$_})
$tagPrefix=([string]$policy.branch_hygiene.provenance_tag_prefix).Trim()
if($tagPrefix-ne'provenance/'){Fail('Unexpected provenance tag prefix.')}

Write-Host '=== KEELARYN REPOSITORY GOVERNANCE ADMIN ===' -ForegroundColor Cyan
Write-Host ('Mode: '+$Mode)
Write-Host ('Repository: '+$Repository)
Write-Host ('Policy ref: '+$PolicyRef)
Write-Host ''

Ensure-ProvenanceRuleset $policy
if($Mode-eq'Apply'){Assert-ProvenanceRuleset $policy}

$branches=Get-Branches
$openHeads=Get-OpenPrHeads
$preserved=@($branches|Where-Object{
    $name=[string]$_.name
    @($prefixes|Where-Object{$name.StartsWith([string]$_,[System.StringComparison]::Ordinal)}).Count-gt0
})
Write-Host ('Preserved-prefix branches discovered: '+$preserved.Count)

$freezeRows=New-Object System.Collections.ArrayList
foreach($branch in $preserved){
    $name=[string]$branch.name
    $sha=[string]$branch.commit.sha
    if($sha-notmatch'^[0-9a-f]{40}$'){Fail('Invalid branch head SHA: '+$name)}
    $tag=$tagPrefix+$name
    $existing=Get-ExistingTagSha $tag
    if($null-ne$existing-and$existing-cne$sha){Fail('Existing provenance tag points to a different SHA: '+$tag+' expected='+$sha+' actual='+$existing)}
    [void]$freezeRows.Add([pscustomobject]@{branch=$name;sha=$sha;tag=$tag;tag_exists=($null-ne$existing);open_pr=($openHeads-ccontains$name)})
}

if($FreezePreservedBranches){
    foreach($row in $freezeRows){
        if(-not$row.tag_exists){
            Write-Host ('Freeze: '+$row.branch+' -> refs/tags/'+$row.tag+' @ '+$row.sha) -ForegroundColor Yellow
            if($Mode-eq'Apply'){
                $body=[ordered]@{ref='refs/tags/'+$row.tag;sha=$row.sha}|ConvertTo-Json -Compress
                $body|gh api --method POST ('repos/'+$Repository+'/git/refs') --input -|Out-Null
                if($LASTEXITCODE-ne0){Fail('Failed to create provenance tag: '+$row.tag)}
                $verify=Get-ExistingTagSha $row.tag
                if($verify-cne$row.sha){Fail('Provenance tag verification failed: '+$row.tag)}
            }
        }else{
            Write-Host ('Freeze already present: '+$row.tag+' @ '+$row.sha) -ForegroundColor DarkGray
        }
    }
}

if($CleanupFrozenBranches){
    if(-not$FreezePreservedBranches){Fail('CleanupFrozenBranches requires FreezePreservedBranches in the same transaction.')}
    if($Mode-eq'Apply'){Assert-ProvenanceRuleset $policy}
    foreach($row in $freezeRows){
        if($row.open_pr){
            Write-Host ('KEEP open-PR branch: '+$row.branch) -ForegroundColor Cyan
            continue
        }
        $tagSha=Get-ExistingTagSha $row.tag
        if($Mode-eq'Plan'-and$null-eq$tagSha){$tagSha=$row.sha}
        if($tagSha-cne$row.sha){Fail('Ref cleanup refused: exact provenance tag is missing for '+$row.branch)}
        Write-Host ('Delete frozen branch: '+$row.branch+' @ '+$row.sha+'; preserved by '+$row.tag) -ForegroundColor Yellow
        if($Mode-eq'Apply'){
            [void](Invoke-Gh @('api','--method','DELETE',('repos/'+$Repository+'/git/refs/heads/'+(Api-RefPath $row.branch))))
        }
    }
}

foreach($branchName in @($DeleteBranchNames|ForEach-Object{([string]$_).Trim()}|Where-Object{$_}|Select-Object -Unique)){
    if($branchName-eq'main'){Fail('Explicit branch deletion may never target main.')}
    if($openHeads-ccontains$branchName){Fail('Explicit branch deletion refused for open-PR branch: '+$branchName)}
    $match=@($branches|Where-Object{[string]$_.name-ceq$branchName})
    if($match.Count-eq0){Write-Host ('Explicit cleanup already absent: '+$branchName) -ForegroundColor DarkGray;continue}
    if($match.Count-ne1){Fail('Explicit cleanup branch lookup is ambiguous: '+$branchName)}
    $isPreserved=@($prefixes|Where-Object{$branchName.StartsWith([string]$_,[System.StringComparison]::Ordinal}).Count-gt0
    if($isPreserved){Fail('Explicit cleanup may not bypass preserved-branch provenance flow: '+$branchName)}
    Write-Host ('Explicit delete non-provenance branch: '+$branchName+' @ '+[string]$match[0].commit.sha) -ForegroundColor Yellow
    if($Mode-eq'Apply'){
        [void](Invoke-Gh @('api','--method','DELETE',('repos/'+$Repository+'/git/refs/heads/'+(Api-RefPath $branchName))))
    }
}

if($Mode-eq'Plan'){
    Write-Host ''
    Write-Host 'PLAN ONLY: no GitHub refs or rulesets were changed.' -ForegroundColor Cyan
}else{
    Write-Host ''
    Write-Host 'Repository governance admin transaction: PASS.' -ForegroundColor Green
}
