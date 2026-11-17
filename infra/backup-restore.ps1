param(
  [Parameter(Mandatory = $true)][string]$OutputPath
)
$ErrorActionPreference = "Stop"
$database = "lifeline_restore_check"
$fullOutput = [System.IO.Path]::GetFullPath($OutputPath)
$directory = [System.IO.Path]::GetDirectoryName($fullOutput)
New-Item -ItemType Directory -Force -Path $directory | Out-Null
$containerDump = "/tmp/lifeline-backup-$([guid]::NewGuid().ToString('N')).dump"
$created = $false
try {
  docker compose -f infra/docker-compose.yml exec -T db pg_dump -U lifeline -Fc lifeline -f $containerDump
  if ($LASTEXITCODE -ne 0) { throw "pg_dump failed" }
  docker compose -f infra/docker-compose.yml cp "db:$containerDump" $fullOutput
  if ($LASTEXITCODE -ne 0) { throw "docker cp backup failed" }
  docker compose -f infra/docker-compose.yml exec -T db psql -U lifeline -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='$database'" | Out-Null
  if ($LASTEXITCODE -ne 0) { throw "could not inspect restore database" }
  docker compose -f infra/docker-compose.yml exec -T db createdb -U lifeline $database
  if ($LASTEXITCODE -ne 0) { throw "restore database already exists or could not be created" }
  $created = $true
  docker compose -f infra/docker-compose.yml exec -T db pg_restore -U lifeline --no-owner -d $database $containerDump
  if ($LASTEXITCODE -ne 0) { throw "pg_restore failed" }
  $count = docker compose -f infra/docker-compose.yml exec -T db psql -U lifeline -d $database -tAc "SELECT count(*) FROM events"
  if ($LASTEXITCODE -ne 0) { throw "restore verification query failed" }
  Write-Output "Restore verification passed; events=$($count.Trim()); backup=$fullOutput"
}
finally {
  if ($created) { docker compose -f infra/docker-compose.yml exec -T db dropdb -U lifeline $database }
  docker compose -f infra/docker-compose.yml exec -T db rm -f $containerDump | Out-Null
}
