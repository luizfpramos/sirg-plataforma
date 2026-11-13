"""Limite diário de tokens por usuário e registro de cada chamada ao Assistente SiRG."""
from django.db.models import Sum
from django.utils import timezone

from . import config, provedores
from .models import UsoIA


def _inicio_do_dia():
    return timezone.localtime().replace(hour=0, minute=0, second=0, microsecond=0)


def limite_dia(usuario):
    from contas.models import Perfil
    p = Perfil.objects.filter(usuario=usuario).only("limite_tokens_dia").first()
    if p and p.limite_tokens_dia is not None:
        return int(p.limite_tokens_dia)
    return int(config.limites().get("tokens_dia_padrao", 0) or 0)


def usado_hoje(usuario):
    agg = UsoIA.objects.filter(usuario=usuario, criado_em__gte=_inicio_do_dia()).aggregate(
        e=Sum("tokens_entrada"), s=Sum("tokens_saida"))
    return (agg["e"] or 0) + (agg["s"] or 0)


def situacao(usuario):
    lim = limite_dia(usuario)
    hoje = usado_hoje(usuario)
    return {"limite": lim, "sem_limite": lim == 0, "usado_hoje": hoje,
            "restante": None if lim == 0 else max(0, lim - hoje),
            "percentual": min(100, round(100 * hoje / lim)) if lim else 0}


def verificar_limite(usuario):
    s = situacao(usuario)
    if not s["sem_limite"] and s["restante"] <= 0:
        raise provedores.ErroIA(f"Você atingiu o seu limite diário de uso do Assistente "
                                f"({s['limite']:,} tokens). O limite renova à meia-noite; se precisar de mais hoje, "
                                f"fale com o administrador da plataforma.".replace(",", "."))


def chamar_e_registrar(usuario, perfil, mensagens, acao, bloco=None):
    verificar_limite(usuario)
    try:
        r = provedores.chamar(perfil, mensagens)
    except provedores.ErroIA as ex:
        UsoIA.objects.create(usuario=usuario, acao=acao, provedor=perfil.provedor, modelo=perfil.modelo,
                             sucesso=False, erro=str(ex)[:300], bloco=bloco)
        raise
    uso = UsoIA.objects.create(usuario=usuario, acao=acao, provedor=perfil.provedor, modelo=perfil.modelo,
                               tokens_entrada=r.tokens_entrada, tokens_saida=r.tokens_saida, duracao_ms=r.duracao_ms,
                               bloco=bloco)
    return r, uso
