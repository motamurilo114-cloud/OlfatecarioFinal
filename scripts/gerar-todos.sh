#!/bin/bash
# Gera os instaladores do Olfatecario para Windows, Mac Apple Silicon e Mac Intel
# usando o workflow do repositório (build.yml) nos servidores do GitHub.
#
# Pré-requisitos (uma vez só):
#   brew install gh        # GitHub CLI
#   gh auth login          # entre com a conta que tem acesso de escrita ao repo
#
# Uso:
#   bash gerar-todos.sh              # gera e baixa os 3 arquivos para ./instaladores
#   bash gerar-todos.sh publicar     # gera, baixa e cria a Release v1.0.0 com os 3
#
# Variáveis opcionais: REPO=dono/repo  BRANCH=main  TAG=v1.0.0
set -euo pipefail
cd "$(dirname "$0")"

REPO="${REPO:-motamurilo114-cloud/OlfatecarioFinal}"
BRANCH="${BRANCH:-main}"
TAG="${TAG:-v1.0.0}"
OUT="$PWD/instaladores"
WORK="$PWD/.baixado"

command -v gh >/dev/null || { echo "Falta o GitHub CLI. Instale com: brew install gh"; exit 1; }
gh auth status >/dev/null 2>&1 || { echo "Você não está logado. Rode: gh auth login"; exit 1; }

ultimo_id() {
  gh run list --repo "$REPO" --workflow build.yml --limit 1 --json databaseId --jq '.[0].databaseId // 0'
}

ANTES=$(ultimo_id)
echo "==> 1/4 Disparando o build em $REPO (branch $BRANCH)"
gh workflow run build.yml --repo "$REPO" --ref "$BRANCH"

echo "==> 2/4 Esperando o GitHub registrar a execução"
RUN_ID=0
for _ in $(seq 1 30); do
  sleep 4
  ATUAL=$(ultimo_id)
  if [ "$ATUAL" != "$ANTES" ]; then RUN_ID="$ATUAL"; break; fi
done
[ "$RUN_ID" != "0" ] || { echo "Não encontrei a execução nova. Veja a aba Actions do repo."; exit 1; }
echo "    execução $RUN_ID: https://github.com/$REPO/actions/runs/$RUN_ID"

echo "    Acompanhando (leva uns 10 a 15 minutos; pode deixar rodando)"
gh run watch "$RUN_ID" --repo "$REPO" --exit-status

echo "==> 3/4 Baixando os arquivos"
rm -rf "$WORK" "$OUT"; mkdir -p "$WORK" "$OUT"
gh run download "$RUN_ID" --repo "$REPO" --dir "$WORK"

EXE=$(find "$WORK" -type f -name "*.exe" | head -1 || true)
ARM=$(find "$WORK" -type f -name "*.dmg" -name "*arm64*" | head -1 || true)
INTEL=$(find "$WORK" -type f -name "*.dmg" ! -name "*arm64*" | head -1 || true)

[ -n "$EXE" ]   && cp "$EXE"   "$OUT/Olfatecario.exe"             || echo "AVISO: .exe do Windows não encontrado"
[ -n "$ARM" ]   && cp "$ARM"   "$OUT/Olfatecario-Mac-arm64.dmg"   || echo "AVISO: .dmg Apple Silicon não encontrado"
[ -n "$INTEL" ] && cp "$INTEL" "$OUT/Olfatecario-Mac-x64.dmg"     || echo "AVISO: .dmg Intel não encontrado"
rm -rf "$WORK"

echo "==> 4/4 Pronto. Arquivos em: $OUT"
ls -lh "$OUT"

if [ "${1:-}" = "publicar" ]; then
  echo "==> Criando a Release $TAG em $REPO"
  gh release create "$TAG" "$OUT"/* --repo "$REPO" --target "$BRANCH" --latest \
    --title "Olfatecario ${TAG#v}" --notes "Instaladores para Windows, Mac Apple Silicon e Mac Intel."
  echo "Release publicada: https://github.com/$REPO/releases/tag/$TAG"
else
  echo
  echo "Para publicar, rode:  bash gerar-todos.sh publicar"
  echo "Ou anexe os 3 arquivos à mão em: https://github.com/$REPO/releases/new"
fi
