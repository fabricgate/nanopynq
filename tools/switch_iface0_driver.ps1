<#
Switches the driver of Interface 0 (JTAG) of the boards' USB debugger (0403:6010) between
WinUSB (what Zadig installs) and FTDI's FTDIBUS (Windows' default), without Zadig.

    .\tools\switch_iface0_driver.ps1            # show the current driver (no admin needed)
    .\tools\switch_iface0_driver.ps1 winusb     # same as Zadig on Interface 0
    .\tools\switch_iface0_driver.ps1 ftdi       # back to the default driver

Switching needs admin: from a normal shell the script runs itself again elevated (one UAC
prompt) and shows that run's output here.

Both drivers must already be in this PC's driver store. The WinUSB one is there after
Zadig has been run once on Interface 0 (Zadig signs it with its own certificate, so the
first time still needs Zadig); FTDI's comes with FTDI's CDM driver. Interface 1 (the
UART) is not touched. Every plugged-in board with this USB ID is switched.
#>
param(
    [ValidateSet('status', 'winusb', 'ftdi')][string]$To = 'status'
)
$ErrorActionPreference = 'Stop'
$HardwareId = 'USB\VID_0403&PID_6010&MI_00'

# The newest oem*.inf in $InfDir that lists Interface 0 and installs service $Service.
# Newest by file time: if several FTDI versions are installed, it takes the last installed one.
function Find-Iface0Inf([string]$Service, [string]$InfDir = "$env:windir\INF") {
    Get-ChildItem -LiteralPath $InfDir -Filter 'oem*.inf' |
        Where-Object {
            $t = Get-Content -LiteralPath $_.FullName -Raw
            $t -match [regex]::Escape('VID_0403&PID_6010&MI_00') -and
            $t -match "(?im)^\s*AddService\s*=\s*$Service\s*,"
        } |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
}

# A type added to a session cannot be added again, so a second run in the same window skips it.
function Add-DriverApi {
    if ('Win32.Drv' -as [type]) { return }
    Add-Type -Namespace Win32 -Name Drv -MemberDefinition @'
[DllImport("setupapi.dll", CharSet = CharSet.Unicode, SetLastError = true)]
public static extern bool SetupGetInfDriverStoreLocationW(string FileName, IntPtr AlternatePlatformInfo,
    string LocaleName, System.Text.StringBuilder ReturnBuffer, int ReturnBufferSize, out int RequiredSize);
[DllImport("newdev.dll", CharSet = CharSet.Unicode, SetLastError = true)]
public static extern bool UpdateDriverForPlugAndPlayDevicesW(IntPtr hwndParent, string HardwareId,
    string FullInfPath, uint InstallFlags, out bool RebootRequired);
'@
}

# Runs "$Script $To" in a new elevated PowerShell (UAC prompt) and shows its output here.
# The child's output goes through a temp file: an elevated window is separate from this one.
# -NoRunAs skips the elevation (tests).
function Invoke-Elevated([string]$Script, [string]$To, [switch]$NoRunAs) {
    $log = [IO.Path]::GetTempFileName()
    # PowerShell's own escaping: it also doubles the typographic quotes (U+2018..U+201B) it accepts.
    $quote = { param($s) "'" + [Management.Automation.Language.CodeGeneration]::EscapeSingleQuotedStringContent($s) + "'" }
    $cmd = "try { & $(& $quote $Script) $To *>&1 | Out-File -Encoding utf8 $(& $quote $log) } " +
           "catch { `$_ | Out-File -Append -Encoding utf8 $(& $quote $log); exit 1 }"
    $encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($cmd))
    $run = @{
        FilePath     = (Get-Process -Id $PID).Path
        ArgumentList = "-NoProfile -ExecutionPolicy Bypass -EncodedCommand $encoded"
        Wait         = $true
        PassThru     = $true
    }
    if (-not $NoRunAs) { $run.Verb = 'RunAs' }
    try {
        $p = Start-Process @run
        Get-Content -LiteralPath $log
        if ($p.ExitCode) { throw "The elevated run failed (exit $($p.ExitCode)); its output is above." }
    } finally {
        Remove-Item -LiteralPath $log -ErrorAction SilentlyContinue
    }
}

function Get-Iface0 { @(Get-PnpDevice -PresentOnly -InstanceId "$HardwareId*" -ErrorAction SilentlyContinue) }

function Show-Iface0 {
    $devs = Get-Iface0
    if (-not $devs) { 'no board (USB 0403:6010) is plugged in'; return }
    foreach ($d in $devs) {
        $prop = { param($k) (Get-PnpDeviceProperty -InstanceId $d.InstanceId -KeyName $k).Data }
        '{0}: {1} ({2}), {3}' -f (& $prop DEVPKEY_Device_Parent), (& $prop DEVPKEY_Device_Service),
            (& $prop DEVPKEY_Device_DriverInfPath), $d.Status
    }
}

if ($MyInvocation.InvocationName -eq '.') { return }   # dot-sourced (tests): functions only

if ($To -eq 'status') { Show-Iface0; return }

# These checks need no admin, so they run before the UAC prompt.
if (-not (Get-Iface0)) { throw 'Plug in the board first (no USB 0403:6010 Interface 0 found).' }
$service = @{ winusb = 'WinUSB'; ftdi = 'FTDIBUS' }[$To]
$inf = Find-Iface0Inf $service
if (-not $inf) {
    $hint = if ($To -eq 'winusb') { 'run Zadig once on Interface 0' } else { "install FTDI's CDM driver" }
    throw "No driver for Interface 0 with service $service in the driver store; $hint."
}

$admin = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
if (-not $admin.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Invoke-Elevated $PSCommandPath $To
    return
}

Add-DriverApi
function Get-Win32Error { [ComponentModel.Win32Exception]::new([Runtime.InteropServices.Marshal]::GetLastWin32Error()).Message }

# Install from the driver store copy: %windir%\INF\oemNN.inf alone lacks the package's other files.
$store = [Text.StringBuilder]::new(1024)
$needed = 0
if (-not [Win32.Drv]::SetupGetInfDriverStoreLocationW($inf.FullName, [IntPtr]::Zero, [NullString]::Value,
        $store, $store.Capacity, [ref]$needed)) {
    throw "Driver store location of $($inf.Name): $(Get-Win32Error)"
}
"installing $($inf.Name) ($store) on $HardwareId"

# INSTALLFLAG_FORCE (1): both drivers rank the same, so without it Windows keeps the one it prefers.
$reboot = $false
if (-not [Win32.Drv]::UpdateDriverForPlugAndPlayDevicesW([IntPtr]::Zero, $HardwareId, $store.ToString(), 1,
        [ref]$reboot)) {
    throw "UpdateDriverForPlugAndPlayDevices: $(Get-Win32Error)"
}
if ($reboot) { 'Windows asks for a reboot to finish.' }
Show-Iface0
