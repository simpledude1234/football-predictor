@echo off
title Football Predictor
cd /d "%~dp0"
echo.
echo  Football Predictor
echo  Getting the latest matches and making predictions. This takes about 30 seconds...
echo.
py -3.13 make_page.py > "%TEMP%\football_predictor_log.txt" 2>&1
if errorlevel 1 (
  echo  Something went wrong while updating. Your last good predictions will open instead.
  echo  Details: %TEMP%\football_predictor_log.txt
  pause
) else (
  echo  Done. Opening your predictions in the browser...
)
start "" "%~dp0predictions.html"
timeout /t 3 > nul

