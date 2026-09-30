"""Textos da proposta comercial personalizados pelo Gemini (nível gratuito do Google).

A ferramenta manda o que a Manu escolheu para o workshop deste cliente (tema, público,
focos, notas, frasco, números) e os textos do modelo. O Gemini devolve os textos das
seções Objetivo, Imersão e sentidos, destaques e O que será entregue, já no formato
que a ferramenta coloca no PDF.
"""
from __future__ import annotations

import json
import logging
from typing import Any

import httpx

import gemini

log = logging.getLogger("olfatecario.proposta")

_SISTEMA = """Você escreve propostas comerciais de workshops corporativos de perfumaria para a \
Olfatecário, ateliê de perfumaria autoral em São Paulo. Em cada workshop, os participantes criam \
o próprio perfume com a condução de uma perfumista profissional.

Personalize os textos da proposta para o cliente descrito, em português do Brasil.
- Tom: sofisticado, caloroso e direto, sem jargão de marketing e sem superlativos vazios.
- Use só as informações recebidas. Não invente prazos, preços, números, programas da empresa nem nomes.
- Mantenha o sentido de cada texto do modelo e acrescente o que é deste cliente.
- Evite artigo antes do nome da empresa; "o time X" funciona bem.
- Objetivo e Imersão: um parágrafo cada, de 60 a 110 palavras.
- Destaques: exatamente 3, título curto e uma ou duas frases.
- Entregas: exatamente 5, na mesma ordem e com os mesmos temas do modelo, duas a quatro frases cada."""

_BLOCO = {"type": "object", "properties": {"t": {"type": "string"}, "x": {"type": "string"}},
          "required": ["t", "x"]}
_SCHEMA = {
    "type": "object",
    "properties": {
        "objetivo": {"type": "string"},
        "imersao": {"type": "string"},
        "destaques": {"type": "array", "items": _BLOCO},
        "entregas": {"type": "array", "items": _BLOCO},
    },
    "required": ["objetivo", "imersao", "destaques", "entregas"],
}

# só estes campos seguem para o Gemini, e com tamanho limitado
_CAMPOS_TEXTO = ("marca", "cliente", "tema", "publico", "notas", "frasco", "local", "data", "duracao")


def _limpar(dados: dict[str, Any]) -> dict[str, Any]:
    d: dict[str, Any] = {k: str(dados.get(k) or "")[:300] for k in _CAMPOS_TEXTO}
    d["focos"] = [str(f)[:60] for f in (dados.get("focos") or [])][:10]
    for k in ("participantes", "essencias", "concentracao"):
        try:
            d[k] = float(dados.get(k) or 0)
        except (TypeError, ValueError):
            d[k] = 0
    modelo = dados.get("modelo") or {}
    d["modelo"] = {
        "imersao": str(modelo.get("imersao") or "")[:1500],
        "destaques": [{"t": str(b.get("t", ""))[:120], "x": str(b.get("x", ""))[:600]}
                      for b in (modelo.get("destaques") or [])[:3] if isinstance(b, dict)],
        "entregas": [{"t": str(b.get("t", ""))[:120], "x": str(b.get("x", ""))[:900]}
                     for b in (modelo.get("entregas") or [])[:5] if isinstance(b, dict)],
    }
    return d


def _limpar_saida(v: Any) -> Any:
    """Tira tabulações e caracteres de controle que o Gemini às vezes põe no lugar de acentos."""
    from pipeline import _limpar_texto
    if isinstance(v, str):
        return _limpar_texto(v)
    if isinstance(v, list):
        return [_limpar_saida(x) for x in v]
    if isinstance(v, dict):
        return {k: _limpar_saida(x) for k, x in v.items()}
    return v


def escrever_textos(dados: dict[str, Any]) -> dict[str, Any]:
    """Devolve {objetivo, imersao, destaques[3], entregas[5]}. Levanta RuntimeError com a
    mensagem para a Manu quando não dá para escrever."""
    if not gemini.credenciais():
        raise RuntimeError("A IA precisa da chave do Gemini — cole em Parâmetros ou no .env do servidor.")

    pedido = "Dados do workshop e textos do modelo (JSON):\n" + json.dumps(_limpar(dados), ensure_ascii=False, indent=1)
    corpo = {
        "contents": [{"role": "user", "parts": [{"text": pedido}]}],
        "systemInstruction": {"parts": [{"text": _SISTEMA}]},
        "generationConfig": {
            "temperature": 0.6,
            "maxOutputTokens": 8000,
            "responseMimeType": "application/json",
            "responseSchema": _SCHEMA,
        },
    }
    try:
        r, modelo = gemini.gerar(corpo, httpx.Timeout(60.0, connect=10.0))
    except httpx.ConnectError:
        raise RuntimeError("Sem conexão com a IA. Confira a internet do servidor.")
    except httpx.TimeoutException:
        raise RuntimeError("A IA demorou demais para responder. Tente de novo.")

    if modelo is None or r is None or r.status_code >= 400:
        if r is not None:
            log.warning("Gemini (proposta) falhou: %s %s", r.status_code, r.text[:300])
        if r is not None and (r.status_code in (401, 403) or "API_KEY_INVALID" in r.text):
            raise RuntimeError("A chave do Gemini não foi aceita. Confira em Parâmetros.")
        if r is not None and r.status_code == 429:
            raise RuntimeError("Limite gratuito do Gemini atingido. Volta de madrugada (por volta das 5h); até lá, use o botão de montar textos.")
        if r is not None and r.status_code >= 500:
            raise RuntimeError("O Gemini está sobrecarregado agora. Tente de novo em alguns minutos.")
        if r is not None and r.status_code == 404:
            raise RuntimeError("Nenhum modelo do Gemini está disponível para esta chave agora.")
        raise RuntimeError(f"A IA está indisponível agora (erro {getattr(r, 'status_code', '?')}).")

    resp = r.json()
    candidatos = resp.get("candidates") or []
    if not candidatos:
        raise RuntimeError("A IA não escreveu estes textos. Use o botão de montar textos.")
    cand = candidatos[0]
    if cand.get("finishReason") in ("SAFETY", "RECITATION", "PROHIBITED_CONTENT"):
        raise RuntimeError("A IA não escreveu estes textos. Use o botão de montar textos.")
    if cand.get("finishReason") == "MAX_TOKENS":
        raise RuntimeError("A resposta da IA veio incompleta. Tente de novo.")

    partes = (cand.get("content") or {}).get("parts") or []
    texto = "".join(p.get("text", "") for p in partes).strip()
    try:
        return _limpar_saida(json.loads(texto))
    except json.JSONDecodeError:
        raise RuntimeError("A IA respondeu fora do formato. Tente de novo.")
