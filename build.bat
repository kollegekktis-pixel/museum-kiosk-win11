@echo off
cd /d "%~dp0"
chcp 65001 >nul
echo Установка нужных библиотек (нужен интернет, один раз)...
python -m pip install PyQt6 pyinstaller
if errorlevel 1 goto err
echo Сборка exe...
python -m PyInstaller --noconsole --onefile museum.py
if errorlevel 1 goto err
copy /Y dist\museum.exe museum.exe >nul
echo.
"%WINDIR%\Microsoft.NET\Framework64\v4.0.30319\csc.exe" /nologo /codepage:65001 /target:winexe /reference:System.Windows.Forms.dll /out:"Обновить архив.exe" refresh_media.cs
if errorlevel 1 goto err
start /wait "" "Обновить архив.exe" --quiet
if errorlevel 1 goto err
echo Готово: museum.exe лежит в этой папке (рядом с папкой data).
pause
exit /b
:err
echo Ошибка. Проверьте, что установлен Python (python.org) с галочкой Add to PATH.
pause
