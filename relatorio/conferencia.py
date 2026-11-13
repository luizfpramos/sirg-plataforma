"""
Planilha de conferência das conexões entre os números e o relatório.

Cada número que aparece no relatório vem de um quadro de Preencher os números. As ligações foram montadas a
partir do RG do ano anterior; esta planilha lista TODAS, lado a lado com o valor do ano anterior que está no
sistema, para que uma pessoa confira contra o PDF publicado marcando “Confere?” linha a linha:

  1. Números no texto: cada número ligado (o trecho em volta, o quadro e a linha a que está ligado e o valor);
  2. Tabelas e gráficos: cada tabela, gráfico e painel, com o quadro de origem e os valores do ano anterior;
  3. Quadros: cada linha de cada quadro, com o valor do ano anterior e onde aparece no relatório.
"""
import io
import re
from html import unescape

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

from . import formato, revisao
from .apresentacao import origens_do_bloco, usos_dos_quadros
from .calculo import TOTAL
from .models import Bloco, Quadro
from .rascunho import _formas

AZUL = "142C46"
F_CAB = Font(bold=True, color="FFFFFF")
FILL_CAB = PatternFill("solid", fgColor=AZUL)
FILL_CONF = PatternFill("solid", fgColor="FFF6D5")
FILL_DIF = PatternFill("solid", fgColor="FDE2E1")
SPAN = re.compile(r'<span class="sirg-num" data-ref="([a-z0-9_]+)\.([a-z0-9_]+)"[^>]*>(.*?)</span>', re.S)
TAG = re.compile(r"<[^>]+>")


def _puro(h):
    return re.sub(r"\s+", " ", unescape(TAG.sub(" ", h or ""))).strip()


def _ordem(s):
    return ((s.pai.ordem if s.pai_id else s.ordem), (s.ordem if s.pai_id else -1))


def _pagina(secao):
    return (secao.referencia_fonte or "").replace("RG ", "").replace(", p.", " p.") or "—"


def _valor(calc, q, linha, col):
    if col is None:
        return None, ""
    r = calc.celula(q, linha, col)
    if r.erro:
        return None, f"(erro: {r.erro})"
    tipo = q.tipo_valor if linha == TOTAL else next((li.tipo for li in calc.linhas_de(q) if li.chave == linha), q.tipo_valor)
    return r.numero, formato.exibir(tipo, r.numero, r.texto, q.casas_decimais)


def _col_ano(calc, q, ano):
    return next((c for c in calc.colunas_de(q) if c.ano == ano), None)


def _rotulo_linha(calc, q, chave):
    if chave == TOTAL:
        return q.rotulo_total or "Total"
    return next((li.rotulo for li in calc.linhas_de(q) if li.chave == chave), chave)


def _cabecalho(ws, titulos, larguras):
    for j, (t, w) in enumerate(zip(titulos, larguras), start=1):
        c = ws.cell(row=1, column=j, value=t)
        c.font, c.fill = F_CAB, FILL_CAB
        c.alignment = Alignment(vertical="center", wrap_text=True)
        ws.column_dimensions[get_column_letter(j)].width = w
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(titulos))}1"


def _confere(ws, col, n_linhas):
    if n_linhas < 2:
        return
    dv = DataValidation(type="list", formula1='"Sim,Não"', allow_blank=True)
    letra = get_column_letter(col)
    dv.add(f"{letra}2:{letra}{n_linhas}")
    ws.add_data_validation(dv)
    for i in range(2, n_linhas + 1):
        ws.cell(row=i, column=col).fill = FILL_CONF


def gerar(ciclo, calc):
    ano_ant = ciclo.ano - 1
    wb = Workbook()
    leia = wb.active
    leia.title = "Leia-me"
    textos = [
        f"Conferência das conexões — {ciclo.titulo}",
        "",
        f"Esta planilha lista todas as ligações entre os números de Preencher os números e o relatório, com o valor de "
        f"{ano_ant} que está no sistema. Confira cada linha contra o RG {ano_ant} publicado (a página está indicada) e "
        f"marque a coluna amarela “Confere?” com Sim ou Não. Em “Não”, explique em “Observação”.",
        "",
        "Aba 1 — Números no texto: cada número do texto ligado a um quadro. Confira se o número fala da mesma coisa "
        "que a linha do quadro (ex.: “alunos matriculados” ligado a “Alunos matriculados”). A coluna “Iguais?” já diz "
        "se o valor no sistema é o mesmo que estava escrito.",
        f"Aba 2 — Tabelas e gráficos: cada tabela, gráfico e painel, com o quadro de origem e os valores de {ano_ant}. "
        "Confira se é a mesma tabela/gráfico da página indicada e se os valores batem.",
        f"Aba 3 — Quadros: cada linha de cada quadro com o valor de {ano_ant} e onde ela aparece no relatório.",
        f"Aba 4 — Números não ligados: números do texto que NÃO vêm de quadro (ficaram como no RG {ano_ant}). "
        f"Cada um precisa ser atualizado à mão por quem escreve a seção; marque “Atualizado?”.",
        "",
        f"Quadros com só o ano do relatório (ou por categorias) não guardam {ano_ant}: aparece “sem {ano_ant} no "
        "sistema” e a conferência é direto no PDF.",
    ]
    for i, t in enumerate(textos, start=1):
        c = leia.cell(row=i, column=1, value=t)
        c.alignment = Alignment(wrap_text=True, vertical="top")
    leia["A1"].font = Font(bold=True, size=13, color=AZUL)
    leia.column_dimensions["A"].width = 120

    # 1. números no texto ---------------------------------------------------------------------------------
    ws = wb.create_sheet("1. Números no texto")
    _cabecalho(ws, ["Seção", f"Página (RG {ano_ant})", "Trecho do texto", "Número no texto", "Ligado ao quadro",
                    "Linha", "Setor", f"Valor {ano_ant} no sistema", "Iguais?", "Confere?", "Observação"],
               [28, 12, 70, 16, 34, 30, 10, 18, 9, 10, 30])
    n = 1
    blocos = Bloco.objects.filter(secao__ciclo=ciclo, tipo=Bloco.TEXTO).select_related("secao", "secao__pai")
    for b in sorted(blocos, key=lambda b: (_ordem(b.secao), b.ordem, b.pk)):
        html = revisao.base(b.conteudo or "")
        for m in SPAN.finditer(html):
            qch, lch, txt = m.group(1), m.group(2), _puro(m.group(3))
            q = calc.quadros.get(qch)
            antes = _puro(html[max(0, m.start() - 600):m.start()])[-140:]
            depois = _puro(html[m.end():m.end() + 400])[:90]
            trecho = f"…{antes} [{txt}] {depois}…"
            if q is None:
                linha, setor, valor, iguais = lch, "", "(quadro não existe)", "Não"
            else:
                num, valor = _valor(calc, q, lch, _col_ano(calc, q, ano_ant))
                tipo = next((li.tipo for li in calc.linhas_de(q) if li.chave == lch), q.tipo_valor)
                formas = _formas(tipo, num, q.casas_decimais) if num is not None else set()
                iguais = "Sim" if txt in formas or txt.replace("R$", "R$ ") in formas else "Não"
                linha = _rotulo_linha(calc, q, lch)
                setor = ", ".join(s.sigla for s in q.setores_responsaveis())
            n += 1
            for j, v in enumerate([b.secao.titulo, _pagina(b.secao), trecho, txt, q.titulo if q else qch, linha, setor,
                                   valor, iguais], start=1):
                ws.cell(row=n, column=j, value=v).alignment = Alignment(wrap_text=True, vertical="top")
            if iguais == "Não":
                ws.cell(row=n, column=9).fill = FILL_DIF
    _confere(ws, 10, n)

    # 2. tabelas e gráficos -------------------------------------------------------------------------------
    ws = wb.create_sheet("2. Tabelas e gráficos")
    _cabecalho(ws, ["Seção", f"Página (RG {ano_ant})", "Tipo", "Título no relatório", "Quadro de origem", "Setor",
                    "O que usa", f"Valores de {ano_ant} no sistema", "Confere?", "Observação"],
               [28, 12, 10, 44, 34, 10, 26, 70, 10, 30])
    n = 1
    tipos = {Bloco.TABELA: "Tabela", Bloco.GRAFICO: "Gráfico", Bloco.DESTAQUES: "Painel"}
    blocos = Bloco.objects.filter(secao__ciclo=ciclo).exclude(tipo=Bloco.TEXTO).select_related("secao", "secao__pai")
    for b in sorted(blocos, key=lambda b: (_ordem(b.secao), b.ordem, b.pk)):
        cfg = b.config or {}
        origens = origens_do_bloco(calc, b)
        if b.tipo == Bloco.DESTAQUES:
            partes = []
            from .texto import resolver
            for it in cfg.get("itens", []):
                ref = it.get("ref") or ""
                q = calc.quadros.get(ref.split(".")[0])
                col = it.get("col") or None
                sem_ant = False
                if q is not None and len(ref.split(".")) < 3 and not col:
                    c_ant = _col_ano(calc, q, ano_ant)
                    col = c_ant.chave if c_ant is not None else None
                    sem_ant = c_ant is None
                r, tipo, casas, desc = resolver(calc, ref, col)
                v = f"(sem {ano_ant} no sistema)" if sem_ant else \
                    "—" if (r.erro or r.vazio) else formato.exibir(tipo, r.numero, r.texto, casas)
                rot = it.get("rotulo") or it.get("legenda") or ""
                partes.append(f"{rot + ' — ' if rot else ''}{desc}: {v}")
            usa, valores = f"{len(partes)} números", "\n".join(partes)
        else:
            q = calc.quadro_por_id.get(b.quadro_id)
            if q is None:
                continue
            cols = calc.colunas_de(q)
            escolhidas = [c for c in cols if not cfg.get("colunas") or c.chave in cfg["colunas"]]
            usa = ", ".join(c.rotulo for c in escolhidas)
            if len(escolhidas) > 4:
                usa = f"{escolhidas[0].rotulo} a {escolhidas[-1].rotulo}"
            c_ant = _col_ano(calc, q, ano_ant)
            linhas = [li for li in calc.linhas_de(q) if not cfg.get("linhas") or li.chave in cfg["linhas"]]
            if c_ant is not None:
                valores = "\n".join(f"{li.rotulo}: {_valor(calc, q, li.chave, c_ant)[1] or '—'}" for li in linhas)
                if q.linha_total:
                    valores += f"\n{q.rotulo_total or 'Total'}: {_valor(calc, q, TOTAL, c_ant)[1] or '—'}"
            else:
                valores = (f"(quadro só com o ano do relatório: o valor de {ano_ant} não fica no sistema; "
                           f"confira no PDF) {q.descricao or ''}").strip()
        n += 1
        quadros_txt = ", ".join(o["quadro"].titulo for o in origens)
        setores = ", ".join(sorted({s.sigla for o in origens for s in o["setores"]}))
        for j, v in enumerate([b.secao.titulo, _pagina(b.secao), tipos.get(b.tipo, b.tipo), b.titulo or "",
                               quadros_txt, setores, usa, valores], start=1):
            ws.cell(row=n, column=j, value=v).alignment = Alignment(wrap_text=True, vertical="top")
    _confere(ws, 9, n)

    # 3. quadros --------------------------------------------------------------------------------------------
    ws = wb.create_sheet("3. Quadros")
    _cabecalho(ws, ["Seção", "Quadro", "Setor", "Fonte", "Linha", f"Valor {ano_ant}", "Onde aparece no relatório",
                    "Confere?", "Observação"], [28, 36, 10, 30, 34, 18, 50, 10, 30])
    usos = usos_dos_quadros(ciclo, calc)
    n = 1
    for q in sorted(calc.quadros.values(), key=lambda q: (_ordem(q.secao), q.ordem, q.pk)):
        u = usos.get(q.chave, {})
        onde = [f"{x['nome']} ({x['secao'].titulo})" for x in u.get("blocos", [])]
        onde += [f"texto de {s.titulo}" for s in u.get("textos", [])]
        onde += [f"cálculo em {x.titulo}" for x in u.get("calculos", [])]
        c_ant = _col_ano(calc, q, ano_ant)
        setor = ", ".join(s.sigla for s in q.setores_responsaveis())
        linhas = [(li.chave, li.rotulo) for li in calc.linhas_de(q)] + ([(TOTAL, q.rotulo_total or "Total")] if q.linha_total else [])
        for k, (lch, rot) in enumerate(linhas):
            n += 1
            val = _valor(calc, q, lch, c_ant)[1] if c_ant is not None else f"(sem {ano_ant} no sistema)"
            for j, v in enumerate([q.secao.titulo, q.titulo, setor, q.fonte or "", rot, val,
                                   "; ".join(onde) if k == 0 else ""], start=1):
                ws.cell(row=n, column=j, value=v).alignment = Alignment(wrap_text=True, vertical="top")
    _confere(ws, 8, n)

    # 4. números do texto que NÃO estão ligados a quadro: precisam ser atualizados à mão ----------------------
    from .rascunho import ANO, NUMERO, _e_identificador
    ws = wb.create_sheet("4. Números não ligados")
    _cabecalho(ws, ["Seção", f"Página (RG {ano_ant})", "Trecho do texto", "Número", "Atualizado?", "Observação"],
               [28, 12, 90, 16, 12, 30])
    n = 1
    blocos = Bloco.objects.filter(secao__ciclo=ciclo, tipo=Bloco.TEXTO).select_related("secao", "secao__pai")
    for b in sorted(blocos, key=lambda b: (_ordem(b.secao), b.ordem, b.pk)):
        sem_ligados = SPAN.sub(lambda m: "§" * len(_puro(m.group(3))), revisao.base(b.conteudo or ""))
        texto = _puro(sem_ligados)
        for m in NUMERO.finditer(texto):
            t = m.group(0)
            if ANO.match(t) or re.fullmatch(r"\d{1,2}", t) or _e_identificador(texto, m.start(), m.end()):
                continue
            ini = texto.rfind(" ", 0, m.start()) + 1
            fim = texto.find(" ", m.end())
            token = texto[ini:fim if fim >= 0 else len(texto)]
            if re.search(r"https?:|www\.|@|\.htm|\d[-–/.]\d*$|^\D*\d+[-–]", token) and not t.startswith("R$") \
                    or re.fullmatch(r"\d{4,}", t) or re.search(r"(?:c[óo]digo|Av\.|Rua|CEP|CNPJ|telefone|tel\.)\s*:?\s*\(?$",
                                                             texto[max(0, m.start() - 15):m.start()], re.I):
                continue      # endereço, código, telefone, link: não é dado do relatório
            n += 1
            trecho = "…" + texto[max(0, m.start() - 110):m.start()] + f"[{t}]" + texto[m.end():m.end() + 70] + "…"
            for j, v in enumerate([b.secao.titulo, _pagina(b.secao), trecho.replace("§", "#"), t], start=1):
                ws.cell(row=n, column=j, value=v).alignment = Alignment(wrap_text=True, vertical="top")
    _confere(ws, 5, n)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def contagem(ciclo, calc):
    """Quantas ligações existem (para a tela)."""
    n_texto = sum(len(SPAN.findall(b.conteudo or "")) for b in Bloco.objects.filter(secao__ciclo=ciclo, tipo=Bloco.TEXTO))
    n_blocos = Bloco.objects.filter(secao__ciclo=ciclo).exclude(tipo=Bloco.TEXTO).count()
    return {"texto": n_texto, "blocos": n_blocos, "quadros": len(calc.quadros)}
