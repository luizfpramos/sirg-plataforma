"""Motor de cálculo, formatos, consistência e cópia de ciclo."""
from decimal import Decimal

from django.core.management import call_command
from django.test import TestCase

from relatorio import construtor as K
from relatorio import formato
from relatorio.calculo import TOTAL, Calculadora, ErroFormula, analisar
from relatorio.consistencia import verificar
from relatorio.models import Ciclo, Quadro, Valor
from relatorio.servicos import Recusado, copiar_ciclo


class FormatoTests(TestCase):
    def test_ler_numeros_brasileiros(self):
        casos = {"1.234": "1234", "1.234,56": "1234.56", "1234,5": "1234.5", "12.5": "12.5", "R$ 3.719.271,19":
                 "3719271.19", "42,34%": "42.34", "-5": "-5", "1.234.567": "1234567", "0,5": "0.5", "  7 ": "7"}
        for entrada, esperado in casos.items():
            self.assertEqual(formato.ler(Quadro.DECIMAL, entrada)[0], Decimal(esperado), entrada)

    def test_entradas_invalidas(self):
        for entrada in ("abc", "1,2,3", "12a"):
            with self.assertRaises(formato.EntradaInvalida):
                formato.ler(Quadro.DECIMAL, entrada)
        with self.assertRaises(formato.EntradaInvalida):
            formato.ler(Quadro.INTEIRO, "2,5")
        self.assertEqual(formato.ler(Quadro.INTEIRO, ""), (None, ""))

    def test_sim_nao(self):
        self.assertEqual(formato.ler(Quadro.SIM_NAO, "√"), (None, "sim"))
        self.assertEqual(formato.ler(Quadro.SIM_NAO, "Não"), (None, "nao"))
        self.assertEqual(formato.exibir(Quadro.SIM_NAO, texto="sim"), "Sim")

    def test_exibir(self):
        self.assertEqual(formato.exibir(Quadro.INTEIRO, Decimal("14755")), "14.755")
        self.assertEqual(formato.exibir(Quadro.MOEDA, Decimal("4457663.2")), "R$ 4.457.663,20")
        self.assertEqual(formato.exibir(Quadro.PERCENTUAL, Decimal("42.345"), casas=2), "42,35%")
        self.assertEqual(formato.exibir(Quadro.DECIMAL, Decimal("-0.5"), casas=1), "-0,5")
        self.assertEqual(formato.para_edicao(Quadro.MOEDA, Decimal("84625.500000")), "84.625,5")

    def test_formula_segura(self):
        with self.assertRaises(ErroFormula):
            analisar("__import__('os').system('x')")
        with self.assertRaises(ErroFormula):
            analisar("a ** 2")
        with self.assertRaises(ErroFormula):
            analisar("a +")
        analisar("(a + b) / c * 100 - d.total")


class Base(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("inicializar", verbosity=0)
        cls.ciclo = Ciclo.objects.create(ano=2025, titulo="RG 2025", situacao=Ciclo.COLETA)
        cap = K.secao(cls.ciclo, "cap2", "Capítulo 2")
        cls.sec_ga = K.secao(cls.ciclo, "gestao_academica", "Gestão Acadêmica", pai=cap, setores=["SRCA"])
        cls.sec_de = K.secao(cls.ciclo, "estudantil", "Desenvolvimento Estudantil", pai=cap, setores=["DAE"])
        cls.mat = K.quadro(cls.sec_ga, "matriculados", "Matriculados",
                           [("tecnico", "Técnico"), ("graduacao", "Graduação"), ("pos", "Pós-graduação")],
                           total=True, valores={"tecnico": [5938, 6010, 6275, 6809, 6895],
                                                "graduacao": [4716, 5050, 5685, 6279, 6770],
                                                "pos": [879, 846, 917, 1023, 1090]})
        cls.re = K.quadro(cls.sec_de, "restaurante", "Restaurantes estudantis", [
            ("atendidos", "Alunos atendidos nos RE"),
            ("matriculados", "Alunos matriculados", "matriculados.total"),
            {"chave": "percentual", "rotulo": "% atendidos", "formula": "atendidos / matriculados * 100",
             "tipo_valor": Quadro.PERCENTUAL, "soma_no_total": False},
        ], valores={"atendidos": [0, 10281, 11402, 10779, 12864]})
        cls.pos = K.quadro(cls.sec_ga, "pos_numeros", "Pós-graduação em números",
                           [("ingressantes", "Ingressantes"), ("matriculados", "Matriculados")],
                           modo=Quadro.CATEGORIAS, colunas=[("mestrado", "Mestrado"), ("doutorado", "Doutorado")],
                           coluna_total=True, valores={"ingressantes": [210, 106], "matriculados": [777, 313]})


class CalculoTests(Base):
    def col(self, q, ano):
        return q.colunas.get(ano=ano)

    def test_total_e_referencia_entre_quadros(self):
        calc = Calculadora(self.ciclo)
        self.assertEqual(calc.celula(self.mat, TOTAL, self.col(self.mat, 2025)).numero, 14755)
        self.assertEqual(calc.celula(self.re, "matriculados", self.col(self.re, 2021)).numero, 11533)
        pct = calc.celula(self.re, "percentual", self.col(self.re, 2024)).numero
        self.assertEqual(round(pct, 1), Decimal("76.4"))

    def test_vazio_nao_vira_zero(self):
        Valor.objects.filter(linha__quadro=self.mat, linha__chave="pos", coluna__ano=2025).delete()
        calc = Calculadora(self.ciclo)
        # ano aberto: total com parcela vazia fica vazio (não vira soma parcial) — achado C1 da auditoria (v2.10)
        self.assertIsNone(calc.celula(self.mat, TOTAL, self.col(self.mat, 2025)).numero)
        # ano já publicado (travado): soma o que existe
        self.col(self.mat, 2025).__class__.objects.filter(pk=self.col(self.mat, 2025).pk).update(travada=True)
        calc = Calculadora(self.ciclo)
        self.assertEqual(calc.celula(self.mat, TOTAL, self.col(self.mat, 2025)).numero, 13665)
        # mas uma conta direta com a célula vazia fica vazia
        r = calc.avaliar("pos * 2", self.mat, self.col(self.mat, 2025))
        self.assertIsNone(r.numero)
        self.assertEqual(r.erro, "")

    def test_divisao_por_zero_fica_vazia(self):
        calc = Calculadora(self.ciclo)
        r = calc.avaliar("tecnico / 0", self.mat, self.col(self.mat, 2025))
        self.assertIsNone(r.numero)

    def test_coluna_total_e_coluna_explicita(self):
        calc = Calculadora(self.ciclo)
        self.assertEqual(calc.celula(self.pos, "ingressantes", TOTAL).numero, 316)
        r = calc.avaliar("pos_numeros.matriculados.total", self.mat, self.col(self.mat, 2025))
        self.assertEqual(r.numero, 1090)
        r = calc.avaliar("matriculados.pos.a2023", self.re, self.col(self.re, 2025))
        self.assertEqual(r.numero, 917)

    def test_erros_de_referencia(self):
        calc = Calculadora(self.ciclo)
        c = self.col(self.mat, 2025)
        self.assertIn("não existe", calc.avaliar("inexistente.total", self.mat, c).erro)
        self.assertIn("não é uma linha", calc.avaliar("xyz", self.mat, c).erro)
        self.assertIn("é um quadro", calc.avaliar("restaurante", self.mat, c).erro)
        # quadro por categoria não tem coluna "2025"
        self.assertIn("não tem coluna correspondente", calc.avaliar("pos_numeros.ingressantes", self.mat, c).erro)

    def test_referencia_circular(self):
        K.quadro(self.sec_ga, "circular", "Circular", [("a", "A", "b + 1"), ("b", "B", "a + 1")], anos=1)
        calc = Calculadora(self.ciclo)
        q = calc.quadros["circular"]
        r = calc.celula(q, "a", calc.colunas_de(q)[0])
        self.assertIn("circular", r.erro)


class ConsistenciaTests(Base):
    def test_regra_violada_aparece(self):
        # mesma situação do RG 2025: gráfico da Gestão Acadêmica com 376 ingressantes na pós, painel com 316
        q = K.quadro(self.sec_ga, "ingressantes", "Ingressantes", [("pos", "Pós-graduação")],
                     valores={"pos": [347, 262, 261, 336, 376]})
        K.regra(q, "Ingressantes da pós = painel da pós", "pos", "pos_numeros.ingressantes.total")
        ps = [p for p in verificar(self.ciclo) if p.tipo == "regra"]
        self.assertEqual(len(ps), 1)
        self.assertIn("376", ps[0].detalhe)
        self.assertIn("316", ps[0].detalhe)

    def test_vazio_obrigatorio_e_variacao(self):
        Valor.objects.filter(linha__quadro=self.mat, linha__chave="pos", coluna__ano=2025).delete()
        self.mat.variacao_alerta = Decimal("5")
        self.mat.save()
        ps = verificar(self.ciclo)
        self.assertTrue(any(p.tipo == "vazio" and p.linha.chave == "pos" for p in ps))
        # graduação 6279 -> 6770 = +7,8% > 5%
        var = [p for p in ps if p.tipo == "variacao"]
        self.assertEqual([p.linha.chave for p in var], ["graduacao"])
        v = Valor.objects.get(linha__quadro=self.mat, linha__chave="graduacao", coluna__ano=2025)
        v.justificativa = "Abertura de novos cursos"
        v.save()
        self.assertFalse(any(p.tipo == "variacao" for p in verificar(self.ciclo)))

    def test_faixa(self):
        li = self.re.linhas.get(chave="percentual")
        li.maximo = Decimal("88")
        li.save()
        ps = [p for p in verificar(self.ciclo) if p.tipo == "faixa"]
        self.assertEqual(len(ps), 1)       # 2023: 88,5%
        self.assertIn("2023", ps[0].mensagem)

    def test_coluna_travada_nao_cobra_preenchimento(self):
        Valor.objects.filter(linha__quadro=self.mat, coluna__ano=2021).delete()
        self.mat.colunas.filter(ano=2021).update(travada=True)
        self.assertFalse([p for p in verificar(self.ciclo) if p.tipo == "vazio"])


class CopiaCicloTests(Base):
    def test_copiar_ciclo_herda_e_trava_passado(self):
        novo = copiar_ciclo(self.ciclo, 2026, "RG 2026")
        q = novo.quadros.get(chave="matriculados")
        self.assertEqual([c.ano for c in q.colunas.all()], [2022, 2023, 2024, 2025, 2026])
        self.assertTrue(all(c.travada for c in q.colunas.filter(ano__lt=2026)))
        self.assertFalse(q.colunas.get(ano=2026).travada)
        calc = Calculadora(novo)
        self.assertEqual(calc.celula(q, TOTAL, q.colunas.get(ano=2025)).numero, 14755)
        self.assertIsNone(calc.celula(q, TOTAL, q.colunas.get(ano=2026)).numero)
        # referências continuam funcionando no novo ciclo
        re = novo.quadros.get(chave="restaurante")
        self.assertEqual(calc.celula(re, "matriculados", re.colunas.get(ano=2022)).numero, 11906)
        # quadro por categorias: estrutura sem valores
        pos = novo.quadros.get(chave="pos_numeros")
        self.assertEqual(pos.colunas.count(), 2)
        self.assertFalse(Valor.objects.filter(linha__quadro=pos).exists())
        # setores da seção copiados
        self.assertEqual(list(novo.secoes.get(chave="estudantil").setores.values_list("sigla", flat=True)), ["DAE"])
        # o ciclo antigo não muda
        self.assertEqual(Valor.objects.filter(linha__quadro=self.mat).count(), 15)

    def test_nao_copia_para_ano_existente_ou_anterior(self):
        with self.assertRaises(Recusado):
            copiar_ciclo(self.ciclo, 2025, "x")
        with self.assertRaises(Recusado):
            copiar_ciclo(self.ciclo, 2024, "x")
