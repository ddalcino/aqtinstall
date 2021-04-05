cinst --no-progress -y python --version=3.6.8 2>&1 | %{ "$_" }
Write-Output "Ignore return value from cinst"
Exit 0