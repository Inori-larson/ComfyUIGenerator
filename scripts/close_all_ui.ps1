$ErrorActionPreference = 'SilentlyContinue'
$procs = Get-CimInstance Win32_Process -Filter "Name='pythonw.exe' OR Name='python.exe'" |
    Where-Object { $_.CommandLine -like '*comfyui_generator.ui*' }
if (-not $procs) {
    Write-Host 'No running UI found.'
    return
}
foreach ($p in $procs) {
    $proc = Get-Process -Id $p.ProcessId -ErrorAction SilentlyContinue
    $sent = $false
    if ($proc) {
        try { $sent = $proc.CloseMainWindow() } catch { $sent = $false }
    }
    Write-Host ("  close-request PID " + $p.ProcessId + " ok=" + $sent)
}
Start-Sleep -Seconds 4
$left = Get-CimInstance Win32_Process -Filter "Name='pythonw.exe' OR Name='python.exe'" |
    Where-Object { $_.CommandLine -like '*comfyui_generator.ui*' }
foreach ($p in $left) {
    Write-Host ("  killed PID " + $p.ProcessId)
    Stop-Process -Id $p.ProcessId -Force
}
