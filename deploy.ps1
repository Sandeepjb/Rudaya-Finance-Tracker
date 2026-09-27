[CmdletBinding()]
param(
    [string]$Branch = "main",
    [string]$Remote = "origin",
    [string]$HealthUrl = "https://finance.rudaya.local:9443/",
    [switch]$SkipTests
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Step([string]$Message) { Write-Host "`n==> $Message" -ForegroundColor Cyan }
function Fail([string]$Message) { throw $Message }

$Repo = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Repo

$previousCommit = $null
$targetCommit = $null
$deploymentStarted = $false

try {
    Step "Pre-flight checks"
    foreach ($cmd in @("git", "docker", "python")) {
        if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) { Fail "Required command not found: $cmd" }
    }
    docker info *> $null
    if ($LASTEXITCODE -ne 0) { Fail "Docker engine is not running." }
    docker compose version *> $null
    if ($LASTEXITCODE -ne 0) { Fail "Docker Compose is unavailable." }
    if (-not (Test-Path ".git")) { Fail "deploy.ps1 must be stored in the repository root." }
    if (-not (Test-Path "docker-compose.yml")) { Fail "docker-compose.yml not found." }
    if (-not (Test-Path "backend\server.py")) { Fail "backend\server.py not found." }

    $currentBranch = (git branch --show-current).Trim()
    if ($LASTEXITCODE -ne 0 -or $currentBranch -ne $Branch) {
        Fail "Current branch is '$currentBranch'. Expected '$Branch'."
    }

    $status = @(git status --porcelain)
    if ($LASTEXITCODE -ne 0) { Fail "Unable to read Git working-tree status." }
    $blocking = @($status | Where-Object {
        $_ -notmatch '^\?\? (deploy\.ps1|backend/Dockerfile|frontend/Dockerfile|frontend/nginx\.conf|caddy/|docker-compose\.yml)$'
    })
    if ($blocking.Count -gt 0) {
        Write-Host ($blocking -join "`n") -ForegroundColor Yellow
        Fail "Working tree contains application changes. Commit/stash them before deployment."
    }

    Step "Fetch $Remote/$Branch"
    git fetch $Remote $Branch --prune
    if ($LASTEXITCODE -ne 0) { Fail "git fetch failed." }

    $previousCommit = (git rev-parse HEAD).Trim()
    $targetCommit = (git rev-parse "$Remote/$Branch").Trim()
    git merge-base --is-ancestor $previousCommit $targetCommit
    if ($LASTEXITCODE -ne 0) { Fail "Local branch has diverged from $Remote/$Branch. Deployment aborted; no merge will be attempted." }

    Step "Validate incoming commit in an isolated Git worktree"
    $tempRoot = Join-Path $env:TEMP ("rudaya-deploy-" + [guid]::NewGuid().ToString("N"))
    git worktree add --detach $tempRoot $targetCommit
    if ($LASTEXITCODE -ne 0) { Fail "Unable to create validation worktree." }
    try {
        python -m tabnanny (Join-Path $tempRoot "backend")
        if ($LASTEXITCODE -ne 0) { Fail "Python indentation validation failed." }
        python -m compileall -q (Join-Path $tempRoot "backend")
        if ($LASTEXITCODE -ne 0) { Fail "Python compilation validation failed." }
    }
    finally {
        git worktree remove --force $tempRoot 2>$null
    }

    Step "Fast-forward local source"
    git merge --ff-only $targetCommit
    if ($LASTEXITCODE -ne 0) { Fail "Fast-forward failed." }

    Step "Validate deployed source"
    python -m tabnanny .\backend
    if ($LASTEXITCODE -ne 0) { Fail "tabnanny failed." }
    python -m compileall -q .\backend
    if ($LASTEXITCODE -ne 0) { Fail "Python compileall failed." }
    docker compose config --quiet
    if ($LASTEXITCODE -ne 0) { Fail "Docker Compose validation failed." }

    Step "Pre-deployment Python validation"

python -m tabnanny .\backend
if ($LASTEXITCODE -ne 0) {
    Fail "Python indentation validation failed."
}

python -m compileall -q .\backend
if ($LASTEXITCODE -ne 0) {
    Fail "Python compilation validation failed."
}

Step "Validate Docker Compose"

docker compose config --quiet
if ($LASTEXITCODE -ne 0) {
    Fail "Docker Compose validation failed."
}

    Step "Build images before replacing running containers"
    docker compose build backend frontend
    if ($LASTEXITCODE -ne 0) { Fail "Docker image build failed." }

    Step "Deploy application containers"
    $deploymentStarted = $true
    docker compose up -d --no-deps --force-recreate backend frontend
    if ($LASTEXITCODE -ne 0) { Fail "Container deployment failed." }

    Start-Sleep -Seconds 8

    Step "Container health checks"
    $bad = @()
    foreach ($name in @("rudaya-mongodb", "rudaya-backend", "rudaya-frontend", "rudaya-caddy")) {
        $state = (docker inspect -f '{{.State.Status}}' $name 2>$null).Trim()
        if ($state -ne "running") { $bad += "$name=$state" }
    }
    if ($bad.Count -gt 0) { Fail ("Containers not healthy: " + ($bad -join ", ")) }

   Step "HTTP health check"

& curl.exe `
    --fail `
    --silent `
    --show-error `
    --max-time 20 `
    --ssl-no-revoke `
    -k `
    $HealthUrl *> $null

if ($LASTEXITCODE -ne 0) *
    Fail "HTTPS health check fail*d: $HealthUrl"
}
    if ($LASTEXITCODE -ne 0) { Fail "HTTPS health check failed: $HealthUrl" }

    Step "Database preservation check"
    docker exec rudaya-mongodb mongosh --quiet --eval 'db.adminCommand({ping:1})' | Out-Host
    if ($LASTEXITCODE -ne 0) { Fail "MongoDB ping failed." }

    $deployed = (git rev-parse --short HEAD).Trim()
    Write-Host "`nDEPLOYMENT SUCCESSFUL: $deployed" -ForegroundColor Green
}
catch {
    Write-Host "`nDEPLOYMENT FAILED: $($_.Exception.Message)" -ForegroundColor Red

    if ($deploymentStarted -and $previousCommit) {
        Write-Host "Attempting image/source rollback to previous commit $previousCommit ..." -ForegroundColor Yellow
        try {
            git reset --hard $previousCommit | Out-Host
            python -m compileall -q .\backend
            docker compose build backend frontend | Out-Host
            docker compose up -d --no-deps --force-recreate backend frontend | Out-Host
            Write-Host "Rollback attempt completed. Verify application manually." -ForegroundColor Yellow
        }
        catch {
            Write-Host "Automatic rollback failed. Existing MongoDB volume was not intentionally modified." -ForegroundColor Red
        }
    }
    exit 1
}
