"""2.21: as telas da montagem têm a mesma barra no alto — volta à montagem, "Passo N de 8", anterior e próximo."""
from django.test import TestCase
from django.urls import reverse

from contas import servicos as CS
from contas.models import Perfil, Setor
from relatorio import montagem as M
from relatorio.models import Bloco, Ciclo, Pagina, Secao

SENHA = "Senha-forte-2026"


class NavegacaoDaMontagemTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin, _ = CS.criar_usuario(login="adm", nome="Admin", e_admin=True, senha=SENHA)
        cls.chefe, _ = CS.criar_usuario(login="chefe", nome="Mara", e_master=True, senha=SENHA)
        Perfil.objects.update(troca_senha=False)
        cls.c = Ciclo.objects.create(ano=2030, titulo="RG 2030", situacao=Ciclo.PREPARACAO)
        cap = Secao.objects.create(ciclo=cls.c, chave="cap", titulo="Capítulo", ordem=1)
        sec = Secao.objects.create(ciclo=cls.c, chave="sec", titulo="Seção", ordem=1, pai=cap)
        pg = Pagina.objects.create(ciclo=cls.c, numero=1, secao=sec)
        Bloco.objects.create(secao=sec, pagina=pg, tipo=Bloco.TEXTO, config={"caixa": {"x": 10, "y": 10, "w": 100,
                                                                                      "h": 40, "css": ""}})

    def telas(self):
        a = self.c.ano
        return [reverse("setores") + f"?montagem={a}", reverse("secoes_lista", args=[a]),
                reverse("importar_pdf", args=[a]), reverse("editor_pagina", args=[a, 1]),
                reverse("blocos_atributos", args=[a]), reverse("quadros_lista", args=[a]),
                reverse("pdf_anterior_enviar", args=[a]), reverse("ciclo_editar", args=[a])]

    def test_roteiro_e_passos_tem_as_mesmas_telas_na_mesma_ordem(self):
        self.assertEqual(len(M.ROTEIRO), len(M.passos(self.c)))
        self.assertEqual([t for t, _ in M.ROTEIRO][:3], ["Setores e pessoas", "Seções", "PDF diagramado"])

    def test_cada_tela_mostra_o_passo_e_volta_para_a_montagem(self):
        self.client.force_login(self.admin)
        montagem = reverse("montagem", args=[self.c.ano])
        for n, url in enumerate(self.telas(), start=1):
            with self.subTest(url=url):
                h = self.client.get(url, follow=True).content.decode()
                self.assertIn(f"Passo {n} de 8", h)
                self.assertIn(f'href="{montagem}"', h)

    def test_anterior_e_proximo(self):
        self.client.force_login(self.admin)
        h = self.client.get(reverse("importar_pdf", args=[self.c.ano])).content.decode()
        self.assertIn("2. Seções", h)
        self.assertIn("4. Blocos nas páginas", h)
        h = self.client.get(reverse("setores") + f"?montagem={self.c.ano}").content.decode()
        self.assertNotIn("Passo anterior", h)          # o primeiro não tem anterior
        self.assertIn("2. Seções", h)
        h = self.client.get(reverse("ciclo_editar", args=[self.c.ano])).content.decode()
        self.assertNotIn("Próximo passo", h)           # o último não tem próximo

    def test_setores_pelo_menu_nao_mostra_os_passos(self):
        self.client.force_login(self.admin)
        h = self.client.get(reverse("setores")).content.decode()
        self.assertNotIn("Passo 1 de 8", h)

    def test_setores_leva_o_passo_para_o_setor_e_volta(self):
        self.client.force_login(self.admin)
        s = Setor.objects.create(sigla="XYZ", nome="Setor XYZ")
        h = self.client.get(reverse("setores") + f"?montagem={self.c.ano}").content.decode()
        self.assertIn(reverse("setor", args=[s.pk]) + f"?montagem={self.c.ano}", h)
        h = self.client.get(reverse("setor", args=[s.pk]) + f"?montagem={self.c.ano}").content.decode()
        self.assertIn(reverse("setores") + f"?montagem={self.c.ano}", h)

    def test_passo_1_da_montagem_abre_setores_com_a_barra(self):
        self.assertIn(f"?montagem={self.c.ano}", M.passos(self.c)[0]["url"])

    def test_editor_chefe_nao_ve_os_passos_e_volta_para_o_relatorio(self):
        self.client.force_login(self.chefe)
        h = self.client.get(reverse("blocos_atributos", args=[self.c.ano]), follow=True).content.decode()
        self.assertNotIn("Passo 5 de 8", h)
        self.assertNotIn(reverse("montagem", args=[self.c.ano]), h)
        self.assertIn(reverse("escrever", args=[self.c.ano]), h)
        h = self.client.get(reverse("editor_pagina", args=[self.c.ano, 1])).content.decode()
        self.assertNotIn("Passo 4 de 8", h)
        self.assertIn(reverse("escrever", args=[self.c.ano]), h)
