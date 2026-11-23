"""Editor visual de blocos (administrador): criar, mover, redimensionar, juntar e apagar os blocos de uma página.

Tudo o que muda aqui é a estrutura da página: posição e tamanho saem do retângulo desenhado, e o setor, a descrição e os
limites de caracteres são os atributos do bloco (etapa 1). Nada do que um setor escreveu se perde sem aviso: apagar ou
juntar blocos com texto editado pede confirmação e guarda uma cópia legível do texto em dados/; blocos com comentários
ou sugestões pendentes só saem depois de resolvidos; bloco em edição por outra pessoa não é mexido.
"""
from django.db import transaction

from . import atributos as AT
from . import fluxo as F
from .html_seguro import limpar, texto_puro
from .models import Bloco, Ciclo, Quadro, Secao

LIMITE_PAGINA = 20      # pontos de folga fora da página
MINIMO = 12             # menor largura/altura de um bloco, em pontos
CSS_PADRAO = ("font-family:Calibri,Carlito,sans-serif;font-size:11px;font-weight:400;font-style:normal;"
              "color:#000000;line-height:13.4px;text-align:justify")
TIPOS_NOVOS = (Bloco.TEXTO, Bloco.GRAFICO, Bloco.TABELA, Bloco.IMAGEM)


class Recusado(Exception):
    pass


# --- leitura -----------------------------------------------------------------------------------------------
def _caixa(b):
    return (b.config or {}).get("caixa") or {}


def serializar(b, setores_da_secao):
    cx = _caixa(b)
    atr = AT.anotar(b, setores_da_secao, cx) if b.tipo in (Bloco.TEXTO, Bloco.IMAGEM) else None
    trava = F.trava_ativa(b)
    return {
        "id": b.pk, "tipo": b.tipo, "tipo_nome": b.get_tipo_display(),
        "secao": b.secao_id, "setor": b.setor_id, "descricao": b.descricao,
        "min": b.min_caracteres, "max": b.max_caracteres, "titulo": b.titulo,
        "quadro": b.quadro_id, "quadro_titulo": b.quadro.titulo if b.quadro_id else "",
        "x": cx.get("x", 0), "y": cx.get("y", 0), "w": cx.get("w", 0), "h": cx.get("h", 0),
        "css": cx.get("css", ""), "html": limpar(b.conteudo) if b.tipo == Bloco.TEXTO else "",
        "previa": texto_puro(b.conteudo)[:120] if b.tipo == Bloco.TEXTO else "",
        "cor": atr["cor"] if atr else AT.NEUTRA, "siglas": atr["siglas"] if atr else "",
        "caracteres": AT.contar_caracteres(b.conteudo) if b.tipo == Bloco.TEXTO else 0,
        "editado": bool(b.atualizado_por_id and (b.conteudo or "").strip()),
        "travado_por": (b.editando_por.get_full_name() or b.editando_por.username) if trava else "",
        "comentarios": b.comentarios.count(), "sugestoes": b.sugestoes.filter(situacao="pendente").count(),
        "fixo": bool((b.config or {}).get("fixo")), "numero_antigo": bool((b.config or {}).get("numero_antigo")),
        "referencia": bool((b.config or {}).get("referencia_pdf")),
    }


def blocos_da_pagina(pagina):
    qs = (pagina.caixas.select_related("secao", "setor", "editando_por", "quadro", "atualizado_por")
          .prefetch_related("secao__setores").order_by("ordem", "id"))
    return [serializar(b, b.secao.setores.all()) for b in qs]


def opcoes(ciclo):
    """Seções, setores e quadros do ciclo, para os seletores da tela."""
    from contas.models import Setor
    secoes = sorted(ciclo.secoes.select_related("pai"), key=lambda s: ((s.pai.ordem if s.pai_id else s.ordem),
                                                                       (s.ordem if s.pai_id else -1), s.pk))
    return {
        "secoes": [{"id": s.pk, "titulo": ("— " if s.pai_id else "") + s.titulo} for s in secoes],
        "setores": [{"id": s.pk, "sigla": s.sigla} for s in Setor.objects.filter(ativo=True).order_by("ordem", "sigla")],
        "quadros": [{"id": q.pk, "titulo": q.titulo} for q in ciclo.quadros.order_by("secao__ordem", "ordem", "id")],
    }


# --- validação -----------------------------------------------------------------------------------------------
def _num(v, nome):
    try:
        return round(float(v), 1)
    except (TypeError, ValueError):
        raise Recusado(f"Valor inválido para {nome}.")


def _geometria(pagina, d):
    x, y, w, h = (_num(d.get(k), k) for k in ("x", "y", "w", "h"))
    w, h = max(MINIMO, w), max(MINIMO, h)
    x = min(max(-LIMITE_PAGINA, x), pagina.largura + LIMITE_PAGINA - w)
    y = min(max(-LIMITE_PAGINA, y), pagina.altura + LIMITE_PAGINA - h)
    return {"x": round(x, 1), "y": round(y, 1), "w": round(w, 1), "h": round(h, 1)}


def _limite(v, nome):
    if v in (None, ""):
        return None
    try:
        n = int(v)
    except (TypeError, ValueError):
        raise Recusado(f"O {nome} de caracteres precisa ser um número.")
    if n < 0:
        raise Recusado(f"O {nome} de caracteres não pode ser negativo.")
    return n


def _atributos(ciclo, d):
    """Setor, descrição e limites vindos da tela, já conferidos."""
    from contas.models import Setor
    setor = None
    if d.get("setor"):
        setor = Setor.objects.filter(pk=d["setor"], ativo=True).first()
        if setor is None:
            raise Recusado("Setor inválido.")
    mn, mx = _limite(d.get("min"), "mínimo"), _limite(d.get("max"), "máximo")
    if mn and mx and mn > mx:
        raise Recusado("O mínimo de caracteres não pode ser maior que o máximo.")
    return {"setor": setor, "descricao": (d.get("descricao") or "").strip()[:2000],
            "min_caracteres": mn, "max_caracteres": mx}


def _secao(ciclo, pk):
    s = Secao.objects.filter(ciclo=ciclo, pk=pk).first()
    if s is None:
        raise Recusado("Escolha a seção do bloco.")
    return s


def _checar_ciclo(ciclo):
    if ciclo.situacao == Ciclo.ENCERRADO:
        raise Recusado("O ciclo está encerrado.")


def _travado_por_outro(user, b):
    if F.trava_ativa(b) and b.editando_por_id != user.pk:
        nome = b.editando_por.get_full_name() or b.editando_por.username
        raise Recusado(f"{nome} está editando um dos blocos. Tente de novo em alguns minutos.")


def _do_ciclo(pagina, pk):
    b = pagina.caixas.select_related("secao", "editando_por").filter(pk=pk).first()
    if b is None:
        raise Recusado("Bloco não encontrado nesta página.")
    return b


def _ordem_leitura(b, largura):
    cx = _caixa(b)
    return (0 if cx.get("x", 0) + cx.get("w", 0) / 2 < largura / 2 else 1, cx.get("y", 0), cx.get("x", 0))


def _css_de_corpo(pagina):
    """Fonte do bloco de texto mais comprido da página (ponto de partida para um bloco novo)."""
    melhor = None
    for b in pagina.caixas.filter(tipo=Bloco.TEXTO):
        css = _caixa(b).get("css")
        if css and (melhor is None or len(b.conteudo) > melhor[0]):
            melhor = (len(b.conteudo), css)
    from contas import design
    from contas.models import Instituicao
    return design.ajustar_css_da_caixa(melhor[1] if melhor else CSS_PADRAO, Instituicao.atual())


def _proxima_ordem(pagina):
    ordens = [o for o in pagina.caixas.values_list("ordem", flat=True) if pagina.numero * 1000 + 600 <= o < pagina.numero * 1000 + 800]
    return (max(ordens) + 1) if ordens else pagina.numero * 1000 + 600


def _guardar_copia(ciclo, blocos):
    """Texto dos blocos que algum setor editou, em arquivo legível (JSON) na pasta de dados, antes de apagar."""
    from .paginas import _guardar_antigos
    _guardar_antigos(ciclo, blocos)


# --- ações -------------------------------------------------------------------------------------------------
@transaction.atomic
def criar(user, pagina, d):
    ciclo = pagina.ciclo
    _checar_ciclo(ciclo)
    tipo = d.get("tipo") or Bloco.TEXTO
    if tipo not in TIPOS_NOVOS:
        raise Recusado("Tipo de bloco inválido.")
    secao = _secao(ciclo, d.get("secao"))
    quadro = None
    if tipo in (Bloco.GRAFICO, Bloco.TABELA):
        quadro = Quadro.objects.filter(ciclo=ciclo, pk=d.get("quadro") or 0).first()
        if quadro is None:
            raise Recusado("Escolha o quadro de números do gráfico ou da tabela.")
    caixa = _geometria(pagina, d)
    if tipo == Bloco.TEXTO:
        caixa.update({"css": _css_de_corpo(pagina), "quebra": False})
        config = {"caixa": caixa, "criado_no_editor": True, "campos212": True}
    else:
        caixa.update({"fundo": "#ffffff", "titulo": False})
        config = {"caixa": caixa, "criado_no_editor": True}
        if tipo == Bloco.GRAFICO:
            config.update({"tipo": "barras", "colunas": [f"a{ciclo.ano}"]})
        elif tipo == Bloco.IMAGEM:
            caixa.update({"fundo": None})
            config["imagem"] = {"ajuste": "contain"}
    b = Bloco.objects.create(secao=secao, pagina=pagina, tipo=tipo, quadro=quadro, ordem=_proxima_ordem(pagina),
                             titulo=quadro.titulo if quadro else "", config=config, atualizado_por=None,
                             **_atributos(ciclo, d))
    return [b.pk], "Bloco criado."


@transaction.atomic
def salvar(user, pagina, d):
    """Muda posição/tamanho e/ou seção e atributos de um bloco. Não toca no texto nem na data de alteração (que os
    setores usam para detectar edição simultânea)."""
    ciclo = pagina.ciclo
    _checar_ciclo(ciclo)
    b = _do_ciclo(pagina, d.get("id"))
    campos = []
    if all(k in d for k in ("x", "y", "w", "h")):
        cfg = dict(b.config or {})
        cx = dict(cfg.get("caixa") or {})
        cx.update(_geometria(pagina, d))
        cfg["caixa"] = cx
        b.config = cfg
        campos.append("config")
    if "secao" in d and int(d["secao"] or 0) != b.secao_id:
        b.secao = _secao(ciclo, d["secao"])
        campos.append("secao")
    if any(k in d for k in ("setor", "descricao", "min", "max")):
        for k, v in _atributos(ciclo, {"setor": d.get("setor", b.setor_id), "descricao": d.get("descricao", b.descricao),
                                       "min": d.get("min", b.min_caracteres),
                                       "max": d.get("max", b.max_caracteres)}).items():
            setattr(b, k, v)
        campos += ["setor", "descricao", "min_caracteres", "max_caracteres"]
    if campos:
        b.save(update_fields=sorted(set(campos)))
    return [b.pk], "Alterações salvas."


@transaction.atomic
def juntar(user, pagina, d):
    """Funde vários blocos de texto da página em um só: a caixa passa a cobrir todos, o texto segue a ordem de leitura
    e os blocos que sobram são apagados (com cópia do texto que algum setor tenha escrito)."""
    ciclo = pagina.ciclo
    _checar_ciclo(ciclo)
    ids = list(dict.fromkeys(int(i) for i in (d.get("ids") or [])))
    if len(ids) < 2:
        raise Recusado("Escolha pelo menos dois blocos para juntar.")
    blocos = [_do_ciclo(pagina, i) for i in ids]
    if any(b.tipo != Bloco.TEXTO for b in blocos):
        raise Recusado("Só blocos de texto podem ser juntados.")
    for b in blocos:
        _travado_por_outro(user, b)
        if b.comentarios.exists() or b.sugestoes.filter(situacao="pendente").exists():
            raise Recusado("Um dos blocos tem comentários ou sugestões. Resolva-os antes de juntar.")
    blocos.sort(key=lambda b: _ordem_leitura(b, pagina.largura))
    com_texto = [b for b in blocos if b.atualizado_por_id and (b.conteudo or "").strip()]
    if len(com_texto) > 1 and not d.get("confirmar"):
        raise Recusado("CONFIRMAR: mais de um destes blocos tem texto escrito pelos setores. Os textos serão "
                       "reunidos em um só, na ordem de leitura. Quer continuar?")
    primeiro = blocos[0]
    caixas = [_caixa(b) for b in blocos]
    x0 = min(c.get("x", 0) for c in caixas)
    y0 = min(c.get("y", 0) for c in caixas)
    x1 = max(c.get("x", 0) + c.get("w", 0) for c in caixas)
    y1 = max(c.get("y", 0) + c.get("h", 0) for c in caixas)
    cfg = dict(primeiro.config or {})
    cx = dict(cfg.get("caixa") or {})
    cx.update({"x": round(x0, 1), "y": round(y0, 1), "w": round(x1 - x0, 1), "h": round(y1 - y0, 1)})
    cfg["caixa"] = cx
    cfg["junta_de"] = [b.pk for b in blocos]
    primeiro.config = cfg
    primeiro.conteudo = "".join(b.conteudo or "" for b in blocos)
    primeiro.setor = next((b.setor for b in blocos if b.setor_id), None)
    primeiro.descricao = next((b.descricao for b in blocos if b.descricao.strip()), "")
    mins = [b.min_caracteres for b in blocos if b.min_caracteres]
    maxs = [b.max_caracteres for b in blocos]
    primeiro.min_caracteres = sum(mins) or None
    primeiro.max_caracteres = sum(maxs) if all(maxs) else None
    if com_texto:
        primeiro.atualizado_por = user
    primeiro.save()
    resto = blocos[1:]
    if com_texto:
        _guardar_copia(ciclo, blocos)           # os textos como eram antes de juntar
    for b in resto:
        b.delete()
    return [primeiro.pk], f"{len(blocos)} blocos juntados."


@transaction.atomic
def apagar(user, pagina, d):
    """Apaga um bloco (id) ou vários (ids: seleção por área). Tudo ou nada."""
    ciclo = pagina.ciclo
    _checar_ciclo(ciclo)
    ids = d.get("ids") or [d.get("id")]
    blocos = [_do_ciclo(pagina, i) for i in ids]
    escritos = []
    for b in blocos:
        _travado_por_outro(user, b)
        if b.comentarios.exists() or b.sugestoes.filter(situacao="pendente").exists():
            raise Recusado("Um dos blocos tem comentários ou sugestões. Resolva-os antes de apagar." if len(blocos) > 1
                           else "Este bloco tem comentários ou sugestões. Resolva-os antes de apagar.")
        if b.atualizado_por_id and (b.conteudo or "").strip():
            escritos.append(b)
    if escritos:
        if not d.get("confirmar"):
            raise Recusado(f"CONFIRMAR: {len(escritos)} bloco(s) têm texto escrito por um setor. Apagar remove o texto "
                           "da página (uma cópia fica guardada na pasta de dados). Quer apagar?")
        _guardar_copia(ciclo, escritos)
    with transaction.atomic():
        for b in blocos:
            b.delete()
    return [], "Bloco apagado." if len(blocos) == 1 else f"{len(blocos)} blocos apagados."


def definir_fixo(user, pagina, d):
    """Liberar para o setor (fixo=False): o texto do PDF vira referência e o bloco fica vazio, para o setor escrever.
    Voltar a fixo (fixo=True): o bloco vazio recebe de volta o texto do PDF, e só o Editor-chefe altera."""
    from .importador import tamanho_sugerido
    ciclo = pagina.ciclo
    _checar_ciclo(ciclo)
    fixo = bool(d.get("fixo"))
    blocos = [_do_ciclo(pagina, i) for i in (d.get("ids") or [d.get("id")])]
    with transaction.atomic():
        for b in blocos:
            if b.tipo != Bloco.TEXTO:
                raise Recusado("Só blocos de texto podem ser fixos ou liberados.")
            _travado_por_outro(user, b)
            cfg = dict(b.config or {})
            if fixo == bool(cfg.get("fixo")):
                continue
            if fixo:
                if (b.conteudo or "").strip() and b.atualizado_por_id:
                    raise Recusado("Um setor já escreveu neste bloco: ele não volta a ser texto fixo.")
                b.conteudo = cfg.pop("referencia_pdf", "") or b.conteudo
                cfg["fixo"] = True
            else:
                if (b.conteudo or "").strip():
                    cfg["referencia_pdf"] = b.conteudo
                b.conteudo = ""
                for k in ("fixo", "rotulo", "numero_antigo"):
                    cfg.pop(k, None)
                if b.min_caracteres is None and b.max_caracteres is None:
                    b.min_caracteres, b.max_caracteres = tamanho_sugerido(AT.contar_caracteres(cfg.get("referencia_pdf")))
            b.config = cfg
            b.save(update_fields=["conteudo", "config", "min_caracteres", "max_caracteres"])
    n = len(blocos)
    if fixo:
        return [b.pk for b in blocos], "Texto fixo do modelo (só o Editor-chefe altera)." if n == 1 else \
            f"{n} blocos voltaram a ser texto fixo."
    return [b.pk for b in blocos], "Liberado para o setor: o bloco ficou vazio e o texto do PDF virou referência." \
        if n == 1 else f"{n} blocos liberados para o setor."


ACOES = {"criar": criar, "salvar": salvar, "juntar": juntar, "apagar": apagar, "fixo": definir_fixo}
