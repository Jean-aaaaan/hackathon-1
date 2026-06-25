# Vantage — Migrate local DB to Azure PostgreSQL
#
# Usage:
#   .\infrastructure\scripts\migrate-to-azure.ps1 `
#     -AzureHost "vantage-db.postgres.database.azure.com" `
#     -AzurePassword "your-password"
#
# Optional: pass -BackupFile to restore an existing dump instead of taking a fresh one.
#   .\migrate-to-azure.ps1 -AzureHost "..." -AzurePassword "..." -BackupFile ".\backups\vantage_2026-05-30_1400.sql"

param(
    [Parameter(Mandatory)][string]$AzureHost,
    [string]$AzureUser     = "vantage",
    [string]$AzureDb       = "vantage",
    [Parameter(Mandatory)][string]$AzurePassword,
    [string]$BackupFile    = ""
)

$ErrorActionPreference = "Stop"

# ── Step 1: Dump local DB (or use existing backup) ────────────────────────────
if ($BackupFile -eq "") {
    $timestamp  = (Get-Date -Format "yyyy-MM-dd_HHmm")
    $backupDir  = "$PSScriptRoot\..\backups"
    if (-not (Test-Path $backupDir)) { New-Item -ItemType Directory -Path $backupDir | Out-Null }
    $BackupFile = "$backupDir\vantage_$timestamp.sql"

    Write-Host "`n[1/3] Dumping local DB → $BackupFile"
    docker exec vantage_postgres pg_dump -U vantage vantage | Out-File -FilePath $BackupFile -Encoding utf8
    $sizeMB = ((Get-Item $BackupFile).Length / 1MB).ToString("0.0")
    Write-Host "      Dump complete: $sizeMB MB"
} else {
    Write-Host "`n[1/3] Using existing backup: $BackupFile"
    if (-not (Test-Path $BackupFile)) { throw "Backup file not found: $BackupFile" }
}

# ── Step 2: Verify Azure connectivity ────────────────────────────────────────
Write-Host "`n[2/3] Verifying connection to $AzureHost ..."
$env:PGPASSWORD = $AzurePassword
$ping = psql "postgresql://${AzureUser}:${AzurePassword}@${AzureHost}/${AzureDb}?sslmode=require" -c "SELECT 1" 2>&1
if ($LASTEXITCODE -ne 0) {
    throw "Cannot connect to Azure PostgreSQL. Check host, credentials, and firewall rules.`n$ping"
}
Write-Host "      Connected OK"

# ── Step 3: Restore ───────────────────────────────────────────────────────────
Write-Host "`n[3/3] Restoring to Azure PostgreSQL ..."
Get-Content $BackupFile | psql "postgresql://${AzureUser}:${AzurePassword}@${AzureHost}/${AzureDb}?sslmode=require"
if ($LASTEXITCODE -ne 0) { throw "Restore failed. Check psql output above." }

Write-Host "`nMigration complete. All data is now on Azure PostgreSQL."
Write-Host "Next: update DATABASE_URL in Azure Container App environment variables."
Write-Host "  postgresql://${AzureUser}:<password>@${AzureHost}/${AzureDb}?sslmode=require"
