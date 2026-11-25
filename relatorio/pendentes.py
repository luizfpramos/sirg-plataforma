"""2.22: a conta única do que falta preencher.

Todas as telas (Início, Relatório, O que falta, Quadros de números, Baixar em Word) mostram o mesmo número,
calculado aqui. Um "item a preencher" é:

- uma célula em branco de tabela, ou uma meta do PDI sem situação, justificativa ou evidência
  (as pendências de severidade "falta" de `consistencia.verificar`);
- um número do texto ainda como xxxxx;
- um bloco vazio que o setor precisa escrever (só nos relatórios montados a partir do PDF).

Escopo: quem tem setor (e não é Editor-chefe) vê o que é dos seus setores; o Editor-chefe e quem não tem setor
veem o relatório inteiro. `todas=True` força o relatório inteiro.
"""
from contas import permissoes as P

from . import consistencia
from . import fluxo as F
from .calculo import Calculadora


def escopo_setores(user, todas=False):
    """Siglas dos setores que limitam a conta, ou None (relatório inteiro)."""
    if todas or user is None or P.e_master(user):
        return None
    meus = set(P.setores_ativos(user).values_list("sigla", flat=True))
    return meus or None


def a_preencher(user, ciclo, calc=None, pend=None, todas=False, setor=""):
    """{"total", "numeros", "campos", "blocos", "por_secao": {pk: n}} para a pessoa (ou um setor, pela sigla)."""
    meus = {setor} if setor else escopo_setores(user, todas)
    if pend is None:
        pend = consistencia.verificar(ciclo, calc or Calculadora(ciclo))
    por_secao, numeros = {}, 0
    for p in pend:
        if p.severidade != "falta":
            continue
        if meus is not None and not (meus & {s.sigla for s in p.setores}):
            continue
        por_secao[p.quadro.secao_id] = por_secao.get(p.quadro.secao_id, 0) + 1
        numeros += 1
    campos = blocos = 0
    for s in ciclo.secoes.prefetch_related("setores"):
        if meus is not None and not (meus & {x.sigla for x in s.setores.all()}):
            continue
        c, b = F.campos_vazios_da_secao(s), F.blocos_vazios_da_secao(s)
        if c or b:
            por_secao[s.pk] = por_secao.get(s.pk, 0) + c + b
        campos += c
        blocos += b
    return {"total": numeros + campos + blocos, "numeros": numeros, "campos": campos, "blocos": blocos,
            "por_secao": por_secao}


def secoes_do_fluxo(ciclo):
    """As seções que passam pelo fluxo (enviar, aprovar): todas as subseções e os capítulos que têm texto,
    tabela ou gráfico próprios. É a mesma base em todas as contagens de seções enviadas e aprovadas."""
    from django.db.models import Q
    return ciclo.secoes.filter(Q(pai__isnull=False) | Q(blocos__isnull=False) | Q(quadros__isnull=False)).distinct()
