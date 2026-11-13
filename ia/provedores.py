"""
Cliente para modelos de IA com API compatível com OpenAI (DeepSeek, Gemini, OpenAI...).

Também há o provedor "simulado", que não chama nenhuma IA: serve para testar a
plataforma sem chave de API (e é usado nos testes automáticos).
"""
import json
import logging
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from decimal import Decimal

log = logging.getLogger("sirg")


class ErroIA(Exception):
    """Erro com mensagem amigável para mostrar ao usuário."""


@dataclass
class Resposta:
    texto: str = ""
    chamadas: list = field(default_factory=list)   # [{"id", "nome", "argumentos"(dict), "bruto"(str)}]
    tokens_entrada: int = 0
    tokens_saida: int = 0
    tokens_cache: int = 0
    duracao_ms: int = 0


# Simulador substituível (os testes registram uma função própria aqui)
_simulador = None


def registrar_simulador(funcao):
    """funcao(perfil, mensagens, ferramentas) -> Resposta"""
    global _simulador
    _simulador = funcao


def chamar(perfil, mensagens, ferramentas=None):
    inicio = time.monotonic()
    if perfil.provedor == "simulado":
        r = (_simulador or _simulador_padrao)(perfil, mensagens, ferramentas)
        r.duracao_ms = int((time.monotonic() - inicio) * 1000)
        return r
    if not perfil.chave:
        log.error("IA: chave de API do provedor '%s' não configurada no .env", perfil.provedor)
        raise ErroIA("O serviço de IA não está configurado no servidor. Avise o administrador da plataforma.")
    corpo = {
        "model": perfil.modelo,
        "messages": mensagens,
        "temperature": perfil.temperatura,
        "max_tokens": perfil.max_tokens,
    }
    if ferramentas:
        corpo["tools"] = [{"type": "function", "function": f} for f in ferramentas]
        corpo["tool_choice"] = "auto"
    corpo.update(perfil.extras.get("parametros_extras", {}) or {})
    url = f"{perfil.base_url}/chat/completions"
    dados = json.dumps(corpo, ensure_ascii=False).encode("utf-8")
    ultimo_erro = None
    for tentativa in range(3):
        req = urllib.request.Request(url, data=dados, method="POST", headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {perfil.chave}",
        })
        try:
            with urllib.request.urlopen(req, timeout=perfil.timeout) as resp:
                js = json.loads(resp.read().decode("utf-8"))
            break
        except urllib.error.HTTPError as ex:
            corpo_erro = ex.read().decode("utf-8", "replace")[:500]
            log.warning("IA %s HTTP %s: %s", perfil.provedor, ex.code, corpo_erro)
            ultimo_erro = ex
            if ex.code in (429, 500, 502, 503, 504) and tentativa < 2:
                time.sleep(2 * (tentativa + 1))
                continue
            extras = perfil.extras.get("parametros_extras", {}) or {}
            if ex.code == 400 and extras and any(k in corpo for k in extras) and tentativa < 2:
                # o modelo pode não aceitar algum parâmetro extra (ex.: reasoning_effort): tenta sem eles
                log.warning("IA: repetindo sem os parâmetros extras %s", list(extras))
                for k in extras:
                    corpo.pop(k, None)
                dados = json.dumps(corpo, ensure_ascii=False).encode("utf-8")
                continue
            # mensagens genéricas: o detalhe (provedor, modelo, resposta) fica só no log do servidor
            if ex.code in (401, 403):
                raise ErroIA("O serviço de IA recusou o acesso (credencial do servidor). Avise o administrador da plataforma.")
            if ex.code == 402:
                raise ErroIA("O serviço de IA está sem créditos. Avise o administrador da plataforma.")
            if ex.code == 429:
                raise ErroIA("O serviço de IA está ocupado agora. Tente de novo em instantes.")
            raise ErroIA(f"O serviço de IA não conseguiu responder (erro {ex.code}). Tente de novo; se persistir, "
                         f"avise o administrador da plataforma.")
        except (urllib.error.URLError, TimeoutError, OSError) as ex:
            ultimo_erro = ex
            log.warning("IA %s falha de conexão: %s", perfil.provedor, ex)
            if tentativa < 2:
                time.sleep(2 * (tentativa + 1))
                continue
            raise ErroIA("Não foi possível conectar ao serviço de IA. Verifique a internet do servidor ou "
                         "tente de novo em instantes.")
    else:  # pragma: no cover
        log.error("IA: falha após tentativas: %s", ultimo_erro)
        raise ErroIA("O serviço de IA não respondeu. Tente de novo em instantes.")

    try:
        msg = js["choices"][0]["message"]
    except (KeyError, IndexError):
        log.error("IA: resposta inesperada: %s", str(js)[:500])
        raise ErroIA("O serviço de IA devolveu uma resposta inesperada. Tente de novo.")
    r = Resposta(texto=msg.get("content") or "")
    for tc in msg.get("tool_calls") or []:
        fn = tc.get("function", {})
        bruto = fn.get("arguments") or "{}"
        try:
            args = json.loads(bruto) if isinstance(bruto, str) else bruto
        except json.JSONDecodeError:
            args = {"_erro_json": bruto}
        r.chamadas.append({"id": tc.get("id", ""), "nome": fn.get("name", ""), "argumentos": args,
                           "bruto": bruto if isinstance(bruto, str) else json.dumps(bruto, ensure_ascii=False)})
    uso = js.get("usage") or {}
    r.tokens_entrada = int(uso.get("prompt_tokens") or 0)
    r.tokens_saida = int(uso.get("completion_tokens") or 0)
    r.tokens_cache = int(uso.get("prompt_cache_hit_tokens") or
                         (uso.get("prompt_tokens_details") or {}).get("cached_tokens") or 0)
    r.duracao_ms = int((time.monotonic() - inicio) * 1000)
    return r


def em_horario_de_pico(perfil, quando=None):
    """True se 'quando' (UTC) cai no horário de pico do provedor (segunda a sexta)."""
    if not perfil.pico_utc:
        return True
    from datetime import datetime, timezone as tz
    quando = quando or datetime.now(tz.utc)
    if quando.weekday() >= 5:
        return False
    hm = quando.hour * 60 + quando.minute
    for faixa in perfil.pico_utc:
        try:
            a, b = [int(x.split(":")[0]) * 60 + int(x.split(":")[1]) for x in faixa.split("-")]
        except (ValueError, IndexError):
            continue
        if a <= hm < b:
            return True
    return False


def custo(perfil, r, quando=None):
    cache = min(r.tokens_cache or 0, r.tokens_entrada)
    p_cache = perfil.preco_cache if perfil.preco_cache >= 0 else perfil.preco_entrada
    v = (Decimal(r.tokens_entrada - cache) * Decimal(str(perfil.preco_entrada)) +
         Decimal(cache) * Decimal(str(p_cache)) +
         Decimal(r.tokens_saida) * Decimal(str(perfil.preco_saida))) / Decimal(1_000_000)
    if not em_horario_de_pico(perfil, quando):
        v *= Decimal(str(perfil.fator_fora_pico))
    return v.quantize(Decimal("0.000001"))


def _simulador_padrao(perfil, mensagens, ferramentas):
    """Sem IA: devolve o texto recebido (entre <texto> e </texto>) sem mudanças — útil para testar o fluxo."""
    ultimo = str(mensagens[-1].get("content", "")) if mensagens else ""
    ini, fim = ultimo.find("<texto>"), ultimo.find("</texto>")
    texto = ultimo[ini + 7:fim].strip() if ini >= 0 and fim > ini else "<p>Modo simulado: nenhuma IA configurada.</p>"
    if "CONFERIR" in ultimo:
        texto = '{"problemas": []}'
    return Resposta(texto=texto, tokens_entrada=sum(len(str(m.get("content", ""))) // 4 for m in mensagens),
                    tokens_saida=len(texto) // 4)
