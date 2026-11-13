"""
Assistente SiRG: ajuda a escrever, revisar e conferir os textos do relatório.

Garantias (independentes do que o modelo responder):
  - O resultado NUNCA é aplicado sozinho: volta como sugestão, com a diferença destacada,
    e o usuário decide se aplica no editor (e ainda precisa salvar).
  - Os números vivos viajam como marcadores {{num:referência}}; na volta, só são aceitos
    marcadores que existiam nos dados enviados. Número inventado não entra.
  - Todo HTML devolvido passa pela mesma limpeza do editor.
  - Só vão para a IA o texto do trecho e os números agregados dos quadros da seção
    (nada de dados pessoais da plataforma).
"""
import json
import re
from decimal import Decimal

from relatorio import formato
from relatorio.calculo import TOTAL
from relatorio.html_seguro import limpar, texto_puro
from relatorio.texto import PADRAO, referencias

from . import blindagem, config, provedores
from .uso import chamar_e_registrar

ACOES = {
    "revisar": ("Revisar português",
                "Corrija ortografia, gramática, concordância, regência, crase e pontuação do texto abaixo. Não mude o "
                "sentido, a estrutura, os títulos nem o estilo; não acrescente nem remova informações. Devolva o texto "
                "completo corrigido."),
    "simplificar": ("Linguagem simples",
                    "Reescreva o texto em linguagem simples, para o cidadão comum: frases curtas, ordem direta, voz "
                    "ativa, sem jargões (explique as siglas na primeira vez que aparecem). Mantenha todas as "
                    "informações e todos os marcadores {{num:...}}."),
    "resumir": ("Encurtar",
                "Reescreva o texto de forma mais concisa, com cerca de metade do tamanho, mantendo as informações mais "
                "relevantes e os marcadores {{num:...}} dos números mais importantes."),
    "formalizar": ("Tom institucional",
                   "Ajuste o texto ao tom de um Relatório de Gestão apresentado ao TCU e à sociedade: impessoal, "
                   "objetivo, sem adjetivos exagerados nem primeira pessoa do singular. Mantenha as informações e os "
                   "marcadores."),
    "analisar": ("Escrever análise dos dados",
                 "Com base SOMENTE nos dados fornecidos, escreva uma breve análise (2 a 4 parágrafos curtos) para esta "
                 "seção do Relatório de Gestão: evolução em relação aos anos anteriores, resultados de destaque e "
                 "pontos de atenção. Sempre que citar um valor dos dados, use o marcador {{num:...}} correspondente "
                 "em vez de escrever o número. Variações percentuais que você calcular podem ser escritas por extenso "
                 "(ex.: “cerca de 10%”). Se o texto atual não estiver vazio, use-o como contexto e não o repita: "
                 "devolva só a análise nova."),
    "conferir": ("Conferir texto × dados",
                 "CONFERIR. Compare as afirmações do texto com os dados fornecidos. Aponte: números escritos à mão que "
                 "divergem dos dados; afirmações de crescimento, redução ou recorde que os dados não sustentam; anos ou "
                 "indicadores trocados; informações que parecem desatualizadas (ex.: ano anterior citado como atual). "
                 "Não aponte questões de estilo. Responda SOMENTE em JSON, no formato "
                 '{"problemas": [{"trecho": "...", "problema": "...", "sugestao": "..."}]}. '
                 'Se não houver problemas, responda {"problemas": []}.'),
    "livre": ("Pedido livre", ""),
}

MARCADOR = re.compile(r"\{\{\s*num:([a-z0-9_.]+)(?:\|([a-z0-9_]+))?\s*\}\}")


class ErroAssistente(Exception):
    pass


# --- marcadores <-> números vivos -------------------------------------------------
def para_marcadores(html):
    return PADRAO.sub(lambda m: "{{num:" + m.group(1) + (f"|{m.group(2)}" if m.group(2) else "") + "}}", html or "")


def de_marcadores(texto, permitidas):
    """Troca {{num:ref}} pelo <span> do número vivo. Referências fora da lista são descartadas."""
    descartadas = []

    def troca(m):
        ref, col = m.group(1), m.group(2)
        if (ref, col or None) in permitidas or (ref, None) in permitidas and not col:
            c = f' data-col="{col}"' if col else ""
            return f'<span class="sirg-num" data-ref="{ref}"{c}>…</span>'
        descartadas.append(ref + (f"|{col}" if col else ""))
        return "[número removido]"

    return MARCADOR.sub(troca, texto or ""), descartadas


# --- contexto de dados -------------------------------------------------------------
def contexto_dados(calc, secao, html_atual):
    """Texto com os quadros da seção (e os citados no texto), cada valor com seu marcador."""
    refs_texto = {ref.split(".")[0] for ref, _ in referencias(html_atual)}
    quadros = [q for q in calc.quadros.values() if q.secao_id == secao.pk or q.chave in refs_texto]
    quadros.sort(key=lambda q: (q.secao_id != secao.pk, q.ordem, q.pk))
    linhas_saida, permitidas = [], set()
    for q in quadros[:14]:
        cols = calc.colunas_de(q)
        linhas_saida.append(f"\n## {q.titulo}" + (f" (fonte: {q.fonte})" if q.fonte else "") +
                            (f"\nDefinição: {q.descricao.strip()}" if q.descricao.strip() else ""))
        itens = [(li.chave, li.rotulo, li.tipo) for li in calc.linhas_de(q)]
        if q.linha_total:
            itens.append((TOTAL, q.rotulo_total, q.tipo_valor))
        for chave, rot, tipo in itens:
            if tipo in ("texto", "sim_nao"):
                valores = []
                for c in cols:
                    r = calc.celula(q, chave, c)
                    valores.append(f"{c.rotulo}: {formato.exibir(tipo, r.numero, r.texto) or 'vazio'}")
                linhas_saida.append(f"- {rot}: " + "; ".join(valores))
                continue
            partes = []
            for c in cols + ([TOTAL] if q.coluna_total else []):
                r = calc.celula(q, chave, c)
                if c == TOTAL:
                    col_chave, rotulo = TOTAL, q.rotulo_total
                else:
                    col_chave, rotulo = c.chave, c.rotulo
                base = c != TOTAL and c.ano == calc.ciclo.ano
                ref = f"{q.chave}.{chave}"
                marcador = "{{num:" + ref + ("" if base else f"|{col_chave}") + "}}"
                permitidas.add((ref, None if base else col_chave))
                valor = formato.exibir(tipo, r.numero, r.texto, q.casas_decimais) if r.numero is not None else "vazio"
                partes.append(f"{rotulo}: {valor} {marcador}")
            linhas_saida.append(f"- {rot}: " + "; ".join(partes))
    for ref, col in referencias(html_atual):
        permitidas.add((ref, col))
    return "\n".join(linhas_saida).strip(), permitidas


# --- chamada --------------------------------------------------------------------------
def executar(user, acao, html, calc, secao, instrucao="", bloco=None):
    if acao not in ACOES:
        raise ErroAssistente("Ação desconhecida.")
    try:
        perfil = config.perfil("assistente")
    except config.ErroConfigIA as ex:
        raise ErroAssistente(f"O Assistente não está configurado no servidor ({ex}). Avise o administrador.")
    if not perfil.ativo:
        raise ErroAssistente("O Assistente SiRG está desativado pelo administrador.")
    limite = int(config.limites().get("max_caracteres_texto", 30000) or 30000)
    texto_base = para_marcadores(limpar(html))
    if len(texto_base) > limite:
        raise ErroAssistente(f"O trecho é longo demais para o Assistente de uma vez ({len(texto_base):,} caracteres; "
                             f"limite {limite:,}). Divida em blocos menores.".replace(",", "."))
    if acao in ("revisar", "simplificar", "resumir", "formalizar", "conferir") and not texto_puro(html).strip():
        raise ErroAssistente("O trecho está vazio.")
    instrucao = (instrucao or "").strip()
    if acao == "livre":
        if not instrucao:
            raise ErroAssistente("Escreva o que você quer que o Assistente faça.")
        if blindagem.pergunta_sobre_identidade(instrucao):
            return {"identidade": True, "mensagem": blindagem.RESPOSTA_IDENTIDADE}
        pedido = ("Faça o que o usuário pede abaixo com o texto (ou escreva o texto pedido). Devolva o texto completo "
                  f"resultante.\nPedido do usuário: {instrucao[:1500]}")
    else:
        pedido = ACOES[acao][1]
    dados, permitidas = contexto_dados(calc, secao, html)
    secao_desc = f"{secao.pai.titulo} › {secao.titulo}" if secao.pai else secao.titulo
    conteudo = (f"Relatório: {calc.ciclo.titulo} (ano-base {calc.ciclo.ano}). Seção: {secao_desc}.\n\n"
                f"TAREFA: {pedido}\n\n"
                f"DADOS DA SEÇÃO (use só estes; os marcadores entre chaves duplas são os números vivos):\n"
                f"{dados or '(esta seção não tem quadros de dados)'}\n\n"
                f"<texto>\n{texto_base or '<p></p>'}\n</texto>")
    mensagens = [{"role": "system", "content": perfil.prompt}, {"role": "user", "content": conteudo}]
    try:
        r, uso = chamar_e_registrar(user, perfil, mensagens, acao, bloco)
    except provedores.ErroIA as ex:
        raise ErroAssistente(str(ex))
    saida = _sem_cercas(r.texto)
    saida = blindagem.limpar_texto(saida)
    if acao == "conferir":
        return {"problemas": _problemas(saida), "uso": uso.pk, "tokens": uso.tokens_total}
    if "<" not in saida:
        saida = "".join(f"<p>{p.strip()}</p>" for p in re.split(r"\n\s*\n", saida) if p.strip())
    html_novo, descartadas = de_marcadores(saida, permitidas)
    html_novo = limpar(html_novo)
    avisos = []
    if descartadas:
        avisos.append(f"O Assistente tentou usar {len(descartadas)} número(s) que não existem nos dados; eles foram "
                      f"removidos e marcados como “[número removido]”.")
    if acao != "analisar":
        perdidos = {ref for ref, _ in referencias(texto_base and limpar(html))} - {ref for ref, _ in referencias(html_novo)}
        if perdidos and acao in ("revisar", "formalizar", "simplificar"):
            avisos.append(f"Atenção: {len(perdidos)} número(s) vivo(s) do texto original não aparecem na sugestão.")
    return {"html": html_novo, "avisos": avisos, "uso": uso.pk, "tokens": uso.tokens_total}


def _sem_cercas(t):
    t = (t or "").strip()
    t = re.sub(r"^```[a-zA-Z]*\s*", "", t)
    t = re.sub(r"\s*```$", "", t)
    t = re.sub(r"^\s*<texto>\s*|\s*</texto>\s*$", "", t)
    return t.strip()


def _problemas(saida):
    m = re.search(r"\{.*\}", saida, re.S)
    try:
        dados = json.loads(m.group(0) if m else saida)
        itens = dados.get("problemas", []) if isinstance(dados, dict) else []
    except (ValueError, AttributeError):
        return [{"trecho": "", "problema": "O Assistente devolveu uma resposta fora do formato. Tente de novo.",
                 "sugestao": ""}]
    out = []
    for it in itens[:30]:
        if isinstance(it, dict):
            out.append({k: blindagem.limpar_texto(str(it.get(k, "")))[:600] for k in ("trecho", "problema", "sugestao")})
    return out


# --- sem IA: ligar números digitados aos quadros --------------------------------------------
ESPELHO = re.compile(r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)?$")
NUM_TEXTO = re.compile(r"(?<![\w.,])(R\$\s?)?(\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d+,\d+|\d{2,})(\s?%)?(?![\w])")


def numeros_digitados(html, calc):
    """Números escritos à mão no texto que batem exatamente com um valor do ano-base de algum quadro."""
    partes = re.split(r"(<span class=\"sirg-num\"[^>]*>.*?</span>|<[^>]+>)", html or "", flags=re.S)
    indice = _indice_valores(calc)
    achados = []
    for p in partes:
        if not p or p.startswith("<"):
            continue
        for m in NUM_TEXTO.finditer(p):
            try:
                n = formato.ler_numero(m.group(2))
            except formato.EntradaInvalida:
                continue
            if 1900 <= n <= 2100 and "," not in m.group(2) and "." not in m.group(2):
                continue            # provavelmente um ano
            cands = indice.get(_chave_num(n), [])
            achados.append({"texto": m.group(0), "valor": str(n), "candidatos": cands[:6]})
    return achados


def _chave_num(n):
    return str(Decimal(n).quantize(Decimal("0.01")))


def _indice_valores(calc):
    idx = {}
    for q in calc.quadros.values():
        cols = calc.colunas_de(q)
        alvo = next((c for c in cols if c.ano == calc.ciclo.ano), None) or (cols[0] if len(cols) == 1 else None)
        if alvo is None:
            continue
        # linhas que só espelham outro quadro (ex.: "ga_matriculados.total") não são candidatas:
        # o número vivo deve apontar para a fonte original
        itens = [(li.chave, li.rotulo) for li in calc.linhas_de(q) if not ESPELHO.match(li.formula.strip())]
        if q.linha_total:
            itens.append((TOTAL, q.rotulo_total))
        for chave, rot in itens:
            r = calc.celula(q, chave, alvo)
            if r.numero is not None and r.numero != 0:
                idx.setdefault(_chave_num(r.numero), []).append(
                    {"ref": f"{q.chave}.{chave}", "col": "" if alvo.ano == calc.ciclo.ano else alvo.chave,
                     "descricao": f"{q.titulo} › {rot} ({alvo.rotulo})"})
    return idx


def ligar_numeros(html, calc, escolhas=None):
    """Troca números digitados por números vivos. `escolhas` = {texto_do_numero: "ref|col"};
    sem escolha, só os números com UM candidato são ligados."""
    escolhas = escolhas or {}
    indice = _indice_valores(calc)
    ligados = []

    def no_texto(trecho):
        def troca(m):
            try:
                n = formato.ler_numero(m.group(2))
            except formato.EntradaInvalida:
                return m.group(0)
            if 1900 <= n <= 2100 and "," not in m.group(2) and "." not in m.group(2):
                return m.group(0)
            escolha = escolhas.get(m.group(0))
            cands = indice.get(_chave_num(n), [])
            if escolha:
                ref, _, col = escolha.partition("|")
            elif len(cands) == 1:
                ref, col = cands[0]["ref"], cands[0]["col"]
            else:
                return m.group(0)
            ligados.append(m.group(0))
            c = f' data-col="{col}"' if col else ""
            return f'<span class="sirg-num" data-ref="{ref}"{c}>{m.group(0)}</span>'
        return NUM_TEXTO.sub(troca, trecho)

    partes = re.split(r"(<span class=\"sirg-num\"[^>]*>.*?</span>|<[^>]+>)", html or "", flags=re.S)
    novo = "".join(p if (not p or p.startswith("<")) else no_texto(p) for p in partes)
    return limpar(novo), ligados
