# Saves your football-data.org key (for referee names) in two places:
# GitHub's encrypted Secrets (for the automatic updates) and a private file on
# this PC (.football_data_key, never uploaded) for testing.
# Run:  powershell -ExecutionPolicy Bypass -File .\tools\set_football_data_key.ps1
# Paste the key with a right-click when asked (it shows as stars), then press Enter.
Set-Location (Split-Path $PSScriptRoot -Parent)
$s = Read-Host "Paste your football-data.org key (right-click), then press Enter" -AsSecureString
$t = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($s)).Trim()
if ($t -notmatch '^[A-Za-z0-9]{20,64}$') {
    Write-Host "That doesn't look like a football-data.org key (letters and numbers, about 32 long). Nothing was saved." -ForegroundColor Red
    Write-Host "You pasted $($t.Length) characters."
    exit 1
}
[IO.File]::WriteAllText((Join-Path (Get-Location) ".football_data_key"), $t)
$t | gh secret set FOOTBALL_DATA_KEY
$t = $null
Write-Host "Saved. You can close this window." -ForegroundColor Green
