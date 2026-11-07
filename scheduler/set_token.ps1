# Saves the GitHub token for the timer job (Cloudflare secret GITHUB_TOKEN).
# Run from this folder:  powershell -ExecutionPolicy Bypass -File .\set_token.ps1
# Paste the token with Ctrl+V when asked (it shows as stars), then press Enter.
$env:CF_API_TOKEN = $null; $env:CLOUDFLARE_API_TOKEN = $null
Set-Location $PSScriptRoot
$s = Read-Host "Paste your GitHub token (Ctrl+V), then press Enter" -AsSecureString
$t = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($s)).Trim()
if ($t -notmatch '^(github_pat_|ghp_)[A-Za-z0-9_]{20,}$') {
    Write-Host "That doesn't look like a GitHub token (they start with github_pat_). Nothing was saved." -ForegroundColor Red
    Write-Host "You pasted $($t.Length) characters starting with '$($t.Substring(0, [Math]::Min(4, $t.Length)))'."
    exit 1
}
$t | npx.cmd wrangler secret put GITHUB_TOKEN
$t = $null
