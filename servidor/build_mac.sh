#!/bin/bash
# Gera o Olfatecario.app e o Olfatecario-Mac.zip. Rode num Mac, a partir desta pasta:
#   bash build_mac.sh
set -e
cd "$(dirname "$0")"
python3 -m venv .venv-mac
.venv-mac/bin/pip install -q -r requirements.txt pyinstaller
EXTRA=()
[ -f dados-iniciais.json ] && EXTRA=(--add-data "dados-iniciais.json:.")
.venv-mac/bin/pyinstaller --noconfirm --windowed --name Olfatecario \
  --add-data "static:static" "${EXTRA[@]}" iniciar_exe.py
cd dist
xattr -cr Olfatecario.app
ditto -c -k --keepParent Olfatecario.app ../Olfatecario-Mac.zip
echo "Pronto: $(pwd)/../Olfatecario-Mac.zip"
