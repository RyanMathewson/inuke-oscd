param([int]$Rate = 48000)
Get-Process roomeqwizard -EA SilentlyContinue | ForEach-Object { $_.CloseMainWindow() | Out-Null }
Start-Sleep -Seconds 3
Get-Process roomeqwizard -EA SilentlyContinue | Stop-Process -Force -EA SilentlyContinue
Start-Sleep -Seconds 2
$log = "C:\Users\Ryan\REW\csjsound-lib.log"
if (Test-Path $log) { Remove-Item $log -Force }
$env:INSTALL4J_ADD_VM_PARAMS = "-DcsjsoundLibLogLevel=trace"
Start-Process -FilePath 'C:\Program Files\REW\roomeqwizard.exe' -ArgumentList '-api' -WorkingDirectory 'C:\Program Files\REW'

$hdr = @{ "Accept" = "application/json"; "Content-Type" = "application/json" }
$up = $false
for ($i = 0; $i -lt 40; $i++) {
  Start-Sleep -Seconds 2
  try { Invoke-RestMethod -Uri 'http://127.0.0.1:4735/version' -Headers $hdr -TimeoutSec 4 | Out-Null; $up = $true; break } catch {}
}
if (-not $up) { Write-Output "API never came up"; exit 1 }

Invoke-RestMethod -Uri 'http://127.0.0.1:4735/audio/samplerate' -Method Post -Headers $hdr -TimeoutSec 20 `
  -Body (@{ value = $Rate; unit = 'Hz' } | ConvertTo-Json) | Out-Null
Start-Sleep -Seconds 1
Write-Output "--- selecting EXCL input at $Rate Hz (first attempt since restart)"
Invoke-RestMethod -Uri 'http://127.0.0.1:4735/audio/java/input-device' -Method Post -Headers $hdr -TimeoutSec 25 `
  -Body (@{ device = 'EXCL: Microphone (Scarlett Solo USB)' } | ConvertTo-Json) | Out-Null
Start-Sleep -Seconds 3

$fmt = Invoke-RestMethod -Uri 'http://127.0.0.1:4735/audio/java/format' -Headers $hdr -TimeoutSec 10
Invoke-RestMethod -Uri 'http://127.0.0.1:4735/input-levels/command' -Method Post -Headers $hdr -TimeoutSec 20 `
  -Body (@{ command = 'Start' } | ConvertTo-Json) | Out-Null
Start-Sleep -Seconds 3
$mask = Invoke-RestMethod -Uri 'http://127.0.0.1:4735/audio/input-bit-mask' -Headers $hdr -TimeoutSec 10
$lv = Invoke-RestMethod -Uri 'http://127.0.0.1:4735/input-levels/last-levels' -Headers $hdr -TimeoutSec 10
Invoke-RestMethod -Uri 'http://127.0.0.1:4735/input-levels/command' -Method Post -Headers $hdr -TimeoutSec 20 `
  -Body (@{ command = 'Stop' } | ConvertTo-Json) | Out-Null

Write-Output "inputBits=$($fmt.inputBits)  activeBits=$($mask.activeBits)  rms=$($lv.rms -join ',')"
Write-Output "--- csjsound-lib.log"
if (Test-Path $log) { Get-Content $log | Where-Object { $_ -match 'ERROR|WARN|format|rate|open' } | Select-Object -Last 12 }
