"""Cliente HTTP mínimo para a API do Gemini (nível gratuito do Google), usado por
pipeline.py e proposta.py. Sem SDK novo: só httpx, do jeito que o resto do servidor
já usa para as outras APIs.

O que o teste com uma chave real mostrou (28/09/2026):
- os modelos 2.x (gemini-2.5-flash etc.) respondem 404 "no longer available to new users":
  chaves novas só enxergam a família 3.x;
- nos 3.x, gerar texto é grátis, mas a busca no Google (google_search) NÃO está no nível
  gratuito: o pedido com busca volta 429 RESOURCE_EXHAUSTED mesmo sem nenhum uso no dia;
- de vez em quando um modelo responde 503 (sobrecarregado), e o seguinte responde normal.

Por isso a ferramenta não usa a busca no Google, e a lista abaixo tenta vários modelos em
ordem, passando para o próximo em 404 (não existe para a chave), 429 (sem cota) e 5xx
(sobrecarga), e lembra qual funcionou.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Optional

import httpx

log = logging.getLogger("olfatecario.gemini")

# o primeiro é o escolhido no .env (se houver); os demais são reserva, testados em ordem.
# Os "latest" são apelidos que a Google mantém apontando para o modelo atual da família.
_CANDIDATOS = [m for m in [
    os.environ.get("OLFA_GEMINI_MODEL"),
    "gemini-flash-latest",
    "gemini-3.8-flash",
    "gemini-3.7-flash",
    "gemini-3.5-flash",
    "gemini-flash-lite-latest",
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
    "gemini-2.5-flash",       # só chaves antigas ainda têm acesso
] if m]
GEMINI_MODELOS = list(dict.fromkeys(_CANDIDATOS))  # remove duplicados, mantém a ordem

_modelo_ok: Optional[str] = None  # lembrado entre chamadas, dura enquanto o processo roda

_PULAR = {404, 429, 500, 502, 503, 504}


def credenciais() -> bool:
    return bool(os.environ.get("GEMINI_API_KEY"))


def gerar(corpo: dict[str, Any], timeout: httpx.Timeout,
          max_modelos: Optional[int] = None) -> tuple[Optional[httpx.Response], Optional[str]]:
    """Chama generateContent, tentando os modelos da lista em ordem. Passa para o próximo em
    404, 429 e 5xx. Levanta httpx.ConnectError / httpx.TimeoutException se nem a conexão for
    possível. Devolve (última resposta, modelo que respondeu) — modelo None se nenhum serviu;
    aí a última resposta diz o porquê (404: nenhum modelo existe; 429: sem cota; 5xx: sobrecarga).
    max_modelos limita quantos modelos tentar."""
    global _modelo_ok
    chave = os.environ.get("GEMINI_API_KEY", "")
    ordem = ([_modelo_ok] if _modelo_ok else []) + [m for m in GEMINI_MODELOS if m != _modelo_ok]
    if max_modelos:
        ordem = ordem[:max_modelos]
    resposta: Optional[httpx.Response] = None
    vistos: set[int] = set()
    demoras = 0
    # prazo curto por modelo: em horário de pico o Google leva 40 s para dizer que está
    # sobrecarregado; melhor passar logo para o próximo modelo da lista
    por_modelo = httpx.Timeout(min(timeout.read or 60.0, 25.0), connect=timeout.connect or 10.0)
    with httpx.Client(timeout=por_modelo) as http:
        for modelo in ordem:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent"
            try:
                r = http.post(url, headers={"x-goog-api-key": chave, "Content-Type": "application/json"}, json=corpo)
            except httpx.TimeoutException:
                log.warning("Gemini: %s não respondeu a tempo, tentando o próximo", modelo)
                demoras += 1
                if demoras >= 2:
                    raise
                continue
            if r.status_code in _PULAR:
                log.warning("Gemini: %s respondeu %s, tentando o próximo", modelo, r.status_code)
                vistos.add(r.status_code)
                resposta = r
                continue
            _modelo_ok = modelo
            return r, modelo
    if resposta is None and demoras:
        raise httpx.ReadTimeout("nenhum modelo respondeu a tempo")
    # nenhum serviu: devolve a resposta que melhor explica o motivo
    if resposta is not None and resposta.status_code == 404 and (vistos - {404}):
        motivo = 429 if 429 in vistos else max(vistos - {404})
        resposta = httpx.Response(motivo, text=f"nenhum modelo disponível (códigos vistos: {sorted(vistos)})")
    return resposta, None


def texto(resposta: httpx.Response) -> tuple[str, dict[str, Any]]:
    """Extrai (texto, candidato) de uma resposta 200 do generateContent."""
    candidatos = (resposta.json() or {}).get("candidates") or []
    if not candidatos:
        return "", {}
    cand = candidatos[0]
    partes = (cand.get("content") or {}).get("parts") or []
    return "".join(p.get("text", "") for p in partes).strip(), cand
