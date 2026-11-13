"""Leitura e exibição de valores no padrão brasileiro (1.234,56 · R$ · %)."""
import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from .models import Quadro

SIM = {"sim", "s", "x", "√", "✓", "1", "yes", "true", "verdadeiro"}
NAO = {"não", "nao", "n", "0", "no", "false", "falso", "-"}


class EntradaInvalida(ValueError):
    pass


def ler(tipo, texto):
    """Converte o que o usuário digitou em (numero, texto). Vazio -> (None, "")."""
    s = (str(texto) if texto is not None else "").strip()
    if s == "":
        return None, ""
    if tipo == Quadro.TEXTO:
        return None, s[:500]
    if tipo == Quadro.SIM_NAO:
        b = s.lower()
        if b in SIM:
            return None, "sim"
        if b in NAO:
            return None, "nao"
        raise EntradaInvalida("Responda Sim ou Não.")
    n = ler_numero(s)
    if tipo == Quadro.INTEIRO and n != n.to_integral_value():
        raise EntradaInvalida("Informe um número inteiro (sem casas decimais).")
    return n, ""


def ler_numero(s):
    if isinstance(s, (int, float, Decimal)):
        return Decimal(str(s))
    t = s.strip().replace("R$", "").replace("%", "").replace(" ", "").replace(" ", "")
    negativo = t.startswith("-") or (t.startswith("(") and t.endswith(")"))
    t = t.strip("-()")
    if not t or not re.fullmatch(r"[0-9.,]+", t):
        raise EntradaInvalida("Informe um número (ex.: 1.234 ou 1.234,56).")
    if "," in t:
        if t.count(",") > 1:
            raise EntradaInvalida("Número com mais de uma vírgula.")
        inteiro, dec = t.split(",")
        t = inteiro.replace(".", "") + "." + dec
    elif t.count(".") > 1 or re.fullmatch(r"\d{1,3}\.\d{3}", t):
        t = t.replace(".", "")           # 1.234 ou 1.234.567 = separador de milhar
    try:
        n = Decimal(t)
    except InvalidOperation:
        raise EntradaInvalida("Número inválido.")
    return -n if negativo else n


def numero_br(n, casas=0):
    if n is None:
        return ""
    casas = int(casas or 0)
    q = Decimal(1).scaleb(-casas)
    n = Decimal(n).quantize(q, rounding=ROUND_HALF_UP)
    s = f"{abs(n):,.{casas}f}"                 # 1,234.56
    s = s.replace(",", "§").replace(".", ",").replace("§", ".")
    return ("-" if n < 0 else "") + s


def exibir(tipo, numero=None, texto="", casas=2):
    """Texto para a tela e para o Word."""
    if tipo == Quadro.SIM_NAO:
        return {"sim": "Sim", "nao": "Não"}.get(texto, texto or "")
    if tipo == Quadro.TEXTO:
        return texto or ""
    if numero is None:
        return texto or ""
    if tipo == Quadro.INTEIRO:
        return numero_br(numero, 0)
    if tipo == Quadro.MOEDA:
        return "R$ " + numero_br(numero, 2)
    if tipo == Quadro.PERCENTUAL:
        return numero_br(numero, casas if casas is not None else 1) + "%"
    return numero_br(numero, casas)


def para_edicao(tipo, numero=None, texto="", casas=2):
    """Valor como aparece dentro do campo de edição (sem R$ e sem %)."""
    if tipo in (Quadro.TEXTO, Quadro.SIM_NAO):
        return exibir(tipo, numero, texto, casas)
    if numero is None:
        return ""
    n = Decimal(numero).normalize()
    if n == n.to_integral_value():
        return numero_br(n, 0)
    casas_reais = max(0, -n.as_tuple().exponent)
    return numero_br(n, min(casas_reais, 6))
