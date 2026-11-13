"""
Números do texto que mudam todo ano (“xxxxx”).

O texto do relatório parte do RG do ano anterior. Cada número que é um dado do ano (quantidades, valores em
R$, percentuais) vira um campo:

    <span class="sirg-campo" data-c="k3x9a1" data-orig="R$ 574,00">R$ 574,00</span>

`data-orig` guarda como o número estava escrito no relatório anterior (com R$, %, “milhões”). O valor do ano
fica no banco (CampoTexto) e é preenchido clicando no número, no documento. Enquanto ninguém preenche, aparece
“xxxxx” (com o R$ ou o % do original), na tela, na leitura e no Word.

Não viram campo: anos (2025), números de normas e processos (Lei nº 11.892, Decisão Normativa nº 198/2022),
páginas, datas (27 de março), ordinais (1º), itens (OD-2.1, Meta 3), horários, números em títulos, links e os
números já ligados às tabelas (sirg-num), que têm o próprio valor.
"""
import random
import re
import string
from decimal import Decimal
from html import escape, unescape

from . import formato
from .rascunho import NUMERO, ANO

CAMPO = re.compile(r'<span class="sirg-campo" data-c="([a-z0-9]+)" data-orig="([^"]*)"[^>]*>(.*?)</span>', re.S)
VAZIO = "xxxxx"

# tabelas coladas do relatório anterior são, em geral, de metodologia (matriz de riscos, escalas): ficam como estão
_PROTEGIDO = re.compile(r'<span class="sirg-(?:num|campo)".*?</span>|<a\b.*?</a>|<h[1-6]\b.*?</h[1-6]>'
                        r'|<table\b.*?</table>|<sup\b.*?</sup>|<(ins|del)\b.*?</\1>|<[^>]+>', re.S)
_ANTES_ID = re.compile(
    r"(?:n\.?\s?[º°o]\.?|n[úu]mero|Lei|Decreto|Portaria|Resolu[çc][ãa]o|Instru[çc][ãa]o|Delibera[çc][ãa]o|"
    r"Ac[óo]rd[ãa]o|Decis[ãa]o|art\.?|artigo|inciso|par[áa]grafo|§|processo|SEI|CNPJ|CPF|CEP|p\.|pp\.|p[áa]ginas?|"
    r"vers[ãa]o|Tabela|Gr[áa]fico|Figura|Quadro|Cap[íi]tulo|se[çc][ãa]o|item|anexo|ap[êe]ndice|ODS|OD|OE|meta|"
    r"objetivo|eixo|fase|etapa|edi[çc][ãa]o|turma|sala|bloco|pr[ée]dio|campus|unidade|n[íi]vel|grau|nota|conceito|"
    r"semestre|elemento|lote|preg[ãa]o|contrato|telefone|ramal|tel\.|c[óo]digo|c[óo]d\.|registro|INEP|e-MEC|CNES|ISO)\s*$", re.I)
_MESES = r"(?:janeiro|fevereiro|mar[çc]o|abril|maio|junho|julho|agosto|setembro|outubro|novembro|dezembro)"
_ESCALA = re.compile(r"\s(milhões|milhão|mil)$")


def _e_dado(texto, ini, fim, t):
    """O número t (texto[ini:fim]) é um dado do ano, que deve virar campo?"""
    if ANO.match(t):
        return False
    antes, depois = texto[max(0, ini - 30):ini], texto[fim:fim + 16]
    if _ANTES_ID.search(antes):
        return False
    if depois[:1] in ("º", "ª", "°", "/", ")") or antes.endswith(("/", "nº", "n.º", "Nº")):
        return False
    if re.match(r"[.,]\d", depois) or re.search(r"\d[.,]$", antes):        # 3.2.1, versões, itens
        return False
    if re.match(r"[-–]\d", depois) or re.search(r"\d[-–]$", antes):        # intervalos de anos/números de norma
        return False
    if re.search(r"[A-Za-zÀ-ÿ][-–]?$", antes) or re.match(r"[A-Za-zÀ-ÿ]", depois):   # OD-2, ODS4, 4G, 12h
        return False
    if re.match(r"\s?h(?:\d|\b)", depois) or re.match(r"\s?(?:min|horas?)\b", depois):
        return False
    if re.match(r"\s+de\s+" + _MESES, depois, re.I) or re.match(r"[º°]?\s+de\s+" + _MESES, depois, re.I):
        return False
    return True


def _nova_chave(usadas):
    while True:
        k = "".join(random.choices(string.ascii_lowercase + string.digits, k=8))
        if k not in usadas:
            usadas.add(k)
            return k


def camposificar(html, valor_inicial=None):
    """Troca os números-dado do texto por campos. `valor_inicial(t)` (opcional) devolve o número já escrito que
    deve ficar como valor do campo (texto já atualizado à mão) ou None (fica xxxxx).
    Devolve (html, [(chave, numero_inicial)])."""
    usadas = set(re.findall(r'data-c="([a-z0-9]+)"', html or ""))
    novos = []

    def no_texto(seg):
        def troca(m):
            t = m.group(0)
            if not _e_dado(m.string, m.start(), m.end(), t):
                return t
            chave = _nova_chave(usadas)
            ini = valor_inicial(t) if valor_inicial else None
            novos.append((chave, ini))
            return (f'<span class="sirg-campo" data-c="{chave}" data-orig="{escape(t, quote=True)}">'
                    f'{escape(t)}</span>')
        return NUMERO.sub(troca, seg)

    saida, pos = [], 0
    for m in _PROTEGIDO.finditer(html or ""):
        trecho = (html or "")[pos:m.start()]
        saida.append(no_texto(unescape(trecho)) if "&" not in trecho else _sem_entidades(trecho, no_texto))
        saida.append(m.group(0))
        pos = m.end()
    resto = (html or "")[pos:]
    saida.append(no_texto(resto) if "&" not in resto else _sem_entidades(resto, no_texto))
    return "".join(saida), novos


def _sem_entidades(trecho, f):
    # mantém &amp; &lt; etc. como estão: só procura números fora das entidades
    partes = re.split(r"(&[a-zA-Z#0-9]+;)", trecho)
    return "".join(p if p.startswith("&") and p.endswith(";") else f(p) for p in partes)


# --- forma do número ------------------------------------------------------------------------------
def forma(orig):
    """("R$ ", " milhões", casas, escala) a partir de como o número estava escrito."""
    orig = unescape(orig or "").strip()
    prefixo = "R$ " if orig.startswith("R$") else ""
    resto = orig[2:].strip() if prefixo else orig
    sufixo, escala = "", None
    m = _ESCALA.search(resto)
    if m:
        escala = m.group(1)
        sufixo = " " + escala
        resto = resto[:m.start()].strip()
    if resto.endswith("%"):
        sufixo = "%" + sufixo
        resto = resto[:-1].strip()
    casas = len(resto.split(",")[1]) if "," in resto else 0
    return prefixo, sufixo, casas, escala


def numero_original(orig):
    p, s, casas, escala = forma(orig)
    try:
        t = unescape(orig).replace("R$", "")
        t = _ESCALA.sub("", t.strip())
        return formato.ler_numero(t.replace("%", ""))
    except formato.EntradaInvalida:
        return None


def exibir(orig, numero):
    """Como o campo aparece: no mesmo formato do original (R$, %, casas, milhões), ou xxxxx."""
    prefixo, sufixo, casas, escala = forma(orig)
    if numero is None:
        return f"{prefixo}{VAZIO}{sufixo}"
    s = formato.numero_br(Decimal(numero), casas)
    if escala in ("milhões", "milhão"):
        sufixo = sufixo.replace(escala, "milhão" if 1 <= abs(Decimal(numero)) < 2 else "milhões")
    return f"{prefixo}{s}{sufixo}"


def ler(orig, texto):
    """Número digitado no campo (aceita “1.234”, “1234,5”, “R$ 1.234,56”, “45%”)."""
    texto = (texto or "").strip()
    if not texto:
        return None
    texto = texto.replace("R$", "")
    texto = _ESCALA.sub("", texto.strip())
    return formato.ler_numero(texto.replace("%", ""))


def renderizar(html, valores, marcar=True, editavel=False):
    """Troca o conteúdo de cada campo pelo valor do ano (ou xxxxx). `valores`: {chave: Decimal|None}.
    Devolve (html, quantos vazios)."""
    vazios = 0

    def troca(m):
        nonlocal vazios
        chave, orig = m.group(1), unescape(m.group(2))
        n = valores.get(chave)
        texto = exibir(orig, n)
        if n is None:
            vazios += 1
        if not marcar:
            return escape(texto)
        classe = "sirg-campo" + (" vazio" if n is None else "") + (" pode" if editavel else "")
        dica = f"No relatório anterior: {orig}" + (". Clique para preencher." if editavel and n is None else ".")
        return (f'<span class="{classe}" data-c="{chave}" data-orig="{escape(orig, quote=True)}" '
                f'title="{escape(dica, quote=True)}" contenteditable="false">{escape(texto)}</span>')
    return CAMPO.sub(troca, html or ""), vazios


def chaves(html):
    return [m.group(1) for m in CAMPO.finditer(html or "")]


def valores_do_bloco(bloco):
    return {c.chave: c.numero for c in bloco.campos.all()}
