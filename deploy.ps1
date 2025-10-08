#!/usr/bin/env pwsh
<#
.SYNOPSIS
Deployment script for gnosis-crawl service
Based on gnosis-ocr deploy.ps1 pattern

.DESCRIPTION
Deploys gnosis-crawl to local Docker or Google Cloud Run
Supports local development and cloud production environments

.PARAMETER Target
Deployment target: 'local' or 'cloudrun'

.PARAMETER Tag
Docker image tag (default: 'latest')

.PARAMETER Rebuild
Force rebuild of Docker image

.EXAMPLE
./deploy.ps1 -Target local
Deploy to local Docker Compose

.EXAMPLE  
./deploy.ps1 -Target cloudrun -Tag v1.0.0
Deploy to Google Cloud Run with specific tag
#>

param(
    [ValidateSet("local", "cloudrun")]
    [string]$Target = "local",
    
    [string]$Tag = "latest",
    
    [switch]$Rebuild = $false
)

# Configuration
$ServiceName = "gnosis-crawl"
$ProjectId = $env:GOOGLE_CLOUD_PROJECT
$Region = "us-central1"
$ImageName = "gcr.io/${ProjectId}/${ServiceName}"

Write-Host "🚀 Deploying $ServiceName to $Target" -ForegroundColor Green

# Validate prerequisites
if ($Target -eq "cloudrun") {
    if (-not $ProjectId) {
        Write-Error "GOOGLE_CLOUD_PROJECT environment variable not set"
        exit 1
    }
    
    # Check if gcloud is installed and authenticated
    try {
        $null = gcloud auth list --filter="status:ACTIVE" --format="value(account)" 2>$null
        if ($LASTEXITCODE -ne 0) {
            Write-Error "Please authenticate with: gcloud auth login"
            exit 1
        }
    }
    catch {
        Write-Error "gcloud CLI not found. Please install Google Cloud SDK"
        exit 1
    }
}

# Build Docker image
Write-Host "📦 Building Docker image..." -ForegroundColor Yellow

if ($Target -eq "local") {
    $FullImageName = "${ServiceName}:${Tag}"
} else {
    $FullImageName = "${ImageName}:${Tag}"
}

$BuildArgs = @()
if ($Rebuild) {
    $BuildArgs += "--no-cache"
}

try {
    docker build $BuildArgs -t $FullImageName . 
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Docker build failed"
        exit 1
    }
    Write-Host "✅ Docker image built: $FullImageName" -ForegroundColor Green
}
catch {
    Write-Error "Failed to build Docker image: $_"
    exit 1
}

# Deploy based on target
switch ($Target) {
    "local" {
        Write-Host "🏠 Deploying to local environment..." -ForegroundColor Yellow
        
        # Stop existing containers
        docker-compose down 2>$null
        
        # Start services
        try {
            docker-compose up -d
            if ($LASTEXITCODE -ne 0) {
                Write-Error "Docker Compose failed"
                exit 1
            }
            
            Write-Host "✅ Service deployed locally" -ForegroundColor Green
            Write-Host "🌐 Service available at: http://localhost:8080" -ForegroundColor Cyan
            Write-Host "📚 API docs at: http://localhost:8080/docs" -ForegroundColor Cyan
            Write-Host "🔍 Health check: http://localhost:8080/health" -ForegroundColor Cyan
            
            # Show logs
            Write-Host "`n📋 Recent logs:" -ForegroundColor Yellow
            docker-compose logs --tail=10
        }
        catch {
            Write-Error "Failed to deploy locally: $_"
            exit 1
        }
    }
    
    "cloudrun" {
        Write-Host "☁️ Deploying to Google Cloud Run..." -ForegroundColor Yellow
        
        # Push image to registry
        Write-Host "📤 Pushing image to Container Registry..." -ForegroundColor Yellow
        try {
            docker push $FullImageName
            if ($LASTEXITCODE -ne 0) {
                Write-Error "Failed to push image to registry"
                exit 1
            }
        }
        catch {
            Write-Error "Failed to push Docker image: $_"
            exit 1
        }
        
        # Deploy to Cloud Run
        Write-Host "🚀 Deploying to Cloud Run..." -ForegroundColor Yellow
        
        # Use production environment config
        $EnvVars = @(
            "RUNNING_IN_CLOUD=true",
            "GCS_BUCKET_NAME=gnosis-crawl-storage-prod",
            "GNOSIS_AUTH_URL=https://gnosis-auth-$($ProjectId.Replace('_', '-')).a.run.app",
            "GOOGLE_CLOUD_PROJECT=$ProjectId"
        )
        
        $EnvArgs = $EnvVars | ForEach-Object { "--set-env-vars", $_ }
        
        try {
            gcloud run deploy $ServiceName `
                --image $FullImageName `
                --platform managed `
                --region $Region `
                --allow-unauthenticated `
                --port 8080 `
                --memory 1Gi `
                --cpu 1 `
                --max-instances 10 `
                --timeout 300 `
                --concurrency 100 `
                $EnvArgs
                
            if ($LASTEXITCODE -ne 0) {
                Write-Error "Cloud Run deployment failed"
                exit 1
            }
            
            # Get service URL
            $ServiceUrl = gcloud run services describe $ServiceName --region $Region --format "value(status.url)"
            
            Write-Host "✅ Service deployed to Cloud Run" -ForegroundColor Green
            Write-Host "🌐 Service URL: $ServiceUrl" -ForegroundColor Cyan
            Write-Host "📚 API docs: $ServiceUrl/docs" -ForegroundColor Cyan
            Write-Host "🔍 Health check: $ServiceUrl/health" -ForegroundColor Cyan
        }
        catch {
            Write-Error "Failed to deploy to Cloud Run: $_"
            exit 1
        }
    }
}

Write-Host "`n🎉 Deployment completed successfully!" -ForegroundColor Green