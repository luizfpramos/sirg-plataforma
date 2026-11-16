"""Etapa 3 do editor de blocos: editor visual do administrador (criar, mover, juntar e apagar blocos na página)."""
import json
import shutil
import tempfile
from datetime import timedelta
from pathlib import Path

from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from contas import servicos as CS
from contas.models import Perfil, Setor
from relatorio import editor_blocos as E
from relatorio.construtor import secao
from relatorio.models import Bloco, Ciclo, Comentario, Pagina, Quadro

SENHA = "Senha-forte-2026"


def caixa(x, y, w, h):
    return {"caixa": {"x": x, "y": y, "w": w, "h": h, "css": "font-family:Calibri;font-size:11px;line-height:13px",
                      "quebra": False}}


class BaseEditor(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.dados = tempfile.mkdtemp()
        cls._cfg = override_settings(DADOS_DIR=Path(cls.dados))
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
        cls.c = Ciclo.objects.create(ano=2030, titulo="RG 2030", situacao=Ciclo.COLETA)
        cap = secao(cls.c, "cap", "Capítulo", ordem=1)
        cls.s1 = secao(cls.c, "grad", "Graduação", pai=cap, ordem=1, setores=[Setor.objects.get(sigla="DIRGRAD")])
        cls.s2 = secao(cls.c, "pos", "Pós-graduação", pai=cap, ordem=2)
        cls.pg = Pagina.objects.create(ciclo=cls.c, numero=5, largura=935.4, altura=566.9, fundo="rg2025/p001.jpg",
                                       secao=cls.s1)
        cls.a = Bloco.objects.create(secao=cls.s1, pagina=cls.pg, tipo=Bloco.TEXTO, ordem=5001,
                                     conteudo="<p>Primeiro parágrafo.</p>", config=caixa(50, 100, 300, 80))
        cls.b = Bloco.objects.create(secao=cls.s1, pagina=cls.pg, tipo=Bloco.TEXTO, ordem=5002,
                                     conteudo="<p>Segundo parágrafo.</p>", config=caixa(50, 200, 300, 60))
        cls.d = Bloco.objects.create(secao=cls.s1, pagina=cls.pg, tipo=Bloco.TEXTO, ordem=5003,
                                     conteudo="<p>Outra coluna.</p>", config=caixa(500, 100, 300, 60))

    def setUp(self):
        for f in Path(self.dados).glob("*.json"):
            f.unlink()

    def entrar(self, login="adm"):
        self.assertTrue(self.client.login(username=login, password=SENHA))

    def acao(self, acao, dados):
        r = self.client.post(reverse("editor_acao", args=[2030, 5, acao]), json.dumps(dados),
                             content_type="application/json")
        return r, (r.json() if r["Content-Type"].startswith("application/json") else {})


class AcessoTests(BaseEditor):
    def test_setor_comum_nao_acessa(self):
        self.entrar("ana")
        self.assertEqual(self.client.get(reverse("editor_pagina", args=[2030, 5])).status_code, 403)
        r, _ = self.acao("apagar", {"id": self.a.pk})
        self.assertEqual(r.status_code, 403)
        self.assertTrue(Bloco.objects.filter(pk=self.a.pk).exists())

    def test_admin_abre_a_tela_com_os_blocos(self):
        self.entrar()
        r = self.client.get(reverse("editor_pagina", args=[2030, 5]))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.context["dados"]["blocos"]), 3)
        self.assertContains(r, "Atributos do bloco")
        self.assertRedirects(self.client.get(reverse("editor_inicio", args=[2030])),
                             reverse("editor_pagina", args=[2030, 5]))

    def test_ciclo_sem_paginas_vai_para_a_importacao(self):
        Pagina.objects.filter(ciclo=self.c).delete()
        self.entrar()
        self.assertRedirects(self.client.get(reverse("editor_inicio", args=[2030])),
                             reverse("importar_pdf", args=[2030]))

    def test_ciclo_encerrado_recusa(self):
        Ciclo.objects.filter(pk=self.c.pk).update(situacao=Ciclo.ENCERRADO)
        self.entrar()
        r, j = self.acao("salvar", {"id": self.a.pk, "x": 1, "y": 1, "w": 100, "h": 50})
        self.assertEqual(r.status_code, 400)
        self.assertIn("encerrado", j["erro"])


class CriarEMoverTests(BaseEditor):
    def test_criar_bloco_de_texto_com_a_fonte_do_corpo_e_os_atributos(self):
        self.entrar()
        r, j = self.acao("criar", {"x": 60, "y": 300, "w": 250, "h": 90, "secao": self.s2.pk,
                                   "setor": Setor.objects.get(sigla="DPPG").pk, "descricao": "Resultados da pós",
                                   "min": 100, "max": 600})
        self.assertEqual(r.status_code, 200, j)
        novo = Bloco.objects.get(pk=j["selecionar"][0])
        self.assertEqual((novo.secao, novo.pagina, novo.tipo), (self.s2, self.pg, Bloco.TEXTO))
        self.assertEqual(novo.config["caixa"]["x"], 60.0)
        self.assertEqual(novo.config["caixa"]["h"], 90.0)
        self.assertIn("font-size:11px", novo.config["caixa"]["css"])         # a do bloco de texto mais comprido
        self.assertEqual((novo.setor.sigla, novo.descricao, novo.min_caracteres, novo.max_caracteres),
                         ("DPPG", "Resultados da pós", 100, 600))
        self.assertEqual(novo.conteudo, "")
        self.assertEqual(len(j["blocos"]), 4)

    def test_criar_exige_secao_do_ciclo_e_limites_coerentes(self):
        self.entrar()
        r, _ = self.acao("criar", {"x": 1, "y": 1, "w": 50, "h": 50, "secao": 999999})
        self.assertEqual(r.status_code, 400)
        r, j = self.acao("criar", {"x": 1, "y": 1, "w": 50, "h": 50, "secao": self.s1.pk, "min": 500, "max": 100})
        self.assertEqual(r.status_code, 400)
        self.assertIn("mínimo", j["erro"])
        self.assertEqual(Bloco.objects.filter(secao__ciclo=self.c).count(), 3)

    def test_criar_grafico_precisa_do_quadro_e_aparece_no_relatorio(self):
        q = Quadro.objects.create(ciclo=self.c, secao=self.s1, chave="q1", titulo="Alunos", ordem=1)
        self.entrar()
        r, _ = self.acao("criar", {"tipo": "grafico", "x": 400, "y": 300, "w": 300, "h": 150, "secao": self.s1.pk})
        self.assertEqual(r.status_code, 400)
        r, j = self.acao("criar", {"tipo": "grafico", "x": 400, "y": 300, "w": 300, "h": 150, "secao": self.s1.pk,
                                   "quadro": q.pk})
        self.assertEqual(r.status_code, 200, j)
        g = Bloco.objects.get(pk=j["selecionar"][0])
        self.assertEqual((g.tipo, g.quadro, g.titulo), (Bloco.GRAFICO, q, "Alunos"))
        self.assertEqual(self.client.get(reverse("escrever", args=[2030])).status_code, 200)

    def test_mover_muda_so_a_posicao_sem_tocar_no_texto_nem_na_versao(self):
        self.entrar()
        antes = Bloco.objects.get(pk=self.a.pk)
        r, j = self.acao("salvar", {"id": self.a.pk, "x": 70.26, "y": 110, "w": 320, "h": 90})
        self.assertEqual(r.status_code, 200)
        depois = Bloco.objects.get(pk=self.a.pk)
        self.assertEqual(depois.config["caixa"]["x"], 70.3)
        self.assertEqual(depois.config["caixa"]["w"], 320.0)
        self.assertEqual(depois.config["caixa"]["css"], antes.config["caixa"]["css"])   # o resto da caixa fica
        self.assertEqual((depois.conteudo, depois.atualizado_em), (antes.conteudo, antes.atualizado_em))

    def test_posicao_fica_dentro_da_pagina_e_com_tamanho_minimo(self):
        self.entrar()
        self.acao("salvar", {"id": self.a.pk, "x": 5000, "y": -5000, "w": 1, "h": 1})
        cx = Bloco.objects.get(pk=self.a.pk).config["caixa"]
        self.assertEqual((cx["w"], cx["h"]), (E.MINIMO, E.MINIMO))
        self.assertLessEqual(cx["x"] + cx["w"], 935.4 + E.LIMITE_PAGINA)
        self.assertGreaterEqual(cx["y"], -E.LIMITE_PAGINA)

    def test_salvar_atributos_e_trocar_de_secao(self):
        self.entrar()
        r, _ = self.acao("salvar", {"id": self.a.pk, "secao": self.s2.pk, "setor": Setor.objects.get(sigla="DPPG").pk,
                                    "descricao": "Texto de abertura", "min": 50, "max": 90})
        self.assertEqual(r.status_code, 200)
        a = Bloco.objects.get(pk=self.a.pk)
        self.assertEqual((a.secao, a.setor.sigla, a.descricao, a.min_caracteres, a.max_caracteres),
                         (self.s2, "DPPG", "Texto de abertura", 50, 90))
        self.assertEqual(a.config["caixa"]["x"], 50)                      # posição intacta

    def test_bloco_de_outra_pagina_nao_e_alterado(self):
        outra = Pagina.objects.create(ciclo=self.c, numero=6, largura=935.4, altura=566.9, fundo="rg2025/p001.jpg")
        b = Bloco.objects.create(secao=self.s1, pagina=outra, tipo=Bloco.TEXTO, config=caixa(0, 0, 50, 50))
        self.entrar()
        r, _ = self.acao("salvar", {"id": b.pk, "x": 9, "y": 9, "w": 60, "h": 60})
        self.assertEqual(r.status_code, 400)


class JuntarEApagarTests(BaseEditor):
    def test_juntar_cobre_todos_na_ordem_de_leitura(self):
        self.entrar()
        r, j = self.acao("juntar", {"ids": [self.d.pk, self.b.pk, self.a.pk]})
        self.assertEqual(r.status_code, 200, j)
        self.assertEqual(j["selecionar"], [self.a.pk])
        a = Bloco.objects.get(pk=self.a.pk)
        self.assertEqual(a.conteudo, "<p>Primeiro parágrafo.</p><p>Segundo parágrafo.</p><p>Outra coluna.</p>")
        cx = a.config["caixa"]
        self.assertEqual((cx["x"], cx["y"], cx["w"], cx["h"]), (50, 100, 750, 160))
        self.assertFalse(Bloco.objects.filter(pk__in=[self.b.pk, self.d.pk]).exists())

    def test_juntar_soma_os_limites_e_herda_setor_e_descricao(self):
        dppg = Setor.objects.get(sigla="DPPG")
        Bloco.objects.filter(pk=self.b.pk).update(setor=dppg, descricao="Dados", min_caracteres=100, max_caracteres=300)
        Bloco.objects.filter(pk=self.a.pk).update(min_caracteres=50, max_caracteres=200)
        self.entrar()
        self.acao("juntar", {"ids": [self.a.pk, self.b.pk]})
        a = Bloco.objects.get(pk=self.a.pk)
        self.assertEqual((a.setor, a.descricao, a.min_caracteres, a.max_caracteres), (dppg, "Dados", 150, 500))

    def test_juntar_pede_confirmacao_se_os_setores_escreveram_e_guarda_copia(self):
        Bloco.objects.filter(pk__in=[self.a.pk, self.b.pk]).update(atualizado_por=self.ana)
        self.entrar()
        r, j = self.acao("juntar", {"ids": [self.a.pk, self.b.pk]})
        self.assertEqual(r.status_code, 409)
        self.assertIn("textos serão", j["confirmar"])
        self.assertTrue(Bloco.objects.filter(pk=self.b.pk).exists())
        r, _ = self.acao("juntar", {"ids": [self.a.pk, self.b.pk], "confirmar": True})
        self.assertEqual(r.status_code, 200)
        copias = list(Path(self.dados).glob("textos_antes_das_paginas_2030_*.json"))
        self.assertEqual(len(copias), 1)
        textos = [x["conteudo"] for x in json.loads(copias[0].read_text(encoding="utf-8"))]
        self.assertIn("<p>Segundo parágrafo.</p>", textos)

    def test_juntar_recusa_comentario_travado_e_tipo(self):
        self.entrar()
        r, _ = self.acao("juntar", {"ids": [self.a.pk]})
        self.assertEqual(r.status_code, 400)
        Comentario.objects.create(secao=self.s1, bloco=self.b, autor=self.ana, texto="Ver isto")
        r, j = self.acao("juntar", {"ids": [self.a.pk, self.b.pk]})
        self.assertEqual(r.status_code, 400)
        self.assertIn("comentários", j["erro"])
        Comentario.objects.all().delete()
        Bloco.objects.filter(pk=self.d.pk).update(editando_por=self.ana, editando_desde=timezone.now())
        r, j = self.acao("juntar", {"ids": [self.a.pk, self.d.pk]})
        self.assertEqual(r.status_code, 400)
        self.assertIn("Ana", j["erro"])
        Bloco.objects.filter(pk=self.d.pk).update(editando_desde=timezone.now() - timedelta(hours=1))   # trava vencida
        r, _ = self.acao("juntar", {"ids": [self.a.pk, self.d.pk]})
        self.assertEqual(r.status_code, 200)

    def test_apagar_bloco_sem_texto_de_setor(self):
        self.entrar()
        r, j = self.acao("apagar", {"id": self.d.pk})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(Bloco.objects.filter(pk=self.d.pk).exists())
        self.assertEqual(len(j["blocos"]), 2)

    def test_apagar_texto_de_setor_pede_confirmacao_e_guarda_copia(self):
        Bloco.objects.filter(pk=self.a.pk).update(atualizado_por=self.ana)
        self.entrar()
        r, j = self.acao("apagar", {"id": self.a.pk})
        self.assertEqual(r.status_code, 409)
        self.assertIn("escrito por um setor", j["confirmar"])
        self.assertTrue(Bloco.objects.filter(pk=self.a.pk).exists())
        r, _ = self.acao("apagar", {"id": self.a.pk, "confirmar": True})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(Bloco.objects.filter(pk=self.a.pk).exists())
        copia = next(Path(self.dados).glob("textos_antes_das_paginas_2030_*.json"))
        self.assertIn("Primeiro parágrafo", copia.read_text(encoding="utf-8"))

    def test_apagar_recusa_bloco_com_comentario(self):
        Comentario.objects.create(secao=self.s1, bloco=self.a, autor=self.ana, texto="Ver isto")
        self.entrar()
        r, _ = self.acao("apagar", {"id": self.a.pk})
        self.assertEqual(r.status_code, 400)
        self.assertTrue(Bloco.objects.filter(pk=self.a.pk).exists())
