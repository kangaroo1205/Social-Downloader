@echo off
cd /d "%~dp0\.."

echo === Installing PyInstaller ===
uv pip install pyinstaller
if errorlevel 1 (
    echo FAILED: could not install pyinstaller
    pause
    exit /b 1
)

echo.
echo === Building exe ===
uv run pyinstaller scripts\social_downloader.spec --clean
if errorlevel 1 (
    echo FAILED: pyinstaller build error
    pause
    exit /b 1
)

echo.
echo === Copying data folder ===
if exist data (
    xcopy /E /I /Y data dist\data
)

echo.
echo === Cleaning up build folder ===
if exist build (
    rmdir /s /q build
)

echo.
echo === Done! ===
echo Output: dist\SocialDownloader.exe
pause
