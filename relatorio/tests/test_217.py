"""2.17: "Master" passa a se chamar "Editor-chefe" e o menu do alto cabe na tela."""
from django.core.management import call_command
from django.test import TestCase

from contas import servicos as CS
from contas.models import Perfil
from relatorio.dados_iniciais import rg2026
from relatorio.models import Ciclo, Quadro

SENHA = "Senha-forte-2026"


class EditorChefeEMenuTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("inicializar", verbosity=0)
        call_command("preparar_rg2026", sem_backup=True, verbosity=0)
        cls.chefe, _ = CS.criar_usuario(login="chefe", nome="Mara", e_master=True, senha=SENHA)
        cls.admin, _ = CS.criar_usuario(login="adm", nome="Admin", e_admin=True, senha=SENHA)
        Perfil.objects.update(troca_senha=False)
        cls.c = Ciclo.objects.get(ano=2026)

    def test_telas_dizem_editor_chefe(self):
        self.client.force_login(self.chefe)
        h = self.client.get("/").content.decode()
        self.assertIn("Editor-chefe", h)
        self.assertNotRegex(h, r"\bMaster\b")
        self.client.force_login(self.admin)
        h = self.client.get("/usuarios/").content.decode()
        self.assertIn(">Editor-chefe</option>", h)

    def test_menu_do_admin_em_duas_colunas_e_sair_fixo(self):
        self.client.force_login(self.admin)
        h = self.client.get("/").content.decode()
        self.assertIn("menu-topo menu-longo", h)
        self.assertIn('class="menu-sair"', h)
        self.client.force_login(self.chefe)
        self.assertNotIn("menu-longo", self.client.get("/").content.decode())

    def test_orientacao_do_sistema_troca_e_a_editada_fica(self):
        q1, q2 = Quadro.objects.filter(ciclo=self.c)[:2]
        Quadro.objects.filter(pk=q1.pk).update(descricao="Peça ao Master para corrigir.")
        q2.descricao = "Texto meu: falar com o Master."
        q2._history_user = self.chefe                      # alterado por alguém pela plataforma
        q2.save()
        n = rg2026.renomear_master(self.c)
        q1.refresh_from_db(); q2.refresh_from_db()
        self.assertEqual(q1.descricao, "Peça ao Editor-chefe para corrigir.")
        self.assertEqual(q2.descricao, "Texto meu: falar com o Master.")
        self.assertGreaterEqual(n, 1)
        self.assertEqual(rg2026.renomear_master(self.c), 0)    # não repete
