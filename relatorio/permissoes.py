"""Quem pode alterar o quê no relatório, conforme a situação do ciclo."""
from contas import permissoes as P

from .models import Ciclo, Secao


def pode_estruturar(user):
    """Montar ciclos, seções, quadros, linhas, colunas e regras."""
    return P.e_admin(user)


def pode_editar_quadro(user, quadro):
    """Pode preencher os dados do quadro (sem contar colunas travadas)?"""
    ciclo = quadro.ciclo
    if ciclo.situacao == Ciclo.ENCERRADO:
        return False
    if P.e_master(user):
        return True
    if ciclo.situacao in (Ciclo.PREPARACAO, Ciclo.REVISAO):
        return False
    if quadro.secao.situacao in (Secao.ENVIADA, Secao.APROVADA):
        return False
    return P.pode_editar_algum(user, quadro.setores_responsaveis())


def pode_editar_celula(user, linha, coluna):
    if (linha.calculada and not linha.importada) or coluna == "total":
        return False
    if not pode_editar_quadro(user, linha.quadro):
        return False
    if linha.setor_id and not P.e_master(user) and not P.pode_editar_algum(user, [linha.setor]):
        return False          # linha de outra unidade (ex.: metas do PDI, uma unidade por meta)
    if coluna.travada:
        return P.e_master(user)
    return True


def motivo_bloqueio(user, quadro):
    """Frase curta explicando por que o quadro está somente leitura (ou "" se editável)."""
    ciclo = quadro.ciclo
    if ciclo.situacao == Ciclo.ENCERRADO:
        return "O ciclo está encerrado: somente leitura."
    if pode_editar_quadro(user, quadro):
        return ""
    if ciclo.situacao == Ciclo.PREPARACAO:
        return "O ciclo ainda está em preparação: a coleta não foi aberta."
    if ciclo.situacao == Ciclo.REVISAO:
        return "O ciclo está em revisão: só o Master altera os dados."
    if quadro.secao.situacao == Secao.ENVIADA:
        return "Seção enviada ao Master: aguardando a revisão."
    if quadro.secao.situacao == Secao.APROVADA:
        return "Seção aprovada pelo Master."
    setores = ", ".join(s.sigla for s in quadro.setores_responsaveis()) or "nenhum setor definido"
    return f"Dados de responsabilidade de: {setores}."
