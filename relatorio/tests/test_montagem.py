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
        self.assertEqual([p["titulo"] for p in passos], ["Setores e pessoas", "Seções", "PDF diagramado", "Blocos nas páginas",
                                                         "Atributos dos blocos", "Quadros de números",
                                                         "PDF do relatório anterior (consulta)", "Situação e prazo"])
        self.assertTrue(all(p["situacao"] == "falta" for p in passos[1:]))
        self.assertContains(r, "Criar as seções")

    def test_secao_sem_setor_e_aviso(self):
        cap = secao(self.c, "cap", "Capítulo", ordem=10)
        secao(self.c, "s1", "Seção", pai=cap, ordem=10)
        p = M.passos(self.c)[1]
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
        self.assertContains(r, "2 capítulos criados, 3 seções criadas.")
        self.assertContains(r, "setor “XYZ” não existe")
        arv = M.arvore(self.c)
        self.assertEqual([c.titulo for c, _ in arv], ["Apresentação", "Visão geral"])
        self.assertEqual([s.titulo for s in arv[0][1]], ["Mensagem da dirigente", "Sobre o relatório"])
        self.assertEqual(sorted(st.sigla for st in arv[0][1][1].setores.all()), ["DGDI", "SEGEP"])
        self.assertEqual([s.titulo for s in arv[1][1]], ["Quem somos"])
        # 2.23: colar de novo um título que já existe atualiza o item, não duplica
        r = M.adicionar_em_lote(self.c, "Apresentação\n- Mensagem da dirigente | DGDI")
        self.assertEqual((r["capitulos"], r["secoes"], r["atualizadas"]), (0, 0, 1))
        self.assertEqual(Secao.objects.filter(ciclo=self.c, titulo="Apresentação").count(), 1)
        self.assertEqual([x.sigla for x in Secao.objects.get(ciclo=self.c, titulo="Mensagem da dirigente").setores.all()],
                         ["DGDI"])
        # um capítulo novo continua depois do último
        M.adicionar_em_lote(self.c, "Anexos\n- Glossário")
        self.assertEqual(M.arvore(self.c)[-1][0].titulo, "Anexos")

    def test_setor_que_nao_existe_leva_a_criar(self):
        self.entrar()
        r = self.client.post(reverse("secoes_lista", args=[2030]), {"lista": "Cap\n- Seção | NOVO, DGDI"})
        url = reverse("secoes_lista", args=[2030]) + "?faltam=NOVO"
        self.assertRedirects(r, url)
        r = self.client.get(url)
        self.assertContains(r, "Criar NOVO")
        r = self.client.get(reverse("setor_novo") + "?sigla=NOVO&next=" + url)
        self.assertContains(r, 'value="NOVO"')
        r = self.client.post(reverse("setor_novo"), {"sigla": "NOVO", "nome": "Setor novo", "ativo": "on",
                                                      "ordem": 999, "descricao": "", "next": url})
        self.assertRedirects(r, url)
        self.assertNotContains(self.client.get(url), "Criar NOVO")       # já existe: o aviso some
        sec = Secao.objects.get(ciclo=self.c, titulo="Seção")
        self.assertEqual(sorted(x.sigla for x in sec.setores.all()), ["DGDI", "NOVO"])   # já entrou na seção
        r = self.client.post(reverse("setor_novo"), {"sigla": "OUTRO", "nome": "Outro", "ativo": "on",
                                                      "ordem": 1000, "descricao": "", "next": "https://exemplo.com/"})
        self.assertRedirects(r, reverse("setor", args=[Setor.objects.get(sigla="OUTRO").pk]))

    def test_passo_dos_setores(self):
        p = M.passos(self.c)[0]
        self.assertEqual(p["titulo"], "Setores e pessoas")
        self.assertEqual(p["situacao"], "aviso")          # há setores iniciais sem ninguém cadastrado
        self.assertIn("Sem ninguém cadastrado", p["texto"])
        self.assertNotIn("DIRGRAD", p["texto"].split("Sem ninguém cadastrado")[1])   # a Ana é do DIRGRAD

    def test_secao_sem_capitulo_vira_capitulo(self):
        r = M.adicionar_em_lote(self.c, "- Solta")
        self.assertEqual((r["capitulos"], r["secoes"]), (1, 0))
        self.assertTrue(r["avisos"])

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


class QuadrosEPdfAnteriorTests(BaseMontagem):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.chefe, _ = CS.criar_usuario(login="chefe", nome="Chefe", e_master=True, senha=SENHA)
        Perfil.objects.update(troca_senha=False)
        cap = secao(cls.c, "cap", "Capítulo", ordem=10)
        cls.sec = secao(cls.c, "grad", "Graduação", pai=cap, ordem=10, setores=["DIRGRAD"])

    def test_quadro_simples_por_anos_nasce_com_o_passado_travado(self):
        from relatorio.models import Quadro
        self.entrar()
        r = self.client.post(reverse("quadros_lista", args=[2030]), {
            "titulo": "Grupos PET", "secao": self.sec.pk, "linhas": "Alunos participantes\nRecursos utilizados\n\n",
            "tipo": "inteiro", "modo": "anos", "anos": "5"}, follow=True)
        self.assertContains(r, "Quadro “Grupos PET” criado")
        q = Quadro.objects.get(ciclo=self.c, titulo="Grupos PET")
        self.assertEqual([l.rotulo for l in q.linhas.all()], ["Alunos participantes", "Recursos utilizados"])
        cols = list(q.colunas.order_by("ordem"))
        self.assertEqual([c.ano for c in cols], [2026, 2027, 2028, 2029, 2030])
        self.assertEqual([c.travada for c in cols], [True, True, True, True, False])
        self.assertEqual(M.passos(self.c)[5]["situacao"], "feito")

    def test_quadro_por_categorias_e_erros(self):
        from relatorio.models import Quadro
        q = M.criar_quadro_simples(self.c, titulo="Por campus", secao=self.sec, linhas="Vagas", modo="categorias",
                                   colunas="Campus I\nCampus II")
        self.assertEqual([c.rotulo for c in q.colunas.order_by("ordem")], ["Campus I", "Campus II"])
        self.assertEqual(q.modo_colunas, Quadro.CATEGORIAS)
        q2 = M.criar_quadro_simples(self.c, titulo="Por campus", secao=self.sec, linhas="Vagas")
        self.assertNotEqual(q.chave, q2.chave)
        with self.assertRaises(M.Recusado):
            M.criar_quadro_simples(self.c, titulo="Sem linhas", secao=self.sec, linhas="  ")
        with self.assertRaises(M.Recusado):
            M.criar_quadro_simples(self.c, titulo="Sem colunas", secao=self.sec, linhas="A", modo="categorias")
        self.entrar("ana")
        self.assertEqual(self.client.get(reverse("quadros_lista", args=[2030])).status_code, 403)

    def test_historico_vazio_nao_pede_justificativa_mas_alterar_pede(self):
        from relatorio import servicos as S
        q = M.criar_quadro_simples(self.c, titulo="PET", secao=self.sec, linhas="Alunos", anos=3)
        li, col = q.linhas.get(), q.colunas.get(ano=2028)
        S.salvar_valor(self.chefe, li, col, "151")
        with self.assertRaises(S.Recusado):
            S.salvar_valor(self.chefe, li, col, "160", anterior="151")
        S.salvar_valor(self.chefe, li, col, "160", anterior="151", justificativa="Dado revisado")
        with self.assertRaises(S.Recusado):                # o setor não mexe no histórico
            S.salvar_valor(self.ana, li, col, "170", anterior="160")

    def test_pdf_do_relatorio_anterior_pela_tela(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        self.entrar()
        r = self.client.post(reverse("pdf_anterior_enviar", args=[2030]),
                             {"pdf": SimpleUploadedFile("x.txt", b"texto", content_type="text/plain")}, follow=True)
        self.assertContains(r, "precisa ser um PDF")
        r = self.client.post(reverse("pdf_anterior_enviar", args=[2030]),
                             {"pdf": SimpleUploadedFile("RG.pdf", b"%PDF-1.4 teste", content_type="application/pdf")})
        self.assertRedirects(r, reverse("montagem", args=[2030]))
        self.assertEqual(M.passos(self.c)[6]["situacao"], "feito")
        self.assertEqual(M.url_pdf_anterior(self.c), reverse("pdf_anterior", args=[2030]))
        self.entrar("ana")
        r = self.client.get(reverse("pdf_anterior", args=[2030]))
        self.assertEqual(b"".join(r.streaming_content), b"%PDF-1.4 teste")
        self.assertContains(self.client.get(reverse("escrever", args=[2030])), reverse("pdf_anterior", args=[2030]))
        self.assertEqual(self.client.get(reverse("pdf_anterior_enviar", args=[2030])).status_code, 403)


class EnvioExigeBlocosTests(BaseMontagem):
    def test_envio_so_sem_bloco_vazio(self):
        from relatorio import fluxo as F
        Ciclo.objects.filter(pk=self.c.pk).update(situacao=Ciclo.COLETA)
        self.c.refresh_from_db()
        cap = secao(self.c, "cap", "Capítulo", ordem=10)
        s = secao(self.c, "grad", "Graduação", pai=cap, ordem=10, setores=["DIRGRAD"])
        Bloco.objects.create(secao=s, conteudo="<p>Título fixo</p>", config={"fixo": True})
        vazio = Bloco.objects.create(secao=s, conteudo="", config={"referencia_pdf": "<p>antigo</p>"})
        Bloco.objects.create(secao=s, tipo=Bloco.IMAGEM, config={})
        self.assertEqual(F.blocos_vazios_da_secao(s), 2)
        with self.assertRaisesRegex(F.Recusado, "2 blocos ainda vazios"):
            F.acao_secao(self.ana, s, "enviar")
        F.salvar_texto(self.ana, vazio, "<p><ins data-s=\"a1b2c3\">Texto novo do setor.</ins></p>")   # fica marcado para o Editor-chefe aceitar
        Bloco.objects.filter(secao=s, tipo=Bloco.IMAGEM).update(config={"imagem": {"id": 1}})
        self.assertEqual(F.blocos_vazios_da_secao(s), 0)
        F.acao_secao(self.ana, s, "enviar")
        s.refresh_from_db()
        self.assertEqual(s.situacao, Secao.ENVIADA)

    def test_rg2026_automatico_segue_a_regra_antiga(self):
        from relatorio import fluxo as F
        Ciclo.objects.filter(pk=self.c.pk).update(automatico=True)
        cap = secao(self.c, "cap", "Capítulo", ordem=10)
        Bloco.objects.create(secao=cap, conteudo="")
        self.assertEqual(F.blocos_vazios_da_secao(Secao.objects.get(pk=cap.pk)), 0)
