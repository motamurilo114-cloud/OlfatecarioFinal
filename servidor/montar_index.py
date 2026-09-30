"""Gera static/index.html a partir da ferramenta publicada no Claude (ferramenta/pub.html).

A versão do Claude salva arquivos pelo recurso de downloads da plataforma; fora dela o
navegador baixa direto. Este script troca só esse trecho e embrulha a página num HTML completo.
Uso:  python montar_index.py [caminho/para/pub.html] --forcar

DESDE A REVISÃO DE 29/09/2026 o original é static/index.html (editado direto). O pub.html
ficou para trás: ainda tem os dados reais da Manu e não tem as mudanças da revisão.
Rodar este script sem --forcar não faz nada, para não apagar o trabalho novo.
"""
import sys
from pathlib import Path

if "--forcar" not in sys.argv:
    raise SystemExit("static/index.html agora é o original; este script sobrescreveria as mudanças da revisão. "
                     "Use --forcar só se souber o que está fazendo.")
sys.argv = [a for a in sys.argv if a != "--forcar"]

BASE = Path(__file__).resolve().parent
origem = Path(sys.argv[1]) if len(sys.argv) > 1 else BASE.parent / "ferramenta" / "pub.html"
s = origem.read_text(encoding="utf-8")

antigo = '''  const d=await getDownloads();
  if(!d){ toast("Downloads não estão disponíveis nesta janela."); return; }'''
novo = '''  const d=await getDownloads();
  if(!d){
    try{
      const blob = data instanceof Blob ? data : new Blob([data],{type:"application/octet-stream"});
      const a=document.createElement("a"); a.href=URL.createObjectURL(blob); a.download=filename;
      document.body.appendChild(a); a.click(); a.remove(); setTimeout(()=>URL.revokeObjectURL(a.href),4000);
      toast("Arquivo salvo.");
    }catch(e){ toast("Não consegui salvar o arquivo."); }
    return;
  }'''
if antigo not in s:
    raise SystemExit("Trecho de downloads não encontrado: a ferramenta mudou, revise o script.")
s = s.replace(antigo, novo, 1)

html = ('<!doctype html>\n<html lang="pt-BR"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">\n'
        '<style>[hidden]:not([hidden=until-found i]){display:none!important}img{max-width:100%}body{margin:0}</style>\n'
        + s + '\n</body></html>\n')
destino = BASE / "static" / "index.html"
destino.parent.mkdir(exist_ok=True)
destino.write_text(html, encoding="utf-8")
print(f"ok: {destino} ({len(html)//1024} KB)")
