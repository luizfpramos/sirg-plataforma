"""Monta as estruturas que as telas usam para desenhar os quadros (grades)."""
from collections import defaultdict

from contas import permissoes as P

from . import formato
from . import permissoes as RP
from .calculo import TOTAL
from .models import Quadro


def chave_celula(linha_id, coluna):
    return f"{linha_id}-{'total' if coluna == TOTAL else coluna.pk}"


def pendencias_por_celula(pendencias):
    mapa = defaultdict(list)
    for p in pendencias:
        if p.linha is not None and p.coluna is not None:
            mapa[chave_celula(p.linha.pk, p.coluna)].append(p)
    return mapa


def montar_quadro(calc, q, user, pendencias=(), corrigir=False):
    """Dicionário pronto para o template _quadro.html e para o JavaScript."""
    editavel_quadro = RP.pode_editar_quadro(user, q)
    master = P.e_master(user)
    cols = calc.colunas_de(q)
    colunas = [{"obj": c, "rotulo": c.rotulo, "travada": c.travada, "atual": c.ano == q.ciclo.ano} for c in cols]
    if q.coluna_total:
        colunas.append({"obj": TOTAL, "rotulo": q.rotulo_total, "travada": False, "total": True})
    por_celula = pendencias_por_celula(pendencias)
    linhas = []
    for li in calc.linhas_de(q):
        celulas = []
        for c in cols + ([TOTAL] if q.coluna_total else []):
            r = calc.celula(q, li.chave, c)
            k = chave_celula(li.pk, c)
            ps = por_celula.get(k, [])
            # anos travados só viram campo quando o Master pede "corrigir anos publicados" neste quadro
            preenchivel = not li.calculada or li.importada
            editavel = (editavel_quadro and preenchivel and c != TOTAL and (not c.travada or (master and corrigir)))
            v = calc.valor_preenchido(li, c) if c != TOTAL and preenchivel else None
            auto = div = None
            if li.importada and c != TOTAL:
                a = calc.automatico(q, li, c)
                auto = "" if (a.erro or a.numero is None) else formato.exibir(li.tipo, a.numero, "", q.casas_decimais)
                div = calc.divergencia(q, li, c)
            if li.importada and editavel:
                edicao = formato.para_edicao(li.tipo, v.numero, "", q.casas_decimais) if v else ""
            else:
                edicao = formato.para_edicao(li.tipo, r.numero, r.texto, q.casas_decimais) if editavel else ""
            celulas.append({
                "importada": li.importada and c != TOTAL, "auto": auto, "digitado": bool(v and v.numero is not None),
                "divergente": bool(div),
                "id": k, "linha_id": li.pk, "coluna_id": None if c == TOTAL else c.pk,
                "editavel": editavel, "travada": c != TOTAL and c.travada,
                "calculada": li.calculada or c == TOTAL,
                "exibido": "⚠" if r.erro else formato.exibir(li.tipo, r.numero, r.texto, q.casas_decimais),
                "edicao": edicao,
                "erro_formula": r.erro,
                "severidade": _pior(ps),
                "mensagens": [p.mensagem for p in ps],
                "justificativa": v.justificativa if v else "",
                "pede_justificativa": any(p.tipo == "variacao" for p in ps),
            })
        linhas.append({"obj": li, "celulas": celulas, "calculada": li.calculada and not li.importada,
                       "importada": li.importada, "tipo": li.tipo})
    if q.linha_total:
        celulas = []
        for c in cols + ([TOTAL] if q.coluna_total else []):
            r = calc.celula(q, TOTAL, c)
            celulas.append({"id": chave_celula(f"t{q.pk}", c), "calculada": True, "editavel": False,
                            "exibido": "⚠" if r.erro else formato.exibir(q.tipo_valor, r.numero, r.texto,
                                                                         q.casas_decimais),
                            "erro_formula": r.erro, "mensagens": [], "severidade": ""})
        linhas.append({"total": True, "rotulo": q.rotulo_total, "celulas": celulas, "calculada": True})
    preenchidas, total_celulas = progresso_quadro(calc, q)
    aguardando, fontes = calculadas_vazias(calc, q)
    return {
        "importadas": any(li.importada for li in calc.linhas_de(q)),
        "q": q, "colunas": colunas, "linhas": linhas, "editavel": editavel_quadro,
        "motivo": RP.motivo_bloqueio(user, q), "setores": q.setores_responsaveis(),
        "pendencias": list(pendencias), "erros": sum(1 for p in pendencias if p.severidade == "erro"),
        "avisos": sum(1 for p in pendencias if p.severidade == "aviso"),
        "faltam": sum(1 for p in pendencias if p.severidade == "falta"),
        "preenchidas": preenchidas, "total_celulas": total_celulas,
        "aguardando": aguardando, "fontes": fontes,
        "tem_texto": q.tipo_valor in (Quadro.TEXTO, Quadro.SIM_NAO),
        "corrigir": corrigir, "pode_corrigir": master and editavel_quadro and any(c.travada for c in cols),
    }


def calculadas_vazias(calc, q):
    """Células calculadas (de colunas abertas) que ainda estão vazias porque os dados de origem não foram
    digitados, e os quadros de onde elas vêm. Evita mostrar "ok" num quadro calculado que está em branco."""
    import re
    abertas = [c for c in calc.colunas_de(q) if not c.travada]
    vazias = 0
    origem = set()
    for li in calc.linhas_de(q):
        if not li.calculada:
            continue
        for c in abertas:
            r = calc.celula(q, li.chave, c)
            if r.vazio and not r.erro:
                vazias += 1
        for chave in re.findall(r"\b([a-z][a-z0-9_]*)\.[a-z]", li.formula or ""):
            if chave != q.chave and chave in calc.quadros:
                origem.add(chave)
    fontes = [calc.quadros[k] for k in sorted(origem)]
    return vazias, fontes


def _pior(ps):
    sevs = {p.severidade for p in ps}
    for s in ("erro", "aviso", "falta"):
        if s in sevs:
            return s
    return ""


def progresso_quadro(calc, q):
    """(células preenchidas, células a preencher) — só as editáveis de colunas não travadas."""
    total = feitas = 0
    for li in calc.linhas_de(q):
        if li.calculada:
            continue
        for c in calc.colunas_de(q):
            if c.travada:
                continue
            total += 1
            v = calc.valor_preenchido(li, c)
            if v is not None and not v.vazio:
                feitas += 1
    return feitas, total


def so_texto(q):
    """Quadro de texto (ex.: metas do PDI): é preenchido no próprio documento, em Escrever o relatório."""
    return q.tipo_valor == "texto"


def progresso_secao(calc, secao, numeros=False):
    """Células preenchidas e total da seção. `numeros`: só os quadros de números (sem os de texto)."""
    feitas = total = 0
    for q in calc.quadros.values():
        if q.secao_id == secao.pk and not (numeros and so_texto(q)):
            f, t = progresso_quadro(calc, q)
            feitas += f
            total += t
    return feitas, total


def percentual(feitas, total):
    return 100 if not total else round(100 * feitas / total)


# --- Blocos do texto -------------------------------------------------------------
def tabela_quadro(calc, q, config=None):
    """Tabela pronta para leitura (tela e Word): cabeçalho e linhas com valores formatados."""
    config = config or {}
    cols = calc.colunas_de(q)
    if config.get("colunas"):
        cols = [c for c in cols if c.chave in config["colunas"]] or cols
    todas = cols + ([TOTAL] if q.coluna_total else [])
    cab = [q.rotulo_total if c == TOTAL else c.rotulo for c in todas]
    linhas = calc.linhas_de(q)
    if config.get("linhas"):
        linhas = [li for li in linhas if li.chave in config["linhas"]] or linhas
    corpo = []
    for li in linhas:
        vals = []
        for c in todas:
            r = calc.celula(q, li.chave, c)
            # ano aberto sem valor: a preencher (texto, como justificativa/evidência das metas, fica em branco)
            vazio = "—" if c == TOTAL or c.travada else ("" if li.tipo == "texto" else "xxxxx")
            vals.append("—" if r.erro else (formato.exibir(li.tipo, r.numero, r.texto, q.casas_decimais) or vazio))
        corpo.append({"rotulo": li.rotulo, "valores": vals, "total": False})
    if q.linha_total and not config.get("sem_total"):
        vals = []
        for c in todas:
            r = calc.celula(q, TOTAL, c)
            vazio = "—" if c == TOTAL or c.travada else "xxxxx"
            vals.append(formato.exibir(q.tipo_valor, r.numero, r.texto, q.casas_decimais) or vazio)
        corpo.append({"rotulo": q.rotulo_total, "valores": vals, "total": True})
    # colunas calculadas só na tabela, ex.: "Empenhadas / dotação (%)" = coluna empenhadas ÷ coluna dotação
    for rz in config.get("razao") or []:
        cab.append(rz.get("rotulo", "%"))
        nums = {c.chave: c for c in cols if c != TOTAL}
        for li, linha in zip(list(linhas) + ([TOTAL] if q.linha_total and not config.get("sem_total") else []), corpo):
            chave = TOTAL if li == TOTAL else li.chave
            a = calc.celula(q, chave, nums[rz["num"]]) if rz.get("num") in nums else None
            b = calc.celula(q, chave, nums[rz["den"]]) if rz.get("den") in nums else None
            if a is None or b is None or a.numero is None or not b.numero:
                linha["valores"].append("—")
            else:
                linha["valores"].append(formato.exibir("percentual", a.numero / b.numero * 100, "", 2))
    return {"cabecalho": cab, "linhas": corpo, "fonte": q.fonte, "texto": q.tipo_valor == "texto"}


def metas_para_editar(calc, q, user):
    """Quadro de texto (metas do PDI) para preencher no documento: para cada linha, o que já se sabe
    (colunas travadas: objetivos, status e justificativa do ano anterior) e os campos do ano."""
    from . import permissoes as RP
    cols = calc.colunas_de(q)
    abertas = [c for c in cols if not c.travada]
    linhas, pode = [], False
    for li in calc.linhas_de(q):
        ref = {}
        for c in cols:
            if c.travada:
                r = calc.celula(q, li.chave, c)
                ref[c.chave] = "" if r.erro else (r.texto or "")
        campos = []
        for c in abertas:
            r = calc.celula(q, li.chave, c)
            ok = RP.pode_editar_celula(user, li, c)
            pode = pode or ok
            campos.append({"l": li.pk, "c": c.pk, "chave": c.chave, "rotulo": c.rotulo, "pode": ok,
                           "valor": "" if r.erro else (r.texto or "")})
        linhas.append({"rotulo": li.rotulo, "ref": ref, "campos": campos, "n": li.ordem,
                       "minha": any(c["pode"] for c in campos),
                       "valores": {c["chave"]: c["valor"] for c in campos}})
    d = {"linhas": linhas, "colunas": abertas, "pode": pode,
         "faltam": sum(1 for x in linhas for c in x["campos"] if not c["valor"].strip())}
    if q.chave == "pdi_metas":
        from .consistencia import SITUACOES_PDI, _metas_pdi
        minhas = {x["n"] for x in linhas if x["minha"]}
        d.update({"pdi2026": True, "situacoes": SITUACOES_PDI, "n_minhas": len(minhas),
                  "faltam": sum(1 for p in _metas_pdi(calc, q, abertas) if p.linha.ordem in minhas)})
    return d


def destaques(calc, config):
    from .texto import resolver
    out = []
    for it in (config or {}).get("itens", []):
        r, tipo, casas, desc = resolver(calc, it.get("ref", ""), it.get("col") or None)
        q = calc.quadros.get((it.get("ref") or "").split(".")[0])
        out.append({"valor": "—" if r.erro else ("xxxxx" if r.vazio else formato.exibir(tipo, r.numero, r.texto, casas)),
                    "quadro_id": q.pk if q else None, "vazio": r.vazio and not r.erro,
                    "rotulo": it.get("rotulo") or desc, "legenda": it.get("legenda", ""), "erro": r.erro,
                    "descricao": desc, "ref": it.get("ref", ""), "col": it.get("col", "")})
    return out


def caixa_na_pagina(b, m):
    """Põe em m (bloco montado) a posição na página do RG: m["caixa"] e m["caixa_css"]."""
    cx = (b.config or {}).get("caixa") if getattr(b, "pagina_id", None) else None
    if not cx:
        return m
    css = f'left:{cx["x"]}px;top:{cx["y"]}px;width:{cx["w"]}px;'
    if b.tipo == "texto":
        css += cx.get("css", "") + (f';background:{cx["fundo"]}' if cx.get("fundo") else "")
    else:
        css += f'height:{cx["h"]}px;background:{cx.get("fundo") or "#fff"}'
    m["caixa"], m["caixa_css"] = cx, css
    return m


def tamanho_na_pagina(b):
    """Gráfico numa página do RG: desenhado do tamanho da área dele na página (em polegadas, 72 pt cada)."""
    cx = (b.config or {}).get("caixa") if getattr(b, "pagina_id", None) else None
    if not cx or b.tipo != "grafico":
        return {}
    titulo = 14 if cx.get("titulo") else 0
    return {"largura": round(cx["w"] / 72, 2), "altura": round(max(60, cx["h"] - titulo) / 72, 2)}


def montar_bloco(calc, b, formato_grafico="svg", largura=7.0, revisao=False, user=None, pode_campos=False,
                 altura=None):
    """`revisao`: mostra as alterações sugeridas ainda pendentes (no editor). Fora dele, vale o texto oficial,
    sem o que ainda não foi aceito."""
    from . import graficos
    from . import revisao as R
    from .models import Bloco
    from .texto import renderizar
    d = {"b": b, "avisos": []}
    q = calc.quadro_por_id.get(b.quadro_id) if b.quadro_id else None
    if b.tipo == Bloco.TEXTO:
        from . import campos as CT
        d["n_alteracoes"] = len(R.itens(b.conteudo))
        valores = CT.valores_do_bloco(b) if b.pk else {}
        html = b.conteudo if revisao else R.base(b.conteudo)
        d["html"], d["problemas"] = renderizar(html, calc, campos=valores, user=user, campos_editaveis=pode_campos)
        d["campos_vazios"] = sum(1 for ch in CT.chaves(html) if valores.get(ch) is None)
    elif b.tipo == Bloco.TABELA:
        if q is None:
            d["avisos"].append("Escolha o quadro desta tabela.")
        else:
            d["tabela"] = tabela_quadro(calc, q, b.config)
            d["quadro"] = q
    elif b.tipo == Bloco.GRAFICO:
        if q is None:
            d["avisos"].append("Escolha o quadro deste gráfico.")
        else:
            cfg = dict(b.config or {}, _altura=altura) if altura else b.config
            d["grafico"], av = graficos.desenhar(calc, q, cfg, "", formato_grafico, largura)
            d["avisos"] += av
            d["quadro"] = q
    elif b.tipo == Bloco.DESTAQUES:
        d["destaques"] = destaques(calc, b.config)
        if not d["destaques"]:
            d["avisos"].append("Escolha os números em destaque.")
    d["origens"] = origens_do_bloco(calc, b)
    return d


def origens_do_bloco(calc, b):
    """De quais quadros (e de que seção e setor) vêm os números de uma tabela, gráfico ou painel."""
    if b.quadro_id:
        chaves = [calc.quadro_por_id[b.quadro_id].chave] if b.quadro_id in calc.quadro_por_id else []
        linha = (b.config or {}).get("linha")      # série desenhada como linha que vem de outro quadro
        ch2 = linha.split(".")[0] if isinstance(linha, str) and "." in linha else None
        if ch2 and ch2 in calc.quadros and ch2 not in chaves:
            chaves.append(ch2)
    else:
        chaves = []
        for it in (b.config or {}).get("itens", []):
            ch = (it.get("ref") or "").split(".")[0]
            if ch in calc.quadros and ch not in chaves:
                chaves.append(ch)
    return [{"quadro": calc.quadros[ch], "secao": calc.quadros[ch].secao,
             "setores": calc.quadros[ch].setores_responsaveis()} for ch in chaves]


def usos_dos_quadros(ciclo, calc):
    """Onde os números de cada quadro aparecem no relatório: tabelas, gráficos e painéis (com a seção),
    números citados nos textos e outros quadros que fazem conta com eles. {chave: {...}}"""
    import re

    from .models import Bloco
    usos = {ch: {"blocos": [], "textos": [], "calculos": []} for ch in calc.quadros}
    for b in Bloco.objects.filter(secao__ciclo=ciclo).select_related("secao", "secao__pai", "quadro"):
        if b.tipo == Bloco.TEXTO:
            for ch in set(re.findall(r'data-ref="([a-z0-9_]+)\.', b.conteudo or "")):
                if ch in usos and b.secao not in usos[ch]["textos"]:
                    usos[ch]["textos"].append(b.secao)
            continue
        nome = b.titulo or {"tabela": "tabela", "grafico": "gráfico", "destaques": "números em destaque"}.get(b.tipo, "")
        for o in origens_do_bloco(calc, b):
            usos[o["quadro"].chave]["blocos"].append({"secao": b.secao, "nome": nome, "tipo": b.tipo})
    for q in calc.quadros.values():
        for li in calc.linhas_de(q):
            for ch in set(re.findall(r"\b([a-z][a-z0-9_]*)\.", li.formula or "")):
                if ch in usos and ch != q.chave and q not in usos[ch]["calculos"]:
                    usos[ch]["calculos"].append(q)
    return usos
