"""
Rascunho do texto de um ano a partir do relatório anterior.

O texto publicado no ano anterior vira o ponto de partida, com dois cuidados:
  1. Os números que existem nos quadros (valor do ano anterior) viram números vivos,
     ligados ao ano do relatório: aparecem como [a preencher] até o dado ser digitado.
  2. Figuras e tabelas do relatório anterior viram avisos entre colchetes, para substituir.
Desde a versão 2.2 o texto NÃO vem com trechos destacados: quem atualiza revisa a seção
inteira (o marca-texto continua disponível no editor). Com `destacar=True`, as frases com
número, data ou ano ficam destacadas (<mark class="atualizar" data-orig="frase anterior">).
O texto do relatório anterior fica guardado na seção (Secao.referencia) para consulta.
"""
import re
from html import escape, unescape

from . import formato
from .calculo import TOTAL

BLOCO = re.compile(r"<(p|h3|h4|blockquote|ul|ol|table)\b[^>]*>.*?</\1>", re.S)
FIGURA = re.compile(r"\{\{FIGURA:([^}]*)\}\}")
GRAFICO = re.compile(r"<p>\{\{GRAFICO:([a-z0-9_,]+)\}\}</p>")
TAG = re.compile(r"<[^>]+>")
FIM_FRASE = re.compile(r"(?<=[.!?;])\s+(?=[A-ZÀ-Ý“\"(•])")
NUMERO = re.compile(r"R\$\s?\d[\d.]*(?:,\d+)?(?:\s(?:milhões|milhão|mil)\b)?|\d{1,3}(?:\.\d{3})+(?:,\d+)?%?|\d+,\d+%?|\d+%?")
ESCALA_TXT = re.compile(r"\s(milhões|milhão|mil)$")
ANO = re.compile(r"^(19|20)\d\d$")


def texto_puro(h):
    return re.sub(r"\s+", " ", unescape(TAG.sub("", h))).strip()


# --- índice dos números do ano anterior ------------------------------------------------------
def indice_de_valores(calc, ano_anterior):
    """{texto do número como aparece no relatório: [(ref, chave da coluna)]} para os valores do ano anterior."""
    idx = {}
    for q in calc.quadros.values():
        cols = calc.colunas_de(q)
        c_ant = next((c for c in cols if c.ano == ano_anterior), None)
        if c_ant is None:
            continue
        linhas = [(li.chave, li.tipo, _derivada(li)) for li in calc.linhas_de(q)]
        if q.linha_total:
            linhas.append((TOTAL, q.tipo_valor, False))
        for chave, tipo, derivada in linhas:
            r = calc.celula(q, chave, c_ant)
            if r.erro or r.numero is None:
                continue
            for forma in _formas(tipo, r.numero, q.casas_decimais):
                idx.setdefault(forma, []).append((f"{q.chave}.{chave}", derivada))
    # o mesmo número em vários quadros: fica a origem (linhas que só copiam outro quadro saem)
    final = {}
    for forma, refs in idx.items():
        origem = sorted({r for r, derivada in refs if not derivada}) or sorted({r for r, _ in refs})
        if len(origem) == 1:
            final[forma] = origem[0]
    return final


def _derivada(li):
    """Linha calculada a partir de outro quadro (ex.: grad_numeros.matriculados = ga_matriculados.graduacao)."""
    return bool(li.formula and re.search(r"\b[a-z][a-z0-9_]*\.[a-z]", li.formula))


def _formas(tipo, numero, casas):
    s = formato.exibir(tipo, numero, "", casas)
    formas = {s, s.replace("R$ ", "R$")}
    if s.endswith(",00"):
        formas.add(s[:-3])
    if tipo == "moeda" and numero is not None:
        # como o RG escreve no texto: "R$ 570,87 milhões", "R$ 14 milhões", "R$ 900 mil" (só se o valor gravado
        # é exatamente o que a forma abreviada diz, para não ligar arredondamentos a outro número)
        from decimal import Decimal
        n = Decimal(numero)
        for div, nomes in ((Decimal(10) ** 6, ("milhões", "milhão")), (Decimal(1000), ("mil",))):
            v = n / div
            if v < 1 or v != v.quantize(Decimal("0.01")):
                continue
            txt = formato.numero_br(v, 2)
            for t in {txt, txt[:-3] if txt.endswith(",00") else txt, txt[:-1] if txt.endswith("0") and "," in txt else txt}:
                for nome in nomes:
                    formas |= {f"R$ {t} {nome}", f"R${t} {nome}"}
    return {f for f in formas if f}


# --- frases --------------------------------------------------------------------------------
def _frases(inner):
    """Divide o HTML de um parágrafo em frases, sem cortar tags ao meio."""
    partes, atual = [], ""
    pedacos = FIM_FRASE.split(inner)
    for p in pedacos:
        atual = (atual + " " + p) if atual else p
        if _equilibrado(atual):
            partes.append(atual)
            atual = ""
    if atual:
        partes.append(atual)
    return partes


def _equilibrado(h):
    pilha = []
    for m in re.finditer(r"<(/?)([a-z0-9]+)[^>]*?(/?)>", h):
        fecha, tag, auto = m.group(1), m.group(2), m.group(3)
        if auto or tag in ("br",):
            continue
        if fecha:
            if not pilha or pilha[-1] != tag:
                return False
            pilha.pop()
        else:
            pilha.append(tag)
    return not pilha


_ANTES_ID = re.compile(r"(?:n\.?\s?[º°o]\.?|n[úu]mero|Lei|Decreto|Portaria|Resolu[çc][ãa]o|Instru[çc][ãa]o|art\.?|artigo|"
                       r"inciso|processo|SEI|CNPJ|CEP|p\.|p[áa]gina|vers[ãa]o)\s*$", re.I)


def _e_identificador(texto, ini, fim):
    """O número é parte de um identificador (nº 198/2022, Lei 15.121, art. 70, p. 12) e não um dado?"""
    antes, depois = texto[max(0, ini - 25):ini], texto[fim:fim + 2]
    return bool(_ANTES_ID.search(antes) or depois.startswith("/") or antes.endswith("/") or depois[:1] in "-–" and
                depois[1:2].isdigit())


_SPAN_NUM = re.compile(r'<span class="sirg-num" data-ref="[^"]*">([^<]*)</span>')


def desligar_identificadores(html):
    """Desfaz ligações feitas por engano em números que são identificadores (nº 198/2022 ligado a um dado que
    também vale 198). (html, quantas desfeitas)"""
    n = 0

    def troca(m):
        nonlocal n
        if _e_identificador(m.string, m.start(), m.end()):
            n += 1
            return m.group(1)
        return m.group(0)
    novo = _SPAN_NUM.sub(troca, html or "")
    return novo, n


def _ligar_numeros(frase, idx):
    """Troca, fora das tags, os números que existem nos quadros (ano anterior) por números vivos."""
    def no_texto(seg):
        def troca(m):
            t = m.group(0)
            if ANO.match(t):
                return t
            ref = idx.get(t) or idx.get(t.replace("R$", "R$ "))
            if not ref or re.fullmatch(r"\d{1,2}%?", t):   # números pequenos são ambíguos demais
                return t
            if _e_identificador(m.string, m.start(), m.end()):
                return t      # número de norma, processo ou data (Decisão Normativa nº 198/2022), não um dado
            m_esc = ESCALA_TXT.search(t)
            escala = (' data-escala="mil"' if m_esc.group(1) == "mil" else ' data-escala="mi"') if m_esc else ""
            return f'<span class="sirg-num" data-ref="{ref}"{escala}>{escape(t)}</span>'
        return NUMERO.sub(troca, seg)
    saida, pos = [], 0
    for m in re.finditer(r"<a\b.*?</a>|<[^>]+>", frase, re.S):
        saida.append(no_texto(frase[pos:m.start()]))
        saida.append(m.group(0))
        pos = m.end()
    saida.append(no_texto(frase[pos:]))
    return "".join(saida)


def _precisa_atualizar(frase):
    return bool(re.search(r"\d", texto_puro(frase)))


def _orig(f):
    t = texto_puro(f)
    return t if len(t) <= 390 else t[:388].rsplit(" ", 1)[0] + " …"


def _marcar(conteudo, idx, tudo=False, destacar=False):
    """Conteúdo (inline) de um parágrafo/item: números ligados aos quadros; com `destacar`, frases com
    números (ou todas, se `tudo`) ficam destacadas."""
    if not destacar:
        return _ligar_numeros(conteudo, idx)
    if tudo and texto_puro(conteudo):
        return f'<mark class="atualizar" data-orig="{escape(_orig(conteudo), quote=True)}">{conteudo}</mark>'
    out = []
    for f in _frases(conteudo):
        if _precisa_atualizar(f):
            orig = _orig(f)
            out.append(f'<mark class="atualizar" data-orig="{escape(orig, quote=True)}">{_ligar_numeros(f, idx)}</mark>')
        else:
            out.append(f)
    return " ".join(out)


def _aviso(texto, destacar=False):
    if destacar:
        return f'<p><mark class="atualizar" data-orig="figura">{escape(texto)}</mark></p>'
    return f'<p><em>{escape(texto)}</em></p>'


AVISO = re.compile(r"\[(?:(?:Figura|Tabela) do RG \d{4}|Foto da obra:)")


def contar_avisos(html):
    """Avisos de figura/tabela do relatório anterior que ainda estão no texto."""
    return len(AVISO.findall(texto_puro(html or "")))


# --- documento -----------------------------------------------------------------------------
def rascunho(html_anterior, calc, ano_anterior, paginas="", tudo=False, destacar=False):
    """HTML do rascunho do ano atual a partir do HTML do relatório anterior.
    `destacar`: frases com números ficam em amarelo; com `tudo`, todos os trechos."""
    idx = indice_de_valores(calc, ano_anterior)
    onde = f", p. {paginas}" if paginas else ""
    out = []
    for m in BLOCO.finditer(html_anterior or ""):
        tag, h = m.group(1), m.group(0)
        if GRAFICO.fullmatch(h):
            continue          # o gráfico vivo entra como bloco próprio (ver dados_iniciais/rg2026.py)
        fig = FIGURA.search(h)
        if fig:
            nome = fig.group(1).strip()
            out.append(_aviso(f"[Figura do RG {ano_anterior}{onde}" + (f": {nome}" if nome else "") +
                              f". Insira aqui a figura de {ano_anterior + 1} com o botão Imagem (ou envie-a à "
                              f"diagramação). Depois, apague este aviso.]", destacar))
            continue
        if tag == "table":
            out.append(_aviso(f"[Tabela do RG {ano_anterior}: atualize os valores para {ano_anterior + 1}. "
                              f"Depois, apague este aviso.]", destacar))
            out.append(h)
            continue
        if tag in ("ul", "ol"):
            itens = re.sub(r"<li>(.*?)</li>", lambda x: f"<li>{_marcar(x.group(1), idx, tudo, destacar)}</li>", h, flags=re.S)
            out.append(itens)
            continue
        if tag == "blockquote":
            out.append(re.sub(r"<p>(.*?)</p>", lambda x: f"<p>{_marcar(x.group(1), idx, tudo, destacar)}</p>", h, flags=re.S))
            continue
        abre = h[:h.index(">") + 1]
        inner = h[len(abre):-len(f"</{tag}>")]
        out.append(f"{abre}{_marcar(inner, idx, tudo and tag == 'p', destacar)}</{tag}>")
    return "".join(out)


def referencia(html_anterior, ano_anterior, paginas=""):
    """HTML do relatório anterior para consulta (figuras viram avisos em itálico)."""
    onde = f", p. {paginas}" if paginas else ""

    def fig(m):
        nome = m.group(1).strip()
        return f"<em>[Figura{': ' + escape(nome) if nome else ''} — veja no PDF do RG {ano_anterior}{onde}]</em>"
    html = GRAFICO.sub(lambda m: f"<p><em>[Gráfico — veja no PDF do RG {ano_anterior}{onde}]</em></p>",
                       html_anterior or "")
    return FIGURA.sub(fig, html)


_OBRAS = re.compile(r"<h4>(Obras (?:concluídas|em andamento)[^<]*)</h4>\s*(<table>.*?</table>)", re.S)


def _celulas(tabela):
    out = []
    for tr in re.findall(r"<tr>(.*?)</tr>", tabela, re.S):
        tds = [re.sub(r"<[^>]+>", "", x).strip() for x in re.findall(r"<td>(.*?)</td>", tr, re.S)]
        if len(tds) >= 3:
            out.append(tds[:3])
    return out


def obras_em_cartoes(html):
    """O painel de fotos das obras do RG (que na versão anterior virou tabela) volta a ser um cartão por
    obra: o lugar da foto, o nome, a situação e os recursos, e o valor."""
    def troca(m):
        titulo, andamento = m.group(1).rstrip("."), "andamento" in m.group(1)
        h = f"<h4>{titulo}.</h4>"
        for nome, sit, valor in _celulas(m.group(2)):
            if andamento and not sit.lower().startswith("em andamento"):
                sit = f"Em andamento com recursos: {sit}."
            h += (f"<p><em>[Foto da obra: {nome}. Insira a foto de 2026 com o botão de imagem ou envie-a à "
                  f"diagramação.]</em></p><p><strong>{nome}</strong><br>{sit}<br><strong>{valor}</strong></p>")
        return h
    return _OBRAS.sub(troca, html or "")


# --- tabelas e figuras do ano anterior que o sistema já monta sozinho -------------------------------------
_NUM_OBJ = re.compile(r"^\s*(Tabela|Gr[áa]fico|Figura|Quadro)\s+(\d+)", re.I)
_LEGENDA_E_AVISOS = re.compile(
    r"<(h4|p)>\s*(?:<strong>)?\s*(?P<tipo>Tabela|Gr[áa]fico|Figura|Quadro)\s+(?P<num>\d+)\b(?:(?!</\1>).)*</\1>\s*"
    r"(?P<avisos>(?:<p>(?:(?!</p>).)*\[(?:Figura|Tabela) do RG \d{4}(?:(?!</p>).)*</p>\s*)*)"
    r"(?P<tabela><table>.*?</table>)?", re.S | re.I)


def chave_objeto(titulo):
    """"Gráfico 3 – Dez maiores..." -> "grafico 3" (para comparar com os títulos dos blocos automáticos)."""
    m = _NUM_OBJ.match(titulo or "")
    if not m:
        return None
    tipo = m.group(1).lower().replace("á", "a")
    return f"{tipo} {int(m.group(2))}"


def tirar_duplicados(html, automaticos):
    """Tira do texto a legenda, o aviso “[Figura/Tabela do RG ...]” e a tabela colada do relatório anterior
    quando a mesma tabela ou gráfico (pelo número: “Tabela 1”, “Gráfico 3”) já é montado sozinho pelo sistema.
    Só sai o que tem aviso ou tabela colada embaixo da legenda. (html, quantos tirados)"""
    n = 0

    def troca(m):
        nonlocal n
        chave = chave_objeto(f"{m.group('tipo')} {m.group('num')}")
        if chave not in automaticos or not (m.group("avisos") or m.group("tabela")):
            return m.group(0)
        n += 1
        return ""
    return _LEGENDA_E_AVISOS.sub(troca, html or ""), n


_JA_LIGADO = re.compile(r'<span class="sirg-num".*?</span>|<mark\b.*?</mark>|<a\b.*?</a>|<h\d\b.*?</h\d>', re.S)


def religar(html, idx):
    """Liga, num texto já existente, os números que agora têm forma reconhecida (ex.: "R$ 570,87 milhões"),
    sem mexer nos que já estão ligados, em links, marcas ou títulos. (html, quantos ligados)"""
    saida, pos, n0 = [], 0, (html or "").count("sirg-num")
    for m in _JA_LIGADO.finditer(html or ""):
        saida += [_ligar_numeros(html[pos:m.start()], idx), m.group(0)]
        pos = m.end()
    saida.append(_ligar_numeros((html or "")[pos:], idx))
    novo = "".join(saida)
    return novo, novo.count("sirg-num") - n0
