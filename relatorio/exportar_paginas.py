"""Word (.docx) com as páginas do RG: cada página do relatório vira uma página do Word do mesmo tamanho, com o fundo
(a imagem da página, sem texto) atrás e, por cima, cada caixa de texto, gráfico e tabela na mesma posição, como
caixas de texto do Word (editáveis). Os números saem com os valores de 2026 (ou xxxxx, se ainda faltam).

As caixas são objetos de desenho do Word 2010+ (wps), ancorados na página. O que não está em página nenhuma (ex.:
a planilha de metas do PDI) vem depois, em páginas de texto corrido.
"""
import io
import re
from html import escape, unescape
from html.parser import HTMLParser
from pathlib import Path

from django.conf import settings
from docx import Document
from docx.enum.section import WD_ORIENT, WD_SECTION
from docx.enum.text import WD_BREAK
from docx.oxml import parse_xml
from docx.shared import Cm, Pt

from . import graficos
from . import revisao
from .apresentacao import tabela_quadro, tamanho_na_pagina
from .calculo import Calculadora
from .models import Bloco
from .texto import renderizar

EMU = 12700        # por ponto
NS = ('xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
      'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
      'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
      'xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture" '
      'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
      'xmlns:wps="http://schemas.microsoft.com/office/word/2010/wordprocessingShape"')
FONTE_WORD = {"calibri": "Calibri", "carlito": "Calibri", "arial": "Arial", "liberation sans": "Arial",
              "trade gothic lt std": "Arial Narrow", "arial narrow": "Arial Narrow", "minion pro": "Georgia",
              "myriad pro": "Calibri", "symbol": "Symbol"}


def _css(s):
    out = {}
    for d in (s or "").split(";"):
        if ":" in d:
            k, v = d.split(":", 1)
            out[k.strip().lower()] = v.strip()
    return out


def _px(v, padrao=0.0):
    m = re.match(r"^(-?[\d.]+)", str(v or ""))
    return float(m.group(1)) if m else padrao


def _fonte(v):
    for nome in (v or "").split(","):
        n = nome.strip().strip("'\"").lower()
        if n in FONTE_WORD:
            return FONTE_WORD[n]
    return "Calibri"


# --- HTML da caixa -> parágrafos do Word ----------------------------------------------------------------------
class _Paragrafos(HTMLParser):
    """Converte o HTML de uma caixa (p, span com estilo, strong, em, sup, br) em XML de parágrafos do Word."""

    def __init__(self, base):
        super().__init__(convert_charrefs=True)
        self.base = base           # estilo da caixa
        self.pars = []             # [(pPr, [runs])]
        self.pilha = [dict(base)]
        self.atual = None

    def _novo_par(self, estilo):
        e = dict(self.pilha[0])
        e.update(estilo)
        self.atual = {"estilo": e, "runs": [], "texto": ""}
        self.pars.append(self.atual)

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "p":
            self._novo_par(_css(a.get("style")))
            self.pilha = [self.pilha[0], dict(self.atual["estilo"])]
            return
        if tag == "br":
            if self.atual is None:
                self._novo_par({})
            self.atual["runs"].append(("br", None))
            return
        e = dict(self.pilha[-1])
        if tag == "span":
            e.update({k: v for k, v in _css(a.get("style")).items() if k in ("font-size", "font-weight", "font-style",
                                                                               "color", "font-family")})
        elif tag in ("strong", "b"):
            e["font-weight"] = "700"
        elif tag in ("em", "i"):
            e["font-style"] = "italic"
        elif tag == "u" or tag == "a":
            e["u"] = "1"
        elif tag == "sup":
            e["sup"] = "1"
        self.pilha.append(e)

    def handle_endtag(self, tag):
        if tag == "p":
            self.pilha = [self.pilha[0]]
            self.atual = None
            return
        if tag in ("span", "strong", "b", "em", "i", "u", "a", "sup", "mark", "ins", "del", "s", "sub") and \
                len(self.pilha) > (2 if self.atual else 1):
            self.pilha.pop()

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

    def handle_data(self, data):
        if not data:
            return
        if self.atual is None:
            if not data.strip():
                return
            self._novo_par({})
        t = re.sub(r"[ \t\r\n]+", " ", data)
        if not self.atual["texto"] or self.atual["texto"].endswith(" "):
            t = t.lstrip(" ")
        if not t:
            return
        self.atual["texto"] += t
        self.atual["runs"].append(("t", (t, dict(self.pilha[-1]))))

    def xml(self):
        saida = []
        for p in self.pars:
            e = p["estilo"]
            jc = {"justify": "both", "center": "center", "right": "right"}.get(e.get("text-align", "left"), "left")
            lh = e.get("line-height", "")
            tam = _px(e.get("font-size"), 11)
            linha = _px(lh) if lh.endswith("px") else (float(lh) * tam if lh else tam * 1.2)
            antes = max(0.0, _px(e.get("margin-top")))
            esq = max(0.0, _px(e.get("padding-left")))
            ind = _px(e.get("text-indent"))
            ppr = [f'<w:spacing w:before="{round(antes * 20)}" w:after="0" w:line="{round(linha * 20)}" '
                   f'w:lineRule="exact"/>']
            if esq or ind:
                ppr.append(f'<w:ind w:left="{round((esq + max(0, -ind)) * 20)}" '
                           + (f'w:firstLine="{round(ind * 20)}"' if ind >= 0 else f'w:hanging="{round(-ind * 20)}"')
                           + "/>")
            ppr.append(f'<w:jc w:val="{jc}"/>')
            # espaço entre letras (e o aperto entre palavras do PDF, distribuído entre as letras)
            ls = _px(e.get("letter-spacing"))
            ws = _px(e.get("word-spacing"))
            texto = p["texto"]
            if ws and texto:
                ls += ws * texto.count(" ") / max(1, len(texto))
            runs = []
            for tipo, val in p["runs"]:
                if tipo == "br":
                    runs.append("<w:r><w:br/></w:r>")
                    continue
                t, st = val
                rpr = [f'<w:rFonts w:ascii="{_fonte(st.get("font-family"))}" w:hAnsi="{_fonte(st.get("font-family"))}" '
                       f'w:cs="{_fonte(st.get("font-family"))}"/>']
                if str(st.get("font-weight", "400")) in ("700", "800", "900", "bold", "600"):
                    rpr.append("<w:b/>")
                if st.get("font-style") == "italic":
                    rpr.append("<w:i/>")
                cor = (st.get("color") or "#000000").lstrip("#")
                if re.fullmatch(r"[0-9a-fA-F]{6}", cor):
                    rpr.append(f'<w:color w:val="{cor.upper()}"/>')
                if ls:
                    rpr.append(f'<w:spacing w:val="{round(ls * 20)}"/>')
                rpr.append(f'<w:sz w:val="{max(2, round(_px(st.get("font-size"), 11) * 2))}"/>')
                if st.get("u"):
                    rpr.append('<w:u w:val="single"/>')
                if st.get("sup"):
                    rpr.append('<w:vertAlign w:val="superscript"/>')
                partes = t.split("­")
                conteudo = "<w:softHyphen/>".join(f'<w:t xml:space="preserve">{escape(x, quote=False)}</w:t>'
                                                  for x in partes)
                runs.append(f'<w:r><w:rPr>{"".join(rpr)}</w:rPr>{conteudo}</w:r>')
            saida.append(f'<w:p><w:pPr>{"".join(ppr)}</w:pPr>{"".join(runs)}</w:p>')
        return "".join(saida) or "<w:p/>"


def paragrafos(html, css):
    p = _Paragrafos(_css(css))
    p.feed(html or "")
    p.close()
    return p.xml()


# --- objetos ancorados na página ----------------------------------------------------------------------------
class _Ids:
    n = 100


def _ancora(conteudo_grafico, x, y, w, h, atras=False, z=1):
    _Ids.n += 1
    return (f'<w:r {NS}><w:drawing><wp:anchor distT="0" distB="0" distL="0" distR="0" simplePos="0" '
            f'relativeHeight="{z}" behindDoc="{1 if atras else 0}" locked="0" layoutInCell="1" allowOverlap="1">'
            f'<wp:simplePos x="0" y="0"/><wp:positionH relativeFrom="page"><wp:posOffset>{round(x * EMU)}'
            f'</wp:posOffset></wp:positionH><wp:positionV relativeFrom="page"><wp:posOffset>{round(y * EMU)}'
            f'</wp:posOffset></wp:positionV><wp:extent cx="{round(w * EMU)}" cy="{round(h * EMU)}"/>'
            f'<wp:effectExtent l="0" t="0" r="0" b="0"/><wp:wrapNone/><wp:docPr id="{_Ids.n}" name="Objeto {_Ids.n}"/>'
            f'<wp:cNvGraphicFramePr/>{conteudo_grafico}</wp:anchor></w:drawing></w:r>')


def _figura(rid, w, h, nome="imagem"):
    _Ids.n += 1
    return (f'<a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture"><pic:pic>'
            f'<pic:nvPicPr><pic:cNvPr id="{_Ids.n}" name="{nome}"/><pic:cNvPicPr/></pic:nvPicPr><pic:blipFill>'
            f'<a:blip r:embed="{rid}"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill><pic:spPr><a:xfrm>'
            f'<a:off x="0" y="0"/><a:ext cx="{round(w * EMU)}" cy="{round(h * EMU)}"/></a:xfrm>'
            f'<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr></pic:pic></a:graphicData></a:graphic>')


def _caixa_texto(conteudo, w, h, fundo=None, crescer=True, quebra=True):
    preench = f'<a:solidFill><a:srgbClr val="{fundo.lstrip("#").upper()}"/></a:solidFill>' if fundo and \
        re.fullmatch(r"#?[0-9a-fA-F]{6}", fundo) else "<a:noFill/>"
    return (f'<a:graphic><a:graphicData uri="http://schemas.microsoft.com/office/word/2010/wordprocessingShape">'
            f'<wps:wsp><wps:cNvSpPr txBox="1"/><wps:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{round(w * EMU)}" '
            f'cy="{round(h * EMU)}"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom>{preench}'
            f'<a:ln><a:noFill/></a:ln></wps:spPr><wps:txbx><w:txbxContent>{conteudo}</w:txbxContent></wps:txbx>'
            f'<wps:bodyPr rot="0" vert="horz" wrap="{"square" if quebra else "none"}" lIns="0" tIns="0" rIns="0" bIns="0" anchor="t" '
            f'anchorCtr="0">{"<a:spAutoFit/>" if crescer else "<a:noAutofit/>"}</wps:bodyPr></wps:wsp>'
            f'</a:graphicData></a:graphic>')


def _inline(rid, w, h):
    _Ids.n += 1
    return (f'<w:r><w:drawing><wp:inline distT="0" distB="0" distL="0" distR="0"><wp:extent cx="{round(w * EMU)}" '
            f'cy="{round(h * EMU)}"/><wp:docPr id="{_Ids.n}" name="Gráfico {_Ids.n}"/><wp:cNvGraphicFramePr/>'
            f'{_figura(rid, w, h, "grafico.png")}</wp:inline></w:drawing></w:r>')


def _tabela_xml(dados, largura):
    cols = 1 + len(dados["cabecalho"])
    w0 = largura * 0.36 if cols > 1 else largura
    wn = (largura - w0) / max(1, cols - 1)
    larg = [w0] + [wn] * (cols - 1)

    def cel(texto, w, negrito=False, direita=False, fundo=None, cor="222222"):
        sh = f'<w:shd w:val="clear" w:color="auto" w:fill="{fundo}"/>' if fundo else ""
        return (f'<w:tc><w:tcPr><w:tcW w:w="{round(w * 20)}" w:type="dxa"/>{sh}</w:tcPr><w:p><w:pPr>'
                f'<w:spacing w:before="0" w:after="0" w:line="190" w:lineRule="exact"/>'
                f'<w:jc w:val="{"right" if direita else "left"}"/></w:pPr><w:r><w:rPr><w:rFonts w:ascii="Calibri" '
                f'w:hAnsi="Calibri"/>{"<w:b/>" if negrito else ""}<w:color w:val="{cor}"/><w:sz w:val="15"/></w:rPr>'
                f'<w:t xml:space="preserve">{escape(str(texto), quote=False)}</w:t></w:r></w:p></w:tc>')
    linhas = ['<w:tr>' + cel("", larg[0], True, fundo="1B3F6E", cor="FFFFFF") +
              "".join(cel(h, larg[i + 1], True, True, "1B3F6E", "FFFFFF") for i, h in enumerate(dados["cabecalho"]))
              + "</w:tr>"]
    for li in dados["linhas"]:
        linhas.append("<w:tr>" + cel(li["rotulo"], larg[0], li.get("total")) +
                      "".join(cel(v, larg[i + 1], li.get("total"), not dados.get("texto"))
                              for i, v in enumerate(li["valores"])) + "</w:tr>")
    grade = "".join(f'<w:gridCol w:w="{round(w * 20)}"/>' for w in larg)
    return (f'<w:tbl><w:tblPr><w:tblW w:w="{round(largura * 20)}" w:type="dxa"/><w:tblBorders>'
            f'<w:bottom w:val="single" w:sz="4" w:color="1B3F6E"/><w:insideH w:val="single" w:sz="2" w:color="D9DEE5"/>'
            f'</w:tblBorders><w:tblLayout w:type="fixed"/><w:tblCellMar><w:left w:w="40" w:type="dxa"/>'
            f'<w:right w:w="40" w:type="dxa"/></w:tblCellMar></w:tblPr><w:tblGrid>{grade}</w:tblGrid>'
            f'{"".join(linhas)}</w:tbl><w:p/>')


def _html_final(b, calc):
    from . import campos as CT
    html, _ = renderizar(revisao.base(b.conteudo), calc, marcar=False, campos=CT.valores_do_bloco(b))
    return re.sub(r"</?mark\b[^>]*>", "", html)


def _pagina(doc, p, caixas, objetos, calc, coletar, cont):
    par = doc.add_paragraph()
    frags = []
    fundo = Path(settings.BASE_DIR) / "static" / p.fundo
    if fundo.exists():
        rid, _ = doc.part.get_or_add_image(str(fundo))
        frags.append(_ancora(_figura(rid, p.largura, p.altura, fundo.name), 0, 0, p.largura, p.altura, atras=True,
                             z=0))
    z = 10
    for m in re.finditer(r'<div class="pg-fixo" style="([^"]*)">(.*?)</div>', p.fixos or "", re.S):
        st = _css(unescape(m.group(1)))
        frags.append(_ancora(_caixa_texto(paragrafos(m.group(2), unescape(m.group(1))), _px(st.get("width"), 100) + 4,
                                          14), _px(st.get("left")), _px(st.get("top")), _px(st.get("width"), 100) + 4,
                             14, z=z))
        z += 1
    for b in caixas:
        cx = b.config["caixa"]
        w = cx["w"] + (1.0 if "justify" in cx.get("css", "") else 4.0)
        frags.append(_ancora(_caixa_texto(paragrafos(_html_final(b, calc), cx.get("css", "")), w, max(6, cx["h"]),
                                          cx.get("fundo"), quebra=not cx.get("quebra")), cx["x"], cx["y"], w,
                             max(6, cx["h"]), z=z))
        z += 1
    for b in objetos:
        cx = b.config["caixa"]
        q = calc.quadro_por_id.get(b.quadro_id)
        titulo = ""
        if cx.get("titulo") and b.titulo:
            titulo = (f'<w:p><w:pPr><w:spacing w:before="0" w:after="20"/><w:jc w:val="center"/></w:pPr><w:r><w:rPr>'
                      f'<w:b/><w:color w:val="1B3F6E"/><w:sz w:val="18"/></w:rPr><w:t xml:space="preserve">'
                      f'{escape(b.titulo, quote=False)}</w:t></w:r></w:p>')
        corpo = ""
        if q is not None and b.tipo == Bloco.GRAFICO:
            tam = tamanho_na_pagina(b)
            cfg = dict(b.config or {}, _altura=tam.get("altura"))
            png, _ = graficos.desenhar(calc, q, cfg, "", "png", tam.get("largura", cx["w"] / 72))
            if png:
                from PIL import Image
                im = Image.open(io.BytesIO(png))
                alt_util = cx["h"] - (14 if titulo else 0)
                k = min(cx["w"] / im.size[0], alt_util / im.size[1])
                rid, _ = doc.part.get_or_add_image(io.BytesIO(png))
                corpo = (f'<w:p><w:pPr><w:spacing w:before="0" w:after="0"/><w:jc w:val="center"/></w:pPr>'
                         f'{_inline(rid, im.size[0] * k, im.size[1] * k)}</w:p>')
                if coletar:
                    cont[0] += 1
                    coletar(cont[0], b.titulo or q.titulo, q, b, png)
            else:
                corpo = ('<w:p><w:r><w:rPr><w:color w:val="8A6D00"/><w:sz w:val="14"/></w:rPr><w:t>Ainda não há '
                         'valores preenchidos para desenhar o gráfico.</w:t></w:r></w:p>')
        elif q is not None and b.tipo == Bloco.TABELA:
            corpo = _tabela_xml(tabela_quadro(calc, q, b.config), cx["w"])
        frags.append(_ancora(_caixa_texto(titulo + (corpo or "<w:p/>"), cx["w"], cx["h"], cx.get("fundo") or "#FFFFFF",
                                          crescer=False), cx["x"], cx["y"], cx["w"], cx["h"], z=z))
        z += 1
    for f in frags:
        par._p.append(parse_xml(f))


def _secao_paginas(doc, p, nova):
    sec = doc.add_section(WD_SECTION.NEW_PAGE) if nova else doc.sections[0]
    sec.orientation = WD_ORIENT.LANDSCAPE
    sec.page_width, sec.page_height = Pt(p.largura), Pt(p.altura)
    for k in ("left_margin", "right_margin", "top_margin", "bottom_margin", "header_distance", "footer_distance"):
        setattr(sec, k, Cm(0))
    return sec


def gerar_docx_paginas(ciclo, inst=None, coletar_graficos=None):
    """Bytes do .docx no formato das páginas do RG."""
    from .exportar_docx import _blocos, _estilos, Contadores
    from .views_doc import em_paginas, estrutura
    calc = Calculadora(ciclo)
    doc = Document()
    _estilos(doc)
    caps = estrutura(ciclo, calc)
    seq = em_paginas(ciclo, caps) or []
    cont, contadores = [0], Contadores()
    modo = None                 # "pagina" ou "texto": troca de seção só quando muda
    primeira = True
    for x in seq:
        if x["tipo"] == "pagina":
            p = x["p"]
            if modo != "pagina" or primeira:
                _secao_paginas(doc, p, nova=not primeira)
            elif not primeira:
                doc.paragraphs[-1].add_run().add_break(WD_BREAK.PAGE)
            caixas = sorted([c["d"]["b"] for c in x["caixas"]], key=lambda b: b.ordem)
            objetos = [c["d"]["b"] for c in x["objetos"]]
            _pagina(doc, p, caixas, objetos, calc, coletar_graficos, cont)
            modo = "pagina"
        else:
            sec = doc.add_section(WD_SECTION.NEW_PAGE) if not primeira else doc.sections[0]
            sec.orientation = WD_ORIENT.LANDSCAPE
            sec.page_width, sec.page_height = Cm(33.0), Cm(20.0)
            sec.left_margin = sec.right_margin = Cm(2.0)
            sec.top_margin = sec.bottom_margin = Cm(1.8)
            doc.add_paragraph(x["it"]["s"].titulo, style="Heading 2")
            _blocos(doc, calc, [d["b"] for d in x["blocos"]], contadores, None)
            modo = "texto"
        primeira = False
    # o primeiro parágrafo vazio do modelo do Word sairia como uma página em branco
    corpo = doc.element.body
    if len(doc.paragraphs) and not doc.paragraphs[0].text and not doc.paragraphs[0]._p.xpath(".//w:drawing"):
        corpo.remove(doc.paragraphs[0]._p)
    doc.core_properties.title = f"Relatório de Gestão {ciclo.ano}"
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()
