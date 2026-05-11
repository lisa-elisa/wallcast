# Run as Administrator
netsh advfirewall firewall add rule name="BallCatcher-HTTP-8000" dir=in action=allow protocol=TCP localport=8000
netsh advfirewall firewall add rule name="BallCatcher-PhoneCam-8766" dir=in action=allow protocol=TCP localport=8766
Write-Host "Done. Firewall rules added for ports 8000 and 8766." -ForegroundColor Green
