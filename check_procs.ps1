Get-Process -Name python -ErrorAction SilentlyContinue | Select-Object Id, @{N='MemMB';E={[math]::Round($_.WorkingSet64/1MB)}} | Format-Table -AutoSize
