"""
Números vivos no texto do relatório.

No editor, "Inserir número" grava no texto uma marcação como

    <span class="sirg-num" data-ref="ga_matriculados.total">14.755</span>

Ao exibir ou exportar, o conteúdo é SEMPRE substituído pelo valor atual do quadro
(no ano-base do ciclo, ou na coluna indicada em data-col). Assim a frase da mensagem
da dirigente e a tabela da Gestão Acadêmica nunca mais divergem.
"""
import re
from decimal import Decimal
from html import escape

from . import formato
from .calculo import TOTAL, Resultado
from .models import Quadro

PADRAO = re.compile(r'<span class="sirg-num" data-ref="([a-z0-9_.]+)"(?: data-col="([a-z0-9_]+)")?'
                    r'(?: data-escala="(mi|mil|nmi)")?>(.*?)</span>', re.S)
ESCALAS = {"mi": (Decimal(10) ** 6, "milhões", "milhão"), "mil": (Decimal(1000), "mil", "mil"),
           "nmi": (Decimal(10) ** 6, "", "")}       # nmi: só o número, em milhões (painel de custos: "5,82")


def em_escala(numero, escala):
    """R$ 570.870.000,00 em "mi" -> "R$ 570,87 milhões" (como o RG escreve no texto)."""
    div, plural, singular = ESCALAS[escala]
    v = Decimal(numero) / div
    s = formato.numero_br(v, 2)
    if s.endswith(",00"):
        s = s[:-3]
    if escala == "nmi":
        return s
    return f"R$ {s} {singular if 1 <= abs(v) < 2 else plural}"


def resolver(calc, ref, col_chave=None):
    """(Resultado, tipo, casas, descrição) para uma referência quadro.linha[.coluna]."""
    partes = ref.split(".")
    q = calc.quadros.get(partes[0])
    if q is None:
        return Resultado(erro=f"quadro “{partes[0]}” não existe"), Quadro.INTEIRO, 0, ref
    linha = partes[1] if len(partes) > 1 else ""
    if len(partes) == 3:
        col_chave = partes[2]
    if col_chave == TOTAL:
        col = TOTAL if q.coluna_total else None
    elif col_chave:
        col = calc.coluna_por_chave(q, col_chave)
    else:
        cols = calc.colunas_de(q)
        col = next((c for c in cols if c.ano == calc.ciclo.ano), None) or (cols[-1] if len(cols) == 1 else None)
    if col is None:
        return Resultado(erro=f"indique a coluna de “{q.titulo}”"), q.tipo_valor, q.casas_decimais, ref
    if linha == TOTAL:
        tipo, rot = q.tipo_valor, q.rotulo_total
    else:
        li = calc.linhas.get(q.pk, {}).get(linha)
        if li is None:
            return Resultado(erro=f"linha “{linha}” não existe em “{q.titulo}”"), q.tipo_valor, 0, ref
        tipo, rot = li.tipo, li.rotulo
    r = calc.celula(q, linha, col)
    col_rot = q.rotulo_total if col == TOTAL else col.rotulo
    return r, tipo, q.casas_decimais, f"{q.titulo} › {rot} ({col_rot})"


def renderizar(html, calc, marcar=True, campos=None, user=None, campos_editaveis=False):
    """Troca o conteúdo de cada número vivo pelo valor atual (e o de cada campo “xxxxx” pelo valor do ano, se
    `campos` vier). Com `user`, marca os números que essa pessoa pode preencher ali mesmo. Devolve (html, problemas)."""
    problemas = []

    def troca(m):
        ref, col, escala = m.group(1), m.group(2), m.group(3)
        r, tipo, casas, desc = resolver(calc, ref, col)
        if r.erro or r.vazio:
            problemas.append({"ref": ref, "descricao": desc, "erro": r.erro or "valor ainda não preenchido"})
            texto = "xxxxx" if not r.erro else "[número inválido]"
            classe = "sirg-num pendente"
        else:
            texto = em_escala(r.numero, escala) if escala and r.numero is not None else \
                formato.exibir(tipo, r.numero, r.texto, casas)
            classe = "sirg-num"
        if not marcar:
            return escape(texto)
        attrs = f' data-ref="{ref}"' + (f' data-col="{col}"' if col else "") + (f' data-escala="{escala}"' if escala else "")
        q = calc.quadros.get(ref.split(".")[0])
        setores = ", ".join(s.sigla for s in q.setores_responsaveis()) if q else ""
        if r.erro:
            situacao = r.erro
        elif r.vazio:
            situacao = "ainda não foi preenchido"
        else:
            situacao = ""
        dica = f"Vem de: {desc}" + (f" — preenchido por {setores}" if setores else "") + \
            (f". {situacao[0].upper()}{situacao[1:]}." if situacao else ".")
        extra = ""
        if q is not None:
            extra = _celula_editavel(calc, q, ref, col, user)
            extra += (f' data-quadro="{q.pk}" data-onde="{escape(desc, quote=True)}" data-setor="{escape(setores, quote=True)}"'
                     f' data-secao="{escape(q.secao.titulo, quote=True)}"'
                     f' data-link="/ciclos/{calc.ciclo.ano}/secoes/{q.secao.chave}/?aba=dados#quadro-{q.chave}"'
                     f' data-situacao="{escape(situacao, quote=True)}"')
        return (f'<span class="{classe}"{attrs} title="{escape(dica, quote=True)}"{extra} contenteditable="false">'
                f'{escape(texto)}</span>')

    saida = PADRAO.sub(troca, html or "")
    if campos is not None:
        from . import campos as CT
        saida, vazios = CT.renderizar(saida, campos, marcar=marcar, editavel=campos_editaveis)
    if marcar:
        saida = MARCA.sub(_titulo_marca, saida)
    return saida, problemas


def _celula_editavel(calc, q, ref, col_chave, user):
    """data-l/data-c (e data-pode) quando o número é uma célula que a pessoa pode preencher ali mesmo."""
    if user is None:
        return ""
    from . import permissoes as RP
    partes = ref.split(".")
    meu = ' data-meu="1"' if RP.pode_editar_quadro(user, q) else ""     # a pessoa preenche esse quadro
    if len(partes) < 2 or partes[1] == TOTAL:
        return meu
    li = calc.linhas.get(q.pk, {}).get(partes[1])
    if li is None or (li.calculada and not li.importada):
        return meu
    if len(partes) == 3:
        col_chave = partes[2]
    if col_chave:
        col = calc.coluna_por_chave(q, col_chave)
    else:
        cols = calc.colunas_de(q)
        col = next((c for c in cols if c.ano == calc.ciclo.ano), None) or (cols[-1] if len(cols) == 1 else None)
    if col is None or col == TOTAL:
        return meu
    v = calc.valor_preenchido(li, col)
    edicao = formato.para_edicao(li.tipo, v.numero, v.texto, q.casas_decimais) if v is not None else ""
    pode = RP.pode_editar_celula(user, li, col)
    return (f' data-l="{li.pk}" data-c="{col.pk}" data-edicao="{escape(edicao, quote=True)}"'
            + (' data-pode="1"' if pode else "") + meu)


# Trechos destacados para atualizar: <mark class="atualizar" data-orig="texto do relatório anterior">
MARCA = re.compile(r'<mark class="atualizar"(?: data-orig="([^"]*)")?>')


def _titulo_marca(m):
    from html import unescape
    orig = unescape(m.group(1) or "")
    dica = "Trecho para atualizar: altere o texto ou, se ele continua certo, use “Concluir destaque”."
    if orig and orig != "figura":
        dica += f" No relatório anterior: “{orig}”."
    return m.group(0)[:-1] + f' title="{escape(dica, quote=True)}">'


def contar_marcas(html):
    """Quantos trechos ainda estão destacados para atualizar."""
    return len(MARCA.findall(html or ""))


def referencias(html):
    return [(m.group(1), m.group(2)) for m in PADRAO.finditer(html or "")]


def opcoes_de_numeros(calc):
    """Lista para o seletor "Inserir número": cada linha (e total) de cada quadro, com o valor atual."""
    out = []
    for q in sorted(calc.quadros.values(), key=lambda q: (q.secao.ordem, q.ordem, q.pk)):
        cols = calc.colunas_de(q)
        alvo = next((c for c in cols if c.ano == calc.ciclo.ano), None)
        anterior = next((c for c in cols if c.ano == calc.ciclo.ano - 1), None)
        itens = []
        linhas = [(li.chave, li.rotulo) for li in calc.linhas_de(q)]
        if q.linha_total:
            linhas.append((TOTAL, q.rotulo_total))
        for chave, rotulo in linhas:
            if alvo is not None:
                r, tipo, casas, _ = resolver(calc, f"{q.chave}.{chave}")
                itens.append({"ref": f"{q.chave}.{chave}", "col": "", "rotulo": rotulo, "coluna": alvo.rotulo,
                              "valor": formato.exibir(tipo, r.numero, r.texto, casas) if not r.erro else ""})
                if anterior is not None:      # o ano anterior, para comparações ("em 2025 eram ...")
                    r, tipo, casas, _ = resolver(calc, f"{q.chave}.{chave}", anterior.chave)
                    itens.append({"ref": f"{q.chave}.{chave}", "col": anterior.chave, "rotulo": rotulo,
                                  "coluna": anterior.rotulo,
                                  "valor": formato.exibir(tipo, r.numero, r.texto, casas) if not r.erro else ""})
            else:
                for c in cols + ([TOTAL] if q.coluna_total else []):
                    ck = TOTAL if c == TOTAL else c.chave
                    r, tipo, casas, _ = resolver(calc, f"{q.chave}.{chave}", ck)
                    itens.append({"ref": f"{q.chave}.{chave}", "col": ck, "rotulo": rotulo,
                                  "coluna": q.rotulo_total if c == TOTAL else c.rotulo,
                                  "valor": formato.exibir(tipo, r.numero, r.texto, casas) if not r.erro else ""})
        out.append({"quadro": q.titulo, "chave": q.chave, "secao": q.secao.titulo, "secao_chave": q.secao.chave,
                    "itens": itens})
    return out
