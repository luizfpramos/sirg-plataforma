"""2.20: grade das páginas (margens, colunas e medianiz do ciclo) e guias de cada página no editor de blocos."""
from django.urls import reverse

from contas import servicos as CS
from contas.models import Perfil
from relatorio import grade as G
from relatorio.models import Bloco, Ciclo, Pagina
from relatorio.tests.test_editor_blocos import SENHA, BaseEditor, caixa

GRADE = {"margem_sup": 40, "margem_inf": 40, "margem_esq": 50, "margem_dir": 50, "colunas": 2, "medianiz": 20}


class GradeFuncoesTests(BaseEditor):
    def test_normalizar_e_linhas(self):
        g = G.normalizar_grade({k: str(v) for k, v in GRADE.items()}, 935.4, 566.9)
        self.assertEqual(g["colunas"], 2)
        L = G.linhas_da_grade(g, 935.4, 566.9)
        # útil = 935.4 - 100 - 20 = 815.4 → colunas de 407.7
        self.assertEqual(L["colunas"], [(50.0, 457.7), (477.7, 885.4)])
        self.assertEqual(L["v"], [50.0, 457.7, 477.7, 885.4])
        self.assertEqual(L["h"], [40.0, 526.9])

    def test_vazio_e_sem_grade(self):
        self.assertEqual(G.normalizar_grade({k: "" for k in G.CAMPOS}), {})
        self.assertEqual(G.linhas_da_grade({}, 935.4, 566.9), {"v": [], "h": [], "colunas": []})

    def test_recusa_valores_ruins(self):
        for errado in ({"colunas": 0}, {"colunas": 13}, {"margem_esq": -1}, {"margem_esq": "abc"},
                       {"margem_esq": 460, "margem_dir": 460}, {"colunas": 12, "medianiz": 80}):
            with self.subTest(errado=errado), self.assertRaises(G.Invalido):
                G.normalizar_grade({**GRADE, **errado}, 935.4, 566.9)

    def test_guias_normalizadas(self):
        g = G.normalizar_guias({"v": [300, "300.04", 10.26, -5, 2000], "h": [100]}, 935.4, 566.9)
        self.assertEqual(g, {"v": [10.3, 300.0], "h": [100.0]})
        with self.assertRaises(G.Invalido):
            G.normalizar_guias({"v": ["x"]}, 935.4, 566.9)
        with self.assertRaises(G.Invalido):
            G.normalizar_guias({"v": list(range(G.MAX_GUIAS + 1))}, 935.4, 566.9)

    def test_fora_da_grade(self):
        dados = {"linhas": G.linhas_da_grade(GRADE, 935.4, 566.9), "pagina": {"v": [], "h": []}}
        self.assertFalse(G.fora_da_grade({"x": 50, "y": 100, "w": 407.7, "h": 50}, dados))
        self.assertFalse(G.fora_da_grade({"x": 50.5, "y": 100, "w": 835, "h": 50}, dados))   # duas colunas
        self.assertTrue(G.fora_da_grade({"x": 60, "y": 100, "w": 397.7, "h": 50}, dados))
        self.assertTrue(G.fora_da_grade({"x": 50, "y": 10, "w": 407.7, "h": 50}, dados))      # acima da margem
        # a exceção alinhada a guias da página deixa de ser apontada
        dados["pagina"] = {"v": [60.0], "h": [10.0]}
        self.assertFalse(G.fora_da_grade({"x": 60, "y": 10, "w": 397.7, "h": 50}, dados))
        # sem grade nem guias, nada fica fora
        self.assertFalse(G.fora_da_grade({"x": 3, "y": 3, "w": 30, "h": 30},
                                         {"linhas": {"v": [], "h": []}, "pagina": {"v": [], "h": []}}))

    def test_lista_de_paginas(self):
        self.assertEqual(G.paginas_da_lista("3, 5-7; 9", [1, 3, 5, 6, 7, 8]), [3, 5, 6, 7])
        self.assertEqual(G.paginas_da_lista("todas", [2, 1]), [1, 2])
        self.assertEqual(G.paginas_da_lista("8-6", [6, 7, 8]), [6, 7, 8])
        with self.assertRaises(G.Invalido):
            G.paginas_da_lista("3 a 5", [3, 4, 5])


class GuiasNoEditorTests(BaseEditor):
    def setUp(self):
        super().setUp()
        Ciclo.objects.filter(pk=self.c.pk).update(grade=GRADE)
        self.pg6 = Pagina.objects.create(ciclo=self.c, numero=6, largura=935.4, altura=566.9, guias={"h": [300.0]})
        self.pg7 = Pagina.objects.create(ciclo=self.c, numero=7, largura=600, altura=400)
        self.entrar()

    def test_tela_traz_grade_e_aponta_fora(self):
        r = self.client.get(reverse("editor_pagina", args=[2030, 5]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'id="ed-regua-h"')
        self.assertContains(r, "Grade do relatório")
        dados = r.context["dados"]
        self.assertEqual(dados["guias"]["linhas"]["v"], [50.0, 457.7, 477.7, 885.4])
        fora = {b["id"]: b["fora"] for b in dados["blocos"]}
        self.assertFalse(fora[self.a.pk] is None)
        self.assertTrue(fora[self.a.pk])      # 50→350: a borda direita não está na grade

    def test_salvar_guias_tira_o_aviso_sem_mover_bloco(self):
        r, j = self.acao("guias", {"guias": {"v": [350, 350.0, 9999], "h": []}, "selecionar": [self.a.pk]})
        self.assertEqual(r.status_code, 200, j)
        self.pg.refresh_from_db()
        self.assertEqual(self.pg.guias, {"v": [350.0], "h": []})
        self.assertEqual(j["guias"]["pagina"]["v"], [350.0])
        self.assertEqual(j["selecionar"], [self.a.pk])
        b = next(b for b in j["blocos"] if b["id"] == self.a.pk)
        self.assertFalse(b["fora"])
        self.a.refresh_from_db()
        self.assertEqual(self.a.config["caixa"]["x"], 50)
        self.assertEqual(self.a.config["caixa"]["w"], 300)

    def test_guia_invalida_recusada(self):
        r, j = self.acao("guias", {"guias": {"v": ["abc"]}})
        self.assertEqual(r.status_code, 400)
        self.assertIn("inválida", j["erro"])

    def test_copiar_soma_ou_substitui(self):
        Pagina.objects.filter(pk=self.pg.pk).update(guias={"v": [350.0, 700.0], "h": [120.0]})
        r, j = self.acao("copiar_guias", {"paginas": "5-7"})
        self.assertEqual(r.status_code, 200, j)
        self.assertIn("2 páginas", j["mensagem"])
        self.pg6.refresh_from_db()
        self.pg7.refresh_from_db()
        self.assertEqual(self.pg6.guias, {"v": [350.0, 700.0], "h": [120.0, 300.0]})
        self.assertEqual(self.pg7.guias, {"v": [350.0], "h": [120.0]})     # 700 não cabe na página de 600
        r, j = self.acao("copiar_guias", {"paginas": "6", "substituir": True})
        self.pg6.refresh_from_db()
        self.assertEqual(self.pg6.guias, {"v": [350.0, 700.0], "h": [120.0]})

    def test_copiar_sem_guias_ou_sem_paginas(self):
        r, j = self.acao("copiar_guias", {"paginas": "6"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("não tem guias", j["erro"])
        Pagina.objects.filter(pk=self.pg.pk).update(guias={"v": [350.0]})
        r, j = self.acao("copiar_guias", {"paginas": "5, 99"})
        self.assertEqual(r.status_code, 400)
        r, j = self.acao("copiar_guias", {"paginas": "seis"})
        self.assertEqual(r.status_code, 400)

    def test_ciclo_encerrado_nao_muda_guias(self):
        Ciclo.objects.filter(pk=self.c.pk).update(situacao=Ciclo.ENCERRADO)
        r, j = self.acao("guias", {"guias": {"v": [10]}})
        self.assertEqual(r.status_code, 400)
        self.pg.refresh_from_db()
        self.assertEqual(self.pg.guias, {})

    def test_setor_nao_mexe_nas_guias(self):
        self.client.logout()
        self.entrar("ana")
        r, _ = self.acao("guias", {"guias": {"v": [10]}})
        self.assertEqual(r.status_code, 403)


class GradeNoPadraoDeDesignTests(BaseEditor):
    def setUp(self):
        super().setUp()
        self.entrar()

    def post(self, **dados):
        return self.client.post(reverse("padrao_design"), {"acao": "grade", "ciclo": 2030, **dados}, follow=True)

    def test_salvar_e_tirar_grade(self):
        r = self.client.get(reverse("padrao_design") + "?ciclo=2030")
        self.assertContains(r, "Grade das páginas")
        r = self.post(**{k: str(v) for k, v in GRADE.items()})
        self.assertContains(r, "não foram movidos")
        self.c.refresh_from_db()
        self.assertEqual(self.c.grade["colunas"], 2)
        self.assertEqual(self.c.grade["margem_esq"], 50.0)
        self.a.refresh_from_db()
        self.assertEqual(self.a.config["caixa"]["x"], 50)          # os blocos existentes ficam onde estavam
        r = self.client.post(reverse("padrao_design"), {"acao": "grade_limpar", "ciclo": 2030}, follow=True)
        self.c.refresh_from_db()
        self.assertEqual(self.c.grade, {})

    def test_valor_ruim_nao_salva(self):
        r = self.post(**{**{k: str(v) for k, v in GRADE.items()}, "colunas": "40"})
        self.assertContains(r, "Use de 1 a 12 colunas")
        self.c.refresh_from_db()
        self.assertEqual(self.c.grade, {})

    def test_salvar_fonte_continua_funcionando(self):
        r = self.client.post(reverse("padrao_design"), {"fonte_texto": "arial", "tamanho_texto": "14",
                                                        "espaco_linhas": "1.4", "espaco_paragrafos": "8"}, follow=True)
        self.assertContains(r, "Padrão de design salvo")

    def test_setor_comum_nao_acessa(self):
        self.client.logout()
        self.entrar("ana")
        r = self.client.post(reverse("padrao_design"), {"acao": "grade", "ciclo": 2030, **GRADE})
        self.assertEqual(r.status_code, 403)
        self.c.refresh_from_db()
        self.assertEqual(self.c.grade, {})

    def test_diagramacao_define_a_grade(self):
        CS.criar_usuario(login="bri", nome="Brígida", senha=SENHA, e_diagramacao=True)
        Perfil.objects.update(troca_senha=False)
        self.client.logout()
        self.assertTrue(self.client.login(username="bri", password=SENHA))
        self.post(**{k: str(v) for k, v in GRADE.items()})
        self.c.refresh_from_db()
        self.assertEqual(self.c.grade["colunas"], 2)
