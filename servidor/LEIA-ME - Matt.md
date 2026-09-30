# Ferramenta Olfatecário: como colocar no site

Oi, Matt. Esta pasta é a ferramenta de gestão da Olfatecário (workshops, proposta comercial, calendário, prospecção, predinho, caixa e investimento) com um backend pequeno em Python que qualifica leads sozinho a partir do CNPJ. A ideia é ela ficar numa área logada do site da Manu.

O backend é leve: FastAPI + httpx, sem modelo de IA local. A IA é o **Gemini, no nível gratuito do Google** — sem custo para a Manu.

## O que tem aqui

| Arquivo | Para que serve |
|---|---|
| `static/index.html` | A ferramenta inteira (HTML, CSS e JS puros, sem build). |
| `app.py` | Servidor FastAPI: entrega a página e a API. Tem login HTTP Basic opcional. |
| `pipeline.py` | A qualificação de leads (detalhes abaixo). |
| `proposta.py` | Escreve os textos da proposta comercial (botão **Escrever com IA** da aba Proposta). |
| `gemini.py` | Cliente mínimo da API do Gemini, usado pelos dois arquivos acima. Troca de modelo sozinho se um não existir para a chave (404), se o limite gratuito dele acabar (429) ou se estiver sobrecarregado (5xx). |
| `iniciar_exe.py` | Gera o `Olfatecario.exe` (versão de dois cliques, sem precisar de Python). |
| `montar_index.py` | Regera `static/index.html` a partir de `../ferramenta/pub.html`, a versão de referência da página. |
| `requirements.txt`, `Dockerfile`, `iniciar.bat` | Instalação, container e atalho para rodar no Windows. |
| `.env.example` | Variáveis de configuração. Copie para `.env`. |

## Como a qualificação funciona

A Manu digita o CNPJ na aba **Workshops > Prospecção**. O navegador chama `POST /api/leads/qualificar` e o servidor:

1. **Receita Federal**: busca os dados cadastrais na [BrasilAPI](https://brasilapi.com.br/docs#tag/CNPJ) (reserva: [minhareceita.org](https://minhareceita.org)). Traz razão social, nome fantasia, situação, porte, atividade e cidade.
2. **GPTW**: consulta a lista de empresas certificadas pela raiz do CNPJ (8 dígitos) em `https://certificadas.gptw.com.br/api/certified/all/filter?cnpj=`. É a API que o próprio site `certificadas.gptw.com.br` usa. Traz validade do selo, número de funcionários e setor.
3. **Gemini, uma chamada só**: com a chave configurada, recebe os dados oficiais e devolve, em JSON estruturado, a descrição da empresa para prospecção e, com probabilidade e motivo, o que não tem fonte oficial: sinais de ações de saúde mental e bem-estar (NR-1), se a empresa forma um grupo de 5 a 15 pessoas e o porte estimado. Sem chave, a descrição é montada só com os dados oficiais e o NR-1 fica para marcar à mão.
4. **Decisão, com a regra "dado oficial vence inferência"**:
   - Selo GPTW: só a lista oficial.
   - Grupo de 5 a 15 pessoas: funcionários informados ao GPTW (5 ou mais) ou porte "demais" na Receita; sem esses números, o Gemini.
   - Sinais de NR-1 e bem-estar: o Gemini, com probabilidade mínima de 0,5 (ajustável em `OLFA_LIMIAR`).
   - O lead é qualificado quando a empresa está ativa e cumpre os três.

O resultado de cada CNPJ fica em cache por 30 dias (`cache/leads.json`), então o mesmo CNPJ não gasta cota de novo. Um resultado feito sem o Gemini (sem chave, limite do dia) é refeito automaticamente na próxima consulta, quando ele voltar. O botão **Analisar de novo** força uma nova consulta.

Os dados de cadastro da Manu (orçamentos, caixa, leads, imagens da proposta) ficam salvos **no navegador dela** (localStorage). O servidor não guarda esses dados, só o cache das análises de CNPJ e o `.env`. O botão **Baixar backup** na tela inicial exporta tudo.

## Por que Gemini, e o que aconteceu com o Claude e o Laya

- A primeira versão usava a API da Anthropic (Claude) para a pesquisa e para os textos. Funciona bem, mas é cobrada por uso, e a Manu não quer uma fatura mensal. O Google AI Studio dá uma chave **gratuita, sem cartão de crédito**. Sem conta de cobrança vinculada, o Google não tem como cobrar nada: no pior caso a chamada é recusada.
- **Sem busca na web.** Testado com uma chave nova em 28/09/2026: os modelos 2.x (`gemini-2.5-flash`, o único com busca no Google gratuita) respondem 404 "no longer available to new users", e nos modelos 3.x a busca no Google fica fora do nível gratuito (volta 429 mesmo sem uso nenhum). Por isso a análise usa os dados oficiais e o conhecimento do próprio modelo. Para empresas conhecidas funciona bem; para empresas pequenas e pouco conhecidas o NR-1 tende a sair "sem sinais", e a tela mostra o motivo.
- A primeira versão também usava o **Laya**, um modelo de decisão local (PyTorch, ~4 GB de disco e 2 GB de RAM), para responder o critério de NR-1. Ele foi retirado em 28/09/2026: pesava demais, deixava o executável de teste sem o critério de NR-1 e exigia um servidor grande. O próprio Gemini, que já pesquisou a empresa, responde esse critério agora.

## Proposta comercial (aba Workshops > Proposta)

A Manu monta o orçamento e, na aba **Proposta**, conta como vai ser o workshop daquele cliente: ocasião, quem participa, o que o workshop deve desenvolver, notas em destaque, personalização do frasco, local e data. A ferramenta gera um PDF no visual da "Proposta Base Olfatecário": capa, Objetivo, Imersão e sentidos, O que será entregue (com os números da oficina), Investimento com até 3 opções de preço e imagem, página de fotos e contato. Também sai em Word.

- **Montar os textos com estas escolhas** funciona sem internet e sem chave: encaixa as escolhas nos textos padrão.
- **Escrever com IA** chama `POST /api/proposta/textos`, que usa a mesma `GEMINI_API_KEY`. Sem a chave, o botão aparece desligado. O servidor só repassa campos conhecidos e com tamanho limitado (`proposta._limpar`).
- **Imagens** (opções e fotos) são reduzidas no navegador para no máximo ~240 KB cada e guardadas no navegador da Manu. O localStorage costuma aceitar uns 5 MB, então cabem perto de 20 imagens. O **Baixar backup** leva as imagens junto.
- **Fonte**: o PDF usa Montserrat, baixada de `cdn.jsdelivr.net` na hora de gerar. Sem acesso a ela, sai em Helvetica com o mesmo layout. Se a política de segurança do site bloquear o jsDelivr, libere `cdn.jsdelivr.net` em `connect-src` (o `cdnjs.cloudflare.com` já é usado para o gerador de PDF).

## Colocar a chave do Gemini pela própria ferramenta

Além de editar o `.env` na mão, a aba **Workshops > Parâmetros** tem o cartão **"Chave da IA (Google Gemini, gratuito)"**, com um passo a passo de onde conseguir a chave em aistudio.google.com. Quem tiver acesso à ferramenta cola a chave ali e clica em **Salvar chave**, sem mexer em arquivo nenhum:

- `POST /api/config/chave-gemini` confere a chave chamando `GET /v1beta/models` da Google antes de gravar (chamada sem custo). Se a chave for recusada, nada é salvo. A Google recusa chave inválida com HTTP 400 e `"reason": "API_KEY_INVALID"`, não com 401/403; o código trata os dois casos.
- Se aceita, o servidor grava `GEMINI_API_KEY=` no `.env` (cria o arquivo se não existir, sem apagar o resto) e já ativa na hora, sem reiniciar. As outras abas passam a ver a IA ligada na mesma hora.
- `GET /api/config/chave-gemini` só diz se há chave (`{"configurada": true/false}`); nunca devolve a chave ao navegador.
- `DELETE /api/config/chave-gemini` remove a chave (do processo e do `.env`).
- Na versão sem servidor (o `static/index.html` aberto direto), o cartão avisa que não funciona ali e esconde o formulário.
- Como qualquer rota da API, fica atrás do login HTTP Basic quando `OLFA_USUARIO`/`OLFA_SENHA` estão definidos.

## Limite gratuito do Gemini

O nível gratuito tem limite de chamadas **por minuto** e **por dia**, por projeto do Google. Os números exatos aparecem em [aistudio.google.com/rate-limit](https://aistudio.google.com/rate-limit). A cota diária zera à **meia-noite do horário do Pacífico** (por volta das 4h ou 5h da manhã em Brasília).

Cada CNPJ novo gasta 1 chamada; cada "Escrever com IA", 1. Para o volume de uma loja isso fica bem abaixo do limite. O que já está feito para não travar:

- **Cache de 30 dias** por CNPJ.
- **Troca de modelo**: quando o limite de um modelo acaba (429) ou ele está sobrecarregado (503, comum nos horários de pico), `gemini.py` tenta o próximo da lista (`gemini-flash-latest`, `gemini-3.8-flash`, `gemini-3.7-flash`, `gemini-3.5-flash`, e os "lite"). No nível gratuito a cota é separada por modelo, então isso estica o uso do dia.
- Sem IA, a ferramenta não para: a análise sai só com dados oficiais, avisa na tela e é refeita sozinha quando a cota voltar.

Na prática, quem esgota o limite é teste em sequência (muitos "Analisar de novo" seguidos). No uso normal da Manu isso não deve acontecer.

## Requisitos

- Python 3.12 (ou use o `Olfatecario.exe`, que já traz o Python dentro).
- Pouca memória e disco: o servidor sobe em segundos e usa uns 100 MB de RAM.
- Internet (Receita Federal, GPTW e Gemini são serviços online).

## Rodar localmente

Windows: dê dois cliques em `iniciar.bat`. Na primeira vez ele cria o ambiente e instala tudo. Ou use o `Olfatecario.exe`, que não precisa de Python.

Linux ou Mac:

```bash
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env   # e preencha, ou cole a chave pela ferramenta depois
.venv/bin/uvicorn app:app --host 127.0.0.1 --port 8765
```

Abra `http://127.0.0.1:8765`. `GET /api/saude` mostra se o Gemini está configurado.

## Gerar o executável

```bash
pip install -r requirements.txt pyinstaller
pyinstaller --onefile --name Olfatecario --add-data "static;static" iniciar_exe.py
```

O arquivo sai em `dist/Olfatecario.exe` (uns 16 MB). O `.env` e o cache ficam ao lado do `.exe`, não na pasta temporária do PyInstaller.

## Colocar em produção

1. **Container**: `docker build -t olfatecario .` e `docker run -p 8765:8765 --env-file .env -v olfa-dados:/data olfatecario`. O volume `/data` guarda o cache.
2. **HTTPS obrigatório.** Coloque atrás do proxy do site (Nginx, Caddy ou o da própria plataforma). O uvicorn já sobe com `--proxy-headers`.
3. **Login.** Duas opções:
   - Rota protegida pelo login que o site já tem (por exemplo `/admin/ferramenta`), com o proxy repassando para o container. Nesse caso deixe `OLFA_USUARIO` e `OLFA_SENHA` vazios.
   - Ou use o login embutido: preencha `OLFA_USUARIO` e `OLFA_SENHA` no `.env` e o navegador pede usuário e senha.
   **Não deixe a ferramenta aberta para qualquer um**: a cota gratuita do Gemini é compartilhada por quem tiver acesso.
4. **Se a API ficar em outro domínio** que não o da página, defina antes do script da ferramenta: `<script>window.OLFA_API_BASE="https://api.seudominio.com.br"</script>` e libere CORS no `app.py`. Servir tudo pelo mesmo domínio é mais simples.
5. **Chave do Gemini**: crie em aistudio.google.com/apikey (gratuita, sem cartão) e coloque em `GEMINI_API_KEY`, ou cole pela ferramenta. Para trocar o modelo principal, use `OLFA_GEMINI_MODEL`.

## Atualizar a ferramenta

A versão de referência da página é `ferramenta/pub.html`. Depois de mudar ela, rode `python montar_index.py` para regerar `static/index.html`. O script só troca o jeito de baixar arquivos.

## Riscos que você precisa saber

- **A API do GPTW não é documentada.** É a que o site deles usa internamente e pode mudar sem aviso. Se mudar, o critério GPTW fica "sem dados" e o sistema avisa na tela. Vale conferir com o GPTW se o uso é permitido.
- **BrasilAPI e minhareceita.org são serviços comunitários gratuitos**, com limite de uso. Para volume alto, troque por um serviço pago de consulta de CNPJ em `buscar_receita()`.
- **O Gemini decide o NR-1 por probabilidade** e pode errar. Por isso a tela mostra a fonte e a porcentagem de cada critério, e o botão **Detalhes** mostra a descrição, os links pesquisados e os motivos.
- **O nível gratuito do Gemini pode mudar.** O Google aposenta modelos com frequência (os 2.x saíram para chaves novas em 2026). Se todos os modelos da lista derem 404, ajuste a lista em `gemini.py` (ou `OLFA_GEMINI_MODEL`); `GET https://generativelanguage.googleapis.com/v1beta/models` com a chave mostra os disponíveis. A troca de volta para uma API paga fica só em `gemini.py`, `pipeline.py`, `proposta.py` e na validação da chave em `app.py`.

Dúvidas depois do projeto: fale com a equipe da FEA Júnior que atendeu a Olfatecário.
