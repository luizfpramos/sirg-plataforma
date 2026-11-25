"""2.21: blocos feitos pela pessoa a partir do texto do PDF, e a página inicial de cada seção corrigível depois."""
import shutil
import tempfile
from pathlib import Path

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse

from contas import servicos as CS
from contas.models import Perfil
from relatorio import editor_blocos as E
from relatorio import importador as I
from relatorio import montagem as M
from relatorio import textos_pdf as TP
from relatorio.construtor import secao
from relatorio.models import Bloco, Ciclo, ImportacaoPDF, Pagina
from relatorio.tests.test_reimportacao import pdf_com

SENHA = "Senha-forte-2026"


@override_settings(SIRG_IMPORTACAO_SINCRONA=True)
class BlocosManuaisTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.media, cls.dados = tempfile.mkdtemp(), tempfile.mkdtemp()
        cls._cfg = override_settings(MEDIA_ROOT=cls.media, DADOS_DIR=Path(cls.dados))
        cls._cfg.enable()
        cls.pdf = pdf_com(paginas=3, extra=True)

    @classmethod
    def tearDownClass(cls):
        cls._cfg.disable()
        shutil.rmtree(cls.media, ignore_errors=True)
        shutil.rmtree(cls.dados, ignore_errors=True)
        super().tearDownClass()

    @classmethod
    def setUpTestData(cls):
        call_command("inicializar", verbosity=0)
        cls.admin, _ = CS.criar_usuario(login="adm", nome="Admin", e_admin=True, senha=SENHA)
        Perfil.objects.update(troca_senha=False)
        cls.c = Ciclo.objects.create(ano=2030, titulo="RG 2030", situacao=Ciclo.PREPARACAO)
        cap = secao(cls.c, "cap1", "1. Visão geral", ordem=1)
        cls.apres = secao(cls.c, "apresentacao", "Apresentação", pai=cap, ordem=1, setores=["DIRGRAD"])
        cls.grad = secao(cls.c, "ensino_graduacao", "Ensino de graduação", pai=cap, ordem=2, setores=["DIRGRAD"])
        cls.pesq = secao(cls.c, "pesquisa", "Pesquisa e inovação", pai=cap, ordem=3, setores=["DIRGRAD"])

    def setUp(self):
        self.client.force_login(self.admin)
        arq = SimpleUploadedFile("RG.pdf", self.pdf, content_type="application/pdf")
        self.imp = I.receber(self.c, arq, self.admin)
        I.iniciar(self.imp)
        self.imp.refresh_from_db()

    def aplicar(self, **extra):
        d = {"conferido": "1", "exibicao_vazio": "orientacao", "modo_blocos": "manual",
             f"inicio_{self.apres.pk}": "1", f"inicio_{self.grad.pk}": "2", f"inicio_{self.pesq.pk}": "3"}
        d.update(extra)
        return self.client.post(reverse("importacao_aplicar", args=[2030, self.imp.pk]), d)

    # --- importação ------------------------------------------------------------------------------------------
    def test_padrao_da_tela_e_manual(self):
        r = self.client.get(reverse("importacao_ver", args=[2030, self.imp.pk]))
        self.assertContains(r, 'value="manual" checked')

    def test_manual_cria_so_as_paginas_e_abre_o_editor(self):
        r = self.aplicar()
        self.assertRedirects(r, reverse("editor_inicio", args=[2030]), fetch_redirect_response=False)
        self.assertEqual(self.c.paginas.count(), 3)
        self.assertFalse(Bloco.objects.filter(secao__ciclo=self.c).exists())
        self.assertEqual(ImportacaoPDF.objects.get(pk=self.imp.pk).resumo["blocos"], I.MANUAL)

    def test_manual_secao_de_conteudo_fixo_ja_recebe_o_texto(self):
        self.aplicar(**{f"fixo_{self.grad.pk}": "1"})
        blocos = Bloco.objects.filter(secao__ciclo=self.c)
        self.assertTrue(blocos.exists())
        self.assertTrue(all(b.secao == self.grad and b.config.get("fixo") for b in blocos))

    def test_sugeridos_continua_como_antes(self):
        self.aplicar(modo_blocos="sugeridos")
        self.assertEqual(Bloco.objects.filter(secao__ciclo=self.c, pagina__numero=2).count(), 3)

    # --- editor ----------------------------------------------------------------------------------------------
    def pagina(self, n):
        self.aplicar()
        return Pagina.objects.get(ciclo=self.c, numero=n)

    def test_texto_do_pdf_aparece_no_editor_sem_rodape(self):
        pg = self.pagina(2)
        caixas = TP.caixas_da_pagina(pg)
        textos = [c["texto"] for c in caixas]
        self.assertTrue(any("Ensino de graduação" in t for t in textos))
        self.assertFalse(any("RELATÓRIO DE GESTÃO" in t for t in textos))       # rodapé repetido fica de fora
        r = self.client.get(reverse("editor_pagina", args=[2030, 2]))
        self.assertContains(r, "ed-ver-pdf")
        self.assertEqual(len(r.context["dados"]["pdf"]), len(caixas))

    def test_criar_bloco_fixo_a_partir_do_pdf(self):
        pg = self.pagina(2)
        titulo = next(c for c in TP.caixas_da_pagina(pg) if "graduação" in c["texto"])
        ids, msg = E.criar(self.admin, pg, {"tipo": "texto", "secao": self.grad.pk, "pdf": [titulo["i"]],
                                            "texto": "fixo", "x": titulo["x"], "y": titulo["y"],
                                            "w": titulo["w"], "h": titulo["h"]})
        b = Bloco.objects.get(pk=ids[0])
        self.assertTrue(b.config["fixo"])
        self.assertIn("Ensino de graduação", b.conteudo)
        self.assertEqual(b.config["caixa"]["css"], titulo["css"])        # fonte do PDF

    def test_criar_bloco_do_setor_a_partir_do_pdf(self):
        pg = self.pagina(2)
        par = next(c for c in TP.caixas_da_pagina(pg) if "resultados" in c["texto"])
        ids, msg = E.criar(self.admin, pg, {"tipo": "texto", "secao": self.grad.pk, "pdf": [par["i"]],
                                            "texto": "setor", "x": par["x"], "y": par["y"], "w": par["w"],
                                            "h": par["h"]})
        b = Bloco.objects.get(pk=ids[0])
        self.assertEqual(b.conteudo, "")
        self.assertIn("resultados do ano", b.config["referencia_pdf"])
        self.assertTrue(b.min_caracteres and b.max_caracteres)

    def test_juntar_varias_caixas_em_ordem_de_leitura(self):
        pg = self.pagina(2)
        cxs = TP.caixas_da_pagina(pg)
        html, css, _q = TP.juntar_caixas(pg, [c["i"] for c in reversed(cxs)])
        self.assertLess(html.index("graduação"), html.index("destaques"))

    def test_fixo_sem_texto_do_pdf_e_recusado(self):
        pg = self.pagina(2)
        with self.assertRaises(E.Recusado):
            E.criar(self.admin, pg, {"tipo": "texto", "secao": self.grad.pk, "texto": "fixo",
                                     "x": 10, "y": 10, "w": 100, "h": 40})

    def test_fixar_todos_os_textos_restantes(self):
        pg = self.pagina(3)
        n = len(TP.caixas_da_pagina(pg))
        r = self.client.post(reverse("editor_acao", args=[2030, 3, "fixar_textos"]), "{}",
                             content_type="application/json")
        self.assertTrue(r.json()["ok"])
        self.assertEqual(Bloco.objects.filter(pagina=pg, config__fixo=True).count(), n)
        with self.assertRaises(E.Recusado):         # nada mais a fixar
            E.fixar_textos(self.admin, pg, {})

    # --- página inicial das seções ---------------------------------------------------------------------------
    def test_mudar_onde_a_secao_comeca_leva_paginas_e_blocos(self):
        self.aplicar(modo_blocos="sugeridos")
        self.assertEqual(dict((s.pk, n) for s, n in M.inicios_das_secoes(self.c))[self.pesq.pk], 3)
        r = self.client.post(reverse("secoes_paginas", args=[2030]),
                             {f"inicio_{self.apres.pk}": "1", f"inicio_{self.grad.pk}": "",
                              f"inicio_{self.pesq.pk}": "2"})
        self.assertRedirects(r, reverse("secoes_lista", args=[2030]) + "#paginas", fetch_redirect_response=False)
        self.assertEqual(Pagina.objects.get(ciclo=self.c, numero=2).secao, self.pesq)
        self.assertTrue(all(b.secao == self.pesq for b in Bloco.objects.filter(pagina__numero__in=[2, 3],
                                                                               secao__ciclo=self.c)))
        self.assertIsNone(ImportacaoPDF.objects.get(pk=self.imp.pk).resumo["inicios"][str(self.grad.pk)])

    def test_bloco_posto_em_outra_secao_nao_muda(self):
        self.aplicar(modo_blocos="sugeridos")
        b = Bloco.objects.filter(pagina__numero=3, secao__ciclo=self.c).first()
        b.secao = self.apres
        b.save()
        M.mudar_inicios(self.c, {self.pesq.pk: 2, self.grad.pk: None})
        b.refresh_from_db()
        self.assertEqual(b.secao, self.apres)

    def test_fora_de_ordem_e_pagina_inexistente_sao_recusadas(self):
        self.aplicar()
        with self.assertRaises(M.Recusado):
            M.mudar_inicios(self.c, {self.grad.pk: 3, self.pesq.pk: 2})
        with self.assertRaises(M.Recusado):
            M.mudar_inicios(self.c, {self.pesq.pk: 9})

    def test_tela_de_secoes_mostra_as_paginas_depois_de_aplicar(self):
        r = self.client.get(reverse("secoes_lista", args=[2030]))
        self.assertNotContains(r, "Página em que cada seção começa")
        self.aplicar()
        r = self.client.get(reverse("secoes_lista", args=[2030]))
        self.assertContains(r, "Página em que cada seção começa")
        self.assertContains(r, f'name="inicio_{self.pesq.pk}" value="3"')
