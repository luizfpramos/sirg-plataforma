"""
Texto do relatório e fluxo das seções.

Permissões do texto (blocos):
  - Master: edita direto ou sugere, em qualquer seção (exceto ciclo encerrado).
  - Setor responsável: edita a própria seção durante a coleta, enquanto ela não foi
    enviada ao Master (ou depois de devolvida).
  - Administrador sem Master: monta a estrutura, mas não escreve o texto dos setores.

Fluxo da seção:
  não iniciada → em preenchimento (sozinho, na 1ª alteração) → enviada ao Master
  → aprovada  (ou devolvida ao setor, voltando a "em preenchimento").
"""
import re
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from contas import permissoes as P

from . import consistencia, formato, revisao
from .html_seguro import limpar
from .models import Bloco, Ciclo, Comentario, MovimentoSecao, Secao, Sugestao

TRAVA_MINUTOS = 10


class Recusado(Exception):
    pass


# --- permissões -------------------------------------------------------------------
def e_do_setor(user, secao):
    """O usuário está (hoje) em algum dos setores responsáveis pela seção?"""
    meus = set(P.setores_ativos(user).values_list("pk", flat=True))
    return bool(meus & set(secao.setores.values_list("pk", flat=True)))


def pode_editar_texto(user, secao):
    ciclo = secao.ciclo
    if ciclo.situacao == Ciclo.ENCERRADO:
        return False
    if P.e_master(user):
        return True
    if ciclo.situacao != Ciclo.COLETA:
        return False
    if secao.situacao in (Secao.ENVIADA, Secao.APROVADA):
        return False
    return e_do_setor(user, secao)


def pode_sugerir(user, secao):
    return P.e_master(user) and secao.ciclo.situacao != Ciclo.ENCERRADO


def pode_responder_sugestao(user, secao):
    """Quem aceita/recusa sugestões: o setor responsável (ou o Master, se a seção não tiver setor)."""
    if secao.ciclo.situacao == Ciclo.ENCERRADO:
        return False
    if e_do_setor(user, secao):
        return True
    return P.e_master(user) and not secao.setores.exists()


def motivo_texto_bloqueado(user, secao):
    ciclo = secao.ciclo
    if ciclo.situacao == Ciclo.ENCERRADO:
        return "Ciclo encerrado: somente leitura."
    if pode_editar_texto(user, secao):
        return ""
    if ciclo.situacao == Ciclo.PREPARACAO:
        return "O ciclo está em preparação: a coleta ainda não foi aberta."
    if ciclo.situacao == Ciclo.REVISAO:
        return "O ciclo está em revisão: só o Master altera o texto."
    if secao.situacao == Secao.ENVIADA:
        return "Seção enviada ao Master: aguardando a revisão."
    if secao.situacao == Secao.APROVADA:
        return "Seção aprovada pelo Master."
    setores = ", ".join(s.sigla for s in secao.setores.all()) or "nenhum setor definido"
    return f"Texto de responsabilidade de: {setores}."


# --- travas de edição --------------------------------------------------------------------
def trava_ativa(bloco, agora=None):
    agora = agora or timezone.now()
    return bool(bloco.editando_por_id and bloco.editando_desde and
                bloco.editando_desde > agora - timedelta(minutes=TRAVA_MINUTOS))


@transaction.atomic
def travar(user, bloco):
    """Reserva o bloco para edição. Devolve (ok, quem_esta_editando)."""
    b = Bloco.objects.select_for_update().select_related("editando_por").get(pk=bloco.pk)
    if trava_ativa(b) and b.editando_por_id != user.pk:
        return False, b.editando_por
    Bloco.objects.filter(pk=b.pk).update(editando_por=user, editando_desde=timezone.now())
    return True, user


def destravar(user, bloco):
    Bloco.objects.filter(pk=bloco.pk, editando_por=user).update(editando_por=None, editando_desde=None)


# --- blocos -------------------------------------------------------------------------------
def _marcar_preenchimento(secao, user):
    if secao.situacao == Secao.NAO_INICIADA:
        mover_secao(secao, Secao.PREENCHIMENTO, user, "", automatico=True)


@transaction.atomic
def salvar_texto(user, bloco, html, titulo=None, versao=None):
    """Grava o texto do bloco. `versao` = atualizado_em que o editor recebeu (para detectar conflito)."""
    if not pode_editar_texto(user, bloco.secao):
        raise Recusado(motivo_texto_bloqueado(user, bloco.secao) or "Você não pode alterar este texto.")
    b = Bloco.objects.select_for_update().get(pk=bloco.pk)
    if trava_ativa(b) and b.editando_por_id not in (None, user.pk):
        raise Recusado(f"{b.editando_por.get_full_name() or b.editando_por.username} está editando este trecho agora.")
    if versao and b.atualizado_em.isoformat() != versao:
        raise Recusado("Este trecho foi alterado por outra pessoa enquanto você editava. Copie o seu texto, "
                       "recarregue a página e aplique de novo.")
    novo = revisao.carimbar(b.conteudo, limpar(html), user)
    if not P.e_master(user) and revisao.texto_base(novo) != revisao.texto_base(b.conteudo):
        # quem não é Master só altera o texto com o controle de alterações ligado (o texto base não muda)
        raise Recusado("Com o controle de alterações, o texto original continua no lugar até o Master aceitar a "
                       "mudança. Recarregue a página (F5) e escreva de novo.")
    b.conteudo = novo
    b.config = {k: v for k, v in (b.config or {}).items() if k not in ("herdado_de", "modelo")}
    if titulo is not None:
        b.titulo = titulo.strip()[:255]
    b.atualizado_por = user
    b.editando_por, b.editando_desde = user, timezone.now()
    b.save()
    _marcar_preenchimento(b.secao, user)
    return b


@transaction.atomic
def salvar_config(user, bloco, titulo, quadro, config):
    if not pode_editar_texto(user, bloco.secao):
        raise Recusado(motivo_texto_bloqueado(user, bloco.secao) or "Você não pode alterar este bloco.")
    if quadro is not None and quadro.ciclo_id != bloco.secao.ciclo_id:
        raise Recusado("Quadro de outro ciclo.")
    bloco.titulo = (titulo or "").strip()[:255]
    bloco.quadro = quadro
    bloco.config = config or {}
    bloco.atualizado_por = user
    bloco.save()
    _marcar_preenchimento(bloco.secao, user)
    return bloco


@transaction.atomic
def criar_bloco(user, secao, tipo, depois_de=None, quadro=None):
    if not pode_editar_texto(user, secao):
        raise Recusado(motivo_texto_bloqueado(user, secao) or "Você não pode alterar esta seção.")
    if not P.e_master(user):
        raise Recusado("Os setores alteram o texto que já está no relatório; novos trechos são incluídos pelo Master.")
    if tipo not in dict(Bloco.TIPOS):
        raise Recusado("Tipo de bloco inválido.")
    blocos = list(secao.blocos.order_by("ordem", "id"))
    pos = len(blocos)
    if depois_de is not None:
        pos = next((i + 1 for i, b in enumerate(blocos) if b.pk == depois_de.pk), pos)
    novo = Bloco(secao=secao, tipo=tipo, quadro=quadro, atualizado_por=user,
                 config={"tipo": "barras"} if tipo == Bloco.GRAFICO else {})
    blocos.insert(pos, novo)
    novo.ordem = (pos + 1) * 10
    novo.save()
    _renumerar(blocos)
    _marcar_preenchimento(secao, user)
    return novo


def _renumerar(blocos):
    for i, b in enumerate(blocos, start=1):
        if b.ordem != i * 10:
            Bloco.objects.filter(pk=b.pk).update(ordem=i * 10)
            b.ordem = i * 10


@transaction.atomic
def mover_bloco(user, bloco, direcao):
    if not pode_editar_texto(user, bloco.secao):
        raise Recusado(motivo_texto_bloqueado(user, bloco.secao))
    blocos = list(bloco.secao.blocos.order_by("ordem", "id"))
    i = next(i for i, b in enumerate(blocos) if b.pk == bloco.pk)
    j = i - 1 if direcao == "subir" else i + 1
    if 0 <= j < len(blocos):
        blocos[i], blocos[j] = blocos[j], blocos[i]
        _renumerar(blocos)


@transaction.atomic
def excluir_bloco(user, bloco):
    if not pode_editar_texto(user, bloco.secao):
        raise Recusado(motivo_texto_bloqueado(user, bloco.secao))
    if not P.e_master(user):
        raise Recusado("Só o Master exclui trechos. Para propor a retirada de um texto, apague-o com o controle de "
                       "alterações (fica riscado até o Master aceitar).")
    if trava_ativa(bloco) and bloco.editando_por_id != user.pk:
        raise Recusado("Outra pessoa está editando este trecho.")
    bloco._change_reason = "bloco excluído"
    bloco.delete()


# --- controle de alterações (sugestões no próprio texto) ----------------------------------------
def pode_resolver_alteracoes(user, secao):
    """Aceitar ou recusar o que foi sugerido no texto: o Master (que revisa o relatório). Quem sugeriu pode
    desfazer (recusar) a própria alteração enquanto escreve."""
    return P.e_master(user) and pode_editar_texto(user, secao)


@transaction.atomic
def resolver_alteracoes(user, bloco, ids=None, aceitar=True):
    """Aceita (ou recusa) as sugestões `ids` do bloco (todas, se None). Devolve (bloco, quantas)."""
    master = pode_resolver_alteracoes(user, bloco.secao)
    if not master and not (not aceitar and pode_editar_texto(user, bloco.secao)):
        raise Recusado("Quem aceita ou recusa as alterações é o Master, na revisão da seção.")
    b = Bloco.objects.select_for_update().select_related("editando_por", "secao__ciclo").get(pk=bloco.pk)
    if trava_ativa(b) and b.editando_por_id not in (None, user.pk):
        raise Recusado(f"{b.editando_por.get_full_name() or b.editando_por.username} está escrevendo neste trecho "
                       f"agora. Tente daqui a pouco.")
    pendentes = {it["id"] for it in revisao.itens(b.conteudo) if master or it["autor_id"] == user.pk}
    alvo = pendentes if ids is None else pendentes & set(ids)
    if not alvo:
        return b, 0
    b.conteudo = limpar(revisao.aplicar(b.conteudo, alvo, aceitar))
    b.atualizado_por = user
    n = len(alvo)
    b._change_reason = f"{n} alteraç{'ões' if n > 1 else 'ão'} {'aceita' if aceitar else 'recusada'}{'s' if n > 1 else ''}"
    b.save()
    _marcar_preenchimento(b.secao, user)
    return b, n


def alteracoes_da_secao(secao):
    """Sugestões pendentes no texto da seção: [{id, autor_id, autor, data, inserido, removido, bloco}]."""
    out = []
    for b in secao.blocos.filter(tipo=Bloco.TEXTO).order_by("ordem", "id"):
        for it in revisao.itens(b.conteudo):
            it["bloco"] = b.pk
            out.append(it)
    return out


def campos_vazios_da_secao(secao):
    """Números do texto da seção (campos xxxxx) ainda sem valor, contando só o texto oficial."""
    from . import campos as CT
    n = 0
    for b in secao.blocos.filter(tipo=Bloco.TEXTO).prefetch_related("campos"):
        valores = CT.valores_do_bloco(b)
        n += sum(1 for ch in CT.chaves(revisao.base(b.conteudo)) if valores.get(ch) is None)
    return n


@transaction.atomic
def preencher_campo(user, bloco, chave, texto):
    """Grava o valor do ano de um número do texto (campo xxxxx). Devolve o CampoTexto."""
    from . import campos as CT
    from .models import CampoTexto
    if not pode_editar_texto(user, bloco.secao):
        raise Recusado(motivo_texto_bloqueado(user, bloco.secao) or "Você não pode alterar este texto.")
    m = next((m for m in CT.CAMPO.finditer(bloco.conteudo or "") if m.group(1) == chave), None)
    if m is None:
        raise Recusado("Este número não está mais no texto. Recarregue a página (F5).")
    from html import unescape
    try:
        n = CT.ler(unescape(m.group(2)), texto)
    except formato.EntradaInvalida as ex:
        raise Recusado(str(ex))
    c, _ = CampoTexto.objects.get_or_create(bloco=bloco, chave=chave)
    c.numero, c.atualizado_por = n, user
    c._history_user = user
    c.save()
    _marcar_preenchimento(bloco.secao, user)
    return c


def alteracoes_de_fora(secao, alteracoes=None):
    """Sugestões feitas por quem não é do setor da seção (ex.: o Master): o setor precisa decidir antes de enviar."""
    from django.contrib.auth import get_user_model
    alteracoes = alteracoes_da_secao(secao) if alteracoes is None else alteracoes
    ids = {a["autor_id"] for a in alteracoes if a["autor_id"]}
    if not ids:
        return []
    setores = set(secao.setores.values_list("pk", flat=True))
    do_setor = set()
    for u in get_user_model().objects.filter(pk__in=ids):
        if setores & set(P.setores_ativos(u).values_list("pk", flat=True)):
            do_setor.add(u.pk)
    return [a for a in alteracoes if a["autor_id"] not in do_setor]


# --- sugestões do Master -------------------------------------------------------------------
@transaction.atomic
def sugerir(user, bloco, html, comentario=""):
    if not pode_sugerir(user, bloco.secao):
        raise Recusado("Só o Master pode sugerir alterações.")
    proposto = limpar(html)
    if proposto == bloco.conteudo:
        raise Recusado("A sugestão é igual ao texto atual.")
    bloco.sugestoes.filter(situacao=Sugestao.PENDENTE, autor=user).update(situacao=Sugestao.RETIRADA,
                                                                          respondida_em=timezone.now())
    return Sugestao.objects.create(bloco=bloco, autor=user, original=bloco.conteudo, proposto=proposto,
                                   comentario=(comentario or "").strip())


@transaction.atomic
def responder_sugestao(user, sugestao, aceitar, resposta=""):
    s = Sugestao.objects.select_for_update().select_related("bloco__secao__ciclo").get(pk=sugestao.pk)
    if s.situacao != Sugestao.PENDENTE:
        raise Recusado("Esta sugestão já foi respondida.")
    if not pode_responder_sugestao(user, s.bloco.secao):
        raise Recusado("Quem responde às sugestões é o setor responsável pela seção.")
    b = s.bloco
    if aceitar:
        b.conteudo = s.proposto
        b.atualizado_por = user
        b._change_reason = f"sugestão de {s.autor.get_full_name() if s.autor else 'Master'} aceita"
        b.save()
        _marcar_preenchimento(b.secao, user)
    s.situacao = Sugestao.ACEITA if aceitar else Sugestao.RECUSADA
    s.respondida_por, s.respondida_em, s.resposta = user, timezone.now(), (resposta or "").strip()
    s.save()
    return s


def retirar_sugestao(user, sugestao):
    if sugestao.autor_id != user.pk or sugestao.situacao != Sugestao.PENDENTE:
        raise Recusado("Só quem sugeriu pode retirar uma sugestão pendente.")
    sugestao.situacao, sugestao.respondida_em = Sugestao.RETIRADA, timezone.now()
    sugestao.save()


# --- comentários ----------------------------------------------------------------------------
def pode_comentar(user, secao):
    return secao.ciclo.situacao != Ciclo.ENCERRADO and (P.e_master(user) or P.setores_ativos(user).exists())


def comentar(user, secao, texto, bloco=None, trecho="", antes="", pai=None):
    texto = (texto or "").strip()
    if not texto:
        raise Recusado("Escreva o comentário.")
    if secao.ciclo.situacao == Ciclo.ENCERRADO:
        raise Recusado("Ciclo encerrado.")
    if pai is not None:
        pai = pai.pai or pai                   # resposta a uma resposta entra na mesma conversa
        if pai.secao_id != secao.pk:
            raise Recusado("Comentário de outra seção.")
        if pai.resolvido:
            Comentario.objects.filter(pk=pai.pk).update(resolvido=False, resolvido_por=None)   # responder reabre
        bloco, trecho, antes = pai.bloco, "", ""
    if bloco is not None and bloco.secao_id != secao.pk:
        raise Recusado("Trecho de outra seção.")
    trecho = re.sub(r"\s+", " ", trecho or "").strip()[:600]
    antes = re.sub(r"\s+", " ", antes or "")[-120:]
    return Comentario.objects.create(secao=secao, bloco=bloco, autor=user, texto=texto[:4000], pai=pai,
                                     trecho=trecho, antes=antes if trecho else "")


def pode_resolver_comentario(user, comentario):
    return comentario.autor_id == user.pk or P.e_master(user) or e_do_setor(user, comentario.secao)


def resolver_comentario(user, comentario, reabrir=False):
    if comentario.pai_id:
        comentario = comentario.pai
    if not pode_resolver_comentario(user, comentario):
        raise Recusado("Você não pode resolver este comentário.")
    comentario.resolvido, comentario.resolvido_por = (False, None) if reabrir else (True, user)
    comentario.save()
    return comentario


def excluir_comentario(user, comentario):
    if comentario.autor_id != user.pk:
        raise Recusado("Só quem escreveu pode apagar o comentário.")
    if comentario.respostas.exists():
        raise Recusado("Este comentário já tem respostas: marque como resolvido.")
    comentario.delete()


# --- fluxo da seção ---------------------------------------------------------------------------
def mover_secao(secao, para, user, comentario="", automatico=False):
    de = secao.situacao
    if de == para:
        return
    Secao.objects.filter(pk=secao.pk).update(situacao=para)
    secao.situacao = para
    MovimentoSecao.objects.create(secao=secao, de=de, para=para, por=user if not automatico else user,
                                  comentario=comentario or ("" if not automatico else "início do preenchimento"))


def pendencias_da_secao(secao):
    """Pendências dos números da seção: os quadros dela e os de outra seção que saem numa tabela ou gráfico dela."""
    from .models import Bloco, Quadro
    ids = set(secao.quadros.values_list("pk", flat=True)) | set(
        Bloco.objects.filter(secao=secao, quadro__isnull=False).exclude(tipo=Bloco.TEXTO).values_list("quadro_id", flat=True))
    quadros = list(Quadro.objects.filter(pk__in=ids))
    if not quadros:
        return []
    return consistencia.verificar(secao.ciclo, quadros=quadros)


def acoes_possiveis(user, secao):
    """Botões de fluxo que o usuário vê nesta seção."""
    ciclo = secao.ciclo
    if ciclo.situacao == Ciclo.ENCERRADO:
        return []
    out = []
    master = P.e_master(user)
    do_setor = e_do_setor(user, secao)
    if secao.situacao in (Secao.NAO_INICIADA, Secao.PREENCHIMENTO) and (do_setor or master) \
            and ciclo.situacao == Ciclo.COLETA:
        out.append("enviar")
    if secao.situacao == Secao.ENVIADA and master:
        out += ["aprovar", "devolver"]
    if secao.situacao == Secao.APROVADA and master:
        out.append("reabrir")
    return out


@transaction.atomic
def acao_secao(user, secao, acao, comentario=""):
    if acao not in acoes_possiveis(user, secao):
        raise Recusado("Esta ação não está disponível para você agora.")
    if acao == "enviar":
        ps = pendencias_da_secao(secao)
        r = consistencia.resumo(ps)
        if r["erros"] or r["faltam"]:
            raise Recusado(f"Antes de enviar, resolva as pendências dos dados desta seção: "
                           f"{r['faltam']} a preencher e {r['erros']} erro(s).")
        if not secao.blocos.exists() and not secao.quadros.exists():
            raise Recusado("A seção está vazia.")
        n_campos = campos_vazios_da_secao(secao)
        if n_campos:
            raise Recusado(f"Antes de enviar, preencha os {n_campos} número{'s' if n_campos > 1 else ''} do texto que "
                           f"ainda aparece{'m' if n_campos > 1 else ''} como xxxxx.")
        mover_secao(secao, Secao.ENVIADA, user, comentario)
    elif acao == "aprovar":
        n = len(alteracoes_da_secao(secao))
        if n:
            raise Recusado(f"Antes de aprovar, aceite ou recuse as {n} alteraç{'ões' if n > 1 else 'ão'} "
                           f"sugerida{'s' if n > 1 else ''} no texto: o relatório só leva o que foi aceito.")
        mover_secao(secao, Secao.APROVADA, user, comentario)
    elif acao == "devolver":
        if not (comentario or "").strip():
            raise Recusado("Explique ao setor o que precisa ser ajustado.")
        mover_secao(secao, Secao.PREENCHIMENTO, user, comentario)
        comentar(user, secao, f"Seção devolvida pelo Master: {comentario}")
    elif acao == "reabrir":
        mover_secao(secao, Secao.PREENCHIMENTO, user, comentario or "reaberta pelo Master")
