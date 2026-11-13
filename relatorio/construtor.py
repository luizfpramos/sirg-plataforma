"""Atalhos para montar estrutura e quadros por código (carga inicial e testes)."""
from decimal import Decimal

from contas.models import Setor

from .models import Coluna, Linha, Quadro, Regra, Secao, Valor
from .servicos import sincronizar_colunas_de_anos


def setor(sigla):
    return Setor.objects.get(sigla=sigla) if sigla else None


def secao(ciclo, chave, titulo, pai=None, ordem=0, setores=(), orientacao=""):
    s = Secao.objects.create(ciclo=ciclo, chave=chave, titulo=titulo, pai=pai, ordem=ordem, orientacao=orientacao)
    if setores:
        s.setores.set(Setor.objects.filter(sigla__in=setores))
    return s


def quadro(sec, chave, titulo, linhas, *, valores=None, modo=Quadro.ANOS, anos=5, colunas=None, tipo=Quadro.INTEIRO,
           casas=2, setor_sigla=None, total=False, coluna_total=False, rotulo_total="Total", descricao="", fonte="",
           obrigatorio=True, variacao=None, ordem=None, travar_passado=False):
    """
    linhas:  [(chave, rótulo)] ou [(chave, rótulo, fórmula)] ou dicts com mais opções.
    valores: {chave_linha: [v_coluna1, v_coluna2, ...]} na ordem das colunas (None = vazio).
    colunas: para modo categorias, [(chave, rótulo)].
    """
    q = Quadro.objects.create(
        ciclo=sec.ciclo, secao=sec, chave=chave, titulo=titulo, descricao=descricao, fonte=fonte,
        setor=setor(setor_sigla), tipo_valor=tipo, casas_decimais=casas, modo_colunas=modo, anos_exibidos=anos,
        linha_total=total, coluna_total=coluna_total, rotulo_total=rotulo_total, obrigatorio=obrigatorio,
        variacao_alerta=variacao, ordem=ordem if ordem is not None else sec.quadros.count() + 1)
    for i, li in enumerate(linhas, start=1):
        if isinstance(li, dict):
            dados = {"ordem": i, **li}
        else:
            dados = {"ordem": i, "chave": li[0], "rotulo": li[1], "formula": li[2] if len(li) > 2 else ""}
        Linha.objects.create(quadro=q, **dados)
    if modo == Quadro.ANOS:
        sincronizar_colunas_de_anos(q)
        if travar_passado:
            q.colunas.filter(ano__lt=q.ciclo.ano).update(travada=True)
    else:
        for i, (ch, rot) in enumerate(colunas or [("valor", "Valor")], start=1):
            Coluna.objects.create(quadro=q, ordem=i, chave=ch, rotulo=rot)
    if valores:
        preencher(q, valores)
    return q


def preencher(q, valores):
    cols = list(q.colunas.order_by("ordem", "id"))
    linhas = {li.chave: li for li in q.linhas.all()}
    for chave, lista in valores.items():
        li = linhas[chave]
        for c, v in zip(cols, lista):
            if v is None:
                continue
            if isinstance(v, str) and q.tipo_valor in (Quadro.TEXTO, Quadro.SIM_NAO):
                Valor.objects.create(linha=li, coluna=c, texto=v)
            else:
                Valor.objects.create(linha=li, coluna=c, numero=Decimal(str(v)))


def regra(q, descricao, esquerda, direita, operador="==", severidade=Regra.ERRO, escopo=Regra.ATUAL, tolerancia=0):
    return Regra.objects.create(ciclo=q.ciclo, quadro=q, descricao=descricao, esquerda=esquerda, operador=operador,
                                direita=direita, severidade=severidade, escopo=escopo, tolerancia=tolerancia)
