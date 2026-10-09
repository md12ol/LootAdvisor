# Dev: bring a window to the front (BG3 minimised first if -HideGame) and take a full-resolution screenshot.
#   winshot.ps1 -TitleLike "LootAdvisor Sets" -Process msedge -Out C:\...\x.png [-HideGame] [-ShowGame]
# -Key <virtual key> presses a key in that window (116 = F5 reload); -Max maximises it.
# -ShowGame restores and focuses BG3 instead (no screenshot unless -Out is given).
param([string]$TitleLike = "", [string]$Process = "", [string]$Out = "", [switch]$HideGame, [switch]$ShowGame, [int]$WaitMs = 1200, [int]$Key = 0, [switch]$Max)
Add-Type @"
using System; using System.Runtime.InteropServices; using System.Text;
public class WS {
  public delegate bool EnumProc(IntPtr h, IntPtr l);
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr l);
  [DllImport("user32.dll")] public static extern int GetWindowText(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int c);
  [DllImport("user32.dll")] public static extern bool BringWindowToTop(IntPtr h);
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
  [DllImport("user32.dll")] public static extern void keybd_event(byte vk, byte scan, uint flags, UIntPtr extra);
}
"@
function Find([string]$like, [string]$proc) {
  $script:hit = [IntPtr]::Zero
  [WS]::EnumWindows({ param($h, $l)
    if (-not [WS]::IsWindowVisible($h)) { return $true }
    $sb = New-Object Text.StringBuilder 512; [WS]::GetWindowText($h, $sb, 512) | Out-Null
    $t = $sb.ToString()
    if ($t -like "*$like*") {
      if ($proc) { $p = 0; [WS]::GetWindowThreadProcessId($h, [ref]$p) | Out-Null; $n = (Get-Process -Id $p -ErrorAction SilentlyContinue).ProcessName; if ($n -ne $proc) { return $true } }
      $script:hit = $h; return $false }
    return $true }, [IntPtr]::Zero) | Out-Null
  return $script:hit
}
function Front([IntPtr]$h) {
  [WS]::keybd_event(0x12, 0, 0, [UIntPtr]::Zero); [WS]::keybd_event(0x12, 0, 2, [UIntPtr]::Zero)   # Alt tap: allows SetForegroundWindow
  [WS]::ShowWindow($h, 9) | Out-Null; [WS]::BringWindowToTop($h) | Out-Null; [WS]::SetForegroundWindow($h) | Out-Null
}
$game = Find "Baldur's Gate 3 (" "bg3_dx11"
if ($ShowGame) { if ($game -ne [IntPtr]::Zero) { Front $game } }
else {
  if ($HideGame -and $game -ne [IntPtr]::Zero) { [WS]::ShowWindow($game, 6) | Out-Null; Start-Sleep -Milliseconds 400 }
  $w = Find $TitleLike $Process
  if ($w -eq [IntPtr]::Zero) { "window not found: $TitleLike $Process"; exit 1 }
  Front $w
  if ($Max) { [WS]::ShowWindow($w, 3) | Out-Null }
  if ($Key) { Start-Sleep -Milliseconds 300; [WS]::keybd_event([byte]$Key, 0, 0, [UIntPtr]::Zero); [WS]::keybd_event([byte]$Key, 0, 2, [UIntPtr]::Zero) }
}
Start-Sleep -Milliseconds $WaitMs
if ($Out) { & "$PSScriptRoot\..\..\..\tools\bg3drive\crop.ps1" -Out $Out -MaxW 4000 | Out-Null; $Out }
