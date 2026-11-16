"""Gera, a partir do PDF do RG 2025, as páginas do relatório no formato da plataforma (uso único, fora do servidor).

A leitura do PDF agora fica em relatorio/pdf_paginas.py, que o importador de PDF do sistema também usa.

Uso:
    python ferramentas/paginas_rg2025.py static/referencia/RG2025.pdf [páginas,separadas,por,vírgula]
"""
import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from relatorio.pdf_paginas import extrair, fundos  # noqa: E402

if __name__ == "__main__":
    pdf = sys.argv[1]
    so = {int(x) for x in sys.argv[2].split(",")} if len(sys.argv) > 2 else None
    fundos(pdf, BASE / "static" / "rg2025", so)
    dados = extrair(pdf, so, ao_avancar=lambda n: print(f"página {n}", file=sys.stderr))
    saida = BASE / "relatorio" / "dados_iniciais" / ("paginas_rg2025.json" if not so else "paginas_amostra.json")
    saida.write_text(json.dumps(dados, ensure_ascii=False), encoding="utf-8")
    print(f"{len(dados)} página(s) em {saida}", file=sys.stderr)
