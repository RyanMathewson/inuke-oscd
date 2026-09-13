# Pixel-coordinate UI automation helpers for the JUCE-based iNuke Remote Connect app.
# JUCE self-paints all controls, so Windows UI Automation can't see individual
# buttons/dropdowns by name -- this operates on raw window-relative pixel coords
# captured from screenshots instead.

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

if (-not ("Native.Win32c" -as [type])) {
Add-Type -MemberDefinition @'
[DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hWnd, out RECT lpRect);
[DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
[DllImport("user32.dll")] public static extern bool SetCursorPos(int X, int Y);
[DllImport("user32.dll")] public static extern void mouse_event(uint dwFlags, uint dx, uint dy, uint dwData, UIntPtr dwExtraInfo);
public struct RECT { public int Left; public int Top; public int Right; public int Bottom; }
'@ -Name Win32c -Namespace Native
}

$script:MOUSEEVENTF_LEFTDOWN = 0x0002
$script:MOUSEEVENTF_LEFTUP = 0x0004

function Get-InukeAppWindow {
    $proc = Get-Process | Where-Object { $_.MainWindowTitle -match 'iNuke Remote Connect \[Device' } | Select-Object -First 1
    if (-not $proc) { throw "iNuke Remote Connect app window not found" }
    $hwnd = $proc.MainWindowHandle
    $rect = New-Object Native.Win32c+RECT
    [Native.Win32c]::GetWindowRect($hwnd, [ref]$rect) | Out-Null
    [Native.Win32c]::SetForegroundWindow($hwnd) | Out-Null
    Start-Sleep -Milliseconds 150
    return $rect
}

function Invoke-InukeScreenshot {
    param([string]$OutPath)
    $rect = Get-InukeAppWindow
    $w = $rect.Right - $rect.Left
    $h = $rect.Bottom - $rect.Top
    $bmp = New-Object System.Drawing.Bitmap $w, $h
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.CopyFromScreen($rect.Left, $rect.Top, 0, 0, (New-Object System.Drawing.Size $w, $h))
    $bmp.Save($OutPath, [System.Drawing.Imaging.ImageFormat]::Png)
    $g.Dispose(); $bmp.Dispose()
    return $rect
}

function Invoke-InukeClick {
    param([int]$X, [int]$Y)
    $rect = Get-InukeAppWindow
    $screenX = $rect.Left + $X
    $screenY = $rect.Top + $Y
    [Native.Win32c]::SetCursorPos($screenX, $screenY) | Out-Null
    Start-Sleep -Milliseconds 80
    [Native.Win32c]::mouse_event($script:MOUSEEVENTF_LEFTDOWN, 0, 0, 0, [UIntPtr]::Zero)
    Start-Sleep -Milliseconds 50
    [Native.Win32c]::mouse_event($script:MOUSEEVENTF_LEFTUP, 0, 0, 0, [UIntPtr]::Zero)
}
