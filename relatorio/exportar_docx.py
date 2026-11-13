"""
Exportação do relatório para Word (.docx) e do pacote para a diagramação.

O .docx sai com:
  capa, sumário automático (o Word atualiza ao abrir), capítulos e seções como títulos
  (Título 1 / Título 2), textos com os números vivos já substituídos pelos valores,
  tabelas e gráficos numerados com legenda e fonte, números em destaque e paginação.

O pacote (.zip) leva o .docx, cada gráfico em PNG (alta resolução) e SVG, e uma
planilha com os dados de cada gráfico e de cada tabela — para a diagramadora refazer
os gráficos no estilo dela sem redigitar nenhum número.
"""
import io
import re
import unicodedata
import zipfile
from html.parser import HTMLParser

from django.utils import timezone
from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK, WD_COLOR_INDEX
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

from . import apresentacao as A
from . import graficos, revisao
from .calculo import Calculadora
from .models import Bloco
from .texto import renderizar

AZUL = RGBColor(0x14, 0x2C, 0x46)      # azul-marinho da marca UFCIMG
AZUL_HEX = "142C46"
CINZA = RGBColor(0x5B, 0x66, 0x76)
FONTE = "Calibri"


# --- utilidades de XML -------------------------------------------------------------
def _sombrear(celula, cor_hex):
    tcPr = celula._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), cor_hex)
    tcPr.append(shd)


def _sombrear_paragrafo(par, cor_hex, borda_esq=None):
    pPr = par._p.get_or_add_pPr()
    if borda_esq:
        bdr = OxmlElement("w:pBdr")
        left = OxmlElement("w:left")
        left.set(qn("w:val"), "single")
        left.set(qn("w:sz"), "24")
        left.set(qn("w:space"), "8")
        left.set(qn("w:color"), borda_esq)
        bdr.append(left)
        pPr.append(bdr)
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), cor_hex)
    pPr.append(shd)


def _campo(par, instrucao, texto_padrao=""):
    """Campo do Word (PAGE, TOC...)."""
    r = par.add_run()
    ini = OxmlElement("w:fldChar")
    ini.set(qn("w:fldCharType"), "begin")
    ini.set(qn("w:dirty"), "true")
    r._r.append(ini)
    r2 = par.add_run()
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = instrucao
    r2._r.append(instr)
    r3 = par.add_run()
    sep = OxmlElement("w:fldChar")
    sep.set(qn("w:fldCharType"), "separate")
    r3._r.append(sep)
    if texto_padrao:
        par.add_run(texto_padrao)
    r4 = par.add_run()
    fim = OxmlElement("w:fldChar")
    fim.set(qn("w:fldCharType"), "end")
    r4._r.append(fim)


def _hyperlink(par, url, texto, negrito=False, italico=False):
    rid = par.part.relate_to(url, "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink",
                             is_external=True)
    h = OxmlElement("w:hyperlink")
    h.set(qn("r:id"), rid)
    r = OxmlElement("w:r")
    rPr = OxmlElement("w:rPr")
    for tag, val in (("w:color", "1F4468"), ("w:u", "single")):
        e = OxmlElement(tag)
        e.set(qn("w:val"), val)
        rPr.append(e)
    if negrito:
        rPr.append(OxmlElement("w:b"))
    if italico:
        rPr.append(OxmlElement("w:i"))
    r.append(rPr)
    t = OxmlElement("w:t")
    t.text = texto
    t.set(qn("xml:space"), "preserve")
    r.append(t)
    h.append(r)
    par._p.append(h)


def _atualizar_campos_ao_abrir(doc):
    settings = doc.settings.element
    e = OxmlElement("w:updateFields")
    e.set(qn("w:val"), "true")
    settings.append(e)


# --- HTML do editor -> parágrafos do Word ----------------------------------------------
class _ParaDocx(HTMLParser):
    """Converte o HTML limpo do editor (p, h3, h4, listas, citação, negrito...) em parágrafos."""

    def __init__(self, doc):
        super().__init__(convert_charrefs=True)
        self.doc = doc
        self.par = None
        self.estilo = {"b": 0, "i": 0, "u": 0, "s": 0, "sup": 0, "sub": 0, "mark": 0}
        self.tabela = None          # linhas da tabela em montagem: [[(texto, cabeçalho?)]]
        self.celula = None
        self.listas = []
        self.link = None
        self.texto_link = ""

    def _novo(self, estilo="Normal"):
        self.par = self.doc.add_paragraph(style=estilo)
        if estilo == "Normal":
            self.par.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        return self.par

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "table":
            self.tabela, self.par = [], None
            return
        if self.tabela is not None:
            if tag == "tr":
                self.tabela.append([])
            elif tag in ("td", "th") and self.tabela:
                self.celula = [tag == "th", ""]
            elif tag == "br" and self.celula is not None:
                self.celula[1] += "\n"
            return
        if tag == "mark":
            self.estilo["mark"] += 1
            return
        if tag == "img":
            self._imagem(a.get("src", ""))
            return
        if tag == "p":
            self._novo()
        elif tag in ("h3", "h4"):
            self._novo("Heading 4" if tag == "h3" else "Heading 5")
        elif tag in ("ul", "ol"):
            self.listas.append(tag)
        elif tag == "li":
            self._novo("List Number" if self.listas and self.listas[-1] == "ol" else "List Bullet")
        elif tag == "blockquote":
            self._novo()
            _sombrear_paragrafo(self.par, "FFF6E6", borda_esq="F0A742")
            self.par.paragraph_format.left_indent = Cm(0.4)
        elif tag in ("strong", "b"):
            self.estilo["b"] += 1
        elif tag in ("em", "i"):
            self.estilo["i"] += 1
        elif tag == "u":
            self.estilo["u"] += 1
        elif tag == "s":
            self.estilo["s"] += 1
        elif tag in ("sup", "sub"):
            self.estilo[tag] += 1
        elif tag == "br":
            if self.par is not None:
                self.par.add_run().add_break()
                if self.par.alignment == WD_ALIGN_PARAGRAPH.JUSTIFY:
                    # parágrafo com quebras de linha (nomes e cargos, obras): justificado, o Word estica a
                    # linha antes de cada quebra; alinhado à esquerda fica como na tela
                    self.par.alignment = WD_ALIGN_PARAGRAPH.LEFT
        elif tag == "a":
            self.link = a.get("href")
            self.texto_link = ""

    def handle_endtag(self, tag):
        if self.tabela is not None:
            if tag in ("td", "th") and self.celula is not None and self.tabela:
                self.tabela[-1].append((self.celula[1].strip(), self.celula[0]))
                self.celula = None
            elif tag == "table":
                self._tabela(self.tabela)
                self.tabela = None
            return
        if tag == "mark":
            self.estilo["mark"] -= 1
            return
        if tag in ("strong", "b"):
            self.estilo["b"] -= 1
        elif tag in ("em", "i"):
            self.estilo["i"] -= 1
        elif tag in ("u", "s", "sup", "sub"):
            self.estilo[tag] -= 1
        elif tag in ("ul", "ol") and self.listas:
            self.listas.pop()
        elif tag == "a" and self.link:
            if self.par is None:
                self._novo()
            _hyperlink(self.par, self.link, self.texto_link, self.estilo["b"] > 0, self.estilo["i"] > 0)
            self.link = None
        elif tag in ("p", "h3", "h4", "li", "blockquote"):
            self.par = None

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

    def _imagem(self, src):
        """Imagem enviada à plataforma: entra no Word com até 15,5 cm de largura."""
        dados = imagem_png_ou_jpg(src)
        if dados is None:
            return
        conteudo, larg_px = dados
        if self.par is None:
            self._novo()
        self.par.alignment = WD_ALIGN_PARAGRAPH.CENTER
        largura = min(Cm(15.5), Cm(larg_px / 150 * 2.54)) if larg_px else Cm(15.5)
        try:
            self.par.add_run().add_picture(io.BytesIO(conteudo), width=largura)
        except Exception:   # noqa: BLE001 - imagem que o Word não aceita não derruba a exportação
            self.par.add_run("[imagem não pôde ser incluída]")

    def _tabela(self, linhas):
        linhas = [li for li in linhas if li]
        if not linhas:
            return
        ncol = max(len(li) for li in linhas)
        t = self.doc.add_table(rows=len(linhas), cols=ncol)
        t.style = "Table Grid"
        for i, li in enumerate(linhas):
            for j, (txt, cab) in enumerate(li):
                c = t.rows[i].cells[j]
                r = c.paragraphs[0].add_run(txt)
                r.font.size = Pt(8.5)
                r.bold = cab or None
                if cab:
                    _sombrear(c, "E6EDF5")
        self.doc.add_paragraph()

    def handle_data(self, data):
        if not data:
            return
        if self.tabela is not None:
            if self.celula is not None:
                self.celula[1] += data
            return
        if self.link:
            self.texto_link += data
            return
        if self.par is None:
            if not data.strip():
                return
            self._novo()
        r = self.par.add_run(data)
        r.bold = self.estilo["b"] > 0 or None
        r.italic = self.estilo["i"] > 0 or None
        r.underline = self.estilo["u"] > 0 or None
        r.font.strike = self.estilo["s"] > 0 or None
        if self.estilo["sup"] > 0:
            r.font.superscript = True
        if self.estilo["sub"] > 0:
            r.font.subscript = True
        if self.estilo["mark"] > 0:
            r.font.highlight_color = WD_COLOR_INDEX.YELLOW


def html_para_docx(doc, html):
    p = _ParaDocx(doc)
    p.feed(html or "")
    p.close()


# --- documento --------------------------------------------------------------------------
def _estilos(doc):
    st = doc.styles
    normal = st["Normal"]
    normal.font.name = FONTE
    normal.element.rPr.rFonts.set(qn("w:eastAsia"), FONTE)
    normal.font.size = Pt(11)
    normal.paragraph_format.space_after = Pt(6)
    normal.paragraph_format.line_spacing = 1.15
    for nome, tam, cor in (("Title", 26, AZUL), ("Heading 1", 18, AZUL), ("Heading 2", 14, AZUL),
                           ("Heading 3", 12, AZUL), ("Heading 4", 12, AZUL), ("Heading 5", 11, RGBColor(0x1F, 0x44, 0x68))):
        s = st[nome]
        s.font.name = FONTE
        s.font.size = Pt(tam)
        s.font.bold = True
        s.font.color.rgb = cor
        rpr = s.element.get_or_add_rPr()
        rpr.get_or_add_rFonts().set(qn("w:ascii"), FONTE)
        rpr.get_or_add_rFonts().set(qn("w:hAnsi"), FONTE)
    st["Heading 1"].paragraph_format.space_before = Pt(0)
    st["Heading 1"].paragraph_format.space_after = Pt(12)
    st["Heading 2"].paragraph_format.space_before = Pt(18)
    st["Heading 2"].paragraph_format.space_after = Pt(8)
    st["Heading 2"].paragraph_format.keep_with_next = True
    for nome in ("Caption",):
        s = st[nome]
        s.font.name = FONTE
        s.font.size = Pt(10)
        s.font.bold = True
        s.font.italic = False
        s.font.color.rgb = AZUL


def _capa(doc, ciclo, inst, versao_texto):
    sec = doc.sections[0]
    for _ in range(3):
        doc.add_paragraph()
    if inst and inst.logo:
        try:
            with inst.logo.open("rb") as f:
                doc.add_picture(io.BytesIO(f.read()), height=Cm(3.2))
                doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
        except (FileNotFoundError, ValueError, OSError):
            pass
    else:
        from django.conf import settings
        try:
            doc.add_picture(str(settings.BASE_DIR / "static" / "img" / "ufcimg-marca.png"), height=Cm(2.6))
            doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
        except (FileNotFoundError, OSError):
            pass
    for _ in range(2):
        doc.add_paragraph()
    for texto, tam, negrito, cor in ((inst.nome.upper() if inst else "", 13, True, AZUL),
                                     ("", 11, False, None),
                                     ("RELATÓRIO DE GESTÃO", 30, True, AZUL),
                                     (f"Exercício {ciclo.ano}", 18, False, AZUL),
                                     ("", 11, False, None),
                                     ("Relatório de Gestão apresentado aos órgãos de controle interno e externo e à "
                                      "sociedade, como prestação de contas anual, nos termos do parágrafo único do art. 70 "
                                      "da Constituição Federal, elaborado de acordo com as disposições da Instrução "
                                      "Normativa TCU nº 84/2020 e da Decisão Normativa TCU nº 198/2022.", 10, False, CINZA)):
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r = p.add_run(texto)
        r.font.size = Pt(tam)
        r.bold = negrito
        if cor is not None:
            r.font.color.rgb = cor
    for _ in range(6):
        doc.add_paragraph()
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run(versao_texto)
    r.font.size = Pt(9)
    r.font.color.rgb = CINZA
    doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)
    del sec


def _sumario(doc):
    doc.add_paragraph("Sumário", style="Heading 1")
    p = doc.add_paragraph()
    _campo(p, 'TOC \\o "1-3" \\h \\z \\u', "Clique com o botão direito aqui e escolha “Atualizar campo” para montar o sumário.")
    doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)


def _rodape_e_cabecalho(doc, ciclo, inst):
    for sec in doc.sections:
        sec.different_first_page_header_footer = True
        cab = sec.header.paragraphs[0]
        cab.text = " · ".join(x for x in ((inst.sigla if inst else ""), f"Relatório de Gestão {ciclo.ano}") if x)
        cab.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        for r in cab.runs:
            r.font.size = Pt(8)
            r.font.color.rgb = CINZA
        rod = sec.footer.paragraphs[0]
        rod.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        _campo(rod, "PAGE", "1")
        for r in rod.runs:
            r.font.size = Pt(9)


class Contadores:
    def __init__(self):
        self.tabela = 0
        self.grafico = 0


def _legenda(doc, rotulo, n, titulo):
    p = doc.add_paragraph(style="Caption")
    p.add_run(f"{rotulo} {n}")
    if titulo:
        p.add_run(f" – {titulo}")
    p.paragraph_format.keep_with_next = True
    return p


def _fonte(doc, fonte):
    if fonte:
        p = doc.add_paragraph()
        r = p.add_run(f"Fonte: {fonte}")
        r.font.size = Pt(8.5)
        r.font.color.rgb = CINZA
        p.paragraph_format.space_after = Pt(10)


def _tabela(doc, dados, titulo, cont):
    cont.tabela += 1
    _legenda(doc, "Tabela", cont.tabela, titulo)
    cab = dados["cabecalho"]
    t = doc.add_table(rows=1 + len(dados["linhas"]), cols=1 + len(cab))
    t.style = "Table Grid"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    largura_rot = Cm(6.0 if len(cab) <= 6 else 4.5)
    resto = int((Cm(16) - largura_rot) / max(1, len(cab)))
    _fixar_larguras(t, [largura_rot] + [resto] * len(cab))
    for i, h in enumerate([""] + cab):
        c = t.rows[0].cells[i]
        c.width = largura_rot if i == 0 else resto
        _sombrear(c, AZUL_HEX)
        p = c.paragraphs[0]
        r = p.add_run(h)
        r.bold = True
        r.font.size = Pt(9)
        r.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
        p.alignment = WD_ALIGN_PARAGRAPH.RIGHT if i and not dados.get("texto") else WD_ALIGN_PARAGRAPH.LEFT
    for li, linha in enumerate(dados["linhas"], start=1):
        valores = [linha["rotulo"]] + linha["valores"]
        for i, v in enumerate(valores):
            c = t.rows[li].cells[i]
            c.width = largura_rot if i == 0 else resto
            p = c.paragraphs[0]
            r = p.add_run(str(v))
            r.font.size = Pt(9)
            r.bold = linha["total"] or None
            p.alignment = WD_ALIGN_PARAGRAPH.RIGHT if i and not dados.get("texto") else WD_ALIGN_PARAGRAPH.LEFT
            if linha["total"]:
                _sombrear(c, "E6EDF5")
    _repetir_cabecalho(t.rows[0])
    _fonte(doc, dados.get("fonte"))


def _fixar_larguras(t, larguras):
    """Larguras fixas (Word e LibreOffice respeitam o tblGrid só com layout fixo)."""
    t.autofit = False
    tblPr = t._tbl.tblPr
    lay = OxmlElement("w:tblLayout")
    lay.set(qn("w:type"), "fixed")
    tblPr.append(lay)
    for col, w in zip(t.columns, larguras):
        col.width = w
    grid = t._tbl.tblGrid
    for gc, w in zip(grid.findall(qn("w:gridCol")), larguras):
        gc.set(qn("w:w"), str(int(w / 635)))


def _repetir_cabecalho(linha):
    trPr = linha._tr.get_or_add_trPr()
    e = OxmlElement("w:tblHeader")
    e.set(qn("w:val"), "true")
    trPr.append(e)


def _destaques(doc, itens, titulo):
    if titulo:
        p = doc.add_paragraph()
        r = p.add_run(titulo)
        r.bold = True
        r.font.color.rgb = AZUL
    n = len(itens)
    if not n:
        return
    porlinha = n if n <= 5 else (4 if n % 4 == 0 or n % 4 > n % 3 else 3)
    linhas = (n + porlinha - 1) // porlinha
    t = doc.add_table(rows=linhas, cols=porlinha)
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    _fixar_larguras(t, [int(Cm(16) / porlinha)] * porlinha)
    maior = max(len(it["valor"]) for it in itens)
    tam = 18 if maior <= 9 else (15 if maior <= 13 else 12)
    for i, it in enumerate(itens):
        c = t.rows[i // porlinha].cells[i % porlinha]
        _sombrear(c, "86C18A")
        p = c.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r = p.add_run(it["valor"].replace(" ", "\u00a0"))
        r.bold = True
        r.font.size = Pt(tam)
        r.font.color.rgb = RGBColor(0x14, 0x2C, 0x46)
        p2 = c.add_paragraph(it["rotulo"])
        p2.alignment = WD_ALIGN_PARAGRAPH.CENTER
        for rr in p2.runs:
            rr.font.size = Pt(9)
        if it.get("legenda"):
            p3 = c.add_paragraph(it["legenda"])
            p3.alignment = WD_ALIGN_PARAGRAPH.CENTER
            for rr in p3.runs:
                rr.font.size = Pt(8)
    doc.add_paragraph()


def gerar_docx(ciclo, inst=None, coletar_graficos=None):
    """Bytes do .docx. `coletar_graficos(numero, titulo, quadro, bloco, png)` recebe cada gráfico (para o pacote)."""
    if inst is None:
        from contas.models import Instituicao
        inst = Instituicao.atual()
    if ciclo.paginas.exists():          # 2.14: o Word com as páginas do RG (mesma diagramação)
        from .exportar_paginas import gerar_docx_paginas
        return gerar_docx_paginas(ciclo, inst, coletar_graficos)
    calc = Calculadora(ciclo)
    doc = Document()
    sec = doc.sections[0]
    sec.page_height, sec.page_width = Cm(29.7), Cm(21.0)
    sec.left_margin = sec.right_margin = Cm(2.5)
    sec.top_margin, sec.bottom_margin = Cm(2.5), Cm(2.0)
    _estilos(doc)
    agora = timezone.localtime()
    versao = (f"Versão final — gerada em {agora:%d/%m/%Y %H:%M}" if ciclo.situacao == ciclo.ENCERRADO
              else f"VERSÃO PRELIMINAR — gerada em {agora:%d/%m/%Y %H:%M} pela Plataforma SiRG")
    _capa(doc, ciclo, inst, versao)
    _sumario(doc)
    cont = Contadores()
    secoes = list(ciclo.secoes.order_by("ordem", "id"))
    blocos = {}
    for b in Bloco.objects.filter(secao__ciclo=ciclo).select_related("quadro").order_by("ordem", "id"):
        blocos.setdefault(b.secao_id, []).append(b)
    primeiro = True
    for cap in [s for s in secoes if s.pai_id is None]:
        if not primeiro:
            doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)
        primeiro = False
        doc.add_paragraph(cap.titulo, style="Heading 1")
        _blocos(doc, calc, blocos.get(cap.pk, []), cont, coletar_graficos)
        for s in [x for x in secoes if x.pai_id == cap.pk]:
            doc.add_paragraph(s.titulo, style="Heading 3" if s.nivel == 2 else "Heading 2")
            _blocos(doc, calc, blocos.get(s.pk, []), cont, coletar_graficos, nivel=s.nivel)
    _rodape_e_cabecalho(doc, ciclo, inst)
    _atualizar_campos_ao_abrir(doc)
    doc.core_properties.title = f"Relatório de Gestão {ciclo.ano}"
    doc.core_properties.author = inst.unidade_gestora_sigla if inst else "SiRG"
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _blocos(doc, calc, blocos, cont, coletar, nivel=1):
    for b in blocos:
        if b.tipo == Bloco.TEXTO:
            if b.titulo:
                doc.add_paragraph(b.titulo, style="Heading 4" if nivel == 2 else "Heading 3")
            from . import campos as CT
            html, _ = renderizar(revisao.base(b.conteudo), calc, marcar=False, campos=CT.valores_do_bloco(b))
            html_para_docx(doc, html)
        elif b.tipo == Bloco.TABELA and b.quadro_id:
            q = calc.quadro_por_id.get(b.quadro_id)
            if q:
                _tabela(doc, A.tabela_quadro(calc, q, b.config), b.titulo or q.titulo, cont)
        elif b.tipo == Bloco.GRAFICO and b.quadro_id:
            q = calc.quadro_por_id.get(b.quadro_id)
            if not q:
                continue
            png, _ = graficos.desenhar(calc, q, b.config, "", "png", largura=7.0)
            if not png:
                continue
            cont.grafico += 1
            _legenda(doc, "Gráfico", cont.grafico, b.titulo or q.titulo)
            doc.add_picture(io.BytesIO(png), width=Cm(15.5))
            doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
            _fonte(doc, q.fonte)
            if coletar:
                coletar(cont.grafico, b.titulo or q.titulo, q, b, png)
        elif b.tipo == Bloco.DESTAQUES:
            _destaques(doc, A.destaques(calc, b.config), b.titulo)


IMAGEM_SRC = re.compile(r"^/ciclos/\d{4}/imagens/(\d+)/$")


def imagem_png_ou_jpg(src):
    """(bytes, largura em px) de uma imagem da plataforma, em formato que o Word aceita."""
    from .models import Imagem
    m = IMAGEM_SRC.match(src or "")
    img = Imagem.objects.filter(pk=int(m.group(1))).first() if m else None
    if img is None:
        return None
    try:
        with img.arquivo.open("rb") as f:
            conteudo = f.read()
    except (FileNotFoundError, OSError, ValueError):
        return None
    if img.tipo not in ("image/png", "image/jpeg", "image/gif"):
        from PIL import Image
        with Image.open(io.BytesIO(conteudo)) as im:
            saida = io.BytesIO()
            im.convert("RGBA").save(saida, "PNG")
            conteudo = saida.getvalue()
    return conteudo, img.largura


# --- pacote para a diagramação --------------------------------------------------------------------
def _nome_arquivo(texto, limite=50):
    t = unicodedata.normalize("NFD", texto or "")
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return re.sub(r"[^A-Za-z0-9]+", "-", t).strip("-")[:limite] or "item"


def gerar_pacote(ciclo, inst=None, usuario=None):
    from openpyxl import Workbook
    from openpyxl.styles import Font

    from . import consistencia, planilhas
    graficos_gerados = []

    def coletar(n, titulo, q, b, png):
        graficos_gerados.append((n, titulo, q, b, png))

    docx = gerar_docx(ciclo, inst, coletar)
    calc = Calculadora(ciclo)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(f"Relatorio-de-Gestao-{ciclo.ano}.docx", docx)
        # gráficos: PNG em alta resolução, SVG editável e os dados de cada um
        wb = Workbook()
        wb.active.title = "Índice"
        wb.active.append(["Gráfico", "Título", "Arquivo", "Quadro de origem", "Fonte"])
        for c in wb.active[1]:
            c.font = Font(bold=True)
        for n, titulo, q, b, png in graficos_gerados:
            nome = f"grafico-{n:02d}-{_nome_arquivo(titulo)}"
            z.writestr(f"graficos/{nome}.png", png)
            svg, _ = graficos.desenhar(calc, q, b.config, "", "svg")
            if svg:
                z.writestr(f"graficos/{nome}.svg", svg)
            categorias, series, tipo, _ = graficos.dados(calc, q, b.config)
            ws = wb.create_sheet(f"Gráfico {n}")
            ws.append([f"Gráfico {n} – {titulo}"])
            ws["A1"].font = Font(bold=True)
            ws.append([f"Tipo sugerido: {dict(graficos.TIPOS).get((b.config or {}).get('tipo', 'barras'))}"
                       f" · Unidade: {dict(q.TIPOS).get(tipo, tipo)}" + (f" · Fonte: {q.fonte}" if q.fonte else "")])
            ws.append([""] + list(categorias))
            for nome_s, vals in series:
                ws.append([nome_s] + [v for v in vals])
            extra = graficos.serie_linha(calc, q, b.config)
            if extra:
                ws.append([f"{extra[0]} (linha, eixo à direita)"] + list(extra[1]))
            ws.column_dimensions["A"].width = 40
            wb["Índice"].append([n, titulo, f"{nome}.png / .svg", q.titulo, q.fonte])
        wb["Índice"].column_dimensions["B"].width = 60
        wb["Índice"].column_dimensions["C"].width = 50
        dados_graficos = io.BytesIO()
        wb.save(dados_graficos)
        z.writestr("graficos/dados-dos-graficos.xlsx", dados_graficos.getvalue())
        # imagens inseridas nos textos (originais, na resolução enviada)
        from .models import Imagem
        usadas = set()
        for b in Bloco.objects.filter(secao__ciclo=ciclo, tipo=Bloco.TEXTO):
            usadas |= {int(x) for x in re.findall(r'src="/ciclos/\d{4}/imagens/(\d+)/"', b.conteudo or "")}
        for img in Imagem.objects.filter(pk__in=usadas).select_related("secao"):
            try:
                with img.arquivo.open("rb") as f:
                    ext = img.arquivo.name.rsplit(".", 1)[-1]
                    onde = _nome_arquivo(img.secao.titulo if img.secao else "texto", 30)
                    z.writestr(f"imagens/{onde}-{img.pk}-{_nome_arquivo(img.nome, 40)}.{ext}", f.read())
            except (FileNotFoundError, OSError):
                continue
        # todos os quadros de dados
        quadros = sorted(calc.quadros.values(), key=lambda q: ((q.secao.pai.ordem if q.secao.pai else 0),
                                                                q.secao.ordem, q.ordem, q.pk))
        z.writestr("dados/todos-os-quadros.xlsx", planilhas.exportar(calc, quadros, usuario) if usuario else
                   planilhas.exportar(calc, quadros, _Anonimo()))
        # avisos para quem diagrama
        pend = consistencia.verificar(ciclo, calc)
        r = consistencia.resumo(pend)
        leia = [f"Relatório de Gestão {ciclo.ano} — pacote para diagramação",
                f"Gerado em {timezone.localtime():%d/%m/%Y %H:%M} pela Plataforma SiRG.", "",
                f"Relatorio-de-Gestao-{ciclo.ano}.docx: texto completo, na ordem, com tabelas e gráficos numerados.",
                "   Ao abrir no Word, aceite atualizar os campos para montar o sumário.",
                "graficos/: cada gráfico em PNG (alta resolução) e SVG (vetorial, editável no Illustrator/Inkscape).",
                "graficos/dados-dos-graficos.xlsx: os números de cada gráfico, para refazê-los no estilo do relatório.",
                "imagens/: as imagens inseridas nos textos (figuras, mapas, fotos), na resolução original.",
                "dados/todos-os-quadros.xlsx: todos os quadros de dados do ciclo.", "",
                "Os números já estão conferidos pela plataforma. Se precisar alterar algum, peça ao setor responsável",
                "que corrija no SiRG e gere um novo pacote — assim o texto, as tabelas e os gráficos continuam iguais.", ""]
        if r["erros"] or r["faltam"]:
            leia.append(f"ATENÇÃO: no momento da geração havia {r['erros']} erro(s) e {r['faltam']} dado(s) a "
                        f"preencher no ciclo. Este pacote NÃO é a versão final.")
        z.writestr("LEIA-ME.txt", "\r\n".join(leia).encode("utf-8-sig"))
    return buf.getvalue()


class _Anonimo:
    is_authenticated = False
    is_active = False
    is_superuser = False
    pk = None
