$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = 'C:\Python314\python.exe'
$psi.Arguments = 'scripts/livekit_agent.py start'
$psi.WorkingDirectory = 'C:\Users\ANAMIKA\DEV\Temp\college_agent-master\college_agent-master'
$psi.UseShellExecute = $false
$psi.RedirectStandardOutput = $true
$psi.RedirectStandardError = $true
$psi.CreateNoWindow = $true

$p = [System.Diagnostics.Process]::Start($psi)
Write-Host "PID=$($p.Id)"

Start-Sleep -Seconds 5

if ($p.HasExited) {
    Write-Host "HasExited=$($p.HasExited) ExitCode=$($p.ExitCode)"
    Write-Host "Stdout: $($p.StandardOutput.ReadToEnd())"
    Write-Host "Stderr: $($p.StandardError.ReadToEnd())"
} else {
    Write-Host "Process still running after 5s"
    $p.StandardOutput.ReadToEnd() | Out-File 'agent_stdout.log'
    $p.StandardError.ReadToEnd() | Out-File 'agent_stderr.log'
}
