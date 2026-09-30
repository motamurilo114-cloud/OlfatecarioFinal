"""Qualificação automática de leads da Olfatecário.

Fluxo para um CNPJ:
  1. BrasilAPI (Receita Federal)   -> dados cadastrais reais da empresa
  2. API pública do GPTW Brasil    -> se tem o selo Great Place to Work válido
  3. Gemini (nível gratuito, uma chamada) -> descrição da empresa + critérios sem fonte oficial

A Manu só informa o CNPJ. Quem decide é o pipeline; ela vê o resultado e o porquê.

Até 28/09/2026 os critérios vinham de um modelo local (Laya, via PyTorch). Foi retirado: pesava ~4 GB,
exigia RAM e disco à parte, e travava o critério de NR-1 sempre que rodava sem ele (ex.: no
executável leve). Como o Gemini já lê e entende a empresa, ele mesmo responde os
critérios que não têm fonte oficial — sem custo, sem dependência pesada, e do mesmo jeito em
qualquer versão do servidor.
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import httpx

import gemini

log = logging.getLogger("olfatecario.pipeline")

BASE = Path(__file__).resolve().parent
CACHE_FILE = Path(os.environ.get("OLFA_CACHE_DIR") or BASE / "cache") / "leads.json"
CACHE_DIAS = int(os.environ.get("OLFA_CACHE_DIAS", "30"))
HTTP_TIMEOUT = httpx.Timeout(20.0, connect=10.0)
UA = {"User-Agent": "Olfatecario-ERP/1.0 (qualificacao de leads)"}


# --------------------------------------------------------------------------- CNPJ

def so_digitos(cnpj: str) -> str:
    return re.sub(r"\D", "", cnpj or "")


def cnpj_valido(cnpj: str) -> bool:
    c = so_digitos(cnpj)
    if len(c) != 14 or c == c[0] * 14:
        return False

    def dv(base: str, pesos: list[int]) -> str:
        s = sum(int(d) * p for d, p in zip(base, pesos))
        r = s % 11
        return "0" if r < 2 else str(11 - r)

    p1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    p2 = [6] + p1
    return c[12] == dv(c[:12], p1) and c[13] == dv(c[:12] + c[12], p2)


_MINUSCULAS = {"de", "da", "do", "das", "dos", "e", "em", "para"}


def nome_legivel(nome: str) -> str:
    """A Receita devolve tudo em maiúsculas. Para usar em mensagens: 'SICOOB CREDIJEQUITINHONHA'
    vira 'Sicoob Credijequitinhonha'. Palavras de até 3 letras (siglas) ficam como estão."""
    if not nome or not nome.isupper():
        return nome or ""
    saida = []
    for i, parte in enumerate(nome.split()):
        low = parte.lower()
        if i and low in _MINUSCULAS:
            saida.append(low)
        elif len(parte) <= 3 and parte.isalpha():
            saida.append(parte)
        else:
            saida.append("-".join(x[:1].upper() + x[1:].lower() for x in parte.split("-")))
    return " ".join(saida)


def formatar_cnpj(c: str) -> str:
    c = so_digitos(c)
    return f"{c[:2]}.{c[2:5]}.{c[5:8]}/{c[8:12]}-{c[12:]}" if len(c) == 14 else c


# ----------------------------------------------------------------------- 1. Receita

def buscar_receita(cnpj: str) -> dict[str, Any]:
    """Dados cadastrais. BrasilAPI primeiro; minhareceita.org como reserva."""
    fontes = [
        ("BrasilAPI", f"https://brasilapi.com.br/api/cnpj/v1/{cnpj}"),
        ("Minha Receita", f"https://minhareceita.org/{cnpj}"),
    ]
    ultimo_erro = None
    with httpx.Client(timeout=HTTP_TIMEOUT, headers=UA, follow_redirects=True) as http:
        for nome, url in fontes:
            try:
                r = http.get(url)
                if r.status_code == 404:
                    raise LookupError("CNPJ não encontrado na Receita Federal.")
                r.raise_for_status()
                d = r.json()
                d["_fonte"] = nome
                return d
            except LookupError:
                raise
            except Exception as e:  # rede fora, limite de uso: tenta a próxima fonte
                ultimo_erro = e
                log.warning("falha em %s: %s", nome, e)
    raise RuntimeError(f"Não consegui consultar a Receita Federal agora ({ultimo_erro}).")


def resumo_receita(d: dict[str, Any]) -> dict[str, Any]:
    secundarios = [c.get("descricao") for c in (d.get("cnaes_secundarios") or []) if c.get("descricao")]
    return {
        "razao_social": d.get("razao_social") or "",
        "nome_fantasia": d.get("nome_fantasia") or "",
        "situacao": d.get("descricao_situacao_cadastral") or "",
        "porte_receita": d.get("porte") or d.get("descricao_porte") or "",
        "atividade_principal": d.get("cnae_fiscal_descricao") or "",
        "atividades_secundarias": secundarios[:6],
        "municipio": d.get("municipio") or "",
        "uf": d.get("uf") or "",
        "abertura": d.get("data_inicio_atividade") or "",
        "capital_social": d.get("capital_social"),
        "natureza_juridica": d.get("natureza_juridica") or "",
        "fonte": d.get("_fonte"),
    }


# -------------------------------------------------------------------------- 2. GPTW

GPTW_API = "https://certificadas.gptw.com.br/api/certified/all/filter"


def buscar_gptw(cnpj: str) -> dict[str, Any]:
    """Consulta a lista oficial de empresas certificadas pela raiz do CNPJ (8 dígitos),
    que é a mesma para matriz e filiais."""
    raiz = cnpj[:8]
    agora_ms = time.time() * 1000
    try:
        with httpx.Client(timeout=HTTP_TIMEOUT, headers=UA) as http:
            r = http.get(GPTW_API, params={"cnpj": raiz})
            r.raise_for_status()
            itens = (r.json() or {}).get("data") or []
    except Exception as e:
        log.warning("falha na API do GPTW: %s", e)
        return {"consultado": False, "certificada": None, "erro": str(e)}

    itens = [i for i in itens if so_digitos(i.get("cnpj", "")).startswith(raiz)]
    if not itens:
        return {"consultado": True, "certificada": False}

    def validade(i):
        try:
            return float(i.get("expirationDate") or 0)
        except (TypeError, ValueError):
            return 0.0

    melhor = max(itens, key=validade)
    exp = validade(melhor)
    return {
        "consultado": True,
        "certificada": exp > agora_ms,
        "validade": datetime.fromtimestamp(exp / 1000, tz=timezone.utc).date().isoformat() if exp else None,
        "funcionarios": melhor.get("TotalEmployees"),
        "setor": melhor.get("sector") or "",
        "nome": melhor.get("fantasyName") or melhor.get("razaoSocial") or "",
        "descricao": (melhor.get("description") or "")[:1500],
        "site": melhor.get("website") or "",
        "linkedin": melhor.get("linkedin") or "",
        "nota_trust_index": melhor.get("TI"),
    }


# ------------------------------------------------------------------------ 3. Gemini (descrição + critérios)

_PROMPT_ANALISE = """Você analisa empresas brasileiras para a Olfatecário, um ateliê de perfumaria autoral em \
São Paulo que vende workshops corporativos de criação de perfume para grupos de 5 a 15 pessoas, \
normalmente lideranças, contratados pelo RH ou pela área de pessoas.

Com os dados cadastrais e do GPTW que você recebe, e o que você já sabe sobre a empresa se ela for \
conhecida, responda em português do Brasil:

1. "descricao": uma descrição objetiva para orientar a prospecção, entre 100 e 170 palavras, em \
parágrafos curtos, sem títulos e sem links. Cubra, nesta ordem: o que a empresa faz, setor e onde \
atua; tamanho aproximado (número de funcionários), dizendo de onde veio o número; se tem área de RH \
ou Pessoas estruturada; ações conhecidas de bem-estar, saúde mental, gestão de riscos psicossociais \
(NR-1), integração de times ou eventos corporativos; se há lideranças ou times que formariam um \
grupo de 5 a 15 pessoas para um workshop.
2. "nr1": há sinais de ações de bem-estar, saúde mental ou gestão de riscos psicossociais (NR-1)?
3. "grupo_5_15": a empresa teria lideranças ou um time que formaria um grupo de 5 a 15 pessoas?
4. "porte": aproximadamente quantos funcionários — "micro" (menos de 20), "pequena" (20 a 99), \
"media" (100 a 499), "grande" (500 ou mais) ou "desconhecido".

Em nr1 e grupo_5_15 dê "estado" ("sim", "nao" ou "indeterminado"), "probabilidade" (0 a 1, a \
chance de a resposta ser sim) e "motivo" (uma frase dizendo o que embasou a resposta).

Regras: escreva só o que recebeu ou sabe com segurança. Você não tem acesso à web: quando não souber \
algo, diga "não encontrado" na descrição e, nos critérios, use "estado": "indeterminado" (ou \
"desconhecido" no porte). Falta de informação não é "nao": use "nao" só quando houver um sinal \
concreto contra. Não invente números nem programas. Escreva com a acentuação normal do português \
(á, é, ç, ã...), sem sequências de escape nem tabulações no meio das palavras."""


def _limpar_texto(t: str) -> str:
    """O Gemini às vezes troca uma letra acentuada por tabulação ("Cosm\\teticos"). Tira os
    caracteres de controle do meio do texto, mantendo as quebras de parágrafo."""
    t = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", t.replace("\t", ""))
    return re.sub(r"\n{3,}", "\n\n", t).strip()

_CRITERIO = {"type": "object", "properties": {
    "estado": {"type": "string", "enum": ["sim", "nao", "indeterminado"]},
    "probabilidade": {"type": "number"}, "motivo": {"type": "string"},
}, "required": ["estado", "probabilidade", "motivo"]}
_SCHEMA_ANALISE = {
    "type": "object",
    "properties": {
        "descricao": {"type": "string"},
        "nr1": _CRITERIO,
        "grupo_5_15": _CRITERIO,
        "porte": {"type": "object", "properties": {
            "classe": {"type": "string", "enum": ["micro", "pequena", "media", "grande", "desconhecido"]},
            "motivo": {"type": "string"},
        }, "required": ["classe", "motivo"]},
    },
    "required": ["descricao", "nr1", "grupo_5_15", "porte"],
}


def credenciais_gemini() -> bool:
    return gemini.credenciais()


def _motivo_falha(r: Optional[httpx.Response]) -> str:
    """Traduz a última resposta de uma chamada que não deu certo em texto para a tela."""
    if r is None:
        return "Gemini não respondeu"
    if r.status_code in (401, 403) or (r.status_code == 400 and "API_KEY_INVALID" in r.text):
        return "chave do Gemini inválida"
    if r.status_code == 429:
        return "limite gratuito do Gemini atingido; volta de madrugada, por volta das 5h"
    if r.status_code == 404:
        return "nenhum modelo do Gemini disponível para esta chave"
    if r.status_code >= 500:
        return "Gemini sobrecarregado agora; tente de novo em alguns minutos"
    return f"Gemini indisponível: {r.status_code}"


def analisar_com_gemini(cnpj: str, receita: dict, gptw: dict) -> tuple[dict[str, Any], Optional[dict[str, Any]]]:
    """Uma chamada só: descrição da empresa + critérios sem fonte oficial (nr1, grupo_5_15, porte).
    Sem busca na web: nos modelos que chaves novas enxergam, a busca no Google fica fora do nível
    gratuito (volta 429 sem nenhum uso), então não vale gastar chamada tentando.
    Devolve (descricao, respostas); respostas é None quando não há chave ou a chamada falha."""
    base = _descricao_so_dados(receita, gptw)
    if not gemini.credenciais():
        return {"texto": base, "fonte": "dados oficiais (Gemini sem chave configurada)"}, None

    dados = {"cnpj": formatar_cnpj(cnpj), "receita_federal": receita, "gptw_lista_oficial": gptw}
    corpo = {
        "contents": [{"role": "user", "parts": [{"text": "Analise esta empresa:\n\n"
                                                 + json.dumps(dados, ensure_ascii=False, indent=1)}]}],
        "systemInstruction": {"parts": [{"text": _PROMPT_ANALISE}]},
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 8000,
                              "responseMimeType": "application/json", "responseSchema": _SCHEMA_ANALISE},
    }
    try:
        r, modelo = gemini.gerar(corpo, httpx.Timeout(60.0, connect=10.0))
    except httpx.ConnectError:
        return {"texto": base, "fonte": "dados oficiais (sem conexão com o Gemini)"}, None
    except httpx.TimeoutException:
        return {"texto": base, "fonte": "dados oficiais (o Gemini demorou demais para responder)"}, None

    if modelo is None or r is None or r.status_code >= 400:
        if r is not None:
            log.warning("Gemini (análise) falhou: %s %s", r.status_code, r.text[:300])
        return {"texto": base, "fonte": f"dados oficiais ({_motivo_falha(r)})"}, None

    texto, cand = gemini.texto(r)
    if cand.get("finishReason") in ("SAFETY", "RECITATION", "PROHIBITED_CONTENT"):
        return {"texto": base, "fonte": "dados oficiais (Gemini recusou o pedido)"}, None
    try:
        res = json.loads(texto)
    except (json.JSONDecodeError, TypeError):
        log.warning("Gemini (análise): resposta fora do formato (%s)", cand.get("finishReason"))
        return {"texto": base, "fonte": "dados oficiais (Gemini respondeu fora do formato)"}, None

    desc = _limpar_texto(str(res.get("descricao") or ""))
    descricao = ({"texto": desc, "fonte": f"Gemini ({modelo}, gratuito)"} if desc
                 else {"texto": base, "fonte": "dados oficiais (Gemini não devolveu a descrição)"})

    respostas: dict[str, Any] = {}
    for chave in ("nr1", "grupo_5_15"):
        c = res.get(chave)
        if isinstance(c, dict) and "probabilidade" in c:
            try:
                prob = max(0.0, min(1.0, float(c["probabilidade"])))
            except (TypeError, ValueError):
                continue
            estado = c.get("estado")
            if estado not in ("sim", "nao", "indeterminado"):
                estado = "sim" if prob >= LIMIAR else "indeterminado"
            respostas[chave] = {"estado": estado, "probabilidade": prob,
                                "motivo": _limpar_texto(str(c.get("motivo") or ""))[:400]}
    classe = (res.get("porte") or {}).get("classe")
    if classe in ("micro", "pequena", "media", "grande"):
        respostas["porte"] = {"choice": classe}
    return descricao, (respostas or None)


def _descricao_so_dados(receita: dict, gptw: dict) -> str:
    nome = receita.get("nome_fantasia") or receita.get("razao_social")
    partes = [f"{nome} ({receita.get('razao_social')}) atua em {receita.get('atividade_principal') or 'atividade não informada'}, "
              f"com sede em {receita.get('municipio')}/{receita.get('uf')}. Situação cadastral: {receita.get('situacao') or 'não informada'}. "
              f"Porte na Receita Federal: {receita.get('porte_receita') or 'não informado'}."]
    if gptw.get("certificada"):
        partes.append(f"Tem o selo Great Place to Work válido até {gptw.get('validade')}, com "
                      f"{gptw.get('funcionarios')} funcionários informados ao GPTW, no setor {gptw.get('setor')}.")
        if gptw.get("descricao"):
            partes.append(gptw["descricao"])
    elif gptw.get("certificada") is False:
        partes.append("Não aparece na lista oficial de empresas certificadas pelo GPTW.")
    return " ".join(partes)


def _fatos_texto(receita: dict, gptw: dict) -> str:
    partes = [f"Empresa: {receita.get('nome_fantasia') or receita.get('razao_social')} ({receita.get('razao_social')}).",
              f"Atividade principal: {receita.get('atividade_principal')}. Local: {receita.get('municipio')}/{receita.get('uf')}.",
              f"Situação cadastral: {receita.get('situacao')}. Porte na Receita: {receita.get('porte_receita')}."]
    if gptw.get("certificada"):
        partes.append(f"Lista oficial do GPTW: CERTIFICADA, válida até {gptw.get('validade')}, "
                      f"{gptw.get('funcionarios')} funcionários informados.")
    elif gptw.get("consultado"):
        partes.append("Lista oficial do GPTW: NÃO certificada.")
    return " ".join(partes)


# ----------------------------------------------------------------------- decisão final

LIMIAR = float(os.environ.get("OLFA_LIMIAR", "0.5"))  # só para respostas do Gemini sem "estado"
# sobe quando o formato dos critérios muda: análises antigas no cache são refeitas
VERSAO_ANALISE = 2


def _porte_oficial(receita: dict, gptw: dict) -> Optional[tuple[bool, str]]:
    """Grupo de 5 a 15 viável pelos números oficiais, quando eles existem."""
    f = gptw.get("funcionarios")
    if isinstance(f, (int, float)) and f > 0:
        return f >= 5, f"{int(f)} funcionários informados ao GPTW."
    porte = (receita.get("porte_receita") or "").upper()
    # Microempresa e EPP são classes de faturamento, não de pessoas: aí quem estima é o Gemini.
    if "DEMAIS" in porte:
        return True, 'Porte "demais" na Receita Federal (faturamento acima de R$ 4,8 milhões por ano).'
    return None


def decidir(receita: dict, gptw: dict, respostas: Optional[dict], poucos_dados: bool) -> dict[str, Any]:
    """Junta fatos oficiais e o julgamento do Gemini em critérios com três estados:
    ok True (sim), False (não) ou None (indeterminado: faltou dado para dizer).
    Regra: dado oficial vence inferência. O Gemini decide o que não tem fonte oficial.
    A nota de 0 a 100 e a faixa A/B/C saem na ferramenta, com os pesos que a Manu define
    em Parâmetros; aqui só se descreve cada critério."""
    crit: dict[str, Any] = {}
    r = respostas or {}

    def prob(chave: str) -> Optional[float]:
        return r.get(chave, {}).get("probabilidade")

    def estado_ia(chave: str) -> Optional[bool]:
        e = r.get(chave, {}).get("estado")
        return True if e == "sim" else False if e == "nao" else None

    def motivo_ia(chave: str, padrao: str) -> str:
        m = r.get(chave, {}).get("motivo")
        p = prob(chave)
        return (f"{m} ({round(p * 100)}%)" if p is not None else m) if m else padrao

    sem_ia = ("Sem a chave do Gemini configurada, não dá para avaliar este critério." if not credenciais_gemini()
              else "O Gemini não conseguiu avaliar agora. Use Analisar de novo em alguns minutos.")

    # Selo GPTW: a lista oficial é o fato, sem inferência nenhuma. Conta como bônus na nota.
    if gptw.get("consultado"):
        crit["gptw"] = {"ok": bool(gptw.get("certificada")), "fonte": "lista oficial do GPTW",
                        "probabilidade": None,
                        "motivo": (f"Selo válido até {gptw.get('validade')}." if gptw.get("certificada")
                                   else "Não está na lista oficial de certificadas.")}
    else:
        crit["gptw"] = {"ok": None, "fonte": "sem dados", "probabilidade": None,
                        "motivo": "A lista oficial do GPTW não respondeu. Use Analisar de novo mais tarde."}

    # Grupo de 5 a 15: números oficiais quando existem, Gemini quando não.
    oficial = _porte_oficial(receita, gptw)
    if oficial is not None:
        crit["grupo_5_15"] = {"ok": oficial[0], "fonte": "dados oficiais", "probabilidade": None,
                              "motivo": oficial[1]}
    elif "grupo_5_15" in r:
        crit["grupo_5_15"] = {"ok": estado_ia("grupo_5_15"), "fonte": "Gemini",
                              "probabilidade": prob("grupo_5_15"),
                              "motivo": motivo_ia("grupo_5_15", "Estimativa do Gemini sobre o tamanho dos times.")}
    else:
        crit["grupo_5_15"] = {"ok": None, "fonte": "sem dados", "probabilidade": None,
                              "motivo": "Sem número de funcionários oficial. " + sem_ia}

    # Sinais de NR-1 / bem-estar: não há fonte oficial, é o Gemini que decide.
    if "nr1" in r:
        crit["nr1"] = {"ok": estado_ia("nr1"), "fonte": "Gemini", "probabilidade": prob("nr1"),
                       "motivo": motivo_ia("nr1", "Estimativa do Gemini sobre ações de saúde mental e bem-estar.")
                                 + (" Analisado só com dados oficiais, sem a pesquisa do Gemini." if poucos_dados else "")}
    else:
        crit["nr1"] = {"ok": None, "fonte": "sem dados", "probabilidade": None,
                       "motivo": sem_ia}

    extras = {}
    if respostas:
        extras = {"porte_estimado": r.get("porte", {}).get("choice")}
    motor = "Gemini" if respostas else "regras"

    ativa = "ATIVA" in (receita.get("situacao") or "").upper()
    nomes = {"gptw": "selo GPTW", "nr1": "sinais de NR-1/bem-estar", "grupo_5_15": "porte para grupo de 5 a 15"}
    indet = [nomes[k] for k, c in crit.items() if c["ok"] is None]
    if not ativa:
        resumo = "Empresa não está ativa na Receita Federal."
    elif indet:
        resumo = "Sem dados para: " + ", ".join(indet) + ". Conta como indeterminado, não como não."
    else:
        resumo = "Todos os critérios foram avaliados."
    return {"ativa": ativa, "resumo": resumo, "criterios": crit, "extras": extras, "motor": motor,
            "poucos_dados": poucos_dados, "versao": VERSAO_ANALISE}


# ------------------------------------------------------------------------- cache

_CACHE_LOCK = threading.Lock()


def _ler_cache() -> dict[str, Any]:
    try:
        return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _gravar_cache(cnpj: str, resultado: dict[str, Any]) -> None:
    with _CACHE_LOCK:
        dados = _ler_cache()
        dados[cnpj] = {"em": time.time(), "resultado": resultado}
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        CACHE_FILE.write_text(json.dumps(dados, ensure_ascii=False, indent=1), encoding="utf-8")


# ------------------------------------------------------------------------ entrada

def qualificar(cnpj_bruto: str, forcar: bool = False) -> dict[str, Any]:
    cnpj = so_digitos(cnpj_bruto)
    if not cnpj_valido(cnpj):
        raise ValueError("CNPJ inválido. Confira os 14 números.")

    if not forcar:
        item = _ler_cache().get(cnpj)
        if item and time.time() - item["em"] < CACHE_DIAS * 86400:
            antigo = item["resultado"]
            # um resultado feito sem o Gemini (sem chave, limite, erro) é refeito quando ele estiver disponível
            sem_gemini = antigo.get("motor") != "Gemini" and credenciais_gemini()
            if not sem_gemini and antigo.get("versao") == VERSAO_ANALISE:
                return {**antigo, "do_cache": True}

    receita = resumo_receita(buscar_receita(cnpj))
    gptw = buscar_gptw(cnpj)
    try:
        descricao, respostas = analisar_com_gemini(cnpj, receita, gptw)
    except Exception:
        log.exception("Gemini falhou na análise")
        descricao, respostas = {"texto": _descricao_so_dados(receita, gptw),
                                "fonte": "dados oficiais (erro na análise do Gemini)"}, None

    poucos_dados = not str(descricao.get("fonte", "")).startswith("Gemini")
    decisao = decidir(receita, gptw, respostas, poucos_dados)
    resultado = {
        "cnpj": cnpj,
        "cnpj_formatado": formatar_cnpj(cnpj),
        "empresa": nome_legivel(receita.get("nome_fantasia") or receita.get("razao_social")),
        "razao_social": receita.get("razao_social"),
        "receita": receita,
        "gptw": gptw,
        "descricao": descricao,
        "avaliacao_ia": respostas,
        **decisao,
        "analisado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    _gravar_cache(cnpj, resultado)
    return resultado
