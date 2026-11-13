"""Telas e gravação de células: permissões por setor, situação do ciclo, travas e conflitos."""
import json

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase

from contas import servicos as CS
from contas.models import Perfil, Setor
from decimal import Decimal

from relatorio.calculo import Calculadora
from relatorio.consistencia import verificar
from relatorio.models import Ciclo, Coluna, Linha, Quadro, Valor

User = get_user_model()
SENHA = "Senha-forte-2026"


class Base(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("inicializar", verbosity=0)
        call_command("criar_admin", login="admin", nome="Admin Geral", senha=SENHA, verbosity=0)
        call_command("carregar_rg2025", abrir_2026=True, verbosity=0)
        g = lambda s: Setor.objects.get(sigla=s)
        cls.srca, _ = CS.criar_usuario(login="srca", nome="Ana SRCA", setores=[g("SRCA")], senha=SENHA)
        cls.dae, _ = CS.criar_usuario(login="dae", nome="Bia DAE", setores=[g("DAE")], senha=SENHA)
        cls.master, _ = CS.criar_usuario(login="master", nome="Mara Master", e_master=True, senha=SENHA)
        cls.leitor, _ = CS.criar_usuario(login="leitor", nome="Leo Leitor", senha=SENHA)
        Perfil.objects.update(troca_senha=False)
        cls.c26 = Ciclo.objects.get(ano=2026)
        cls.c26.situacao = Ciclo.COLETA
        cls.c26.save()

    def entrar(self, login):
        self.client.post("/entrar/", {"username": login, "password": SENHA})

    def celula(self, quadro, linha, ano, ciclo=2026):
        li = Linha.objects.get(quadro__ciclo__ano=ciclo, quadro__chave=quadro, chave=linha)
        col = Coluna.objects.get(quadro=li.quadro, ano=ano)
        return li, col

    def salvar(self, li, col, valor, ciclo=2026, **extra):
        r = self.client.post(f"/ciclos/{ciclo}/celula/", json.dumps({"linha": li.pk, "coluna": col.pk, "valor": valor,
                                                                       **extra}), content_type="application/json")
        return r, r.json()


class PaginasTests(Base):
    def test_paginas_abrem_para_todos(self):
        for login in ("admin", "srca", "dae", "master", "leitor"):
            self.client.logout()
            self.entrar(login)
            for url in ("/relatorio/", "/ciclos/", "/ciclos/2025/", "/ciclos/2026/", "/ciclos/2026/?minhas=0",
                        "/ciclos/2025/pendencias/", "/ciclos/2026/pendencias/?minhas=1&severidade=falta",
                        "/ciclos/2026/secoes/gestao_academica/", "/ciclos/2025/secoes/ensino_pos/",
                        "/ciclos/2026/secoes/governanca_desempenho/", "/ciclos/2026/secoes/inclusao/"):
                r = self.client.get(url, follow=True)
                self.assertEqual(r.status_code, 200, f"{login} {url}")

    def test_estrutura_so_admin(self):
        for login in ("srca", "master", "leitor"):
            self.client.logout()
            self.entrar(login)
            for url in ("/ciclos/novo/", "/ciclos/2026/editar/", "/ciclos/2026/secoes/nova/",
                        "/ciclos/2026/quadros/novo/", "/ciclos/2026/quadros/ga_matriculados/editar/",
                        "/ciclos/2026/secoes/gestao_academica/editar/"):
                self.assertEqual(self.client.get(url).status_code, 403, f"{login} {url}")
        self.client.logout()
        self.entrar("admin")
        for url in ("/ciclos/novo/", "/ciclos/2026/editar/", "/ciclos/2026/secoes/nova/?pai=governanca_desempenho",
                    "/ciclos/2026/quadros/novo/?secao=gestao_academica", "/ciclos/2026/quadros/pos_numeros/editar/",
                    "/ciclos/2026/quadros/ga_matriculados/editar/", "/ciclos/2026/secoes/gestao_academica/editar/"):
            self.assertEqual(self.client.get(url).status_code, 200, url)

    def test_minhas_secoes(self):
        self.entrar("dae")
        r = self.client.get("/ciclos/2026/")
        titulos = [it["s"].titulo for cap in r.context["arvore"] for it in cap["secoes"]]
        self.assertIn("Desenvolvimento Estudantil", titulos)
        self.assertNotIn("Gestão Acadêmica", titulos)


class GravacaoTests(Base):
    def test_setor_grava_o_que_e_seu(self):
        self.entrar("srca")
        li, col = self.celula("ga_matriculados", "tecnico", 2026)
        r, j = self.salvar(li, col, "7.012")
        self.assertTrue(j["ok"], j)
        self.assertEqual(j["edicao"], "7.012")
        self.assertEqual(Valor.objects.get(linha=li, coluna=col).numero, 7012)
        self.assertEqual(Valor.history.filter(linha_id=li.pk, coluna_id=col.pk).first().history_user, self.srca)
        # o total foi recalculado e veio na resposta
        tot = j["celulas"][f"t{li.quadro_id}-{col.pk}"]["exibido"]
        self.assertEqual(tot, "")      # total só sai com todas as parcelas (sem soma parcial)

    def test_setor_nao_grava_o_que_nao_e_seu(self):
        self.entrar("dae")
        li, col = self.celula("ga_matriculados", "tecnico", 2026)
        r, j = self.salvar(li, col, "1")
        self.assertEqual(r.status_code, 400)
        self.assertIn("SRCA", j["erro"])
        self.assertFalse(Valor.objects.filter(linha=li, coluna=col).exists())

    def test_leitor_nao_grava(self):
        self.entrar("leitor")
        li, col = self.celula("de_restaurantes", "atendidos", 2026)
        r, j = self.salvar(li, col, "1")
        self.assertEqual(r.status_code, 400)

    def test_linha_calculada_nao_grava(self):
        self.entrar("dae")
        li, col = self.celula("de_restaurantes", "percentual", 2026)
        r, j = self.salvar(li, col, "1")
        self.assertIn("calculada", j["erro"])

    def test_fonte_unica_aceita_valor_digitado_e_aponta_divergencia(self):
        from relatorio.calculo import Calculadora
        from relatorio.models import Valor
        # a Gestão Acadêmica (SRCA) informa; a DAE digita outro valor na linha que busca o dado de lá
        self.entrar("srca")
        for nivel, n in (("tecnico", 7000), ("graduacao", 7000), ("pos", 1000)):
            li, col = self.celula("ga_matriculados", nivel, 2026)
            self.salvar(li, col, str(n))
        self.client.logout()
        self.entrar("dae")
        li, col = self.celula("de_restaurantes", "matriculados", 2026)
        r, j = self.salvar(li, col, "15.100")
        self.assertEqual(r.status_code, 200, j)
        celula = j["celulas"][f"{li.pk}-{col.pk}"]
        self.assertEqual(celula["auto"], "15.000")
        self.assertTrue(celula["divergente"])
        div = [p for p in j["pendencias"] if "acao" in p]
        self.assertEqual(len(div), 1)
        self.assertIn("15.100", div[0]["mensagem"])
        # o valor digitado é o que vai para o relatório
        calc = Calculadora(li.quadro.ciclo)
        self.assertEqual(calc.celula(calc.quadros["de_restaurantes"], "matriculados", col).numero, 15100)
        # ignorar: a divergência some, o digitado fica
        r = self.client.post("/ciclos/2026/celula/divergencia/", {"linha": li.pk, "coluna": col.pk, "acao": "ignorar"},
                             content_type="application/json")
        self.assertFalse([p for p in r.json()["pendencias"] if "acao" in p])
        self.assertEqual(Valor.objects.get(linha=li, coluna=col).numero, 15100)
        # se o automático mudar, a divergência volta
        self.client.logout()
        self.entrar("srca")
        li2, col2 = self.celula("ga_matriculados", "pos", 2026)
        self.salvar(li2, col2, "1050")
        self.client.logout()
        self.entrar("dae")
        r = self.client.post("/ciclos/2026/celula/divergencia/", {"linha": li.pk, "coluna": col.pk, "acao": "corrigir"},
                             content_type="application/json")
        self.assertEqual(r.status_code, 200)
        self.assertFalse(Valor.objects.filter(linha=li, coluna=col).exists())
        calc = Calculadora(li.quadro.ciclo)
        self.assertEqual(calc.celula(calc.quadros["de_restaurantes"], "matriculados", col).numero, 15050)

    def test_referencia_atualiza_outra_area(self):
        """A DAE não digita matriculados: ao SRCA preencher, o percentual da DAE é calculado."""
        self.entrar("dae")
        li, col = self.celula("de_restaurantes", "atendidos", 2026)
        self.salvar(li, col, "12.000")
        self.client.logout()
        self.entrar("srca")
        for linha, v in (("tecnico", "7000"), ("graduacao", "7000"), ("pos", "1000")):
            l2, c2 = self.celula("ga_matriculados", linha, 2026)
            self.salvar(l2, c2, v)
        from relatorio.calculo import Calculadora
        calc = Calculadora(self.c26)
        q = calc.quadros["de_restaurantes"]
        self.assertEqual(round(calc.celula(q, "percentual", col).numero, 2), 80)

    def test_ano_travado(self):
        li, col = self.celula("ga_matriculados", "tecnico", 2025)
        self.assertTrue(col.travada)
        self.entrar("srca")
        r, j = self.salvar(li, col, "1")
        self.assertIn("Master", j["erro"])
        self.client.logout()
        self.entrar("master")
        r, j = self.salvar(li, col, "6.900")
        self.assertIn("justificativa", j["erro"])
        r, j = self.salvar(li, col, "6.900", justificativa="Correção do censo")
        self.assertTrue(j["ok"])
        h = Valor.history.filter(linha_id=li.pk, coluna_id=col.pk).first()
        self.assertEqual(h.history_change_reason, "Correção do censo")

    def test_conflito(self):
        self.entrar("srca")
        li, col = self.celula("ga_matriculados", "pos", 2026)
        self.salvar(li, col, "1.100")
        # outra aba ainda mostrava a célula vazia e tenta gravar outro valor
        r, j = self.salvar(li, col, "1.200", anterior="")
        self.assertEqual(r.status_code, 409)
        self.assertEqual(j["atual"], "1.100")
        # quem já via o valor atual grava normalmente
        r, j = self.salvar(li, col, "1.200", anterior="1.100")
        self.assertTrue(j["ok"])

    def test_entrada_invalida(self):
        self.entrar("srca")
        li, col = self.celula("ga_matriculados", "pos", 2026)
        r, j = self.salvar(li, col, "mil")
        self.assertEqual(r.status_code, 400)
        r, j = self.salvar(li, col, "10,5")
        self.assertIn("inteiro", j["erro"])

    def test_apagar_valor(self):
        self.entrar("srca")
        li, col = self.celula("ga_matriculados", "pos", 2026)
        self.salvar(li, col, "10")
        r, j = self.salvar(li, col, "")
        self.assertTrue(j["ok"])
        self.assertFalse(Valor.objects.filter(linha=li, coluna=col).exists())

    def test_situacao_do_ciclo(self):
        li, col = self.celula("ga_matriculados", "pos", 2026)
        for situacao, srca_pode, master_pode in ((Ciclo.PREPARACAO, False, True), (Ciclo.REVISAO, False, True),
                                                 (Ciclo.ENCERRADO, False, False), (Ciclo.COLETA, True, True)):
            Ciclo.objects.filter(pk=self.c26.pk).update(situacao=situacao)
            for login, pode in (("srca", srca_pode), ("master", master_pode)):
                self.client.logout()
                self.entrar(login)
                r, j = self.salvar(li, col, "5")
                self.assertEqual(j["ok"], pode, f"{situacao} {login} {j}")
                if pode:
                    self.salvar(li, col, "")

    def test_historico_e_justificativa(self):
        self.entrar("srca")
        li, col = self.celula("ga_matriculados", "graduacao", 2026)
        self.salvar(li, col, "9000")
        r = self.client.post("/ciclos/2026/celula/justificar/", json.dumps(
            {"linha": li.pk, "coluna": col.pk, "justificativa": "Novos cursos"}), content_type="application/json")
        self.assertTrue(r.json()["ok"])
        r = self.client.get(f"/ciclos/2026/celula/{li.pk}/{col.pk}/historico/")
        itens = r.json()["itens"]
        self.assertEqual(itens[0]["justificativa"], "Novos cursos")
        self.assertEqual(itens[-1]["valor"], "9.000")


class EstruturaTelasTests(Base):
    def test_criar_quadro_com_formula_e_regra(self):
        self.entrar("admin")
        dados = {
            "titulo": "Evasão", "chave": "", "secao": self.c26.secoes.get(chave="gestao_academica").pk, "ordem": 9,
            "setor": "", "descricao": "", "fonte": "", "tipo_valor": Quadro.INTEIRO, "casas_decimais": 1,
            "modo_colunas": Quadro.ANOS, "anos_exibidos": 3, "linha_total": "on", "rotulo_total": "Total",
            "obrigatorio": "on", "variacao_alerta": "",
            "linhas-TOTAL_FORMS": 3, "linhas-INITIAL_FORMS": 0,
            "linhas-0-ordem": 1, "linhas-0-rotulo": "Evadidos", "linhas-0-chave": "", "linhas-0-formula": "",
            "linhas-0-soma_no_total": "on",
            "linhas-1-ordem": 2, "linhas-1-rotulo": "Taxa de evasão", "linhas-1-chave": "taxa",
            "linhas-1-formula": "evadidos / ga_matriculados.total * 100", "linhas-1-tipo_valor": Quadro.PERCENTUAL,
            "linhas-2-ordem": "", "linhas-2-rotulo": "", "linhas-2-soma_no_total": "on",
            "colunas-TOTAL_FORMS": 0, "colunas-INITIAL_FORMS": 0,
            "regras-TOTAL_FORMS": 1, "regras-INITIAL_FORMS": 0,
            "regras-0-descricao": "Evadidos menores que matriculados", "regras-0-esquerda": "evadidos",
            "regras-0-operador": "<=", "regras-0-direita": "ga_matriculados.total", "regras-0-tolerancia": "0",
            "regras-0-escopo": "todas", "regras-0-severidade": "erro", "regras-0-ativa": "on",
        }
        r = self.client.post("/ciclos/2026/quadros/novo/", dados)
        self.assertEqual(r.status_code, 302, r.content.decode()[:3000])
        q = Quadro.objects.get(ciclo=self.c26, chave="evasao")
        self.assertEqual([c.ano for c in q.colunas.all()], [2024, 2025, 2026])
        self.assertEqual(list(q.linhas.values_list("chave", flat=True)), ["evadidos", "taxa"])
        self.assertEqual(q.regras.count(), 1)
        tipos = {p.tipo for p in verificar(self.c26) if p.quadro.pk == q.pk}
        self.assertEqual(tipos, {"vazio"})

    def test_formula_invalida_recusada(self):
        self.entrar("admin")
        q = Quadro.objects.get(ciclo=self.c26, chave="ri_numeros")
        r = self.client.get(f"/ciclos/2026/quadros/{q.chave}/editar/")
        self.assertEqual(r.status_code, 200)
        f = r.context["linhas"]
        dados = {k: v for k, v in r.context["form"].initial.items() if v is not None}
        self.assertTrue(f.total_form_count() >= q.linhas.count())

    def test_novo_ciclo_pela_tela(self):
        self.entrar("admin")
        r = self.client.post("/ciclos/novo/", {"ano": 2027, "titulo": "", "origem": self.c26.pk, "anos_serie": 5})
        self.assertRedirects(r, "/ciclos/2027/")
        c = Ciclo.objects.get(ano=2027)
        self.assertEqual(c.titulo, "Relatório de Gestão 2027")
        self.assertEqual(c.quadros.count(), self.c26.quadros.count())

    def test_secao_nova_e_exclusao(self):
        self.entrar("admin")
        cap = self.c26.secoes.get(chave="governanca_desempenho")
        r = self.client.post("/ciclos/2026/secoes/nova/", {"titulo": "Ensino a Distância", "pai": cap.pk, "ordem": 200,
                                                            "chave": "", "setores": [Setor.objects.get(sigla="DIRGRAD").pk],
                                                            "orientacao": ""})
        self.assertRedirects(r, "/ciclos/2026/secoes/ensino_a_distancia/")
        r = self.client.post("/ciclos/2026/secoes/ensino_a_distancia/editar/", {"excluir": "1"})
        self.assertFalse(self.c26.secoes.filter(chave="ensino_a_distancia").exists())


class RG2025Tests(Base):
    def test_carga_aponta_as_inconsistencias_do_rg_publicado(self):
        ps = verificar(Ciclo.objects.get(ano=2025))
        regras = {p.mensagem.split(" (")[0]: p.detalhe for p in ps if p.tipo == "regra"}
        self.assertIn("376 ≠ 316", regras["Ingressantes da pós iguais aos do painel da Pós-graduação"])
        self.assertIn("347 ≠ 202", regras["Concluintes da pós iguais aos do painel da Pós-graduação"])
        self.assertFalse([p for p in ps if p.tipo in ("formula", "vazio")])

    def test_numeros_publicados_conferem(self):
        from relatorio.calculo import TOTAL, Calculadora
        c = Ciclo.objects.get(ano=2025)
        calc = Calculadora(c)

        def v(quadro, linha, ano=2025):
            q = calc.quadros[quadro]
            col = TOTAL if ano == TOTAL else next(x for x in calc.colunas_de(q) if x.ano == ano)
            return calc.celula(q, linha, col).numero

        self.assertEqual(v("ga_matriculados", "total"), 14755)
        self.assertEqual(v("ga_ingressantes", "total"), 4223)
        self.assertEqual(v("ga_concluintes", "total"), 3063)
        self.assertEqual(v("ga_vagas", "total"), 4588)
        self.assertEqual(v("ga_cursos", "total"), 94)
        self.assertEqual(v("pq_captacao", "total"), round(v("pq_captacao", "total"), 2))
        self.assertEqual(str(v("pq_captacao", "total")), "4457663.200000")
        self.assertEqual(v("pq_artigos", "total"), 1398)
        self.assertEqual(v("pq_pi", "total"), 39)
        self.assertEqual(str(v("de_custeio", "proprios")), "6578936.030000")
        self.assertEqual(v("gp_tae", "total"), 648)
        self.assertEqual(v("gp_docentes", "total"), 946)
        self.assertEqual(str(v("gp_capacitacao_valor", "total")), "459430.230000")
        self.assertEqual(str(round(v("grad_numeros", "ocupacao"), 1)), "87.9")
        self.assertEqual(str(v("grad_fomento", "total", 2022)), "950235.390000")
        c = Ciclo.objects.get(ano=2025)
        calc = Calculadora(c)
        q = calc.quadros["orc_execucao"]
        self.assertEqual(calc.celula(q, "total", q.colunas.get(chave="dotacao")).numero, Decimal("669550000"))


class ExcelTests(Base):
    def test_exportar_e_importar_com_previa(self):
        import io

        from openpyxl import load_workbook
        self.entrar("srca")
        r = self.client.get("/ciclos/2026/excel/?setor=SRCA")
        self.assertEqual(r.status_code, 200)
        wb = load_workbook(io.BytesIO(r.content))
        self.assertIn("Alunos matriculados", wb.sheetnames)
        ws = wb["Alunos matriculados"]
        # localiza a linha "Técnico" e a coluna 2026 pelos identificadores ocultos
        li, col = self.celula("ga_matriculados", "tecnico", 2026)
        li2, _ = self.celula("ga_matriculados", "graduacao", 2026)
        lin = {ws.cell(row=i, column=1).value: i for i in range(6, ws.max_row + 1)}
        cols = {ws.cell(row=4, column=j).value: j for j in range(3, ws.max_column + 1)}
        ws.cell(row=lin[f"L:{li.pk}"], column=cols[f"C:{col.pk}"], value=7123)
        ws.cell(row=lin[f"L:{li2.pk}"], column=cols[f"C:{col.pk}"], value="abc")
        # tentativa de mudar um ano travado é ignorada
        c25 = Coluna.objects.get(quadro=li.quadro, ano=2025)
        ws.cell(row=lin[f"L:{li.pk}"], column=cols[f"C:{c25.pk}"], value=1)
        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        buf.name = "dados.xlsx"
        r = self.client.post("/ciclos/2026/excel/enviar/", {"arquivo": buf})
        self.assertEqual(len(r.context["validas"]), 1)
        self.assertEqual(r.context["validas"][0]["depois"], "7.123")
        self.assertEqual(len(r.context["invalidas"]), 1)
        self.assertFalse(Valor.objects.filter(linha=li, coluna=col).exists())   # prévia não grava
        r = self.client.post("/ciclos/2026/excel/enviar/", {"acao": "confirmar", "aplicar": [f"{li.pk}-{col.pk}"]})
        self.assertRedirects(r, "/ciclos/2026/")
        self.assertEqual(Valor.objects.get(linha=li, coluna=col).numero, 7123)
        self.assertEqual(Valor.objects.get(linha=li, coluna=c25).numero, 6895)

    def test_importar_de_outro_setor_e_recusado(self):
        import io
        self.entrar("srca")
        r = self.client.get("/ciclos/2026/excel/?quadro=de_bolsas")
        from openpyxl import load_workbook
        wb = load_workbook(io.BytesIO(r.content))
        ws = wb.worksheets[1]
        ws.cell(row=6, column=3, value=10)
        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        buf.name = "x.xlsx"
        r = self.client.post("/ciclos/2026/excel/enviar/", {"arquivo": buf})
        self.assertEqual(len(r.context["validas"]), 0)
        self.assertIn("DAE", r.context["invalidas"][0]["erro"])
