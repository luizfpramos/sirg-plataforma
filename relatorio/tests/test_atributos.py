"""Etapa 1 do editor de blocos: atributos do bloco (setor, conteúdo esperado, mínimo e máximo, cor)."""
import json

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from contas import servicos as CS
from contas.models import Perfil, Setor
from relatorio import atributos as AT
from relatorio import fluxo as F
from relatorio.models import Bloco, Ciclo, Secao

SENHA = "Senha-forte-2026"


class AtributosUnidadeTests(SimpleTestCase):
    def test_contagem_considera_o_texto_como_ficara(self):
        self.assertEqual(AT.contar_caracteres("<p>Olá,   mundo</p><p>Fim</p>"), len("Olá, mundo Fim"))
        com_marcas = '<p>Ola <ins data-s="1">novo</ins><del data-s="2"> velho</del></p>'
        self.assertEqual(AT.contar_caracteres(com_marcas), len("Ola novo"))
        self.assertEqual(AT.contar_caracteres(""), 0)

    def test_situacao_do_tamanho(self):
        self.assertEqual(AT.situacao_do_tamanho(10, 20, 50)[0], "pouco")
        self.assertEqual(AT.situacao_do_tamanho(60, 20, 50)[0], "muito")
        self.assertEqual(AT.situacao_do_tamanho(30, 20, 50)[0], "ok")
        self.assertEqual(AT.situacao_do_tamanho(5, None, None)[0], "ok")
        self.assertEqual(AT.frase_dos_limites(10, 20), "Entre 10 e 20 caracteres")
        self.assertEqual(AT.frase_dos_limites(None, 20), "No máximo 20 caracteres")
        self.assertEqual(AT.frase_dos_limites(None, None), "")

    def test_bloco_grande_ou_pequeno(self):
        self.assertTrue(AT.e_grande({"w": 300, "h": 120}))
        self.assertFalse(AT.e_grande({"w": 300, "h": 20}))
        self.assertFalse(AT.e_grande({"w": 80, "h": 200}))
        self.assertTrue(AT.e_grande(None))          # fora de página: sempre cabe


class BaseAtributos(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("inicializar", verbosity=0)
        call_command("preparar_rg2026", sem_backup=True, verbosity=0)
        g = lambda s: Setor.objects.get(sigla=s)
        cls.grad, _ = CS.criar_usuario(login="grad", nome="Ana DIRGRAD", setores=[g("DIRGRAD")], senha=SENHA)
        cls.dppg, _ = CS.criar_usuario(login="dppg", nome="Paulo DPPG", setores=[g("DPPG")], senha=SENHA)
        cls.master, _ = CS.criar_usuario(login="master", nome="Mara Master", e_master=True, senha=SENHA)
        cls.admin, _ = CS.criar_usuario(login="adm", nome="Admin", e_admin=True, senha=SENHA)
        Perfil.objects.update(troca_senha=False)
        cls.c = Ciclo.objects.get(ano=2026)
        cls.c.situacao = Ciclo.COLETA
        cls.c.save()
        cls.sec = Secao.objects.get(ciclo=cls.c, chave="ensino_graduacao")
        cls.bloco = Bloco.objects.filter(secao=cls.sec, tipo=Bloco.TEXTO).first()

    def entrar(self, login):
        self.assertTrue(self.client.login(username=login, password=SENHA))

    def post(self, url, dados):
        return self.client.post(url, json.dumps(dados), content_type="application/json")


class PermissaoPorBlocoTests(BaseAtributos):
    def test_sem_setor_no_bloco_vale_o_da_secao(self):
        self.assertTrue(F.pode_editar_bloco(self.grad, self.bloco))
        self.assertFalse(F.pode_editar_bloco(self.dppg, self.bloco))

    def test_setor_do_bloco_vale_no_lugar_do_da_secao(self):
        self.bloco.setor = Setor.objects.get(sigla="DPPG")
        self.bloco.save()
        self.assertFalse(F.pode_editar_bloco(self.grad, self.bloco))     # era da seção, mas o bloco é da DPPG
        self.assertTrue(F.pode_editar_bloco(self.dppg, self.bloco))      # não é da seção, mas o bloco é dela
        self.assertTrue(F.pode_editar_bloco(self.master, self.bloco))
        self.assertIn("DPPG", F.motivo_bloco_bloqueado(self.grad, self.bloco))

    def test_travar_e_salvar_respeitam_o_setor_do_bloco(self):
        self.bloco.setor = Setor.objects.get(sigla="DPPG")
        self.bloco.save()
        self.entrar("grad")
        r = self.post(reverse("bloco_travar", args=[2026, self.bloco.pk]), {"modo": "editar"})
        self.assertEqual(r.status_code, 403)
        self.client.logout()
        self.entrar("dppg")
        r = self.post(reverse("bloco_travar", args=[2026, self.bloco.pk]), {"modo": "editar"})
        self.assertEqual(r.status_code, 200)

    def test_secao_enviada_bloqueia_ate_o_setor_do_bloco(self):
        self.bloco.setor = Setor.objects.get(sigla="DPPG")
        self.bloco.save()
        self.sec.situacao = Secao.ENVIADA
        self.sec.save()
        self.assertFalse(F.pode_editar_bloco(self.dppg, self.bloco))

    def test_resposta_do_salvamento_traz_a_contagem(self):
        self.bloco.min_caracteres, self.bloco.max_caracteres = 5000, 6000
        self.bloco.save()
        self.entrar("grad")
        self.post(reverse("bloco_travar", args=[2026, self.bloco.pk]), {"modo": "editar"})
        self.bloco.refresh_from_db()
        r = self.post(reverse("bloco_texto", args=[2026, self.bloco.pk]),
                      {"html": self.bloco.conteudo, "versao": self.bloco.atualizado_em.isoformat()})
        d = r.json()
        self.assertTrue(d["ok"], d)
        self.assertEqual(d["caracteres"], AT.contar_caracteres(self.bloco.conteudo))
        self.assertIn(d["tamanho"], ("pouco", "muito", "ok"))

    def test_limite_nao_impede_salvar(self):
        self.bloco.max_caracteres = 3
        self.bloco.save()
        self.entrar("grad")
        self.post(reverse("bloco_travar", args=[2026, self.bloco.pk]), {"modo": "editar"})
        self.bloco.refresh_from_db()
        r = self.post(reverse("bloco_texto", args=[2026, self.bloco.pk]),
                      {"html": self.bloco.conteudo, "versao": self.bloco.atualizado_em.isoformat()})
        self.assertTrue(r.json()["ok"])
        self.assertEqual(r.json()["tamanho"], "muito")


class TelaDoAdministradorTests(BaseAtributos):
    def url(self):
        return reverse("blocos_atributos", args=[2026])

    def test_setor_comum_nao_acessa(self):
        self.entrar("grad")
        self.assertEqual(self.client.get(self.url()).status_code, 403)

    def test_sem_filtro_abre_na_primeira_pagina(self):
        self.entrar("adm")
        r = self.client.get(self.url())
        self.assertEqual(r.status_code, 302)
        self.assertIn("?pagina=", r["Location"])

    def test_admin_ve_a_tela_filtrada_por_secao(self):
        self.entrar("adm")
        r = self.client.get(self.url() + "?secao=ensino_graduacao")
        self.assertEqual(r.status_code, 200)
        n = Bloco.objects.filter(secao=self.sec, tipo=Bloco.TEXTO).count()
        self.assertEqual(len(r.context["linhas"]), n)

    def _dados(self, fs, mudancas):
        dados = {k: v for k, v in fs.management_form.initial.items()}
        dados = {"form-TOTAL_FORMS": len(fs.forms), "form-INITIAL_FORMS": len(fs.forms),
                 "form-MIN_NUM_FORMS": 0, "form-MAX_NUM_FORMS": 1000}
        for i, f in enumerate(fs.forms):
            b = f.instance
            dados[f"form-{i}-id"] = b.pk
            dados[f"form-{i}-setor"] = b.setor_id or ""
            dados[f"form-{i}-descricao"] = b.descricao
            dados[f"form-{i}-min_caracteres"] = b.min_caracteres or ""
            dados[f"form-{i}-max_caracteres"] = b.max_caracteres or ""
            if b.pk in mudancas:
                for k, v in mudancas[b.pk].items():
                    dados[f"form-{i}-{k}"] = v
        return dados

    def test_admin_salva_os_atributos_sem_mexer_no_texto_nem_na_versao(self):
        self.entrar("adm")
        url = self.url() + "?secao=ensino_graduacao"
        fs = self.client.get(url).context["fs"]
        versao, texto = self.bloco.atualizado_em, self.bloco.conteudo
        dppg = Setor.objects.get(sigla="DPPG")
        r = self.client.post(url, self._dados(fs, {self.bloco.pk: {
            "setor": dppg.pk, "descricao": "Resultados do ano", "min_caracteres": 100, "max_caracteres": 900}}))
        self.assertEqual(r.status_code, 302)
        self.bloco.refresh_from_db()
        self.assertEqual((self.bloco.setor, self.bloco.descricao, self.bloco.min_caracteres, self.bloco.max_caracteres),
                         (dppg, "Resultados do ano", 100, 900))
        self.assertEqual(self.bloco.conteudo, texto)
        self.assertEqual(self.bloco.atualizado_em, versao)

    def test_minimo_maior_que_maximo_e_recusado(self):
        self.entrar("adm")
        url = self.url() + "?secao=ensino_graduacao"
        fs = self.client.get(url).context["fs"]
        r = self.client.post(url, self._dados(fs, {self.bloco.pk: {"min_caracteres": 500, "max_caracteres": 100}}))
        self.assertEqual(r.status_code, 200)
        self.bloco.refresh_from_db()
        self.assertIsNone(self.bloco.min_caracteres)


class TelaDoRelatorioTests(BaseAtributos):
    def test_orientacao_cor_e_contador_aparecem_no_editor(self):
        self.bloco.descricao = "Resultados da graduação em 2026"
        self.bloco.min_caracteres, self.bloco.max_caracteres = 100, 900
        self.bloco.save()
        self.entrar("grad")
        r = self.client.get(reverse("escrever", args=[2026]))
        self.assertEqual(r.status_code, 200)
        html = r.content.decode()
        self.assertIn("--cor-setor:", html)
        self.assertIn(f'data-min="100"', html)
        self.assertIn(f'data-max="900"', html)

    def test_outro_setor_nao_ganha_o_botao_de_editar_no_bloco(self):
        self.bloco.setor = Setor.objects.get(sigla="DPPG")
        self.bloco.save()
        self.entrar("grad")
        html = self.client.get(reverse("escrever", args=[2026])).content.decode()
        import re
        trecho = re.search(r'<div class="texto-rg doc-texto[^"]*"[^>]*data-bloco="%d"' % self.bloco.pk, html)
        self.assertIsNotNone(trecho)
        self.assertNotIn("editavel", trecho.group(0))
        self.client.logout()
        self.entrar("dppg")
        html = self.client.get(reverse("escrever", args=[2026])).content.decode()
        trecho = re.search(r'<div class="texto-rg doc-texto[^"]*"[^>]*data-bloco="%d"' % self.bloco.pk, html)
        self.assertIn("editavel", trecho.group(0))


class NovoCicloCopiaAtributosTests(BaseAtributos):
    def test_atributos_vao_para_o_ciclo_seguinte(self):
        from relatorio import servicos as S
        self.bloco.setor = Setor.objects.get(sigla="DPPG")
        self.bloco.descricao = "Texto de teste"
        self.bloco.min_caracteres, self.bloco.max_caracteres = 10, 20
        self.bloco.save()
        novo = S.copiar_ciclo(self.c, 2027, "RG 2027")
        copia = Bloco.objects.filter(secao__ciclo=novo, conteudo=self.bloco.conteudo, ordem=self.bloco.ordem,
                                     secao__chave=self.sec.chave).first()
        self.assertEqual((copia.setor, copia.descricao, copia.min_caracteres, copia.max_caracteres),
                         (self.bloco.setor, "Texto de teste", 10, 20))
