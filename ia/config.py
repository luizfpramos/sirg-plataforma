"""
Leitura da configuração da IA do SiRG (config_ia/ia.toml + prompts + chaves no .env).

O arquivo é relido sempre que for modificado: dá para trocar provedor, modelo,
limites e prompts com a plataforma rodando.
"""
import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from django.conf import settings


class ErroConfigIA(Exception):
    pass


_cache = {"assinatura": None, "dados": None}


def _arquivo():
    return Path(settings.SIRG_IA_CONFIG)


def _ler_env():
    """Lê o .env a cada carga, para que uma chave nova valha sem reiniciar."""
    valores = dict(os.environ)
    env = Path(settings.BASE_DIR) / ".env"
    if env.exists():
        try:
            from dotenv import dotenv_values
            valores.update({k: v for k, v in dotenv_values(env).items() if v is not None})
        except ImportError:
            pass
    return valores


def carregar():
    arq = _arquivo()
    if not arq.exists():
        raise ErroConfigIA(f"Arquivo de configuração da IA não encontrado: {arq}")
    pasta = arq.parent
    arquivos = [arq] + sorted((pasta / "prompts").glob("*.md")) + [Path(settings.BASE_DIR) / ".env"]
    assinatura = tuple((str(a), a.stat().st_mtime) for a in arquivos if a.exists())
    if _cache["assinatura"] == assinatura:
        return _cache["dados"]
    try:
        dados = tomllib.loads(arq.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as ex:
        raise ErroConfigIA(f"Erro de sintaxe em {arq.name}: {ex}")
    dados["_pasta"] = str(pasta)
    dados["_env"] = _ler_env()
    _cache.update(assinatura=assinatura, dados=dados)
    return dados


@dataclass
class Perfil:
    nome: str                      # assistente
    ativo: bool
    provedor: str
    modelo: str
    base_url: str
    chave: str
    temperatura: float
    max_tokens: int
    timeout: int
    prompt: str
    preco_entrada: float
    preco_saida: float
    moeda: str
    extras: dict = field(default_factory=dict)
    preco_cache: float = -1.0                 # -1 = mesmo preço da entrada normal
    pico_utc: list = field(default_factory=list)
    fator_fora_pico: float = 1.0


def perfil(nome):
    dados = carregar()
    sec = dados.get(nome)
    if not sec:
        raise ErroConfigIA(f"Seção [{nome}] não encontrada em ia.toml.")
    prov_nome = sec.get("provedor", "deepseek")
    prov = dados.get("provedores", {}).get(prov_nome)
    if prov is None:
        raise ErroConfigIA(f"Provedor '{prov_nome}' não está configurado em [provedores.{prov_nome}].")
    chave = dados["_env"].get(prov.get("chave_env", ""), "") if prov.get("chave_env") else ""
    prompt_arq = Path(dados["_pasta"]) / sec.get("prompt", f"prompts/{nome}.md")
    prompt = prompt_arq.read_text(encoding="utf-8") if prompt_arq.exists() else ""
    return Perfil(
        nome=nome,
        ativo=bool(sec.get("ativo", True)),
        provedor=prov_nome,
        modelo=sec.get("modelo", ""),
        base_url=prov.get("base_url", "").rstrip("/"),
        chave=chave,
        temperatura=float(sec.get("temperatura", 0.2)),
        max_tokens=int(sec.get("max_tokens_resposta", 2000)),
        timeout=int(prov.get("timeout_segundos", 180)),
        prompt=prompt,
        preco_entrada=float(prov.get("preco_entrada_por_milhao", 0) or 0),
        preco_saida=float(prov.get("preco_saida_por_milhao", 0) or 0),
        moeda=prov.get("moeda", "USD"),
        extras={k: v for k, v in sec.items()},
        preco_cache=float(prov.get("preco_entrada_cache_por_milhao", -1)),
        pico_utc=list(prov.get("horario_pico_utc", []) or []),
        fator_fora_pico=float(prov.get("fator_fora_do_pico", 1.0) or 1.0),
    )


def limites():
    return carregar().get("limites", {})


def resumo_publico():
    """Informações que podem aparecer na tela (sem chaves)."""
    out = {}
    for nome in ("assistente",):
        try:
            p = perfil(nome)
            out[nome] = {"ativo": p.ativo, "provedor": p.provedor, "modelo": p.modelo,
                         "chave_configurada": bool(p.chave) or p.provedor == "simulado"}
        except ErroConfigIA as ex:
            out[nome] = {"ativo": False, "erro": str(ex)}
    return out


def pode_ver_uso(user):
    """Consumo de tokens de todos: administradores da plataforma."""
    from contas.permissoes import e_admin
    return e_admin(user)
