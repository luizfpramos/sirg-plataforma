"""2.18, etapa 1: montar o relatório do ano (passos, seções, ciclo de trabalho, excluir na homologação) e a
preparação automática que não mexe mais nos ciclos montados pela tela."""
import shutil
import tempfile
from pathlib import Path

from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse

from contas import servicos as CS
from contas.models import EventoAuditoria, Perfil, Setor
from relatorio import montagem as M
from relatorio.construtor import secao
from relatorio.models import Bloco, Ciclo, ImportacaoPDF, Pagina, Secao
from relatorio.views import ciclo_atual

SENHA = "Senha-forte-2026"


class BaseMontagem(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.dados = tempfile.mkdtemp()
        cls._cfg = override_settings(DADOS_DIR=Path(cls.dados), MEDIA_ROOT=Path(cls.dados) / "arquivos")
        cls._cfg.enable()

    @classmethod
    def tearDownClass(cls):
        cls._cfg.disable()
        shutil.rmtree(cls.dados, ignore_errors=True)
        super().tearDownClass()

    @classmethod
    def setUpTestData(cls):
        call_command("inicializar", verbosity=0)
        cls.admin, _ = CS.criar_usuario(login="adm", nome="Admin", e_admin=True, senha=SENHA)
        cls.ana, _ = CS.criar_usuario(login="ana", nome="Ana", setores=[Setor.objects.get(sigla="DIRGRAD")],
                                      senha=SENHA)
        Perfil.objects.update(troca_senha=False)
        cls.c = Ciclo.objects.create(ano=2030, titulo="RG 2030", situacao=Ciclo.PREPARACAO)

    def entrar(self, login="adm"):
        self.assertTrue(self.client.login(username=login, password=SENHA))


class CicloDeTrabalhoTests(BaseMontagem):
    def test_sem_marca_vale_o_mais_recente(self):
        Ciclo.objects.create(ano=2020, titulo="Teste")
        self.assertEqual(ciclo_atual(), self.c)

    def test_ciclo_de_trabalho_e_o_marcado(self):
        t = Ciclo.objects.create(ano=2020, titulo="RG 2026-B (teste)")
        self.entrar()
        self.client.post(reverse("ciclo_de_trabalho", args=[2020]))
        self.assertEqual(ciclo_atual(), t)
        r = self.client.get(reverse("painel"))
        self.assertContains(r, reverse("escrever", args=[2020]))
        # só um marcado por vez
        self.client.post(reverse("ciclo_de_trabalho", args=[2030]))
        self.assertEqual(list(Ciclo.objects.filter(em_trabalho=True)), [self.c])

    def test_setor_nao_muda_o_ciclo_de_trabalho(self):
        Ciclo.objects.create(ano=2020, titulo="Teste")
        self.entrar("ana")
        self.assertEqual(self.client.post(reverse("ciclo_de_trabalho", args=[2020])).status_code, 403)
        self.assertEqual(ciclo_atual(), self.c)


class PassosTests(BaseMontagem):
    def test_ciclo_vazio_mostra_o_que_falta(self):
        self.entrar()
        r = self.client.get(reverse("montagem", args=[2030]))
        self.assertEqual(r.status_code, 200)
        passos = r.context["passos"]
        self.assertEqual([p["titulo"] for p in passos], ["Seções", "PDF diagramado", "Blocos nas páginas",
                                                         "Atributos dos blocos", "Quadros de números", "Abrir a coleta"])
        self.assertTrue(all(p["situacao"] == "falta" for p in passos))
        self.assertContains(r, "Criar as seções")

    def test_secao_sem_setor_e_aviso(self):
        cap = secao(self.c, "cap", "Capítulo", ordem=10)
        secao(self.c, "s1", "Seção", pai=cap, ordem=10)
        p = M.passos(self.c)[0]
        self.assertEqual(p["situacao"], "aviso")
        self.assertIn("sem setor", p["texto"])

    def test_menu_leva_a_montagem(self):
        self.entrar()
        r = self.client.get(reverse("painel"))
        self.assertContains(r, "Montar o relatório")
        self.assertRedirects(self.client.get(reverse("montagem_inicio")), reverse("montagem", args=[2030]))

    def test_setor_nao_acessa(self):
        self.entrar("ana")
        self.assertEqual(self.client.get(reverse("montagem", args=[2030])).status_code, 403)
        self.assertEqual(self.client.get(reverse("secoes_lista", args=[2030])).status_code, 403)

    def test_novo_ciclo_vai_para_a_montagem(self):
        self.entrar()
        r = self.client.post(reverse("ciclo_novo"), {"ano": 2020, "titulo": "RG 2026-B (teste)", "origem": "",
                                                      "anos_serie": 5})
        self.assertRedirects(r, reverse("montagem", args=[2020]))
        r = self.client.get(reverse("montagem", args=[2020]))
        self.assertContains(r, "Este não é o relatório de trabalho")


class SecoesTests(BaseMontagem):
    def test_lista_colada_cria_capitulos_secoes_e_setores(self):
        self.entrar()
        lista = ("Apresentação\n- Mensagem da dirigente | GAB\n- Sobre o relatório | DGDI, SEGEP\n\n"
                 "Visão geral\n  Quem somos | XYZ\n")
        r = self.client.post(reverse("secoes_lista", args=[2030]), {"lista": lista}, follow=True)
        self.assertContains(r, "2 capítulo(s) e 3 seção(ões) criados")
        self.assertContains(r, "setor “XYZ” não existe")
        arv = M.arvore(self.c)
        self.assertEqual([c.titulo for c, _ in arv], ["Apresentação", "Visão geral"])
        self.assertEqual([s.titulo for s in arv[0][1]], ["Mensagem da dirigente", "Sobre o relatório"])
        self.assertEqual(sorted(st.sigla for st in arv[0][1][1].setores.all()), ["DGDI", "SEGEP"])
        self.assertEqual([s.titulo for s in arv[1][1]], ["Quem somos"])
        # uma segunda lista continua depois do último capítulo e não repete chaves
        M.adicionar_em_lote(self.c, "Apresentação\n- Mensagem da dirigente")
        self.assertEqual(Secao.objects.filter(ciclo=self.c, titulo="Apresentação").count(), 2)
        self.assertEqual(M.arvore(self.c)[-1][0].titulo, "Apresentação")

    def test_secao_sem_capitulo_vira_capitulo(self):
        caps, secs, avisos = M.adicionar_em_lote(self.c, "- Solta")
        self.assertEqual((caps, secs), (1, 0))
        self.assertTrue(avisos)

    def test_mover(self):
        cap = secao(self.c, "cap", "Capítulo", ordem=10)
        a = secao(self.c, "a", "A", pai=cap, ordem=10)
        secao(self.c, "b", "B", pai=cap, ordem=20)
        self.entrar()
        self.client.post(reverse("secao_mover", args=[2030, "a", "descer"]))
        self.assertEqual([s.chave for s in M.arvore(self.c)[0][1]], ["b", "a"])
        self.client.post(reverse("secao_mover", args=[2030, "a", "descer"]))   # já é a última: nada muda
        self.client.post(reverse("secao_mover", args=[2030, "a", "subir"]))
        self.assertEqual([s.chave for s in M.arvore(self.c)[0][1]], ["a", "b"])
        a.refresh_from_db()
        self.assertEqual(a.ordem, 10)

    def test_editar_volta_para_a_lista(self):
        cap = secao(self.c, "cap", "Capítulo", ordem=10)
        self.entrar()
        r = self.client.post(reverse("secao_editar", args=[2030, "cap"]),
                             {"titulo": "Capítulo 1", "pai": "", "ordem": 10, "chave": "cap", "orientacao": "",
                              "voltar": "secoes"})
        self.assertRedirects(r, reverse("secoes_lista", args=[2030]))
        cap.refresh_from_db()
        self.assertEqual(cap.titulo, "Capítulo 1")


class ExcluirCicloTests(BaseMontagem):
    def _com_conteudo(self):
        cap = secao(self.c, "cap", "Capítulo", ordem=10)
        pg = Pagina.objects.create(ciclo=self.c, numero=1, largura=900, altura=500, fundo="", secao=cap)
        Bloco.objects.create(secao=cap, pagina=pg, conteudo="<p>Texto</p>")
        imp = ImportacaoPDF.objects.create(ciclo=self.c, nome="rg.pdf")
        imp.pasta.mkdir(parents=True)
        (imp.pasta / "original.pdf").write_bytes(b"%PDF-")
        return imp

    def test_na_producao_nao_existe(self):
        self.entrar()
        with override_settings(SIRG_PERMITE_EXCLUIR_CICLO=False):
            self.assertEqual(self.client.get(reverse("ciclo_excluir", args=[2030])).status_code, 403)
            self.assertNotContains(self.client.get(reverse("montagem", args=[2030])), "Excluir este relatório")
        self.assertTrue(Ciclo.objects.filter(ano=2030).exists())

    @override_settings(SIRG_PERMITE_EXCLUIR_CICLO=True)
    def test_na_homologacao_exclui_com_confirmacao(self):
        imp = self._com_conteudo()
        self.entrar()
        self.assertContains(self.client.get(reverse("montagem", args=[2030])), "Excluir este relatório")
        r = self.client.post(reverse("ciclo_excluir", args=[2030]), {"confirmacao": "2029"}, follow=True)
        self.assertContains(r, "digite o ano-base (2030)")
        self.assertTrue(Ciclo.objects.filter(ano=2030).exists())
        r = self.client.post(reverse("ciclo_excluir", args=[2030]), {"confirmacao": "2030"})
        self.assertRedirects(r, reverse("ciclos"))
        self.assertFalse(Ciclo.objects.filter(ano=2030).exists())
        self.assertFalse(Bloco.objects.exists())
        self.assertFalse(imp.pasta.exists())
        self.assertTrue(EventoAuditoria.objects.filter(acao="ciclo_excluido").exists())
        self.assertTrue(Setor.objects.exists())

    @override_settings(SIRG_PERMITE_EXCLUIR_CICLO=True)
    def test_setor_nao_exclui(self):
        self.entrar("ana")
        self.assertEqual(self.client.post(reverse("ciclo_excluir", args=[2030]), {"confirmacao": "2030"}).status_code,
                         403)
        self.assertTrue(Ciclo.objects.filter(ano=2030).exists())


class PreparacaoAutomaticaTests(BaseMontagem):
    def test_rg2026_excluido_nao_volta(self):
        Ciclo.objects.create(ano=2026, titulo="Relatório de Gestão 2026", automatico=True).delete()
        teste = Ciclo.objects.create(ano=2020, titulo="RG 2026-B (teste)")
        call_command("preparar_rg2026", sem_backup=True, verbosity=0)
        self.assertFalse(Ciclo.objects.filter(ano=2026).exists())
        self.assertTrue(Ciclo.objects.filter(pk=teste.pk).exists())

    def test_rg2026_montado_pela_tela_nao_e_alterado(self):
        rg = Ciclo.objects.create(ano=2026, titulo="RG 2026 (montado pela tela)")
        teste = Ciclo.objects.create(ano=2020, titulo="Teste")
        call_command("preparar_rg2026", sem_backup=True, verbosity=0)
        self.assertEqual(rg.secoes.count(), 0)
        self.assertEqual(rg.quadros.count(), 0)
        self.assertTrue(Ciclo.objects.filter(pk=teste.pk).exists())
