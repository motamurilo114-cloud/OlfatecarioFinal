"""Ponto de entrada do executável standalone (gerado com PyInstaller).

Roda a mesma ferramenta do app.py, sem precisar de Python instalado na máquina de
quem for usar: é um único .exe, de dois cliques. Tem exatamente as mesmas funções
da versão com Python (desde que o Laya saiu, em 28/09/2026, não há mais diferença).

Gerar o .exe (a partir desta pasta):
    pip install -r requirements.txt pyinstaller
    pyinstaller --onefile --name Olfatecario --add-data "static;static" iniciar_exe.py
O arquivo final fica em dist/Olfatecario.exe.
"""
from __future__ import annotations

import os
import sys
import threading
import time
import webbrowser
from pathlib import Path


def _pasta_dados() -> Path:
    if os.environ.get("OLFA_DATA_DIR"):  # definido pelo Electron
        return Path(os.environ["OLFA_DATA_DIR"])
    if getattr(sys, "frozen", False):
        if sys.platform == "darwin":
            return Path.home() / "Library" / "Application Support" / "Olfatecario"
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


# precisa vir antes de importar app/pipeline: eles leem estas variáveis na primeira vez
os.environ.setdefault("OLFA_CACHE_DIR", str(_pasta_dados() / "cache"))

import uvicorn  # noqa: E402
import app as olfa_app  # noqa: E402

HOST, PORTA = "127.0.0.1", 8765


def _abrir_navegador() -> None:
    time.sleep(1.3)
    try:
        webbrowser.open(f"http://{HOST}:{PORTA}")
    except Exception:
        pass


def _ja_esta_rodando() -> bool:
    import socket
    with socket.socket() as sk:
        sk.settimeout(0.5)
        return sk.connect_ex((HOST, PORTA)) == 0


if __name__ == "__main__":
    SEM_NAVEGADOR = bool(os.environ.get("OLFA_SEM_NAVEGADOR"))  # o Electron tem janela própria
    if _ja_esta_rodando():  # segundo clique: só volta para o navegador
        if not SEM_NAVEGADOR:
            webbrowser.open(f"http://{HOST}:{PORTA}")
        sys.exit(0)
    print("Olfatecário: subindo o servidor de teste...")
    print(f"Se o navegador não abrir sozinho, acesse http://{HOST}:{PORTA}")
    print("Para fechar, feche esta janela.")
    if not SEM_NAVEGADOR:
        threading.Thread(target=_abrir_navegador, daemon=True).start()
    uvicorn.run(olfa_app.app, host=HOST, port=PORTA, log_level="warning")
