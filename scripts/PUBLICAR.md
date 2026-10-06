# Gerar e publicar os instaladores

O `gerar-todos.sh` usa o workflow `.github/workflows/build.yml` para gerar, nos servidores do GitHub, os três instaladores do Olfatecario:

| Arquivo | Sistema |
|---|---|
| `Olfatecario.exe` | Windows 10 e 11 (portátil, sem instalar) |
| `Olfatecario-Mac-arm64.dmg` | Mac com chip Apple (M1, M2, M3 ou mais novo) |
| `Olfatecario-Mac-x64.dmg` | Mac com processador Intel |

Esses nomes são os que a landing (`docs/index.html`) espera. Os botões baixam de `releases/latest/download/<arquivo>`.

## Uma vez só

```bash
brew install gh
gh auth login
```

Use uma conta com acesso de escrita ao repositório. O Actions é gratuito em repositório público.

## Gerar

```bash
bash scripts/gerar-todos.sh
```

O script dispara o build, acompanha até terminar (cerca de 10 a 15 minutos) e baixa os arquivos para `scripts/instaladores/`, já com os nomes acima.

## Publicar

```bash
bash scripts/gerar-todos.sh publicar
```

Faz o mesmo e cria a Release `v1.0.0` com os três arquivos. Para outra versão, use `TAG=v1.1.0 bash scripts/gerar-todos.sh publicar`.

Pela interface do GitHub: Releases > Draft a new release > crie a tag > arraste os três arquivos > **Set as the latest release** > Publish release.

Sem terminal: aba **Actions** > **Gerar Olfatecario** > **Run workflow**. Ao terminar, baixe os artefatos no fim da página da execução e anexe à Release com os nomes da tabela.

## Landing page

A pasta `docs/` serve o GitHub Pages: Settings > Pages > Deploy from a branch > `main` > `/docs`.

## Atenção

- O build inclui `servidor/dados-iniciais.json` (dados da obra e custos do prédio) quando o arquivo existe no repositório. Se os instaladores forem públicos, esses dados vão junto. Para um build sem eles, defina `SEM_DADOS_INICIAIS=1` no passo de build do workflow, ou localmente ao rodar `npm run backend`.
- O app não é assinado por conta de desenvolvedor paga. No Mac, o app baixado da internet aparece como "danificado" (é a quarentena do Gatekeeper, o arquivo não está corrompido). Quem baixar precisa rodar uma vez, depois de copiar para Aplicativos: `xattr -cr /Applications/Olfatecario.app`. Se ainda reclamar: Ajustes do Sistema > Privacidade e Segurança > "Abrir mesmo assim". O "botão direito > Abrir" não funciona mais desde o macOS 15. No Windows aparece o aviso do SmartScreen ("Mais informações" > "Executar assim mesmo").
