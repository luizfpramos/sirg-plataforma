"""
Excel: baixar os quadros (para conferência ou para preencher fora da plataforma) e
enviar de volta a planilha preenchida, com prévia das alterações antes de gravar.

Cada aba é um quadro. A coluna A (oculta) guarda o identificador de cada linha e a
linha 4 (oculta) o de cada coluna, para que a importação saiba exatamente onde cada
valor vai — mesmo que a pessoa reordene ou renomeie as abas.
"""
import io
import re
from decimal import Decimal

from openpyxl import Workbook, load_workbook
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

from . import formato
from . import permissoes as RP
from .calculo import TOTAL
from .models import Coluna, Linha, Quadro, Valor

AZUL = "142C46"
F_TITULO = Font(name="Calibri", size=13, bold=True, color=AZUL)
F_CAB = Font(name="Calibri", bold=True, color="FFFFFF")
FILL_CAB = PatternFill("solid", fgColor=AZUL)
FILL_EDITAR = PatternFill("solid", fgColor="FFF6D5")       # amarelo claro: preencher
FILL_TRAVADA = PatternFill("solid", fgColor="EDEDED")
FILL_CALC = PatternFill("solid", fgColor="E6EDF5")
FINA = Side(style="thin", color="C9D4E3")
BORDA = Border(left=FINA, right=FINA, top=FINA, bottom=FINA)
FORMATOS = {Quadro.INTEIRO: "#,##0", Quadro.MOEDA: '"R$" #,##0.00', Quadro.DECIMAL: "#,##0.00",
            Quadro.PERCENTUAL: '0.0"%"'}
MARCA = "SiRG"


def _nome_aba(titulo, usados):
    """Nome de aba que o Excel aceita: até 31 caracteres, sem [ ] * ? / \\ :, sem espaço ou apóstrofo nas
    pontas, sem espaços repetidos, sem repetir (sem diferenciar maiúsculas) e diferente de “History”."""
    def limpo(t):
        t = re.sub(r"[\[\]\*\?/\\:\x00-\x1f]", " ", t)
        t = re.sub(r"\s+", " ", t)
        return t.strip(" '’")
    base = limpo(limpo(titulo)[:28]) or "Quadro"
    if base.lower() == "history":
        base = "Quadro History"
    nome, n = base, 2
    while nome.lower() in usados:
        nome = f"{limpo(base[:25])} ({n})"
        n += 1
    usados.add(nome.lower())
    return nome


def exportar(calc, quadros, user):
    wb = Workbook()
    leia = wb.active
    leia.title = "Leia-me"
    _leia_me(leia, calc.ciclo)
    usados = {"leia-me"}
    for q in quadros:
        ws = wb.create_sheet(_nome_aba(q.titulo, usados))
        _aba_quadro(ws, calc, q, user)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _leia_me(ws, ciclo):
    ws["A1"] = f"{ciclo.titulo} — dados exportados da Plataforma SiRG"
    ws["A1"].font = F_TITULO
    linhas = [
        "Cada aba é um quadro de dados do relatório.",
        "Células AMARELAS: você pode preencher e enviar de volta pela plataforma (botão “Enviar planilha preenchida”).",
        "Células CINZA: anos já publicados (travados) — não são importadas.",
        "Células AZUIS (itálico): calculadas pela plataforma (totais, percentuais e números de outras áreas) — "
        "não precisam ser preenchidas e não são importadas.",
        "Não apague nem mova as linhas e colunas ocultas: elas dizem à plataforma onde cada valor vai.",
        "Ao enviar, a plataforma mostra uma prévia com tudo o que vai mudar antes de gravar.",
    ]
    for i, t in enumerate(linhas, start=3):
        ws.cell(row=i, column=1, value=t)
    ws.column_dimensions["A"].width = 120


def _aba_quadro(ws, calc, q, user):
    cols = calc.colunas_de(q)
    todas = cols + ([TOTAL] if q.coluna_total else [])
    editavel_q = RP.pode_editar_quadro(user, q)
    ws["B1"] = q.titulo
    ws["B1"].font = F_TITULO
    setores = ", ".join(s.sigla for s in q.setores_responsaveis())
    ws["B2"] = f"Responsável: {setores or '—'}" + (f" · Fonte: {q.fonte}" if q.fonte else "")
    ws["B2"].font = Font(italic=True, color="5B6676")
    ws["A1"] = f"{MARCA}:{q.ciclo.ano}:{q.pk}"          # identificação do quadro (coluna A fica oculta)
    # linha 4: identificadores das colunas (oculta); linha 5: cabeçalho
    for j, c in enumerate(todas, start=3):
        ws.cell(row=4, column=j, value="total" if c == TOTAL else f"C:{c.pk}")
        cab = ws.cell(row=5, column=j, value=q.rotulo_total if c == TOTAL else
                      (f"{c.rotulo} (publicado)" if c.travada else c.rotulo))
        cab.font, cab.fill, cab.alignment, cab.border = F_CAB, FILL_CAB, Alignment(horizontal="center"), BORDA
    cab = ws.cell(row=5, column=2, value="")
    cab.fill, cab.border = FILL_CAB, BORDA
    ws.row_dimensions[4].hidden = True
    linha_excel = 6
    sim_nao = DataValidation(type="list", formula1='"Sim,Não"', allow_blank=True)
    for li in calc.linhas_de(q):
        ws.cell(row=linha_excel, column=1, value=f"L:{li.pk}")
        rot = ws.cell(row=linha_excel, column=2, value=li.rotulo + (" (calculada)" if li.calculada else ""))
        rot.border = BORDA
        for j, c in enumerate(todas, start=3):
            r = calc.celula(q, li.chave, c)
            cel = ws.cell(row=linha_excel, column=j)
            _valor_celula(cel, li.tipo, r)
            cel.border = BORDA
            if li.calculada or c == TOTAL:
                cel.fill, cel.font = FILL_CALC, Font(italic=True, color="3B4A63")
            elif c.travada:
                cel.fill = FILL_TRAVADA
            elif editavel_q:
                cel.fill = FILL_EDITAR
                if li.tipo == Quadro.SIM_NAO:
                    sim_nao.add(cel)
            if r.erro:
                cel.comment = Comment(r.erro, "SiRG")
        linha_excel += 1
    if q.linha_total:
        ws.cell(row=linha_excel, column=1, value="total")
        rot = ws.cell(row=linha_excel, column=2, value=q.rotulo_total)
        rot.font, rot.border = Font(bold=True), BORDA
        for j, c in enumerate(todas, start=3):
            cel = ws.cell(row=linha_excel, column=j)
            _valor_celula(cel, q.tipo_valor, calc.celula(q, TOTAL, c))
            cel.fill, cel.font, cel.border = FILL_CALC, Font(bold=True, italic=True), BORDA
        linha_excel += 1
    if q.descricao:
        ws.cell(row=linha_excel + 1, column=2, value=q.descricao).font = Font(italic=True, color="5B6676")
    if sim_nao.sqref:
        ws.add_data_validation(sim_nao)
    ws.column_dimensions["A"].hidden = True
    ws.column_dimensions["B"].width = 52
    for j in range(3, 3 + len(todas)):
        ws.column_dimensions[get_column_letter(j)].width = 16
    ws.freeze_panes = "C6"


def _valor_celula(cel, tipo, r):
    if tipo in (Quadro.TEXTO, Quadro.SIM_NAO):
        cel.value = formato.exibir(tipo, None, r.texto) or None
        return
    if r.numero is not None:
        n = r.numero
        cel.value = int(n) if n == n.to_integral_value() and tipo == Quadro.INTEIRO else float(n)
        cel.number_format = FORMATOS.get(tipo, "#,##0.00")
        cel.alignment = Alignment(horizontal="right")


# --- Importação ----------------------------------------------------------------
class ErroPlanilha(Exception):
    pass


def ler_alteracoes(arquivo, ciclo, user):
    """Lê a planilha e devolve a lista de alterações propostas (sem gravar nada)."""
    try:
        wb = load_workbook(arquivo, data_only=True)
    except Exception:
        raise ErroPlanilha("Não foi possível abrir o arquivo. Envie a planilha .xlsx baixada da plataforma.")
    linhas_db = {li.pk: li for li in Linha.objects.filter(quadro__ciclo=ciclo).select_related(
        "quadro__ciclo", "quadro__secao", "quadro__setor")}
    colunas_db = {c.pk: c for c in Coluna.objects.filter(quadro__ciclo=ciclo)}
    atuais = {(v.linha_id, v.coluna_id): v for v in Valor.objects.filter(linha__quadro__ciclo=ciclo)}
    alteracoes, abas_lidas = [], 0
    for ws in wb.worksheets:
        marca = str(ws["A1"].value or "")
        if not marca.startswith(f"{MARCA}:"):
            continue
        partes = marca.split(":")
        if len(partes) != 3 or partes[1] != str(ciclo.ano):
            raise ErroPlanilha(f"A aba “{ws.title}” é de outro ciclo ({partes[1] if len(partes) > 1 else '?'}). "
                               f"Baixe a planilha deste ciclo ({ciclo.ano}).")
        abas_lidas += 1
        ids_col = {}
        for j in range(3, ws.max_column + 1):
            v = str(ws.cell(row=4, column=j).value or "")
            if v.startswith("C:"):
                ids_col[j] = int(v[2:])
        for i in range(6, ws.max_row + 1):
            marca_l = str(ws.cell(row=i, column=1).value or "")
            if not marca_l.startswith("L:"):
                continue
            li = linhas_db.get(int(marca_l[2:]))
            if li is None or li.calculada:
                continue
            for j, cid in ids_col.items():
                col = colunas_db.get(cid)
                if col is None or col.quadro_id != li.quadro_id or col.travada:
                    continue
                bruto = ws.cell(row=i, column=j).value
                entrada = _texto_da_celula(bruto)
                tipo, casas = li.tipo, li.quadro.casas_decimais
                v = atuais.get((li.pk, col.pk))
                antes = formato.exibir(tipo, v.numero, v.texto, casas) if v else ""
                try:
                    numero, texto = formato.ler(tipo, entrada)
                except formato.EntradaInvalida as ex:
                    alteracoes.append(_alt(li, col, antes, entrada, erro=str(ex)))
                    continue
                if v is not None and v.numero == numero and v.texto == texto:
                    continue
                if v is None and numero is None and not texto:
                    continue
                depois = formato.exibir(tipo, numero, texto, casas)
                erro = "" if RP.pode_editar_celula(user, li, col) else (
                    RP.motivo_bloqueio(user, li.quadro) or "Sem permissão para esta célula.")
                alteracoes.append(_alt(li, col, antes, depois, entrada=formato.para_edicao(tipo, numero, texto, casas),
                                       erro=erro))
    if not abas_lidas:
        raise ErroPlanilha("A planilha não tem nenhuma aba de quadro do SiRG. Baixe o modelo pela plataforma.")
    return alteracoes


def _texto_da_celula(bruto):
    if bruto is None:
        return ""
    if isinstance(bruto, bool):
        return "Sim" if bruto else "Não"
    if isinstance(bruto, (int, float, Decimal)):
        d = Decimal(str(bruto))
        d = d.quantize(Decimal("0.000001")).normalize()
        return formato.numero_br(d, max(0, -d.as_tuple().exponent)) if d != d.to_integral_value() else \
            formato.numero_br(d, 0)
    return str(bruto).strip()


def _alt(li, col, antes, depois, entrada=None, erro=""):
    return {"linha": li.pk, "coluna": col.pk, "quadro": li.quadro.titulo, "quadro_chave": li.quadro.chave,
            "secao": li.quadro.secao.chave, "rotulo": li.rotulo, "coluna_rotulo": col.rotulo,
            "antes": antes, "depois": depois, "entrada": entrada if entrada is not None else depois, "erro": erro}
