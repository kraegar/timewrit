# run.ps1 - Convenience script to start the server using .env settings

# Load .env variables manually for use in this script
if (Test-Path ".env") {
    Get-Content .env | ForEach-Object {
        if ($_ -match "^([^#\s][^=]*)=(.*)$") {
            $name = $matches[1].Trim()
            $value = $matches[2].Trim()
            [Environment]::SetEnvironmentVariable($name, $value)
        }
    }
}

# Get address from ENV or default to localhost
$addr = [Environment]::GetEnvironmentVariable("RUNSERVER_ADDR")
if (-not $addr) { $addr = "127.0.0.1:8000" }

Write-Host "Starting Django server at $addr..." -ForegroundColor Cyan

Write-Host "Starting Django background task worker..." -ForegroundColor Cyan
Start-Process -NoNewWindow -FilePath ".\.venv\Scripts\python.exe" -ArgumentList "manage.py process_tasks"

# Run server
.\.venv\Scripts\python manage.py runserver $addr
