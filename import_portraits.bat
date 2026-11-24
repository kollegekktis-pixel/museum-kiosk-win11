@echo off
cd /d "%~dp0"
if exist museum.exe (
    museum.exe --import-portraits
) else (
    python museum.py --import-portraits
)
