@echo off
call "C:\Users\seeya\miniconda3\condabin\activate.bat" carddatabase
cd /d "%~dp0"
python menu.py
if errorlevel 1 pause
