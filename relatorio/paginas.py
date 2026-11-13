"""O relatório em páginas, iguais às do RG publicado no ano anterior.

As páginas vêm de relatorio/dados_iniciais/paginas_rg2025.json (gerado por ferramentas/paginas_rg2025.py a partir do
PDF): para cada página, o fundo (static/rg2025/pNNN.jpg, sem texto), as caixas de texto (posição, fonte, tamanho, cor
e o texto em HTML) e as formas desenhadas. Cada caixa de texto vira um trecho de texto (Bloco) da seção a que a página
pertence; os gráficos e tabelas que a plataforma monta a partir dos quadros ficam por cima da área do gráfico ou da
tabela do PDF.
"""
import json
import re
import unicodedata
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path

ARQUIVO = Path(__file__).resolve().parent / "dados_iniciais" / "paginas_rg2025.json"


@lru_cache(maxsize=1)
def paginas_pdf():
    if not ARQUIVO.exists():
        return {}
    return {p["n"]: p for p in json.loads(ARQUIVO.read_text(encoding="utf-8"))}


def normalizar(t):
    t = unicodedata.normalize("NFKD", t or "").encode("ascii", "ignore").decode().lower()
    t = re.sub(r"^(grafico|tabela|figura|quadro)\s*\d+\s*[-–—:]?\s*", "", t.strip())
    t = re.sub(r"[^a-z0-9]+", " ", t)
    return t.strip()


def _parecido(a, b):
    a, b = normalizar(a), normalizar(b)
    if not a or not b or min(len(a), len(b)) < 5:
        return 0
    if a == b:
        return 1
    if b.startswith(a) or a.startswith(b):
        return 0.95 if min(len(a), len(b)) >= 0.6 * max(len(a), len(b)) else 0.8
    return SequenceMatcher(None, a, b).ratio()


def _bbox(c):
    return [c["x"], c["y"], c["x"] + c["w"], c["y"] + c["h"]]


def _perto(a, b, folga):
    return not (a[2] + folga < b[0] or b[2] + folga < a[0] or a[3] + folga < b[1] or b[3] + folga < a[1])


def _corpo_de_texto(c):
    """Caixa que é parágrafo de texto corrido (não rótulo de gráfico)."""
    return c["fam"] != "a" and (c["linhas"] >= 3 or len(c["texto"]) > 90)


def achar_titulo(pagina, titulo):
    melhor, nota = None, 0.0
    for i, c in enumerate(pagina["caixas"]):
        n = _parecido(titulo, c["texto"])
        if n > nota:
            melhor, nota = i, n
    return (melhor, nota) if nota >= 0.82 else (None, nota)


def area_do_objeto(pagina, i_titulo, folga=9):
    """A área do gráfico ou da tabela cujo título é a caixa i_titulo: o título e tudo o que está desenhado ou
    escrito colado a ele (barras, eixos, rótulos, legenda), sem pegar parágrafos de texto nem fundos grandes."""
    W, H = pagina["w"], pagina["h"]
    t = pagina["caixas"][i_titulo]
    reg = _bbox(t)
    formas = [f[:4] for f in pagina.get("formas", [])
              if (f[2] - f[0]) < 0.6 * W and (f[3] - f[1]) < 0.75 * H and (f[2] - f[0]) * (f[3] - f[1]) > 0.5]
    caixas = [(i, _bbox(c)) for i, c in enumerate(pagina["caixas"]) if i != i_titulo and not _corpo_de_texto(c)]
    usadas_f, usadas_c = set(), {i_titulo}
    mudou = True
    while mudou:
        mudou = False
        for k, f in enumerate(formas):
            if k not in usadas_f and _perto(reg, f, folga):
                novo = [min(reg[0], f[0]), min(reg[1], f[1]), max(reg[2], f[2]), max(reg[3], f[3])]
                if novo[2] - novo[0] > 0.62 * W or novo[3] - novo[1] > 0.8 * H:
                    usadas_f.add(k)
                    continue
                reg = novo
                usadas_f.add(k)
                mudou = True
        for i, b in caixas:
            if i not in usadas_c and _perto(reg, b, folga * 0.6):
                novo = [min(reg[0], b[0]), min(reg[1], b[1]), max(reg[2], b[2]), max(reg[3], b[3])]
                if novo[2] - novo[0] > 0.62 * W or novo[3] - novo[1] > 0.8 * H:
                    usadas_c.add(i)
                    continue
                reg = novo
                usadas_c.add(i)
                mudou = True
    return [round(v, 1) for v in reg], sorted(usadas_c)


# --- onde ficam os gráficos e tabelas da plataforma nas páginas do RG 2025 --------------------------------------
# (seção, título do gráfico/tabela) -> (página, [x0, y0, x1, y1] em pontos do PDF). Conferido página a página;
# o que não está aqui não tem gráfico/tabela no PDF (o número aparece no próprio texto da página).
LUGARES = {
    ("ambiente_externo", "Manifestações recebidas pela Ouvidoria"): (26, [478, 56, 882, 201]),
    ("ambiente_externo", "Distribuição das respostas dos pedidos de acesso à informação"): (29, [497, 301, 833, 421]),
    ("quem_somos", "Titulação dos docentes"): (37, [55, 103, 342, 428]),
    ("quem_somos", "Titulação dos servidores TAE"): (37, [492, 103, 834, 432]),
    ("quem_somos", "Programas de capacitação"): (38, [62, 222, 448, 455]),
    ("quem_somos", "Quantidade de servidores atendidos por curso EDS"): (38, [485, 100, 882, 266]),
    ("ensino_tecnico", "Auxílio discente"): (50, [315, 226, 646, 396]),
    ("ensino_tecnico", "Mostra Específica de Trabalhos e Aplicações (META)"): (54, [585, 148, 882, 346]),
    ("ensino_graduacao", "Grupos PET"): (51, [50, 178, 393, 301]),
    ("ensino_graduacao", "Monitoria"): (51, [75, 392, 392, 508]),
    ("ensino_graduacao", "Auxílio discente"): (51, [430, 347, 690, 504]),
    ("ensino_graduacao", "Cursos avaliados in loco ou ENADE"): (51, [738, 160, 870, 306]),
    ("ensino_pos", "Bolsas stricto sensu"): (52, [60, 197, 385, 346]),
    ("ensino_pos", "Auxílio discente"): (52, [475, 385, 880, 501]),
    ("pesquisa_inovacao", "Artigos publicados"): (53, [55, 250, 207, 512]),
    ("pesquisa_inovacao", "Pedidos de propriedade intelectual"): (53, [585, 195, 880, 331]),
    ("pesquisa_inovacao", "Recursos captados junto às agências de fomento à pesquisa"): (53, [245, 345, 570, 512]),
    ("pesquisa_inovacao", "Iniciação científica"): (54, [2, 115, 362, 336]),
    ("extensao", "Ações de extensão por campus"): (55, [58, 213, 330, 432]),
    ("extensao", "Ações de extensão por natureza"): (55, [230, 345, 482, 502]),
    ("extensao", "Ações de extensão por área temática"): (55, [486, 213, 760, 432]),
    ("extensao", "Ações de extensão por categoria"): (55, [655, 345, 882, 502]),
    ("desenvolvimento_estudantil", "Alunos atendidos nos restaurantes estudantis"): (56, [56, 212, 345, 417]),
    ("desenvolvimento_estudantil", "Custeio e orçamento da assistência estudantil"): (56, [392, 210, 785, 381]),
    ("desenvolvimento_estudantil", "Refeições servidas nos restaurantes estudantis"): (56, [375, 402, 802, 507]),
    ("inclusao", "Alunos com necessidades educacionais específicas identificados/atendidos"): (58, [355, 160, 558, 355]),
    ("inclusao", "Porcentagem de alunos ingressantes cotistas"): (58, [578, 366, 882, 511]),
    ("cooperacao_internacional", "Alunos em mobilidade acadêmica"): (59, [55, 225, 322, 372]),
    ("cooperacao_internacional", "Participantes do Programa de Português como Língua Estrangeira"): (59, [612, 186, 878, 291]),
    ("cooperacao_internacional", "Alunos em dupla diplomação"): (59, [362, 355, 528, 508]),
    ("cooperacao_internacional", "Docentes em mobilidade internacional"): (59, [598, 370, 882, 510]),
    ("gestao_academica", "Alunos ingressantes"): (61, [57, 298, 330, 429]),
    ("gestao_academica", "Alunos matriculados"): (61, [333, 298, 602, 429]),
    ("gestao_academica", "Alunos concluintes"): (61, [604, 298, 880, 429]),
    ("orcamento", "Gráfico 1 – Principais grupos de despesas do orçamento institucional"): (73, [55, 258, 460, 426]),
    ("orcamento", "Gráfico 2 – Evolução orçamentária (despesas discricionárias) na última década"): (73, [482, 243, 882, 426]),
    ("execucao_orcamentaria", "Tabela 1 – Despesas empenhadas, liquidadas e pagas, por grupo de despesa"): (74, [482, 328, 882, 513]),
    ("execucao_orcamentaria", "Gráfico 3 – Dez maiores despesas discricionárias"): (75, [55, 67, 457, 226]),
    ("execucao_orcamentaria", "Gráfico 4 – Uso do recurso orçamentário relativo a investimentos"): (75, [488, 222, 872, 412]),
    ("contabeis", "Gráfico 5 – Quilometragem total por ano e tipo de veículo"): (78, [480, 212, 882, 429]),
}
_LUGARES_N = {(s, normalizar(t)): v for (s, t), v in LUGARES.items()}


def lugar_de(bloco):
    return _LUGARES_N.get((bloco.secao.chave, normalizar(bloco.titulo)))


NOTA_DE_RODAPE = re.compile(r"^\d{1,3}\s*(Dispon[íi]vel|Fonte|Consult|Acesso|Documentos?|Para |O |A |Ver |Link|http)", re.I)
RODAPE = re.compile(r"^CAP[ÍI]TULO\s+\d+\s*\|")
APENDICE = re.compile(r"^AP[ÊE]NDICE\b", re.I)
ANO_DO_RELATORIO = re.compile(r"(?i)((?:relat[óo]rio de gest[ãa]o|exerc[íi]cio(?: de)?|ano base:?|\bRG)\s*)(\d{4})\b")


def _e_fixo(c, H):
    t = c["texto"].strip()
    return (c["y"] > H * 0.9 and RODAPE.match(t)) or (c["y"] > H * 0.86 and t.isdigit() and len(t) <= 3)


def _caixa_css(c):
    return f'left:{c["x"]}px;top:{c["y"]}px;width:{c["w"]}px;{c["css"]}'


def _coluna(c, W):
    return 0 if c["x"] + c["w"] / 2 < W / 2 else 1


def _cor_de_fundo(fundo, regiao, larg):
    """Cor do fundo da página em volta da área (para cobrir o gráfico antigo com a mesma cor)."""
    try:
        from django.conf import settings
        from PIL import Image
        im = Image.open(Path(settings.BASE_DIR) / "static" / fundo).convert("RGB")
    except Exception:  # pragma: no cover - imagem ausente
        return "#ffffff"
    k = im.size[0] / larg
    x0, y0, x1, y1 = [v * k for v in regiao]
    pontos = []
    for i in range(1, 12):
        x = x0 + (x1 - x0) * i / 12
        y = y0 + (y1 - y0) * i / 12
        for px, py in ((x, y0 + 2), (x, y1 - 2), (x0 + 2, y), (x1 - 2, y)):
            if 0 <= px < im.size[0] and 0 <= py < im.size[1]:
                pontos.append(im.getpixel((int(px), int(py))))
    if not pontos:
        return "#ffffff"
    pontos.sort(key=lambda p: sum(p))
    r, g, b = pontos[len(pontos) // 2]
    return "#%02x%02x%02x" % (r, g, b)


def _marcos(ciclo, pags):
    """Onde começa cada seção: (página, coluna, altura) do título da seção no PDF."""
    marcos = []
    for s in ciclo.secoes.all():
        ref = s.referencia_pagina
        if not ref:
            continue
        titulo = re.sub(r"^\d+\.\s*", "", s.titulo)
        melhor = None
        capitulo = s.pai_id is None
        for n in ((ref - 1, ref, ref + 1) if capitulo else (ref, ref + 1, ref - 1)):
            p = pags.get(n)
            if not p:
                continue
            for c in p["caixas"]:
                if c["tam"] < 13:
                    continue
                nota = _parecido(titulo, c["texto"])
                if nota >= 0.8 and (melhor is None or nota > melhor[0] + 0.05):
                    melhor = (nota, n, _coluna(c, p["w"]), -1 if capitulo else c["y"])
            if melhor and capitulo:
                break                         # capítulo: a página de abertura (a primeira em que o título aparece)
        if melhor:
            marcos.append((melhor[1], melhor[2], melhor[3] - 1, s.ordem, s))
        else:
            marcos.append((ref, 0, -1, s.ordem, s))
    marcos.sort(key=lambda m: m[:4])
    return marcos


def _guardar_antigos(ciclo, antigos):
    """Cópia legível (JSON) dos trechos de texto editados na versão anterior, na pasta de dados."""
    from django.conf import settings
    from django.utils import timezone
    from .campos import valores_do_bloco
    destino = Path(settings.DADOS_DIR) / f"textos_antes_das_paginas_{ciclo.ano}_{timezone.now():%Y%m%d_%H%M%S}.json"
    dados = [{"secao": b.secao.chave, "titulo_secao": b.secao.titulo, "tipo": b.tipo, "conteudo": b.conteudo,
              "campos": {k: str(v) for k, v in valores_do_bloco(b).items() if v is not None},
              "editado_por": b.atualizado_por.get_full_name() if b.atualizado_por else "",
              "editado_em": b.atualizado_em.isoformat()} for b in antigos if b.atualizado_por_id]
    try:
        destino.write_text(json.dumps(dados, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError:  # pragma: no cover - disco
        pass


def criar_paginas(ciclo):
    """Monta o relatório de `ciclo` nas páginas do RG publicado (uma vez só). Devolve um resumo."""
    from django.db import transaction

    from . import campos as CT
    from . import rascunho as R
    from .calculo import Calculadora
    from .html_seguro import limpar
    from .models import Bloco, Pagina
    feito = {"paginas": 0, "caixas": 0, "objetos": 0, "campos": 0, "ligados": 0, "antigos": 0, "antigos_editados": 0}
    pags = paginas_pdf()
    if not pags or ciclo.paginas.exists():
        return feito
    from .dados_iniciais.rg2026 import trocar_nome_no_texto
    idx = R.indice_de_valores(Calculadora(ciclo), ciclo.ano - 1)
    marcos = _marcos(ciclo, pags)
    padrao = ciclo.secoes.filter(chave="apresentacao").first() or (marcos[0][4] if marcos else None)
    if padrao is None:
        return feito
    # gráficos e tabelas que vão para as páginas
    objetos = {}
    for b in Bloco.objects.filter(secao__ciclo=ciclo, tipo__in=[Bloco.GRAFICO, Bloco.TABELA]).select_related("secao"):
        lugar = lugar_de(b)
        if lugar:
            objetos.setdefault(lugar[0], []).append((b, lugar[1]))

    def dono(n, col, y):
        atual = None
        for m in marcos:
            if (m[0], m[1], m[2]) <= (n, col, y):
                atual = m[4]
            else:
                break
        return atual or padrao

    with transaction.atomic():
        com_paginas = set()
        for n in sorted(pags):
            p = pags[n]
            if any(APENDICE.match(c["texto"].strip()) and c["tam"] >= 14 for c in p["caixas"]):
                break                         # o apêndice do RG anterior foi trocado pela planilha de metas
            W, H = p["w"], p["h"]
            fundo = f"rg2025/p{n:03d}.jpg"
            regioes = [r for _, r in objetos.get(n, [])]

            def coberta(c):
                bx = [c["x"], c["y"], c["x"] + c["w"], c["y"] + c["h"]]
                area = max(1.0, (bx[2] - bx[0]) * (bx[3] - bx[1]))
                limite = 0.25 if len(c["texto"]) <= 25 else 0.55     # rótulos de eixo meio para fora da área
                rotulo = re.fullmatch(r"[\sR$\d.,%()+\-–]*\d[\sR$\d.,%()+\-–]*", c["texto"])
                for r in regioes:
                    if rotulo and r[0] - 60 <= bx[0] and bx[2] <= r[2] + 60 and r[1] - 6 <= bx[1] and bx[3] <= r[3] + 6:
                        return True                       # valor de eixo logo ao lado do gráfico

                    ix = max(0, min(bx[2], r[2]) - max(bx[0], r[0])) * max(0, min(bx[3], r[3]) - max(bx[1], r[1]))
                    if ix / area > limite:
                        return True
                return False

            caixas = sorted(p["caixas"], key=lambda c: (_coluna(c, W), c["y"], c["x"]))
            sumario = any(normalizar(c["texto"]) == "sumario" for c in caixas)   # números do sumário são páginas
            fixos = "".join(f'<div class="pg-fixo" style="{_caixa_css(c)}">{c["html"]}</div>'
                            for c in caixas if _e_fixo(c, H))
            primeira = next((c for c in caixas if not _e_fixo(c, H)), None)
            sec_pag = dono(n, _coluna(primeira, W), primeira["y"]) if primeira else dono(n, 0, 0)
            pg = Pagina.objects.create(ciclo=ciclo, numero=n, largura=W, altura=H, fundo=fundo, secao=sec_pag,
                                       fixos=fixos)
            feito["paginas"] += 1
            for i, c in enumerate(caixas):
                if _e_fixo(c, H) or coberta(c):
                    continue
                s = dono(n, _coluna(c, W), c["y"])
                html = limpar(c["html"])
                html = ANO_DO_RELATORIO.sub(lambda m: m.group(1) + (str(ciclo.ano) if m.group(2) == str(ciclo.ano - 1)
                                                                      else m.group(2)), html)
                if n <= 2 and c["texto"].strip() == str(ciclo.ano - 1):    # capa e folha de rosto
                    html = html.replace(str(ciclo.ano - 1), str(ciclo.ano))
                if not sumario and not NOTA_DE_RODAPE.match(c["texto"]):
                    html, k = R.religar(html, idx)
                    feito["ligados"] += max(0, k)
                    html, _ = R.desligar_identificadores(html)
                    html, novos = CT.camposificar(html)
                    feito["campos"] += len(novos)
                html = trocar_nome_no_texto(html)
                Bloco.objects.create(
                    secao=s, pagina=pg, tipo=Bloco.TEXTO, ordem=n * 1000 + i, conteudo=html,
                    config={"caixa": {"x": c["x"], "y": c["y"], "w": c["w"], "h": c["h"], "css": c["css"],
                                      "quebra": c["quebra"]}, "rascunho_rg": True, "campos212": True})
                com_paginas.add(s.pk)
                feito["caixas"] += 1
            for k, (b, r) in enumerate(objetos.get(n, [])):
                it, _ = achar_titulo(p, b.titulo)
                b.pagina = pg
                b.ordem = n * 1000 + 900 + k
                b.config = dict(b.config or {}, caixa={"x": r[0], "y": r[1], "w": r[2] - r[0], "h": r[3] - r[1],
                                                       "fundo": _cor_de_fundo(fundo, r, W),
                                                       "titulo": bool(it is not None and coberta(p["caixas"][it]))})
                b.save(update_fields=["pagina", "ordem", "config"])
                com_paginas.add(b.secao_id)
                feito["objetos"] += 1
        # o texto e os painéis de números da versão anterior (fora das páginas) saem das seções que agora têm
        # páginas; o histórico de cada trecho continua guardado
        antigos = Bloco.objects.filter(secao_id__in=com_paginas, pagina__isnull=True,
                                       tipo__in=[Bloco.TEXTO, Bloco.DESTAQUES]).select_related("secao")
        feito["antigos_editados"] = antigos.filter(atualizado_por__isnull=False).count()
        feito["antigos"] = antigos.count()
        if feito["antigos_editados"]:
            _guardar_antigos(ciclo, antigos)
        for b in antigos:
            b.delete()
    return feito
