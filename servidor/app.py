"""Servidor da ferramenta Olfatecário.

Serve a ferramenta (static/index.html), a API de qualificação de leads e a que escreve
os textos da proposta com o Gemini (nível gratuito do Google).
Rodar:  .venv/Scripts/python -m uvicorn app:app --host 127.0.0.1 --port 8765
"""
from __future__ import annotations

import base64
import json
import logging
import os
import secrets
import sys
from pathlib import Path

import httpx
import re

from fastapi import FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel

import pipeline
import proposta


def _pasta_dados() -> Path:
    """Onde ficam .env, cache e log: sempre ao lado do .exe (ou desta pasta, rodando
    como script Python), para persistir entre execuções. Nunca a pasta temporária
    onde o PyInstaller extrai o programa — essa é apagada a cada início."""
    if os.environ.get("OLFA_DATA_DIR"):  # definido pelo Electron
        pasta = Path(os.environ["OLFA_DATA_DIR"])
        pasta.mkdir(parents=True, exist_ok=True)
        return pasta
    if getattr(sys, "frozen", False):
        if sys.platform == "darwin":
            # dentro do .app não dá para gravar (e o Mac roda o app de um lugar temporário)
            pasta = Path.home() / "Library" / "Application Support" / "Olfatecario"
            pasta.mkdir(parents=True, exist_ok=True)
            return pasta
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _pasta_recursos() -> Path:
    """Onde ficam os arquivos empacotados junto com o programa (a pasta static/).
    No .exe é a pasta temporária que o PyInstaller cria (sys._MEIPASS); rodando
    como script Python é esta mesma pasta."""
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))


BASE = _pasta_dados()
RECURSOS = _pasta_recursos()

ENV_PATH = BASE / ".env"


def _carregar_env() -> None:
    """Lê o arquivo .env ao lado do app (formato CHAVE=valor), sem sobrescrever o ambiente."""
    if not ENV_PATH.exists():
        return
    for linha in ENV_PATH.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        chave, valor = linha.split("=", 1)
        os.environ.setdefault(chave.strip(), valor.strip().strip('"').strip("'"))


def _gravar_no_env(chave_var: str, valor: str) -> None:
    """Escreve uma variável no .env, sem apagar o resto do arquivo. Cria o arquivo se não existir."""
    linhas = ENV_PATH.read_text(encoding="utf-8").splitlines() if ENV_PATH.exists() else []
    achou = False
    for i, linha in enumerate(linhas):
        if linha.strip().startswith(chave_var + "="):
            linhas[i] = f"{chave_var}={valor}"
            achou = True
            break
    if not achou:
        linhas.append(f"{chave_var}={valor}")
    ENV_PATH.write_text("\n".join(linhas) + "\n", encoding="utf-8")


_carregar_env()
logging.basicConfig(level=os.environ.get("OLFA_LOG", "INFO"),
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")

USUARIO = os.environ.get("OLFA_USUARIO", "")
SENHA = os.environ.get("OLFA_SENHA", "")


app = FastAPI(title="Olfatecário", docs_url=None, redoc_url=None)


@app.middleware("http")
async def exigir_login(request: Request, call_next):
    """Se OLFA_USUARIO e OLFA_SENHA estiverem definidos, pede login (HTTP Basic) em tudo."""
    if USUARIO and SENHA:
        auth = request.headers.get("authorization", "")
        ok = False
        if auth.lower().startswith("basic "):
            try:
                u, _, s = base64.b64decode(auth[6:]).decode("utf-8").partition(":")
                ok = secrets.compare_digest(u, USUARIO) and secrets.compare_digest(s, SENHA)
            except Exception:
                ok = False
        if not ok:
            return Response(status_code=401, headers={"WWW-Authenticate": 'Basic realm="Olfatecario"'})
    resp = await call_next(request)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["Cache-Control"] = "no-store"
    return resp


class PedidoLead(BaseModel):
    cnpj: str
    forcar: bool = False


@app.get("/api/saude")
def saude():
    return {"ok": True, "gemini": pipeline.credenciais_gemini()}


@app.post("/api/leads/qualificar")
async def qualificar(pedido: PedidoLead):
    try:
        return await run_in_threadpool(pipeline.qualificar, pedido.cnpj, pedido.forcar)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.post("/api/proposta/textos")
async def textos_proposta(dados: dict):
    """Textos da proposta personalizados pelo Gemini (botão "Escrever com IA")."""
    try:
        return await run_in_threadpool(proposta.escrever_textos, dados)
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))


class PedidoChave(BaseModel):
    chave: str


@app.get("/api/config/chave-gemini")
def status_chave_gemini():
    """Diz só se há chave configurada — nunca devolve a chave em si."""
    return {"configurada": pipeline.credenciais_gemini()}


@app.post("/api/config/chave-gemini")
async def salvar_chave_gemini(pedido: PedidoChave):
    """Confere a chave com a própria Google antes de salvar (lista os modelos disponíveis,
    uma chamada sem custo), e já ativa na hora, sem precisar reiniciar o servidor."""
    chave = pedido.chave.strip()
    if not chave:
        raise HTTPException(status_code=422, detail="Cole a chave antes de salvar.")
    if len(chave) < 30:
        raise HTTPException(status_code=422, detail="Essa chave parece curta demais para ser do Gemini.")
    # só letras, números, "-" e "_": uma quebra de linha colada junto derrubava o pedido e
    # poderia virar outra linha no .env
    if not re.fullmatch(r"[A-Za-z0-9_\-]+", chave):
        raise HTTPException(status_code=422, detail="A chave tem espaços ou caracteres estranhos. Copie de novo, só a chave.")

    def _testar() -> httpx.Response:
        return httpx.get("https://generativelanguage.googleapis.com/v1beta/models",
                          headers={"x-goog-api-key": chave}, timeout=httpx.Timeout(15.0, connect=8.0))

    try:
        r = await run_in_threadpool(_testar)
    except httpx.ConnectError:
        raise HTTPException(status_code=502, detail="Sem conexão para confirmar a chave agora. Tente de novo.")
    except httpx.TimeoutException:
        raise HTTPException(status_code=502, detail="A Google demorou demais para responder. Tente de novo.")
    except httpx.HTTPError:
        raise HTTPException(status_code=502, detail="Não consegui falar com a Google agora. Tente de novo.")

    if r.status_code in (401, 403) or (r.status_code == 400 and "API_KEY_INVALID" in r.text):
        raise HTTPException(status_code=422, detail="O Google recusou essa chave. Confira se copiou certo.")
    if r.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"Não consegui confirmar a chave agora (erro {r.status_code}).")

    os.environ["GEMINI_API_KEY"] = chave
    await run_in_threadpool(_gravar_no_env, "GEMINI_API_KEY", chave)
    return {"ok": True}


@app.delete("/api/config/chave-gemini")
async def remover_chave_gemini():
    os.environ.pop("GEMINI_API_KEY", None)
    await run_in_threadpool(_gravar_no_env, "GEMINI_API_KEY", "")
    return {"ok": True}


DADOS_INICIAIS = BASE / "dados-iniciais.json"
if not DADOS_INICIAIS.exists() and (RECURSOS / "dados-iniciais.json").exists():
    DADOS_INICIAIS = RECURSOS / "dados-iniciais.json"  # embutido no .app do Mac


@app.get("/api/dados-iniciais")
def dados_iniciais():
    """Base da Manu (obra, compras, salas, custos do prédio) que não vai dentro do .exe:
    fica num arquivo à parte, ao lado dele, só na máquina dela. A ferramenta importa uma
    vez, na primeira abertura; depois o arquivo pode ser apagado."""
    if not DADOS_INICIAIS.exists():
        raise HTTPException(status_code=404, detail="Sem arquivo de dados iniciais nesta pasta.")
    try:
        return JSONResponse(json.loads(DADOS_INICIAIS.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError):
        raise HTTPException(status_code=422, detail="O arquivo dados-iniciais.json está corrompido.")


@app.exception_handler(StarletteHTTPException)
async def erro_http(_: Request, exc: StarletteHTTPException):
    detalhe = exc.detail if isinstance(exc.detail, str) else "Pedido não atendido."
    detalhe = {"Not Found": "Endereço não encontrado.", "Method Not Allowed": "Método não permitido."}.get(detalhe, detalhe)
    return JSONResponse(status_code=exc.status_code, content={"erro": detalhe}, headers=getattr(exc, "headers", None))


@app.exception_handler(RequestValidationError)
async def erro_validacao(_: Request, exc: RequestValidationError):
    """Corpo fora do formato: devolve {"erro": ...} como os outros erros, que é o que a tela lê."""
    campos = [str(e.get("loc", ["", ""])[-1]) for e in exc.errors()]
    if any(e.get("type") == "json_invalid" for e in exc.errors()):
        msg = "O pedido chegou fora do formato (JSON inválido)."
    elif campos and all(c and not c.isdigit() and c != "body" for c in campos):
        msg = "Confira o campo " + ", ".join(dict.fromkeys(campos)) + "."
    else:
        msg = "O pedido chegou fora do formato esperado."
    return JSONResponse(status_code=422, content={"erro": msg})


@app.get("/")
def pagina():
    return FileResponse(RECURSOS / "static" / "index.html", media_type="text/html; charset=utf-8")
