@echo off
REM Mini WMS RFID - inicia o servidor no PC (Windows)
cd /d %~dp0
if not exist .venv (
  python -m venv .venv
  .venv\Scripts\pip install -r requirements.txt
)
echo.
echo Tela do PC:  http://localhost:8000
echo No coletor, use o IP deste PC (veja com o comando ipconfig), ex.: http://192.168.0.10:8000
echo.
.venv\Scripts\uvicorn app.main:app --host 0.0.0.0 --port 8000
