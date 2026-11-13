"""
Verificação de consistência de um ciclo — o "relatório de inconsistências".

Tipos de pendência:
  vazio     célula obrigatória não preenchida
  faixa     valor fora do mínimo/máximo da linha
  variacao  variação em relação ao ano anterior acima do limite, sem justificativa
  regra     regra de consistência violada (ex.: soma dos níveis ≠ total)
  formula   fórmula ou regra com erro (referência inexistente etc.)
  divergencia  linha de fonte única com valor digitado diferente do automático
"""
import re
from dataclasses import dataclass, field
from decimal import Decimal

from . import formato
from .calculo import TOTAL, Calculadora
from .models import Quadro, Regra


@dataclass
class Pendencia:
    severidade: str           # erro | aviso | falta (célula ainda não preenchida)
    tipo: str
    quadro: Quadro
    mensagem: str
    linha: object = None
    coluna: object = None
    detalhe: str = ""
    setores: list = field(default_factory=list)
    acao: dict = None         # divergência: {"auto": "6.895", "digitado": "6.900"} (botões corrigir/ignorar)

    @property
    def rotulo_tipo(self):
        return {"vazio": "Não preenchido", "faixa": "Fora da faixa", "variacao": "Variação sem justificativa",
                "regra": "Regra de consistência", "formula": "Erro de fórmula",
                "divergencia": "Digitado ≠ automático"}.get(self.tipo, self.tipo)

    @property
    def ancora(self):
        if self.linha is not None and self.coluna not in (None, TOTAL):
            return f"c-{self.linha.pk}-{self.coluna.pk}"
        return f"quadro-{self.quadro.chave}"


OPS = {"==": lambda a, b, t: abs(a - b) <= t, "!=": lambda a, b, t: abs(a - b) > t,
       "<=": lambda a, b, t: a <= b + t, ">=": lambda a, b, t: a + t >= b,
       "<": lambda a, b, t: a < b, ">": lambda a, b, t: a > b}


def verificar(ciclo, calc=None, quadros=None):
    calc = calc or Calculadora(ciclo)
    alvo = quadros if quadros is not None else list(calc.quadros.values())
    ids = {q.pk for q in alvo}
    out = []
    for q in alvo:
        setores = q.setores_responsaveis()
        cols = calc.colunas_de(q)
        abertas = [c for c in cols if not c.travada]   # anos já publicados não geram pendência
        if q.chave == "pdi_metas":
            out.extend(_metas_pdi(calc, q, abertas))
            continue
        for li in calc.linhas_de(q):
            tipo = li.tipo
            casas = q.casas_decimais
            for c in abertas:
                r = calc.celula(q, li.chave, c)
                if r.erro:
                    out.append(Pendencia("erro", "formula", q, f"{li.rotulo} ({c.rotulo}): {r.erro}", li, c,
                                         setores=setores))
                    continue
                if li.importada:
                    d = calc.divergencia(q, li, c)
                    if d:
                        dig, aut = (formato.exibir(tipo, n, "", casas) for n in d)
                        out.append(Pendencia(   # erro: impede o envio até alguém escolher corrigir ou ignorar
                            "erro", "divergencia", q,
                            f"{li.rotulo} — {c.rotulo}: o valor digitado ({dig}) é diferente do automático ({aut})",
                            li, c, detalhe=f"O automático vem de {_origem(calc, li)}. Corrija (passa a valer {aut}) "
                                           f"ou ignore (fica {dig}).",
                            setores=setores, acao={"auto": aut, "digitado": dig}))
                if not li.calculada and q.obrigatorio and r.vazio:
                    out.append(Pendencia("falta", "vazio", q, f"{li.rotulo} — {c.rotulo}: não preenchido", li, c,
                                         setores=setores))
                    continue
                if r.numero is not None:
                    if li.minimo is not None and r.numero < li.minimo:
                        out.append(Pendencia("erro", "faixa", q, f"{li.rotulo} — {c.rotulo}: "
                                             f"{formato.exibir(tipo, r.numero, '', casas)} é menor que o mínimo "
                                             f"{formato.exibir(tipo, li.minimo, '', casas)}", li, c, setores=setores))
                    if li.maximo is not None and r.numero > li.maximo:
                        out.append(Pendencia("erro", "faixa", q, f"{li.rotulo} — {c.rotulo}: "
                                             f"{formato.exibir(tipo, r.numero, '', casas)} é maior que o máximo "
                                             f"{formato.exibir(tipo, li.maximo, '', casas)}", li, c, setores=setores))
                    if tipo == Quadro.PERCENTUAL and li.minimo is None and li.maximo is None and \
                            not li.calculada and not 0 <= r.numero <= 100:
                        out.append(Pendencia("aviso", "faixa", q, f"{li.rotulo} — {c.rotulo}: "
                                             f"{formato.exibir(tipo, r.numero, '', casas)} está fora de 0% a 100%. "
                                             f"Confira se o número foi digitado como percentual.", li, c, setores=setores))
            out.extend(_variacao(calc, q, li, cols, setores))
    for regra in Regra.objects.filter(ciclo=ciclo, ativa=True, quadro_id__in=ids).select_related("quadro"):
        q = calc.quadro_por_id.get(regra.quadro_id, regra.quadro)
        out.extend(_regra(calc, regra, q))
    ordem = {"erro": 0, "aviso": 1, "falta": 2}
    out.sort(key=lambda p: (ordem.get(p.severidade, 3), p.quadro.secao.pai.ordem if p.quadro.secao.pai else 0,
                            p.quadro.secao.ordem, p.quadro.ordem, p.quadro.pk))
    return out


def _origem(calc, li):
    nomes = []
    for chave in re.findall(r"\b([a-z][a-z0-9_]*)\.[a-z]", li.formula or ""):
        o = calc.quadros.get(chave)
        if o is not None and o.titulo not in nomes:
            siglas = ", ".join(x.sigla for x in o.setores_responsaveis())
            nomes.append(f"“{o.titulo}”" + (f" ({siglas})" if siglas else ""))
    return " e ".join(nomes) or "outro quadro"


SITUACOES_PDI = ("Não iniciado", "Em andamento", "Interrompido", "Concluído")


def _metas_pdi(calc, q, abertas):
    """Metas do PDI: cada unidade informa a situação; justificativa para Não iniciado/Interrompido e evidência
    para Em andamento/Concluído (a regra da planilha da DGDI)."""
    cols = {c.chave: c for c in abertas}
    out = []
    for li in calc.linhas_de(q):
        setores = [li.setor] if li.setor_id else q.setores_responsaveis()
        val = {ch: (calc.celula(q, li.chave, c).texto or "").strip() for ch, c in cols.items()}
        rot = f"Meta {li.ordem}"
        sit = val.get("situacao", "")
        if not sit:
            out.append(Pendencia("falta", "vazio", q, f"{rot}: escolha a situação", li, cols.get("situacao"), setores=setores))
            continue
        if sit not in SITUACOES_PDI:
            out.append(Pendencia("aviso", "faixa", q, f"{rot}: situação “{sit}” fora da lista da planilha "
                                 f"({', '.join(SITUACOES_PDI)})", li, cols.get("situacao"), setores=setores))
        if sit in ("Não iniciado", "Interrompido") and not val.get("justificativa"):
            out.append(Pendencia("falta", "vazio", q, f"{rot}: {sit.lower()} — escreva a justificativa", li,
                                 cols.get("justificativa"), setores=setores))
        if sit in ("Em andamento", "Concluído") and not val.get("evidencia"):
            out.append(Pendencia("falta", "vazio", q, f"{rot}: {sit.lower()} — informe a evidência", li,
                                 cols.get("evidencia"), setores=setores))
    return out


VARIACAO_PADRAO = 50      # %: limite usado nos quadros por ano que não definiram o seu


def _variacao(calc, q, li, cols, setores):
    if q.modo_colunas != Quadro.ANOS or li.tipo in (Quadro.TEXTO, Quadro.SIM_NAO, Quadro.PERCENTUAL):
        return []
    limite = q.variacao_alerta if q.variacao_alerta is not None else VARIACAO_PADRAO
    por_ano = {c.ano: c for c in cols if c.ano is not None}
    c_atual = por_ano.get(q.ciclo.ano)
    c_ant = por_ano.get(q.ciclo.ano - 1)
    if not c_atual or not c_ant or li.calculada:
        return []
    a, b = calc.celula(q, li.chave, c_ant), calc.celula(q, li.chave, c_atual)
    if a.numero is None or b.numero is None or a.numero == 0:
        return []
    pct = (b.numero - a.numero) / abs(a.numero) * 100
    if abs(pct) <= limite:
        return []
    v = calc.valor_preenchido(li, c_atual)
    if v is not None and v.justificativa.strip():
        return []
    sentido = "aumento" if pct > 0 else "redução"
    razao = abs(b.numero / a.numero) if a.numero else 0
    unidade = ""
    if b.numero and (razao <= 0.002 or razao >= 500):
        unidade = (" O valor está umas mil vezes " + ("menor" if razao < 1 else "maior") +
                   ": confira se foi digitado em reais (e não em milhares ou milhões).")
    return [Pendencia("aviso", "variacao", q,
                      f"{li.rotulo}: {sentido} de {formato.numero_br(abs(pct), 1)}% em relação a {c_ant.rotulo} "
                      f"(limite {formato.numero_br(limite, 1)}%).{unidade} Confira o número ou justifique a variação.",
                      li, c_atual, setores=setores)]


def _regra(calc, regra, q):
    if regra.escopo == Regra.ATUAL:
        cols = [c for c in calc.colunas_de(q) if c.ano == q.ciclo.ano] or calc.colunas_de(q)[-1:]
    else:
        cols = [c for c in calc.colunas_de(q) if not c.travada]   # anos publicados ficam de fora
    out = []
    setores = q.setores_responsaveis()
    for c in cols:
        a = calc.avaliar(regra.esquerda, q, c)
        b = calc.avaliar(regra.direita, q, c)
        if a.erro or b.erro:
            out.append(Pendencia("erro", "formula", q, f"Regra “{regra.descricao}”: {a.erro or b.erro}", None, c,
                                 setores=setores))
            continue
        if a.numero is None or b.numero is None:
            continue   # a falta de dado já aparece como "não preenchido"
        if not OPS[regra.operador](a.numero, b.numero, Decimal(regra.tolerancia)):
            va = formato.numero_br(a.numero, _casas(a.numero))
            vb = formato.numero_br(b.numero, _casas(b.numero))
            if regra.operador == "==":
                det = f"{va} ≠ {vb} (diferença de {formato.numero_br(abs(a.numero - b.numero), _casas(a.numero - b.numero))})"
            else:
                det = f"{va} deveria ser {regra.get_operador_display()} {vb}"
            out.append(Pendencia(regra.severidade, "regra", q, f"{regra.descricao} ({c.rotulo})", None, c,
                                 detalhe=det, setores=setores))
    return out


def _casas(n):
    n = Decimal(n).normalize()
    return 0 if n == n.to_integral_value() else min(2, max(0, -n.as_tuple().exponent))


def resumo(pendencias):
    return {"erros": sum(1 for p in pendencias if p.severidade == "erro"),
            "avisos": sum(1 for p in pendencias if p.severidade == "aviso"),
            "faltam": sum(1 for p in pendencias if p.severidade == "falta")}
