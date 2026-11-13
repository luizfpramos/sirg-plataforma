"""Operações do relatório: colunas por ano, gravação de valores e cópia de ciclo."""
import logging

from django.db import transaction

from . import formato
from . import permissoes as RP
from .models import Ciclo, Coluna, Linha, Quadro, Regra, Secao, Valor

log = logging.getLogger("sirg")


class Recusado(Exception):
    """Operação não permitida ou dado inválido (mensagem amigável)."""


class Conflito(Exception):
    def __init__(self, atual):
        super().__init__("Outra pessoa alterou esta célula enquanto você editava.")
        self.atual = atual


# --- Colunas ---------------------------------------------------------------
def anos_do_quadro(quadro):
    n = max(1, quadro.anos_exibidos or 1)
    return list(range(quadro.ciclo.ano - n + 1, quadro.ciclo.ano + 1))


@transaction.atomic
def sincronizar_colunas_de_anos(quadro):
    """Garante uma coluna para cada ano exibido (chave a2025, rótulo 2025). Remove as de fora."""
    if quadro.modo_colunas != Quadro.ANOS:
        return
    anos = anos_do_quadro(quadro)
    existentes = {c.ano: c for c in quadro.colunas.all() if c.ano is not None}
    for ordem, ano in enumerate(anos, start=1):
        c = existentes.get(ano)
        if c is None:
            Coluna.objects.create(quadro=quadro, ordem=ordem, chave=f"a{ano}", rotulo=str(ano), ano=ano)
        elif c.ordem != ordem:
            c.ordem = ordem
            c.save(update_fields=["ordem"])
    quadro.colunas.exclude(ano__in=anos).delete()


# --- Valores ---------------------------------------------------------------
def texto_edicao(valor, tipo, casas):
    if valor is None:
        return ""
    return formato.para_edicao(tipo, valor.numero, valor.texto, casas)


@transaction.atomic
def salvar_valor(user, linha, coluna, entrada, anterior=None, justificativa=""):
    """Grava o que o usuário digitou. Devolve o Valor (ou None se a célula ficou vazia).

    `anterior` é o valor que a tela mostrava quando o usuário começou a editar: se o
    banco tiver outro valor (alguém salvou antes), a gravação é recusada com Conflito.
    """
    if not RP.pode_editar_celula(user, linha, coluna):
        if linha.calculada and not linha.importada:
            raise Recusado("Esta linha é calculada automaticamente.")
        if coluna.travada and RP.pode_editar_quadro(user, linha.quadro):
            raise Recusado("Ano anterior já publicado: só o Master pode alterar.")
        raise Recusado(RP.motivo_bloqueio(user, linha.quadro) or "Você não pode alterar esta célula.")
    tipo, casas = linha.tipo, linha.quadro.casas_decimais
    try:
        numero, texto = formato.ler(tipo, entrada)
    except formato.EntradaInvalida as ex:
        raise Recusado(str(ex))
    v = Valor.objects.select_for_update().filter(linha=linha, coluna=coluna).first()
    atual = texto_edicao(v, tipo, casas)
    novo = formato.para_edicao(tipo, numero, texto, casas)
    if anterior is not None and _norm(anterior) != _norm(atual) and _norm(novo) != _norm(atual):
        raise Conflito(atual)
    justificativa = (justificativa or "").strip()
    if coluna.travada and _norm(novo) != _norm(atual) and not justificativa:
        raise Recusado("Para alterar um ano já publicado, informe a justificativa.")
    if numero is None and not texto:
        if v is not None:
            v._change_reason = justificativa or "valor apagado"
            v.delete()
        return None
    if v is None:
        v = Valor(linha=linha, coluna=coluna)
    elif v.numero == numero and v.texto == texto and not (justificativa and justificativa != v.justificativa):
        return v
    if v.numero != numero:
        v.auto_aceito = None          # valor novo: a divergência (se houver) precisa ser vista de novo
    v.numero, v.texto, v.atualizado_por = numero, texto, user
    if justificativa:
        v.justificativa = justificativa
    v._change_reason = justificativa
    v.save()
    _marcar_secao(linha.quadro.secao, user)
    return v


def _marcar_secao(secao, user):
    if secao.situacao == Secao.NAO_INICIADA:
        from .fluxo import mover_secao
        mover_secao(secao, Secao.PREENCHIMENTO, user, "", automatico=True)


def _norm(s):
    return (s or "").strip()


@transaction.atomic
def resolver_divergencia(user, linha, coluna, acao, calc):
    """Linha de fonte única com valor digitado diferente do automático.
    acao "corrigir": apaga o digitado (fica valendo o automático); "ignorar": mantém o digitado."""
    if not RP.pode_editar_celula(user, linha, coluna):
        raise Recusado(RP.motivo_bloqueio(user, linha.quadro) or "Você não pode alterar esta célula.")
    v = Valor.objects.select_for_update().filter(linha=linha, coluna=coluna).first()
    if v is None or not linha.importada:
        raise Recusado("Não há divergência nesta célula.")
    q = calc.quadros[linha.quadro.chave]
    li = calc.linhas[q.pk][linha.chave]
    auto = calc.automatico(q, li, coluna)
    if acao == "corrigir":
        if auto.numero is None:
            raise Recusado("O valor automático ainda não está disponível.")
        v._change_reason = "divergência corrigida: passa a valer o valor automático"
        v.delete()
    elif acao == "ignorar":
        v.auto_aceito = auto.numero
        v.atualizado_por = user
        v._change_reason = "divergência ignorada: mantido o valor digitado"
        v.save()
    else:
        raise Recusado("Ação desconhecida.")


@transaction.atomic
def salvar_justificativa(user, linha, coluna, justificativa):
    if not RP.pode_editar_quadro(user, linha.quadro):
        raise Recusado("Você não pode alterar este quadro.")
    v = Valor.objects.filter(linha=linha, coluna=coluna).first()
    if v is None:
        raise Recusado("Preencha o valor antes de justificar.")
    v.justificativa = (justificativa or "").strip()
    v.atualizado_por = user
    v._change_reason = "justificativa"
    v.save()
    return v


# --- Ciclos ------------------------------------------------------------------
@transaction.atomic
def copiar_ciclo(origem, ano, titulo, anos_serie=None):
    """Cria o ciclo `ano` com a estrutura de `origem`.

    Quadros por ano: os anos que já existiam em `origem` trazem os valores e ficam
    travados; o novo ano-base fica em branco. Quadros por categoria: copiam a
    estrutura (linhas e colunas), sem valores.
    """
    if Ciclo.objects.filter(ano=ano).exists():
        raise Recusado(f"Já existe um ciclo para {ano}.")
    if ano <= origem.ano:
        raise Recusado("O novo ciclo precisa ser de um ano posterior ao de origem.")
    novo = Ciclo.objects.create(ano=ano, titulo=titulo, situacao=Ciclo.PREPARACAO, origem=origem,
                                anos_serie=anos_serie or origem.anos_serie)
    mapa_secao = {}
    for s in origem.secoes.order_by("pai_id", "ordem", "id"):   # capítulos (pai nulo) primeiro
        ns = Secao.objects.create(ciclo=novo, pai=mapa_secao.get(s.pai_id), ordem=s.ordem, chave=s.chave,
                                  titulo=s.titulo, orientacao=s.orientacao, nivel=s.nivel)
        ns.setores.set(s.setores.all())
        mapa_secao[s.pk] = ns
    for q in origem.quadros.select_related("secao").order_by("ordem", "id"):
        nq = Quadro.objects.create(
            ciclo=novo, secao=mapa_secao[q.secao_id], ordem=q.ordem, chave=q.chave, titulo=q.titulo,
            descricao=q.descricao, fonte=q.fonte, setor=q.setor, tipo_valor=q.tipo_valor,
            casas_decimais=q.casas_decimais, modo_colunas=q.modo_colunas, anos_exibidos=q.anos_exibidos,
            linha_total=q.linha_total, coluna_total=q.coluna_total, rotulo_total=q.rotulo_total,
            obrigatorio=q.obrigatorio, variacao_alerta=q.variacao_alerta)
        mapa_linha = {}
        for li in q.linhas.all():
            mapa_linha[li.pk] = Linha.objects.create(
                quadro=nq, ordem=li.ordem, chave=li.chave, rotulo=li.rotulo, formula=li.formula,
                tipo_valor=li.tipo_valor, minimo=li.minimo, maximo=li.maximo, soma_no_total=li.soma_no_total)
        if q.modo_colunas == Quadro.ANOS:
            sincronizar_colunas_de_anos(nq)
            cols_novas = {c.ano: c for c in nq.colunas.all()}
            for c_antiga in q.colunas.all():
                c_nova = cols_novas.get(c_antiga.ano)
                if c_nova is None:
                    continue
                c_nova.travada = True          # ano anterior ao novo ano-base: publicado
                c_nova.save(update_fields=["travada"])
                for v in Valor.objects.filter(coluna=c_antiga):
                    if v.linha_id in mapa_linha:
                        Valor.objects.create(linha=mapa_linha[v.linha_id], coluna=c_nova, numero=v.numero,
                                             texto=v.texto, justificativa=v.justificativa)
            # anos sem dado no ciclo de origem (ex.: série maior) também são passado
            nq.colunas.filter(ano__lt=ano).update(travada=True)
        else:
            for c in q.colunas.all():
                Coluna.objects.create(quadro=nq, ordem=c.ordem, chave=c.chave, rotulo=c.rotulo, ano=None)
    mapa_quadro = {q.chave: q for q in novo.quadros.all()}
    from .models import Bloco, Pagina
    mapa_pagina = {}
    for p in origem.paginas.all():         # o relatório nas páginas do RG: mesma diagramação no ano seguinte
        mapa_pagina[p.pk] = Pagina.objects.create(ciclo=novo, numero=p.numero, largura=p.largura, altura=p.altura,
                                                  fundo=p.fundo, secao=mapa_secao.get(p.secao_id), fixos=p.fixos)
    for b in Bloco.objects.filter(secao__ciclo=origem).select_related("quadro").order_by("ordem", "id"):
        cfg = dict(b.config or {})
        if b.tipo == Bloco.TEXTO:
            cfg["herdado_de"] = origem.ano      # texto do ano anterior, como ponto de partida
        Bloco.objects.create(secao=mapa_secao[b.secao_id], ordem=b.ordem, tipo=b.tipo, titulo=b.titulo,
                             conteudo=b.conteudo, quadro=mapa_quadro.get(b.quadro.chave) if b.quadro else None,
                             config=cfg, pagina=mapa_pagina.get(b.pagina_id))
    for r in origem.regras.select_related("quadro"):
        Regra.objects.create(ciclo=novo, quadro=mapa_quadro[r.quadro.chave], descricao=r.descricao,
                             esquerda=r.esquerda, operador=r.operador, direita=r.direita, tolerancia=r.tolerancia,
                             escopo=r.escopo, severidade=r.severidade, ativa=r.ativa)
    return novo
