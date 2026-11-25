"""2.18, etapa 2: conferência das páginas de cada seção, blocos vazios, conteúdo fixo e o texto do ano anterior."""
import shutil
import tempfile
from pathlib import Path

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse

from contas import servicos as CS
from contas.models import Perfil, Setor
from relatorio import atributos as AT
from relatorio import fluxo as F
from relatorio import importador as I
from relatorio.construtor import secao
from relatorio.models import Bloco, Ciclo, ImportacaoPDF, Secao
from relatorio.tests.test_reimportacao import pdf_com

SENHA = "Senha-forte-2026"


@override_settings(SIRG_IMPORTACAO_SINCRONA=True)
class ConferenciaTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.media, cls.dados = tempfile.mkdtemp(), tempfile.mkdtemp()
        cls._cfg = override_settings(MEDIA_ROOT=cls.media, DADOS_DIR=Path(cls.dados))
        cls._cfg.enable()
        cls.pdf = pdf_com(paginas=3)

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
        cls.chefe, _ = CS.criar_usuario(login="chefe", nome="Chefe", e_master=True, senha=SENHA)
        g = Setor.objects.get(sigla="DIRGRAD")
        cls.ana, _ = CS.criar_usuario(login="ana", nome="Ana", setores=[g], senha=SENHA)
        Perfil.objects.update(troca_senha=False)
        cls.c = Ciclo.objects.create(ano=2030, titulo="RG 2030", situacao=Ciclo.COLETA)
        cap = secao(cls.c, "cap1", "1. Visão geral", ordem=1)
        cls.apres = secao(cls.c, "apresentacao", "Apresentação", pai=cap, ordem=1, setores=["DIRGRAD"])
        cls.grad = secao(cls.c, "ensino_graduacao", "Ensino de graduação", pai=cap, ordem=2, setores=["DIRGRAD"])
        cls.pesq = secao(cls.c, "pesquisa", "Pesquisa e inovação", pai=cap, ordem=3, setores=["DIRGRAD"])

    def setUp(self):
        self.assertTrue(self.client.login(username="adm", password=SENHA))
        arq = SimpleUploadedFile("RG.pdf", self.pdf, content_type="application/pdf")
        self.imp = I.receber(self.c, arq, self.admin)
        I.iniciar(self.imp)
        self.imp.refresh_from_db()
        self.assertEqual(self.imp.situacao, ImportacaoPDF.PRONTA, self.imp.mensagem)

    def form(self, **muda):
        d = {"conferido": "1", "exibicao_vazio": "orientacao", "modo_blocos": "sugeridos"}
        for s, n in ((self.apres, 1), (self.grad, 2), (self.pesq, 3)):
            d[f"inicio_{s.pk}"] = str(n)
        d[f"inicio_{self.c.secoes.get(chave='cap1').pk}"] = ""
        d.update(muda)
        return d

    def blocos(self, n):
        return list(Bloco.objects.filter(secao__ciclo=self.c, pagina__numero=n).order_by("ordem"))

    def test_conferencia_mostra_o_que_o_sistema_achou(self):
        linhas = {l["s"].chave: l for l in I.conferencia(self.imp)}
        self.assertEqual((linhas["apresentacao"]["achada"], linhas["ensino_graduacao"]["achada"],
                          linhas["pesquisa"]["achada"]), (1, 2, 3))
        self.assertIsNone(linhas["cap1"]["achada"])
        r = self.client.get(reverse("importacao_ver", args=[2030, self.imp.pk]))
        self.assertContains(r, "Páginas de cada seção")
        self.assertContains(r, "não achada")

    def test_blocos_nascem_vazios_com_referencia_e_titulo_fixo(self):
        r = self.client.post(reverse("importacao_aplicar", args=[2030, self.imp.pk]), self.form())
        self.assertRedirects(r, reverse("montagem", args=[2030]))
        titulo, corpo = self.blocos(2)
        self.assertIn("Ensino de graduação", titulo.conteudo)        # título: texto do PDF, fixo
        self.assertTrue(titulo.config["fixo"])
        self.assertEqual(corpo.conteudo, "")                         # corpo: vazio
        self.assertIn("resultados do ano", corpo.config["referencia_pdf"])
        self.assertTrue(corpo.min_caracteres and corpo.max_caracteres > corpo.min_caracteres)
        self.assertEqual(corpo.secao, self.grad)
        self.assertEqual(self.imp.ciclo.importacoes.get().resumo["inicios"][str(self.grad.pk)], 2)

    def test_pagina_escolhida_muda_a_secao_dos_blocos(self):
        # a pesquisa passa a começar na página 2 e a graduação some do PDF
        self.client.post(reverse("importacao_aplicar", args=[2030, self.imp.pk]),
                         self.form(**{f"inicio_{self.grad.pk}": "", f"inicio_{self.pesq.pk}": "2"}))
        self.assertTrue(all(b.secao == self.pesq for b in self.blocos(2) + self.blocos(3)))
        self.assertFalse(Bloco.objects.filter(secao=self.grad).exists())
        self.assertIn("Ensino de graduação", ImportacaoPDF.objects.get().resumo["secoes_faltando"])

    def test_pagina_inexistente_e_recusada(self):
        r = self.client.post(reverse("importacao_aplicar", args=[2030, self.imp.pk]),
                             self.form(**{f"inicio_{self.pesq.pk}": "9"}), follow=True)
        self.assertContains(r, "A página 9")
        self.assertFalse(self.c.paginas.exists())

    def test_so_guardar_as_escolhas(self):
        self.client.post(reverse("importacao_aplicar", args=[2030, self.imp.pk]),
                         self.form(salvar="1", exibicao_vazio="lorem", **{f"inicio_{self.pesq.pk}": "2",
                                                                           f"fixo_{self.apres.pk}": "1"}))
        self.assertFalse(self.c.paginas.exists())
        linhas = {l["s"].chave: l for l in I.conferencia(ImportacaoPDF.objects.get())}
        self.assertEqual(linhas["pesquisa"]["pagina"], 2)
        self.assertTrue(linhas["apresentacao"]["fixo"])
        self.assertTrue(linhas["pesquisa"]["fora_de_ordem"] is False)
        self.c.refresh_from_db()
        self.assertEqual(self.c.exibicao_vazio, "lorem")

    def test_secao_de_conteudo_fixo_recebe_o_texto_e_so_o_editor_chefe_altera(self):
        self.client.post(reverse("importacao_aplicar", args=[2030, self.imp.pk]),
                         self.form(**{f"fixo_{self.apres.pk}": "1"}))
        self.assertTrue(Secao.objects.get(pk=self.apres.pk).conteudo_fixo)
        corpo = self.blocos(1)[1]
        self.assertIn("resultados do ano", corpo.conteudo)
        self.assertTrue(corpo.config["fixo"])
        self.assertFalse(F.pode_editar_bloco(self.ana, corpo))
        self.assertIn("só o Editor-chefe", F.motivo_bloco_bloqueado(self.ana, corpo))
        self.assertTrue(F.pode_editar_bloco(self.chefe, corpo))
        vazio = self.blocos(2)[1]
        self.assertTrue(F.pode_editar_bloco(self.ana, vazio))

    def test_texto_do_ano_anterior_e_enchimento_na_tela(self):
        self.client.post(reverse("importacao_aplicar", args=[2030, self.imp.pk]), self.form(exibicao_vazio="lorem"))
        corpo = self.blocos(2)[1]
        self.assertTrue(self.client.login(username="ana", password=SENHA))
        r = self.client.get(reverse("bloco_referencia", args=[2030, corpo.pk]))
        self.assertIn("resultados do ano", r.json()["html"])
        r = self.client.get(reverse("escrever", args=[2030]))
        self.assertContains(r, "guia-enchimento")
        self.assertContains(r, "Lorem ipsum")
        self.assertContains(r, 'data-tem-ref="1"')
        self.assertContains(r, "Ano anterior")

    def test_enchimento_tem_o_tamanho_do_bloco(self):
        b = Bloco(max_caracteres=120, config={})
        t = AT.enchimento("lorem", AT.tamanho_do_enchimento(b))
        self.assertTrue(100 <= len(t) <= 120)
        self.assertTrue(set(AT.enchimento("xxx", 60).replace(" ", "")) == {"x"})
        self.assertEqual(AT.anotar(b, [], None, "nada")["enchimento"], "")

    def test_reimportacao_mantem_as_paginas_escolhidas(self):
        from relatorio import reimportador as RI
        self.client.post(reverse("importacao_aplicar", args=[2030, self.imp.pk]),
                         self.form(**{f"inicio_{self.grad.pk}": "", f"inicio_{self.pesq.pk}": "2"}))
        arq = SimpleUploadedFile("RG2.pdf", pdf_com(paginas=3, extra=True), content_type="application/pdf")
        nova = I.receber(self.c, arq, self.admin)
        I.iniciar(nova)
        nova.refresh_from_db()
        RI.reimportar(nova, self.admin)
        criado = Bloco.objects.get(pagina__numero=2, conteudo__contains="Quadro de destaques")
        self.assertEqual(criado.secao, self.pesq)          # segue a escolha feita, não o título achado
        self.assertTrue(criado.config["rotulo"])           # texto curto: rótulo fixo do modelo

    def test_texto_curto_fica_fixo_e_numero_antigo_e_marcado(self):
        sec = Secao(conteudo_fixo=False)
        html, extra, mi, ma, _ = I.conteudo_da_caixa({"html": "<p>4.512 estudantes</p>", "tam": 11}, sec, 20)
        self.assertIn("4.512", html)
        self.assertEqual((extra["fixo"], extra["rotulo"], extra["numero_antigo"]), (True, True, True))
        _, extra, _, _, _ = I.conteudo_da_caixa({"html": "<p>Ensino técnico</p>", "tam": 11}, sec, 20)
        self.assertFalse(extra["numero_antigo"])
        html, extra, mi, ma, _ = I.conteudo_da_caixa(
            {"html": "<p>" + "Parágrafo longo do relatório. " * 4 + "</p>", "tam": 11}, sec, 20)
        self.assertEqual(html, "")
        self.assertIn("referencia_pdf", extra)

    def test_editor_libera_para_o_setor_apaga_por_area_e_avisa_na_montagem(self):
        from relatorio import editor_blocos as E
        from relatorio import montagem as M
        import json
        self.client.post(reverse("importacao_aplicar", args=[2030, self.imp.pk]), self.form())
        pg = self.c.paginas.get(numero=1)
        rot = Bloco.objects.create(secao=self.apres, pagina=pg, conteudo="<p>4.512 alunos</p>",
                                   config={"caixa": {"x": 1, "y": 1, "w": 50, "h": 10, "css": "", "quebra": False},
                                           "fixo": True, "rotulo": True, "numero_antigo": True})
        self.assertIn("número do ano anterior", M.passos(self.c)[3]["texto"])
        self.assertEqual(M.passos(self.c)[3]["situacao"], "aviso")
        url = lambda a: reverse("editor_acao", args=[2030, 1, a])
        r = self.client.post(url("fixo"), json.dumps({"id": rot.pk, "fixo": False}), content_type="application/json")
        self.assertTrue(r.json()["ok"])
        rot.refresh_from_db()
        self.assertEqual(rot.conteudo, "")
        self.assertIn("4.512", rot.config["referencia_pdf"])
        self.assertNotIn("fixo", rot.config)
        self.assertTrue(F.pode_editar_bloco(self.ana, rot))
        self.assertEqual(M.passos(self.c)[3]["situacao"], "feito")
        self.client.post(url("fixo"), json.dumps({"id": rot.pk, "fixo": True}), content_type="application/json")
        rot.refresh_from_db()
        self.assertIn("4.512", rot.conteudo)
        self.assertTrue(rot.config["fixo"])
        # apagar vários de uma vez (seleção por área)
        ids = [b.pk for b in pg.caixas.all()]
        r = self.client.post(url("apagar"), json.dumps({"ids": ids}), content_type="application/json")
        self.assertTrue(r.json()["ok"])
        self.assertFalse(pg.caixas.exists())

    def test_editor_chefe_salvar_tira_a_marca_de_numero(self):
        self.client.post(reverse("importacao_aplicar", args=[2030, self.imp.pk]), self.form())
        pg = self.c.paginas.get(numero=1)
        rot = Bloco.objects.create(secao=self.apres, pagina=pg, conteudo="<p>4.512 alunos</p>",
                                   config={"caixa": {"x": 1, "y": 1, "w": 50, "h": 10}, "fixo": True,
                                           "numero_antigo": True})
        F.salvar_texto(self.chefe, rot, "<p>4.800 alunos</p>")
        rot.refresh_from_db()
        self.assertNotIn("numero_antigo", rot.config)
        self.assertTrue(rot.config["fixo"])
