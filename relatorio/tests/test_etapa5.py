"""Etapa 5 do editor de blocos: concluir/desfazer, versões por bloco, bloco de imagem e padrão de design."""
import io
import json
import shutil
import tempfile
from pathlib import Path

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse

from contas import design
from contas import servicos as CS
from contas.models import Instituicao, Perfil, Setor
from relatorio import fluxo as F
from relatorio.construtor import secao
from relatorio.models import Bloco, Ciclo, Imagem, Pagina

SENHA = "Senha-forte-2026"


def png(cor=(200, 30, 30), tam=(60, 40)):
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", tam, cor).save(buf, "PNG")
    return buf.getvalue()


class Base(TestCase):
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
        g = lambda s: Setor.objects.get(sigla=s)          # noqa: E731
        cls.grad, _ = CS.criar_usuario(login="grad", nome="Ana", setores=[g("DIRGRAD")], senha=SENHA)
        cls.dppg, _ = CS.criar_usuario(login="dppg", nome="Paulo", setores=[g("DPPG")], senha=SENHA)
        cls.master, _ = CS.criar_usuario(login="master", nome="Mara", e_master=True, senha=SENHA)
        cls.admin, _ = CS.criar_usuario(login="adm", nome="Admin", e_admin=True, senha=SENHA)
        Perfil.objects.update(troca_senha=False)
        cls.c = Ciclo.objects.create(ano=2030, titulo="RG 2030", situacao=Ciclo.COLETA)
        cap = secao(cls.c, "cap", "Capítulo", ordem=1)
        cls.s = secao(cls.c, "grad", "Graduação", pai=cap, ordem=1, setores=[g("DIRGRAD")])
        cls.texto = Bloco.objects.create(secao=cls.s, tipo=Bloco.TEXTO, ordem=1, conteudo="<p>Texto do setor.</p>",
                                         min_caracteres=50)
        cls.img = Bloco.objects.create(secao=cls.s, tipo=Bloco.IMAGEM, ordem=2, setor=g("DPPG"),
                                       descricao="Foto do campus", config={"imagem": {"ajuste": "contain"}})

    def entrar(self, login):
        self.assertTrue(self.client.login(username=login, password=SENHA))

    def post_json(self, nome, bloco, dados=None):
        return self.client.post(reverse(nome, args=[2030, bloco.pk]), json.dumps(dados or {}),
                                content_type="application/json")


class ConcluirTests(Base):
    def test_concluir_e_desfazer(self):
        self.entrar("grad")
        r = self.post_json("bloco_concluir", self.texto)
        self.assertEqual(r.status_code, 409)                              # 24 caracteres, mínimo 50: pede confirmação
        self.assertIn("mínimo é 50", r.json()["confirmar"])
        self.assertFalse(Bloco.objects.get(pk=self.texto.pk).concluido_em)
        r = self.post_json("bloco_concluir", self.texto, {"confirmar": True})
        self.assertEqual((r.status_code, r.json()["concluido"]), (200, True))
        b = Bloco.objects.get(pk=self.texto.pk)
        self.assertEqual(b.concluido_por, self.grad)
        r = self.post_json("bloco_desfazer", self.texto)
        self.assertFalse(r.json()["concluido"])
        self.assertIsNone(Bloco.objects.get(pk=self.texto.pk).concluido_em)

    def test_concluido_nao_se_edita_nem_vira_versao_nova(self):
        self.entrar("grad")
        self.post_json("bloco_concluir", self.texto, {"confirmar": True})
        b = Bloco.objects.get(pk=self.texto.pk)
        self.assertFalse(F.pode_editar_bloco(self.master, b))
        self.assertIn("concluído", F.motivo_bloco_bloqueado(self.master, b))
        with self.assertRaises(F.Recusado):
            F.salvar_texto(self.master, b, "<p>Outro texto.</p>")
        self.assertEqual(Bloco.objects.get(pk=self.texto.pk).conteudo, "<p>Texto do setor.</p>")
        self.assertEqual(b.history.count(), 1)                            # concluir não gerou versão no histórico
        self.assertTrue(F.pode_responder_pelo_bloco(self.grad, b))        # mas quem escreve ainda pode desfazer

    def test_so_quem_escreve_conclui(self):
        self.entrar("dppg")                                                # a seção é da DIRGRAD, o bloco não tem setor
        r = self.post_json("bloco_concluir", self.texto, {"confirmar": True})
        self.assertEqual(r.status_code, 403)
        self.assertFalse(Bloco.objects.get(pk=self.texto.pk).concluido_em)
        r = self.post_json("bloco_desfazer", self.texto)
        self.assertEqual(r.status_code, 403)

    def test_texto_vazio_e_imagem_sem_arquivo_nao_concluem(self):
        vazio = Bloco.objects.create(secao=self.s, tipo=Bloco.TEXTO, ordem=3, conteudo="")
        self.entrar("grad")
        r = self.post_json("bloco_concluir", vazio, {"confirmar": True})
        self.assertEqual(r.status_code, 400)
        self.assertIn("Escreva", r.json()["erro"])
        self.client.logout()
        self.entrar("dppg")
        r = self.post_json("bloco_concluir", self.img)
        self.assertEqual(r.status_code, 400)
        self.assertIn("imagem", r.json()["erro"])

    def test_ciclo_encerrado_recusa(self):
        Ciclo.objects.filter(pk=self.c.pk).update(situacao=Ciclo.ENCERRADO)
        self.entrar("grad")
        self.assertEqual(self.post_json("bloco_concluir", self.texto, {"confirmar": True}).status_code, 403)

    def test_tela_mostra_a_barra_e_marca_os_blocos_da_pessoa(self):
        self.entrar("grad")
        r = self.client.get(reverse("escrever", args=[2030]))
        self.assertContains(r, 'id="bloco-barra"')
        html = r.content.decode()
        self.assertIn(f'id="bloco-{self.texto.pk}"', html)
        trecho = html[html.index(f'id="bloco-{self.texto.pk}"'):][:400]
        self.assertIn("data-pode-concluir", trecho)
        trecho = html[html.index(f'id="bloco-{self.img.pk}"'):][:400]
        self.assertNotIn("data-pode-concluir", trecho)                    # a imagem é da DPPG
        self.post_json("bloco_concluir", self.texto, {"confirmar": True})
        r = self.client.get(reverse("escrever", args=[2030]))
        self.assertContains(r, "Concluído")

    def test_versoes_restaurar_vale_pelo_setor_do_bloco(self):
        Bloco.objects.filter(pk=self.texto.pk).update(setor=Setor.objects.get(sigla="DPPG"))
        self.entrar("dppg")
        r = self.client.get(reverse("bloco_historico", args=[2030, self.texto.pk]))
        self.assertTrue(r.json()["pode_restaurar"])
        self.client.logout()
        self.entrar("grad")
        r = self.client.get(reverse("bloco_historico", args=[2030, self.texto.pk]))
        self.assertFalse(r.json()["pode_restaurar"])


class ImagemTests(Base):
    def enviar(self, arquivo=None, **campos):
        dados = dict(campos)
        if arquivo is not None:
            dados["arquivo"] = arquivo
        return self.client.post(reverse("bloco_imagem", args=[2030, self.img.pk]), dados)

    def test_setor_do_bloco_insere_e_a_tela_mostra(self):
        self.entrar("dppg")
        r = self.enviar(SimpleUploadedFile("campus.png", png(), content_type="image/png"), alt="Prédio do campus")
        self.assertEqual(r.status_code, 200, r.content)
        b = Bloco.objects.get(pk=self.img.pk)
        im = Imagem.objects.get(pk=b.config["imagem"]["id"])
        self.assertEqual((im.largura, im.altura, im.tipo), (60, 40, "image/png"))
        self.assertEqual(b.config["imagem"]["alt"], "Prédio do campus")
        self.assertEqual(b.atualizado_por, self.dppg)
        tela = self.client.get(reverse("escrever", args=[2030]))
        self.assertContains(tela, f'src="{im.url}"')
        self.assertContains(tela, 'alt="Prédio do campus"')
        self.assertEqual(self.client.get(im.url).status_code, 200)
        self.assertEqual(self.client.get(reverse("ler", args=[2030])).status_code, 200)
        # agora pode concluir
        self.assertTrue(self.post_json("bloco_concluir", self.img).json()["concluido"])

    def test_outro_setor_nao_insere(self):
        self.entrar("grad")
        r = self.enviar(SimpleUploadedFile("a.png", png(), content_type="image/png"), alt="Qualquer coisa")
        self.assertEqual(r.status_code, 403)
        self.assertFalse(Imagem.objects.exists())

    def test_recusa_arquivo_invalido_sem_alt_e_bloco_de_texto(self):
        self.entrar("dppg")
        r = self.enviar(SimpleUploadedFile("a.png", b"nao e imagem", content_type="image/png"), alt="Texto")
        self.assertEqual(r.status_code, 400)
        self.assertIn("não é uma imagem", r.json()["erro"])
        r = self.enviar(SimpleUploadedFile("a.png", png(), content_type="image/png"), alt="")
        self.assertEqual(r.status_code, 400)
        self.assertIn("texto alternativo", r.json()["erro"])
        self.assertFalse(Imagem.objects.exists())
        self.client.logout()
        self.entrar("grad")
        r = self.client.post(reverse("bloco_imagem", args=[2030, self.texto.pk]),
                             {"arquivo": SimpleUploadedFile("a.png", png(), content_type="image/png"), "alt": "xx yy"})
        self.assertEqual(r.status_code, 400)

    def test_trocar_enquadramento_e_tirar_a_imagem(self):
        self.entrar("dppg")
        self.enviar(SimpleUploadedFile("a.png", png(), content_type="image/png"), alt="Prédio do campus")
        r = self.enviar(ajuste="cover", alt="Prédio do campus, vista aérea")
        self.assertEqual(r.json()["imagem"]["ajuste"], "cover")
        self.assertEqual(Bloco.objects.get(pk=self.img.pk).config["imagem"]["alt"], "Prédio do campus, vista aérea")
        r = self.enviar(remover="1")
        self.assertEqual(r.json()["imagem"]["url"], "")
        self.assertNotIn("id", Bloco.objects.get(pk=self.img.pk).config["imagem"])

    def test_vai_para_o_word(self):
        from relatorio.exportar_docx import gerar_docx
        self.entrar("dppg")
        self.enviar(SimpleUploadedFile("a.png", png(), content_type="image/png"), alt="Prédio do campus")
        dados = gerar_docx(self.c)
        self.assertGreater(len(dados), 1000)
        import zipfile
        nomes = zipfile.ZipFile(io.BytesIO(dados)).namelist()
        self.assertTrue(any(n.startswith("word/media/") for n in nomes))

    def test_copia_do_ciclo_nao_leva_a_imagem(self):
        from relatorio.servicos import copiar_ciclo
        self.entrar("dppg")
        self.enviar(SimpleUploadedFile("a.png", png(), content_type="image/png"), alt="Prédio do campus",
                    ajuste="cover")
        novo = copiar_ciclo(self.c, 2031, "RG 2031")
        b = Bloco.objects.get(secao__ciclo=novo, tipo=Bloco.IMAGEM)
        self.assertEqual(b.config["imagem"], {"ajuste": "cover"})
        self.assertEqual(b.setor.sigla, "DPPG")

    def test_editor_de_paginas_cria_bloco_de_imagem(self):
        pg = Pagina.objects.create(ciclo=self.c, numero=5, largura=935.4, altura=566.9, fundo="x.jpg", secao=self.s)
        self.entrar("adm")
        r = self.client.post(reverse("editor_acao", args=[2030, 5, "criar"]), json.dumps(
            {"tipo": "imagem", "x": 50, "y": 60, "w": 200, "h": 150, "secao": self.s.pk,
             "setor": Setor.objects.get(sigla="DPPG").pk, "descricao": "Foto do reitor"}),
            content_type="application/json")
        self.assertEqual(r.status_code, 200, r.content)
        b = Bloco.objects.get(pk=r.json()["selecionar"][0])
        self.assertEqual((b.tipo, b.pagina, b.setor.sigla), (Bloco.IMAGEM, pg, "DPPG"))
        self.assertEqual(b.config["imagem"], {"ajuste": "contain"})
        self.entrar("dppg")
        tela = self.client.get(reverse("escrever", args=[2030]))
        self.assertContains(tela, "Clique para inserir a imagem")


class DesignTests(Base):
    def test_so_master_admin_ou_diagramacao(self):
        self.entrar("grad")
        self.assertEqual(self.client.get(reverse("padrao_design")).status_code, 403)

    def test_salva_e_vale_na_tela(self):
        self.entrar("master")
        self.assertContains(self.client.get(reverse("padrao_design")), "Padrão de design")
        r = self.client.post(reverse("padrao_design"), {"fonte_texto": "georgia", "tamanho_texto": "17",
                                                       "espaco_linhas": "1.75", "espaco_paragrafos": "12"})
        self.assertEqual(r.status_code, 302)
        inst = Instituicao.atual()
        self.assertEqual((inst.fonte_texto, inst.tamanho_texto, str(inst.espaco_linhas), inst.espaco_paragrafos),
                         ("georgia", 17, "1.75", 12))
        tela = self.client.get(reverse("escrever", args=[2030]))
        self.assertContains(tela, "--rg-fonte:Georgia")
        self.assertContains(tela, "--rg-tamanho:17px")
        self.client.post(reverse("padrao_design"), {"acao": "restaurar"})
        self.assertNotContains(self.client.get(reverse("escrever", args=[2030])), "--rg-fonte")

    def test_recusa_valor_fora_das_listas(self):
        self.entrar("master")
        self.client.post(reverse("padrao_design"), {"fonte_texto": "comic;x", "tamanho_texto": "17",
                                                    "espaco_linhas": "1.75", "espaco_paragrafos": "12"})
        self.client.post(reverse("padrao_design"), {"fonte_texto": "", "tamanho_texto": "99",
                                                    "espaco_linhas": "0", "espaco_paragrafos": "0"})
        self.assertEqual(Instituicao.atual().tamanho_texto, 0)
        self.assertEqual(Instituicao.atual().fonte_texto, "")

    def test_bloco_novo_do_editor_segue_o_padrao(self):
        pg = Pagina.objects.create(ciclo=self.c, numero=5, largura=935.4, altura=566.9, fundo="x.jpg", secao=self.s)
        Bloco.objects.create(secao=self.s, pagina=pg, tipo=Bloco.TEXTO, ordem=5001, conteudo="<p>x</p>",
                             config={"caixa": {"x": 1, "y": 1, "w": 100, "h": 50, "quebra": False,
                                               "css": "font-family:Calibri;font-size:11px;line-height:13px"}})
        Instituicao.objects.update(fonte_texto="arial", tamanho_texto=14, espaco_linhas="1.4")
        self.entrar("adm")
        r = self.client.post(reverse("editor_acao", args=[2030, 5, "criar"]), json.dumps(
            {"x": 50, "y": 200, "w": 200, "h": 80, "secao": self.s.pk}), content_type="application/json")
        css = Bloco.objects.get(pk=r.json()["selecionar"][0]).config["caixa"]["css"]
        self.assertIn("font-size:14px", css)
        self.assertIn("line-height:19.6px", css)
        self.assertIn("Arial", css)
        self.assertNotIn("11px", css)

    def test_ajustar_css_sem_padrao_nao_muda(self):
        inst = Instituicao.atual()
        self.assertEqual(design.ajustar_css_da_caixa("font-size:11px", inst), "font-size:11px")
        self.assertEqual(design.css_variaveis(inst), "")
