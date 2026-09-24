@echo off
cd /d "%~dp0"

REM Resolve o caminho do ffmpeg via imageio-ffmpeg e adiciona ao PATH
for /f "delims=" %%i in ('..\.venv\Scripts\python.exe -c "import shutil; f=shutil.which('ffmpeg'); print(f if f else ''); " 2^>nul') do (
    if not "%%i"=="" (
        for %%d in ("%%i") do set "FFMPEG_DIR=%%~dpd"
        set "PATH=%FFMPEG_DIR%;%PATH%"
    )
)

REM Fallback: tenta via imageio-ffmpeg
if not defined FFMPEG_DIR (
    for /f "delims=" %%i in ('..\.venv\Scripts\python.exe -c "import imageio_ffmpeg; import os; print(os.path.dirname(imageio_ffmpeg.get_ffmpeg_exe()))" 2^>nul') do (
        set "PATH=%%i;%PATH%"
    )
)

"..\.venv\Scripts\python.exe" "main.py" >> "automacao.log" 2>&1
exit /b %ERRORLEVEL%
