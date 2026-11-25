"""Etapa 2 do editor de blocos: importador de PDF dentro do sistema."""
import io
import shutil
import tempfile
from pathlib import Path

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from contas import servicos as CS
from contas.models import Perfil
from relatorio import importador as I
from relatorio import pdf_paginas as PP
from relatorio.construtor import secao
from relatorio.models import Bloco, Ciclo, ImportacaoPDF, Pagina

SENHA = "Senha-forte-2026"


def pdf_de_teste(paginas=3):
    """PDF pequeno, em paisagem como o RG: título grande, um parágrafo, um retângulo colorido e o número da página
    no rodapé (repetido em todas as páginas)."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages
    from matplotlib.patches import Rectangle
    matplotlib.rcParams["pdf.fonttype"] = 42
    matplotlib.rcParams["font.family"] = "DejaVu Sans"          # vem com o matplotlib, em qualquer máquina
    titulos = ["Apresentação", "Ensino de graduação", "Pesquisa e inovação", "Extensão"]
    buf = io.BytesIO()
    with PdfPages(buf) as pdf:
        for n in range(1, paginas + 1):
            fig = plt.figure(figsize=(935.4 / 72, 566.9 / 72))
            fig.patches.append(Rectangle((0, 0.9), 1, 0.1, transform=fig.transFigure, color="#1b3f6e"))
            fig.text(0.06, 0.78, titulos[(n - 1) % len(titulos)], fontsize=22, fontweight="bold")
            fig.text(0.06, 0.62, "O relatório apresenta os resultados do ano.\nOs setores escrevem cada trecho.",
                     fontsize=11)
            fig.text(0.94, 0.03, str(n), fontsize=9)
            fig.text(0.06, 0.03, "RELATÓRIO DE GESTÃO", fontsize=8)
            pdf.savefig(fig)
            plt.close(fig)
    return buf.getvalue()


class PdfPaginasTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.tmp = Path(tempfile.mkdtemp())
        cls.pdf = cls.tmp / "teste.pdf"
        cls.pdf.write_bytes(pdf_de_teste(2))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)
        super().tearDownClass()

    def test_le_caixas_de_texto_com_posicao_e_fonte(self):
        paginas = PP.extrair(self.pdf)
        self.assertEqual([p["n"] for p in paginas], [1, 2])
        p = paginas[0]
        self.assertAlmostEqual(p["w"], 935.4, delta=1)
        textos = [c["texto"] for c in p["caixas"]]
        self.assertIn("Apresentação", textos)
        titulo = next(c for c in p["caixas"] if c["texto"] == "Apresentação")
        self.assertEqual(titulo["tam"], 22)
        self.assertIn("700", titulo["css"])                      # negrito
        self.assertIn("DejaVu Sans", titulo["css"])              # fonte de fora da lista: o nome real
        self.assertLess(titulo["y"], 150)

    def test_fundo_sem_texto(self):
        from PIL import Image
        PP.fundos(self.pdf, self.tmp / "fundos")
        self.assertTrue((self.tmp / "fundos" / "p001.jpg").exists())
        self.assertTrue((self.tmp / "fundos" / "p002.jpg").exists())
        im = Image.open(self.tmp / "fundos" / "p001.jpg").convert("L")
        k = im.size[0] / 935.4
        # faixa azul do alto continua; onde estava o título (texto preto), agora é fundo branco
        self.assertLess(im.getpixel((int(400 * k), int(20 * k))), 120)
        titulo = next(c for c in PP.extrair(self.pdf, so={1})[0]["caixas"] if c["texto"] == "Apresentação")
        caixa = im.crop((int(titulo["x"] * k), int(titulo["y"] * k), int((titulo["x"] + titulo["w"]) * k),
                         int((titulo["y"] + titulo["h"]) * k)))
        self.assertGreater(min(caixa.getdata()), 200)

    def test_familia_css(self):
        self.assertEqual(PP.familia_css("c"), PP.FAMILIAS["c"])
        self.assertTrue(PP.familia_css("Times New Roman").endswith("serif"))
        self.assertNotIn(";", PP.familia_css("Fonte;estranha<x>"))

    def test_largura_sem_arquivo_de_fonte(self):
        guardado = dict(PP._FONTES)
        try:
            PP._FONTES[("c", False, False)] = None
            self.assertAlmostEqual(PP.largura("abcd", ("c", 400, False, 10, "#000")), 20)
        finally:
            PP._FONTES.clear()
            PP._FONTES.update(guardado)


@override_settings(SIRG_IMPORTACAO_SINCRONA=True)
class ImportadorTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.media = tempfile.mkdtemp()
        cls._media = override_settings(MEDIA_ROOT=cls.media)
        cls._media.enable()

    @classmethod
    def tearDownClass(cls):
        cls._media.disable()
        shutil.rmtree(cls.media, ignore_errors=True)
        super().tearDownClass()

    @classmethod
    def setUpTestData(cls):
        call_command("inicializar", verbosity=0)
        cls.admin, _ = CS.criar_usuario(login="adm", nome="Admin", e_admin=True, senha=SENHA)
        cls.comum, _ = CS.criar_usuario(login="comum", nome="Comum", senha=SENHA)
        Perfil.objects.update(troca_senha=False)
        cls.c = Ciclo.objects.create(ano=2030, titulo="RG 2030")
        cap = secao(cls.c, "cap1", "1. Visão geral", ordem=1)
        secao(cls.c, "apresentacao", "Apresentação", pai=cap, ordem=1)
        secao(cls.c, "ensino_graduacao", "Ensino de graduação", pai=cap, ordem=2)
        secao(cls.c, "pesquisa", "Pesquisa e inovação", pai=cap, ordem=3)
        secao(cls.c, "nao_esta", "Seção que não está no PDF", pai=cap, ordem=4)
        cls.pdf = pdf_de_teste(3)

    def entrar(self, login="adm"):
        self.assertTrue(self.client.login(username=login, password=SENHA))

    def enviar(self, conteudo=None, nome="RG2030.pdf"):
        arq = SimpleUploadedFile(nome, conteudo if conteudo is not None else self.pdf, content_type="application/pdf")
        return self.client.post(reverse("importar_pdf", args=[2030]), {"pdf": arq})

    def test_so_o_administrador_importa(self):
        self.entrar("comum")
        self.assertEqual(self.client.get(reverse("importar_pdf", args=[2030])).status_code, 403)
        self.assertEqual(self.enviar().status_code, 403)
        self.assertFalse(ImportacaoPDF.objects.exists())

    def test_recusa_o_que_nao_e_pdf(self):
        self.entrar()
        self.enviar(b"nao sou pdf", nome="x.pdf")
        self.enviar(self.pdf, nome="x.docx")
        self.assertFalse(ImportacaoPDF.objects.exists())

    def test_envio_le_o_pdf_e_mostra_as_paginas(self):
        self.entrar()
        r = self.enviar()
        imp = ImportacaoPDF.objects.get()
        self.assertRedirects(r, reverse("importacao_ver", args=[2030, imp.pk]))
        self.assertEqual(imp.situacao, ImportacaoPDF.PRONTA, imp.mensagem)
        self.assertEqual(imp.resumo["paginas"], 3)
        self.assertTrue((imp.pasta / "p003.jpg").exists())
        self.assertTrue((imp.pasta / "paginas.json").exists())
        r = self.client.get(reverse("importacao_ver", args=[2030, imp.pk]) + "?p=2")
        self.assertContains(r, "Ensino de graduação")
        self.assertContains(r, "Aplicar ao relatório")
        self.assertContains(r, reverse("importacao_arquivo", args=[imp.pk, "p002.jpg"]))
        # o fundo é servido a quem está logado
        r = self.client.get(reverse("importacao_arquivo", args=[imp.pk, "p002.jpg"]))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Content-Type"], "image/jpeg")
        self.assertEqual(self.client.get(reverse("importacao_arquivo", args=[imp.pk, "original.pdf"])).status_code, 404)
        self.client.logout()
        self.assertEqual(self.client.get(reverse("importacao_arquivo", args=[imp.pk, "p002.jpg"])).status_code, 302)

    def test_pdf_corrompido_vira_erro_e_pode_ler_de_novo(self):
        self.entrar()
        self.enviar(b"%PDF-1.4 quebrado")
        imp = ImportacaoPDF.objects.get()
        self.assertEqual(imp.situacao, ImportacaoPDF.ERRO)
        self.assertIn("Não foi possível ler o PDF", imp.mensagem)
        self.assertContains(self.client.get(reverse("importacao_ver", args=[2030, imp.pk])), "Ler de novo")
        (imp.pasta / "original.pdf").write_bytes(self.pdf)
        self.client.post(reverse("importacao_ler_de_novo", args=[2030, imp.pk]))
        imp.refresh_from_db()
        self.assertEqual(imp.situacao, ImportacaoPDF.PRONTA)

    def test_aplicar_cria_paginas_e_trechos_nas_secoes_certas(self):
        self.entrar()
        self.enviar()
        imp = ImportacaoPDF.objects.get()
        r = self.client.post(reverse("importacao_aplicar", args=[2030, imp.pk]))
        self.assertRedirects(r, reverse("montagem", args=[2030]))
        imp.refresh_from_db()
        self.assertEqual(imp.situacao, ImportacaoPDF.APLICADA)
        self.assertEqual(imp.aplicada_por, self.admin)
        pgs = list(Pagina.objects.filter(ciclo=self.c))
        self.assertEqual([p.numero for p in pgs], [1, 2, 3])
        self.assertEqual(pgs[1].fundo, f"arquivos/importacoes/{imp.pk}/p002.jpg")
        self.assertEqual(pgs[1].fundo_url, reverse("importacao_arquivo", args=[imp.pk, "p002.jpg"]))
        self.assertTrue(pgs[1].fundo_caminho.exists())
        # o número da página e o rodapé repetido viram textos fixos, não trechos editáveis
        self.assertIn(">2<", pgs[1].fixos.replace(" ", ""))
        blocos = Bloco.objects.filter(secao__ciclo=self.c, pagina__isnull=False)
        self.assertFalse(blocos.filter(conteudo__contains="RELATÓRIO DE GESTÃO").exists())
        # cada trecho vai para a seção cujo título vem antes dele no PDF
        b2 = blocos.filter(pagina__numero=2, config__referencia_pdf__icontains="resultados do ano").get()
        self.assertEqual(b2.secao.chave, "ensino_graduacao")
        b3 = blocos.filter(pagina__numero=3, config__referencia_pdf__icontains="resultados do ano").get()
        self.assertEqual(b3.secao.chave, "pesquisa")
        self.assertEqual(pgs[0].secao.chave, "apresentacao")
        self.assertEqual(b2.config["caixa"]["css"][:12], "font-family:")
        self.assertIn("Seção que não está no PDF", imp.resumo["secoes_faltando"])
        # o relatório abre com as páginas novas
        r = self.client.get(reverse("escrever", args=[2030]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, reverse("importacao_arquivo", args=[imp.pk, "p001.jpg"]))

    def test_nao_aplica_duas_vezes_nem_em_ciclo_com_paginas(self):
        self.entrar()
        self.enviar()
        self.enviar()
        a, b = ImportacaoPDF.objects.order_by("id")
        I.aplicar(a, self.admin)
        n = Bloco.objects.filter(secao__ciclo=self.c).count()
        self.assertIn("já tem páginas", I.motivo_para_nao_aplicar(b))
        self.client.post(reverse("importacao_aplicar", args=[2030, b.pk]))
        self.client.post(reverse("importacao_aplicar", args=[2030, a.pk]))
        self.assertEqual(Bloco.objects.filter(secao__ciclo=self.c).count(), n)
        b.refresh_from_db()
        self.assertEqual(b.situacao, ImportacaoPDF.PRONTA)

    def test_ciclo_encerrado_nao_recebe_pdf(self):
        Ciclo.objects.filter(pk=self.c.pk).update(situacao=Ciclo.ENCERRADO)
        self.entrar()
        self.enviar()
        self.assertFalse(ImportacaoPDF.objects.exists())

    def test_leitura_interrompida(self):
        from django.utils import timezone
        self.entrar()
        self.enviar()
        imp = ImportacaoPDF.objects.get()
        ImportacaoPDF.objects.filter(pk=imp.pk).update(situacao=ImportacaoPDF.PROCESSANDO,
                                                        atualizado_em=timezone.now() - timezone.timedelta(hours=1))
        imp.refresh_from_db()
        self.assertTrue(imp.interrompida)
        self.assertContains(self.client.get(reverse("importacao_ver", args=[2030, imp.pk])), "parou no meio")


class FundoDoRG2025Tests(SimpleTestCase):
    def test_fundo_antigo_continua_em_static(self):
        from relatorio.paginas import caminho_do_fundo, url_do_fundo
        self.assertEqual(url_do_fundo("rg2025/p001.jpg"), "/static/rg2025/p001.jpg")
        self.assertTrue(str(caminho_do_fundo("rg2025/p001.jpg")).endswith("static/rg2025/p001.jpg"))
        self.assertTrue(caminho_do_fundo("rg2025/p001.jpg").exists())

