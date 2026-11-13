"""2.14: painéis do RG 2025 que no PDF eram imagem (tabelas e números de painéis da Ouvidoria, da LAI, do PGEN, da
gestão de riscos, da integridade, dos custos, a matriz SWOT...).

Cada número ou texto da imagem ganha, por cima, uma caixa de texto editável na mesma posição, com a mesma cor e
tamanho, e o fundo da cor do painel (cobre o número antigo). Os números viram xxxxx ou ficam ligados ao quadro
correspondente. Os dois rankings da Ouvidoria (p. 27) viram gráficos da plataforma.
As posições foram medidas na imagem do PDF (relatorio/dados_iniciais/paineis_rg2025.json).
"""
import json
from functools import lru_cache
from pathlib import Path

ARQUIVO = Path(__file__).resolve().parent / "dados_iniciais" / "paineis_rg2025.json"

# gráficos novos no lugar de imagens de gráfico: (id, página, seção, quadro, título, área, config)
GRAFICOS = [
    ("rank_assunto", 27, "ambiente_externo", "ouv_ranking_assunto", "Quantidade de manifestações por assunto",
     [60, 266, 452, 452], {"tipo": "barras_horizontais", "inverter": True, "ordenar": True}),
    ("rank_subassunto", 27, "ambiente_externo", "ouv_ranking_subassunto", "Quantidade de manifestações por subassunto",
     [484, 143, 878, 318], {"tipo": "barras_horizontais", "inverter": True, "ordenar": True}),
]


@lru_cache(maxsize=1)
def itens():
    return json.loads(ARQUIVO.read_text(encoding="utf-8")) if ARQUIVO.exists() else []


def aplicar_paineis(ciclo):
    """Cria (uma vez cada) as caixas e gráficos dos painéis que eram imagem. Devolve quantos criou."""
    from . import campos as CT
    from . import rascunho as R
    from .calculo import Calculadora
    from .html_seguro import limpar
    from .models import Bloco, Quadro
    from .paginas import _cor_de_fundo
    paginas = {p.numero: p for p in ciclo.paginas.all()}
    if not paginas:
        return 0
    # capa e folha de rosto: o ano sozinho numa caixa ("2025") passa ao ano do relatório (instalações da 2.13)
    import re
    for b in Bloco.objects.filter(pagina__in=[p for n_, p in paginas.items() if n_ <= 2], tipo=Bloco.TEXTO,
                                  atualizado_por__isnull=True):
        if re.fullmatch(rf"\s*(<p[^>]*>)?\s*{ciclo.ano - 1}\s*(</p>)?\s*", b.conteudo or ""):
            Bloco.objects.filter(pk=b.pk).update(conteudo=b.conteudo.replace(str(ciclo.ano - 1), str(ciclo.ano)))
    feitos = {(b.config or {}).get("painel") for b in Bloco.objects.filter(secao__ciclo=ciclo, pagina__isnull=False)
              .only("config")}
    secoes = {s.chave: s for s in ciclo.secoes.all()}
    idx = None
    n = 0
    for it in itens():
        pg, sec = paginas.get(it["pagina"]), secoes.get(it["secao"])
        if it["id"] in feitos or pg is None or sec is None:
            continue
        if idx is None:
            idx = R.indice_de_valores(Calculadora(ciclo), ciclo.ano - 1)
        html = limpar(it["html"])
        html, _ = R.religar(html, idx)
        html, _ = R.desligar_identificadores(html)
        html, _ = CT.camposificar(html)
        Bloco.objects.create(
            secao=sec, pagina=pg, tipo=Bloco.TEXTO, ordem=it["pagina"] * 1000 + 800 + n, conteudo=html,
            config={"caixa": {"x": it["x"], "y": it["y"], "w": it["w"], "h": it["h"], "css": it["css"],
                              "quebra": it.get("quebra", True), "fundo": it.get("fundo")},
                    "painel": it["id"], "rascunho_rg": True, "campos212": True, "nome_inst": True})
        n += 1
    for ident, num, sch, qch, titulo, r, cfg in GRAFICOS:
        pg, sec = paginas.get(num), secoes.get(sch)
        q = Quadro.objects.filter(ciclo=ciclo, chave=qch).first()
        if ident in feitos or pg is None or sec is None or q is None:
            continue
        Bloco.objects.create(
            secao=sec, pagina=pg, tipo=Bloco.GRAFICO, quadro=q, titulo=titulo, ordem=num * 1000 + 950,
            config=dict(cfg, colunas=[f"a{ciclo.ano}"], painel=ident,
                        caixa={"x": r[0], "y": r[1], "w": r[2] - r[0], "h": r[3] - r[1], "titulo": True,
                               "fundo": _cor_de_fundo(pg.fundo, r, pg.largura)}))
        n += 1
    return n
