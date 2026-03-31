$ErrorActionPreference = "Stop"

$venvPath = ".\.venv"

if (-not (Test-Path $venvPath)) {
  python -m venv $venvPath
}

& "$venvPath\Scripts\python.exe" -m pip install --upgrade pip
& "$venvPath\Scripts\python.exe" -m pip install -r .\requirements.txt

if (-not $args -or $args.Count -eq 0) {
  & "$venvPath\Scripts\python.exe" .\cli.py --thread-id demo1 --message "Help me study calculus"
  exit $LASTEXITCODE
}

& "$venvPath\Scripts\python.exe" .\cli.py @args
exit $LASTEXITCODE
