$ErrorActionPreference = 'SilentlyContinue'
$procs = Get-CimInstance Win32_Process -Filter "Name='pythonw.exe' OR Name='python.exe'" |
    Where-Object { $_.CommandLine -like '*comfyui_generator.ui*' }
if (-not $procs) {
    Write-Host 'No running UI found.'
}
foreach ($p in $procs) {
    Write-Host ("  killed PID " + $p.ProcessId)
    Stop-Process -Id $p.ProcessId -Force
}
