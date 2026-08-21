@echo off
REM Daily repricing of the newest tracking sheet.
REM Coverage fills in as books post -- roughly one day ahead for MLB/WNBA.
cd /d "%~dp0"
for /f "tokens=2 delims==" %%I in ('wmic os get localdatetime /value 2^>nul') do set DT=%%I
set STAMP=%DT:~0,8%
python price_sheet.py >> "out\price_sheet_log.txt" 2>&1
echo --- run finished %STAMP% --- >> "out\price_sheet_log.txt"
