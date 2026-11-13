"""
Motor de cálculo dos quadros: fórmulas, totais e referências entre quadros.

Fórmulas usam as CHAVES das linhas e quadros, com + - * / e parênteses:

    tecnico + graduacao + pos              linhas do mesmo quadro
    atendidos / matriculados * 100         percentual
    gestao_matriculados.total              linha de total de outro quadro (mesmo ano/coluna)
    pos_numeros.ingressantes.total         linha e coluna explícitas de outro quadro
    pos_numeros.ingressantes.a2025         coluna de um ano específico (chave a + ano)

Uma célula vazia faz o resultado ficar vazio (não vira zero), para que a falta
de um dado nunca passe despercebida. Divisão por zero também resulta vazio.
Os valores calculados nunca são gravados: são sempre recalculados a partir dos
valores preenchidos. Linhas que buscam o dado em OUTRO quadro (fonte única) também aceitam
um valor digitado: ele prevalece, e a divergência com o automático é apontada.
"""
import ast
from dataclasses import dataclass
from decimal import Decimal, DivisionByZero, InvalidOperation

TOTAL = "total"


class ErroFormula(Exception):
    pass


@dataclass
class Resultado:
    numero: Decimal | None = None
    texto: str = ""
    erro: str = ""

    @property
    def vazio(self):
        return self.numero is None and not self.texto


_cache_ast = {}


def analisar(expr):
    """Converte a expressão em árvore sintática segura (só aritmética e nomes)."""
    expr = (expr or "").strip()
    if expr in _cache_ast:
        return _cache_ast[expr]
    if not expr:
        raise ErroFormula("fórmula vazia")
    try:
        arvore = ast.parse(expr.replace(",", "."), mode="eval")
    except SyntaxError:
        raise ErroFormula(f"fórmula inválida: “{expr}”")
    for no in ast.walk(arvore):
        if isinstance(no, (ast.Expression, ast.BinOp, ast.UnaryOp, ast.Name, ast.Attribute, ast.Load,
                           ast.Add, ast.Sub, ast.Mult, ast.Div, ast.USub, ast.UAdd)):
            continue
        if isinstance(no, ast.Constant) and isinstance(no.value, (int, float)) and not isinstance(no.value, bool):
            continue
        raise ErroFormula(f"a fórmula “{expr}” usa algo não permitido (só + - * / parênteses, números e chaves)")
    _cache_ast[expr] = arvore
    return arvore


def referencias(expr):
    """Lista de referências (tuplas de nomes) usadas na expressão, ex.: [('tecnico',), ('q', 'total')]."""
    out = []
    for no in ast.walk(analisar(expr)):
        if isinstance(no, (ast.Name, ast.Attribute)):
            partes = _partes(no)
            if partes and not any(partes == o[:len(partes)] for o in out):
                out.append(partes)
    # remove prefixos (o ast.walk visita q.l e depois q)
    return [r for r in out if not any(len(o) > len(r) and o[:len(r)] == r for o in out)]


def _partes(no):
    partes = []
    while isinstance(no, ast.Attribute):
        partes.append(no.attr)
        no = no.value
    if isinstance(no, ast.Name):
        partes.append(no.id)
        return tuple(reversed(partes))
    return None


class Calculadora:
    """Carrega um ciclo inteiro na memória e calcula qualquer célula."""

    def __init__(self, ciclo):
        from .models import Coluna, Linha, Quadro, Valor
        self.ciclo = ciclo
        self.quadros = {q.chave: q for q in Quadro.objects.filter(ciclo=ciclo).select_related("secao__pai", "setor")}
        self.quadro_por_id = {q.pk: q for q in self.quadros.values()}
        self.linhas = {}       # quadro_id -> {chave: Linha}
        self.lista_linhas = {}  # quadro_id -> [Linha]
        for li in Linha.objects.filter(quadro__ciclo=ciclo).order_by("ordem", "id"):
            li.quadro = self.quadro_por_id[li.quadro_id]
            self.linhas.setdefault(li.quadro_id, {})[li.chave] = li
            self.lista_linhas.setdefault(li.quadro_id, []).append(li)
        self.colunas = {}      # quadro_id -> [Coluna]
        for c in Coluna.objects.filter(quadro__ciclo=ciclo).order_by("ordem", "id"):
            self.colunas.setdefault(c.quadro_id, []).append(c)
        self.valores = {(v.linha_id, v.coluna_id): v for v in Valor.objects.filter(linha__quadro__ciclo=ciclo)}
        self._memo = {}

    # --- acesso -----------------------------------------------------------
    def colunas_de(self, quadro):
        return self.colunas.get(quadro.pk, [])

    def linhas_de(self, quadro):
        return self.lista_linhas.get(quadro.pk, [])

    def coluna_por_chave(self, quadro, chave):
        for c in self.colunas_de(quadro):
            if c.chave == chave:
                return c
        return None

    def coluna_alinhada(self, quadro, coluna_ref):
        """Coluna de `quadro` que corresponde à coluna de contexto (mesmo ano, ou mesma chave)."""
        cols = self.colunas_de(quadro)
        if coluna_ref is None:
            return cols[0] if len(cols) == 1 else None
        if coluna_ref == TOTAL:
            return TOTAL if quadro.coluna_total else None
        if coluna_ref.ano is not None:
            for c in cols:
                if c.ano == coluna_ref.ano:
                    return c
        for c in cols:
            if c.chave == coluna_ref.chave:
                return c
        if len(cols) == 1:
            return cols[0]
        return None

    def valor_preenchido(self, linha, coluna):
        return self.valores.get((linha.pk, coluna.pk))

    # --- cálculo ------------------------------------------------------------
    def celula(self, quadro, linha_chave, coluna, _pilha=None):
        """Resultado da célula. `coluna` é uma Coluna ou TOTAL; `linha_chave` pode ser TOTAL."""
        ckey = coluna if coluna == TOTAL else coluna.pk
        chave = (quadro.pk, linha_chave, ckey)
        if chave in self._memo:
            return self._memo[chave]
        pilha = _pilha or set()
        if chave in pilha:
            return Resultado(erro="referência circular nas fórmulas")
        pilha = pilha | {chave}
        r = self._calcular(quadro, linha_chave, coluna, pilha)
        self._memo[chave] = r
        return r

    def _calcular(self, quadro, linha_chave, coluna, pilha):
        if coluna == TOTAL:
            if not quadro.coluna_total:
                return Resultado(erro=f"o quadro “{quadro.chave}” não tem coluna de total")
            return self._somar([self.celula(quadro, linha_chave, c, pilha) for c in self.colunas_de(quadro)])
        if linha_chave == TOTAL:
            linhas = [li for li in self.linhas_de(quadro) if li.soma_no_total]
            partes = [self.celula(quadro, li.chave, coluna, pilha) for li in linhas]
            # num ano ainda aberto, total de quadro obrigatório só sai com todas as parcelas: uma soma parcial
            # (7.000 de 3 parcelas) passaria como número certo para tabelas, painéis e outros quadros
            if quadro.obrigatorio and not coluna.travada and any(r.vazio and not r.erro for r in partes):
                return Resultado()
            return self._somar(partes)
        linha = self.linhas.get(quadro.pk, {}).get(linha_chave)
        if linha is None:
            return Resultado(erro=f"a linha “{linha_chave}” não existe no quadro “{quadro.chave}”")
        if linha.calculada:
            if linha.importada:
                # fonte única: o valor digitado (se houver) prevalece; senão, o automático
                v = self.valor_preenchido(linha, coluna)
                if v is not None and v.numero is not None:
                    return Resultado(numero=v.numero)
            try:
                return self._avaliar(linha.formula, quadro, coluna, pilha)
            except ErroFormula as ex:
                return Resultado(erro=str(ex))
        v = self.valor_preenchido(linha, coluna)
        if v is None:
            return Resultado()
        return Resultado(numero=v.numero, texto=v.texto)

    @staticmethod
    def _somar(resultados):
        erros = [r.erro for r in resultados if r.erro]
        if erros:
            return Resultado(erro=erros[0])
        nums = [r.numero for r in resultados if r.numero is not None]
        if not nums:
            return Resultado()
        return Resultado(numero=sum(nums, Decimal(0)))

    def automatico(self, quadro, linha, coluna):
        """Valor que a fórmula da linha calcula (sem considerar o valor digitado)."""
        return self.avaliar(linha.formula, quadro, coluna)

    def divergencia(self, quadro, linha, coluna):
        """(digitado, automático) quando uma linha de fonte única tem os dois e eles não batem
        (e ninguém escolheu manter o digitado para este automático). Senão, None."""
        if not linha.importada or coluna == TOTAL:
            return None
        v = self.valor_preenchido(linha, coluna)
        if v is None or v.numero is None:
            return None
        a = self.automatico(quadro, linha, coluna)
        if a.erro or a.numero is None:
            return None
        casas = 0 if linha.tipo == "inteiro" else quadro.casas_decimais
        tol = Decimal(1).scaleb(-casas) / 2
        if abs(a.numero - v.numero) < tol:
            return None
        if v.auto_aceito is not None and abs(v.auto_aceito - a.numero) < tol:
            return None
        return v.numero, a.numero

    def avaliar(self, expr, quadro, coluna):
        """Avalia uma expressão (fórmula ou regra) no contexto de uma coluna de `quadro`."""
        try:
            return self._avaliar(expr, quadro, coluna, set())
        except ErroFormula as ex:
            return Resultado(erro=str(ex))

    def _avaliar(self, expr, quadro, coluna, pilha):
        arvore = analisar(expr)
        try:
            n = self._no(arvore.body, quadro, coluna, pilha)
        except _Vazio:
            return Resultado()
        except (DivisionByZero, InvalidOperation, ZeroDivisionError):
            return Resultado()
        return Resultado(numero=n)

    def _no(self, no, quadro, coluna, pilha):
        if isinstance(no, ast.Constant):
            return Decimal(str(no.value))
        if isinstance(no, ast.UnaryOp):
            v = self._no(no.operand, quadro, coluna, pilha)
            return -v if isinstance(no.op, ast.USub) else v
        if isinstance(no, ast.BinOp):
            a = self._no(no.left, quadro, coluna, pilha)
            b = self._no(no.right, quadro, coluna, pilha)
            if isinstance(no.op, ast.Add):
                return a + b
            if isinstance(no.op, ast.Sub):
                return a - b
            if isinstance(no.op, ast.Mult):
                return a * b
            if b == 0:
                raise _Vazio()
            return a / b
        partes = _partes(no)
        r = self._referencia(partes, quadro, coluna, pilha)
        if r.erro:
            raise ErroFormula(r.erro)
        if r.numero is None:
            raise _Vazio()
        return r.numero

    def _referencia(self, partes, quadro, coluna, pilha):
        if partes is None:
            return Resultado(erro="referência inválida")
        if len(partes) == 1:
            nome = partes[0]
            if nome != TOTAL and nome not in self.linhas.get(quadro.pk, {}):
                if nome in self.quadros:
                    return Resultado(erro=f"“{nome}” é um quadro: indique a linha (ex.: {nome}.total)")
                return Resultado(erro=f"“{nome}” não é uma linha do quadro “{quadro.chave}”")
            return self.celula(quadro, nome, coluna, pilha)
        alvo = self.quadros.get(partes[0])
        if alvo is None:
            return Resultado(erro=f"o quadro “{partes[0]}” não existe neste ciclo")
        linha = partes[1]
        if linha != TOTAL and linha not in self.linhas.get(alvo.pk, {}):
            return Resultado(erro=f"a linha “{linha}” não existe no quadro “{alvo.chave}”")
        if len(partes) == 3:
            if partes[2] == TOTAL:
                col = TOTAL if alvo.coluna_total else None
            elif partes[2] == "atual":          # a coluna do ano do relatório (vale em qualquer ciclo)
                col = next((c for c in self.colunas_de(alvo) if c.ano == self.ciclo.ano), None)
            else:
                col = self.coluna_por_chave(alvo, partes[2])
            if col is None:
                return Resultado(erro=f"a coluna “{partes[2]}” não existe no quadro “{alvo.chave}”")
        elif len(partes) == 2:
            col = self.coluna_alinhada(alvo, coluna)
            if col is None:
                rotulo = "total" if coluna == TOTAL else getattr(coluna, "rotulo", "")
                return Resultado(erro=f"o quadro “{alvo.chave}” não tem coluna correspondente a “{rotulo}”")
        else:
            return Resultado(erro="use quadro.linha ou quadro.linha.coluna")
        return self.celula(alvo, linha, col, pilha)


class _Vazio(Exception):
    """Algum valor usado na conta está vazio: o resultado também fica vazio."""
