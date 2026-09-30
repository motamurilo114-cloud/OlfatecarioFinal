@echo off
rem Sobe a ferramenta da Olfatecario em http://127.0.0.1:8765
cd /d "%~dp0"
if not exist .venv (
  echo Criando o ambiente pela primeira vez. Isso leva alguns minutos...
  py -3.12 -m venv .venv || goto erro
  .venv\Scripts\python.exe -m pip install --upgrade pip
  .venv\Scripts\python.exe -m pip install -r requirements.txt || goto erro
)
start "" http://127.0.0.1:8765
.venv\Scripts\python.exe -m uvicorn app:app --host 127.0.0.1 --port 8765
goto fim
:erro
echo Algo deu errado na instalacao. Confira se o Python 3.12 esta instalado.
pause
:fim
