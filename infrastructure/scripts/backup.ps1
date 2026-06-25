# Vantage — Local backup
# Usage: .\infrastructure\scripts\backup.ps1
# Dumps the local Docker PostgreSQL to a timestamped .sql file in infrastructure/backups/

$timestamp = (Get-Date -Format "yyyy-MM-dd_HHmm")
$backupDir = "$PSScriptRoot\..\backups"
$outFile   = "$backupDir\vantage_$timestamp.sql"

if (-not (Test-Path $backupDir)) { New-Item -ItemType Directory -Path $backupDir | Out-Null }

Write-Host "Backing up local Vantage DB → $outFile"
docker exec vantage_postgres pg_dump -U vantage vantage | Out-File -FilePath $outFile -Encoding utf8
Write-Host "Done. $(((Get-Item $outFile).Length / 1MB).ToString('0.0')) MB"
