<#
One-time setup, run in an ELEVATED PowerShell with the Tang Nano 4K plugged in.

Registers a scheduled task that does exactly one thing: pnputil /restart-device on the
board's USB device (BL702). The task runs elevated without a UAC prompt, so
tools/usb_recover.py (or you) can start it from a normal shell:

    schtasks /run /tn nanopynq-tangnano4k-usb-restart

It re-enumerates the device; it does not power-cycle the board.
Remove it with:  .\tools\register_usb_restart_task.ps1 -Unregister
#>
param(
    [string]$InstanceId = 'USB\VID_0403&PID_6010\FACTORYAIOT_PRO',
    [switch]$Unregister
)
$ErrorActionPreference = 'Stop'
$name = 'nanopynq-tangnano4k-usb-restart'

if ($Unregister) {
    Unregister-ScheduledTask -TaskName $name -Confirm:$false
    "unregistered $name"
    return
}

$admin = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
if (-not $admin.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Run this in an elevated PowerShell (Run as administrator).'
}
$dev = Get-PnpDevice -InstanceId $InstanceId   # stops here if the board is not plugged in
"device: $($dev.FriendlyName) [$($dev.InstanceId)]"

$action = New-ScheduledTaskAction -Execute "$env:SystemRoot\System32\pnputil.exe" `
    -Argument "/restart-device `"$InstanceId`""
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" `
    -LogonType Interactive -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 1)
Register-ScheduledTask -TaskName $name -Action $action -Principal $principal -Settings $settings `
    -Description 'nanopynq: restart the Tang Nano 4K USB device (BL702) instead of replugging it' `
    -Force | Out-Null
Get-ScheduledTask -TaskName $name | Select-Object TaskName, State
