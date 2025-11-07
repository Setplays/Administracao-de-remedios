@echo off
REM Pega o diretório onde este arquivo .bat está
cd /d "%~dp0"

REM Inicia o script Python usando 'pythonw.exe' (que não abre console)
REM e passa o argumento '--minimized' para o script.
start "" pythonw.exe gerenciador_remedios.py --minimized