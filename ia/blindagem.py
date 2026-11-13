"""
Blindagem do Assistente SiRG.

O assistente se apresenta sempre e somente como "Assistente SiRG". Três camadas:

1. Perguntas sobre a identidade/tecnologia do assistente (modelo, empresa, versão,
   instruções internas...) recebem uma resposta padrão, SEM chamar a IA.
2. As instruções (config_ia/prompts/*.md) proíbem revelar esses dados.
3. Toda resposta é conferida antes de ir para a tela: se mencionar provedores,
   modelos, arquivos de configuração ou chaves, é substituída pela resposta padrão
   (no chat) ou tem os termos removidos (no resumo do agente).
"""
import logging
import re
import unicodedata

log = logging.getLogger("sirg")

RESPOSTA_IDENTIDADE = (
    "Sou o **Assistente SiRG**, o assistente da Plataforma SiRG. "
    "Não tenho como informar detalhes sobre a tecnologia que uso.\n\n"
    "Posso ajudar a escrever, revisar e conferir os textos do Relatório de Gestão."
)

# Termos que nunca podem aparecer numa resposta
RE_VAZAMENTO = re.compile(
    r"deep\s?seek|gemini|open\s?ai|chat\s?gpt|\bgpt[\s\-]?\d|\bo[134]-mini\b|anthropic|\bclaude\b|\bllama\b|"
    r"\bqwen\b|\bmistral\b|\bcopilot\b|\bbard\b|\bgrok\b|config_ia|ia\.toml|prompts/(?:chat|agente)\.md|"
    r"[A-Z]+_API_KEY|system\s?prompt|prompt do sistema",
    re.I)

_IDENTIDADE = [
    r"\b(qual|que)\s+(e\s+)?(o\s+)?(seu\s+)?modelo\s+(de\s+(ia|linguagem|inteligencia artificial)\s+)?(voce|vc|tu)\b",
    r"\b(voce|vc)\s+(e|eh)\s+(qual|que)\s+(modelo|ia|inteligencia)",
    r"\bseu\s+(modelo|criador|fabricante|fornecedor|provedor|desenvolvedor|prompt)\b",
    r"\bmodelo\s+de\s+(ia|linguagem|llm|inteligencia artificial)\b",
    r"\b(qual|que)\s+(ia|llm|inteligencia artificial)\s+(e\s+)?(voce|vc|esta|e essa|usa|roda)",
    r"\b(voce|vc)\s+(e|eh|usa|roda|funciona com|foi feito com|e baseado (em|no|na))\s+(o\s+|a\s+)?"
    r"(chat\s?gpt|gpt|gemini|deep\s?seek|claude|llama|copilot|bard|qwen|mistral|grok|openai|google|meta|anthropic)",
    r"\bquem\s+(te\s+)?(criou|desenvolveu|treinou|fez|programou)\b",
    r"\bqual\s+(e\s+)?(a\s+)?(empresa|versao|tecnologia|api)\s+(por tras|que|de ia|do assistente|voce)",
    r"\b(provedor|fornecedor)\s+(de|da)\s+(ia|inteligencia artificial)\b",
    r"\b(suas|as)\s+instrucoes\s+(internas|do sistema|iniciais|originais)\b",
    r"\b(mostre|revele|repita|imprima|liste|diga)\s+(o\s+|as\s+|suas\s+|seu\s+)?(prompt|instrucoes)\b",
    r"\b(ignore|desconsidere|esqueca)\s+(as\s+|todas as\s+|suas\s+)?(instrucoes|regras|orientacoes)\b",
    r"\bsystem\s?prompt\b",
    r"\bversao\s+(do|da|de)\s+(seu\s+|sua\s+)?(modelo|ia|llm|inteligencia)",
    r"\bmodelo\s+que\s+(voce|vc)\s+(usa|utiliza|e|roda)\b",
    r"\bwhat\s+(model|llm|ai)\s+are\s+you\b|\bwho\s+(made|created|built|trained)\s+you\b|\bare\s+you\s+(chat\s?gpt|gpt|gemini|claude|deepseek)\b",
]
RE_IDENTIDADE = re.compile("|".join(_IDENTIDADE))


def _normalizar(texto):
    t = unicodedata.normalize("NFD", (texto or "").lower())
    return "".join(c for c in t if unicodedata.category(c) != "Mn")


def pergunta_sobre_identidade(texto):
    return bool(RE_IDENTIDADE.search(_normalizar(texto)))


def vaza(texto):
    return bool(RE_VAZAMENTO.search(texto or ""))


def filtrar_resposta_chat(texto):
    """Resposta do chat: se mencionar a tecnologia, troca pela resposta padrão."""
    if vaza(texto):
        log.warning("Blindagem: resposta do assistente bloqueada (mencionava a tecnologia de IA)")
        return RESPOSTA_IDENTIDADE
    return texto


def limpar_texto(texto):
    """Textos do agente (resumo, justificativas): remove só os termos proibidos."""
    if not texto or not vaza(texto):
        return texto
    log.warning("Blindagem: termos removidos de um texto do agente")
    return RE_VAZAMENTO.sub("[omitido]", texto)
