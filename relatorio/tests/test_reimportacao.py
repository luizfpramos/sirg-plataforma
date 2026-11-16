"""Etapa 4 do editor de blocos: reimportar um PDF revisado sem perder o que os setores escreveram."""
import io
import shutil
import tempfile
from pathlib import Path

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse

from contas import servicos as CS
from contas.models import Perfil
from relatorio import importador as I
from relatorio import reimportador as RI
from relatorio.construtor import secao
from relatorio.models import Bloco, Ciclo, ImportacaoPDF, Pagina

SENHA = "Senha-forte-2026"


def pdf_com(paginas=2, y_paragrafo=0.62, extra=False, sem_paragrafo=False, faixa=True):
    """Como o PDF do teste do importador, mas com o parágrafo em outra altura e, se pedido, uma caixa a mais."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages
    from matplotlib.patches import Rectangle
    matplotlib.rcParams["pdf.fonttype"] = 42
    matplotlib.rcParams["font.family"] = "DejaVu Sans"
    titulos = ["Apresentação", "Ensino de graduação", "Pesquisa e inovação"]
    buf = io.BytesIO()
    with PdfPages(buf) as pdf:
        for n in range(1, paginas + 1):
            fig = plt.figure(figsize=(935.4 / 72, 566.9 / 72))
            if faixa:
                fig.patches.append(Rectangle((0, 0.9), 1, 0.1, transform=fig.transFigure, color="#1b3f6e"))
            fig.text(0.06, 0.78, titulos[(n - 1) % 3], fontsize=22, fontweight="bold")
            if not sem_paragrafo:
                fig.text(0.06, y_paragrafo, "O relatório apresenta os resultados do ano.\nOs setores escrevem cada trecho.",
                         fontsize=11)
            if extra:
                fig.text(0.06, 0.4, "Quadro de destaques do ano.", fontsize=11)
            fig.text(0.94, 0.03, str(n), fontsize=9)
            fig.text(0.06, 0.03, "RELATÓRIO DE GESTÃO", fontsize=8)
            pdf.savefig(fig)
            plt.close(fig)
    return buf.getvalue()


@override_settings(SIRG_IMPORTACAO_SINCRONA=True)
class ReimportacaoTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.media = tempfile.mkdtemp()
        cls.dados = tempfile.mkdtemp()
        cls._cfg = override_settings(MEDIA_ROOT=cls.media, DADOS_DIR=Path(cls.dados))
        cls._cfg.enable()

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
        cls.ana, _ = CS.criar_usuario(login="ana", nome="Ana", senha=SENHA)
        Perfil.objects.update(troca_senha=False)
        cls.c = Ciclo.objects.create(ano=2030, titulo="RG 2030", situacao=Ciclo.COLETA)
        cap = secao(cls.c, "cap1", "1. Visão geral", ordem=1)
        secao(cls.c, "apresentacao", "Apresentação", pai=cap, ordem=1)
        secao(cls.c, "ensino_graduacao", "Ensino de graduação", pai=cap, ordem=2)

    def setUp(self):
        for f in Path(self.dados).glob("*.json"):
            f.unlink()
        self.assertTrue(self.client.login(username="adm", password=SENHA))
        self.primeira = self.ler(pdf_com())
        I.aplicar(self.primeira, self.admin)
        self.par = Bloco.objects.get(secao__ciclo=self.c, pagina__numero=1, conteudo__contains="resultados do ano")
        # o setor reescreve o parágrafo da página 1
        Bloco.objects.filter(pk=self.par.pk).update(conteudo="<p>Texto escrito pelo setor.</p>",
                                                    atualizado_por=self.ana)
        self.par.refresh_from_db()

    def ler(self, conteudo):
        arq = SimpleUploadedFile("RG.pdf", conteudo, content_type="application/pdf")
        imp = I.receber(self.c, arq, self.admin)
        I.iniciar(imp)
        imp.refresh_from_db()
        self.assertEqual(imp.situacao, ImportacaoPDF.PRONTA, imp.mensagem)
        return imp

    def test_reposiciona_sem_tocar_no_texto_escrito(self):
        antes = Bloco.objects.get(pk=self.par.pk)
        y0 = antes.config["caixa"]["y"]
        nova = self.ler(pdf_com(y_paragrafo=0.55))
        f = RI.reimportar(nova, self.admin)
        self.assertEqual(f["pareados"], 6)                               # título, parágrafo e rodapé, nas 2 páginas
        depois = Bloco.objects.get(pk=self.par.pk)
        self.assertEqual((depois.conteudo, depois.atualizado_em, depois.atualizado_por),
                         (antes.conteudo, antes.atualizado_em, self.ana))
        self.assertNotEqual(depois.config["caixa"]["y"], y0)
        self.assertEqual(depois.config["importacao"], nova.pk)
        pg = Pagina.objects.get(ciclo=self.c, numero=1)
        self.assertIn(f"/{nova.pk}/", pg.fundo)
        nova.refresh_from_db()
        self.assertEqual(nova.situacao, ImportacaoPDF.APLICADA)
        self.assertEqual(len(list(Path(self.dados).glob("posicoes_antes_da_reimportacao_2030_*.json"))), 1)

    def test_caixa_nova_vira_bloco_e_bloco_sem_caixa_fica_marcado(self):
        n = Bloco.objects.filter(secao__ciclo=self.c).count()
        nova = self.ler(pdf_com(extra=True, sem_paragrafo=True))
        plano = RI.plano(nova)["total"]
        self.assertEqual((plano["novos"], plano["sem_par"], plano["com_texto_sem_par"]), (2, 2, 2))
        RI.reimportar(nova, self.admin)
        self.assertEqual(Bloco.objects.filter(secao__ciclo=self.c).count(), n + 2)   # nada foi apagado
        par = Bloco.objects.get(pk=self.par.pk)
        self.assertEqual(par.conteudo, "<p>Texto escrito pelo setor.</p>")
        self.assertEqual(par.config["sem_par_no_pdf"], nova.pk)
        criado = Bloco.objects.get(pagina__numero=1, conteudo__contains="Quadro de destaques")
        self.assertTrue(criado.config["novo_na_reimportacao"])

    def test_blocos_do_editor_e_paginas_so_do_ciclo_nao_mudam(self):
        pg1 = Pagina.objects.get(ciclo=self.c, numero=1)
        feito_no_editor = Bloco.objects.create(
            secao=self.par.secao, pagina=pg1, tipo=Bloco.TEXTO, ordem=1600,
            config={"caixa": {"x": 100, "y": 400, "w": 200, "h": 50, "css": "", "quebra": False},
                    "criado_no_editor": True})
        so_no_ciclo = Pagina.objects.create(ciclo=self.c, numero=9, largura=935.4, altura=566.9, fundo="x.jpg")
        nova = self.ler(pdf_com(paginas=1, y_paragrafo=0.5))
        RI.reimportar(nova, self.admin)
        feito_no_editor.refresh_from_db()
        self.assertEqual(feito_no_editor.config["caixa"]["y"], 400)
        so_no_ciclo.refresh_from_db()
        self.assertEqual(so_no_ciclo.fundo, "x.jpg")
        self.assertEqual(Pagina.objects.get(ciclo=self.c, numero=2).fundo, Pagina.objects.get(pk=pg1.pk).fundo.replace(
            f"/{nova.pk}/p001", f"/{self.primeira.pk}/p002"))                    # a página 2 não veio no PDF novo
        nova.refresh_from_db()
        self.assertEqual(nova.resumo["reimportado"]["so_no_ciclo"], [2, 9])

    def test_telas_e_permissao(self):
        nova = self.ler(pdf_com(y_paragrafo=0.5))
        r = self.client.get(reverse("importacao_ver", args=[2030, nova.pk]))
        self.assertContains(r, "Reimportar no ciclo")
        self.assertContains(r, "Nenhum texto escrito é alterado")
        self.client.logout()
        self.client.login(username="ana", password=SENHA)
        r = self.client.post(reverse("importacao_reimportar", args=[2030, nova.pk]))
        self.assertEqual(r.status_code, 403)
        nova.refresh_from_db()
        self.assertEqual(nova.situacao, ImportacaoPDF.PRONTA)
        self.client.logout()
        self.client.login(username="adm", password=SENHA)
        r = self.client.post(reverse("importacao_reimportar", args=[2030, nova.pk]), follow=True)
        self.assertContains(r, "Nenhum texto foi alterado")
        self.assertContains(r, "Reimportado")

    def test_recusas(self):
        nova = self.ler(pdf_com())
        RI.reimportar(nova, self.admin)
        with self.assertRaises(I.Recusado):
            RI.reimportar(nova, self.admin)                                       # já aplicado
        outra = self.ler(pdf_com())
        Ciclo.objects.filter(pk=self.c.pk).update(situacao=Ciclo.ENCERRADO)
        outra.ciclo.refresh_from_db()
        with self.assertRaises(I.Recusado):
            RI.reimportar(outra, self.admin)
        Ciclo.objects.filter(pk=self.c.pk).update(situacao=Ciclo.COLETA)
        outra.ciclo.refresh_from_db()
        Pagina.objects.filter(ciclo=self.c).delete()
        self.assertIn("ainda não tem páginas", RI.motivo_para_nao_reimportar(outra))

    def test_pareamento_por_texto_quando_a_caixa_anda_muito(self):
        # caixa longe do lugar antigo, mas com o mesmo texto (bloco ainda não editado)
        outro = Bloco.objects.get(secao__ciclo=self.c, pagina__numero=2, conteudo__contains="resultados do ano")
        nova = self.ler(pdf_com(y_paragrafo=0.2))
        RI.reimportar(nova, self.admin)
        outro.refresh_from_db()
        self.assertNotIn("sem_par_no_pdf", outro.config)
        self.assertEqual(outro.config["importacao"], nova.pk)
