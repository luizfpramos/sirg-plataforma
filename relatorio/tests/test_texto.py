"""Texto do relatório: limpeza do HTML, números vivos, edição, travas, sugestões, fluxo e gráficos."""
import json

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase

from contas import servicos as CS
from contas.models import Perfil, Setor
from relatorio import fluxo as F
from relatorio import graficos
from relatorio.calculo import Calculadora
from relatorio.html_seguro import limpar, texto_puro
from relatorio.models import Bloco, Ciclo, MovimentoSecao, Secao, Sugestao, Valor
from relatorio.texto import renderizar

User = get_user_model()
SENHA = "Senha-forte-2026"


class LimpezaTests(TestCase):
    def test_remove_perigos_e_estilos(self):
        sujo = ('<p style="color:red" onclick="x()">Oi <b>forte</b> <script>alert(1)</script>'
                '<a href="javascript:alert(1)">link</a> <a href="https://cefetmg.br">ok</a></p>'
                '<h1>Título</h1><div>bloco</div><o:p></o:p><img src=x onerror=alert(1)>')
        limpo = limpar(sujo)
        self.assertNotIn("script", limpo)
        self.assertNotIn("onclick", limpo)
        self.assertNotIn("style", limpo)
        self.assertNotIn("javascript", limpo)
        self.assertNotIn("<img", limpo)
        self.assertIn("<strong>forte</strong>", limpo)
        self.assertIn('href="https://cefetmg.br"', limpo)
        self.assertIn("<h3>Título</h3>", limpo)
        self.assertIn("<p>bloco</p>", limpo)

    def test_mantem_numero_vivo(self):
        h = limpar('<p>São <span class="sirg-num pendente" data-ref="ga_matriculados.total" title="x" '
                   'contenteditable="false">14.755</span> alunos</p>')
        self.assertIn('<span class="sirg-num" data-ref="ga_matriculados.total">14.755</span>', h)
        self.assertNotIn("contenteditable", h)
        # referência malformada vira texto comum
        h = limpar('<span class="sirg-num" data-ref="x; drop">1</span>')
        self.assertNotIn("sirg-num", h)

    def test_texto_puro(self):
        self.assertEqual(texto_puro("<p>a &amp; b</p><p>c</p>"), "a & b\nc")


class Base(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("inicializar", verbosity=0)
        call_command("criar_admin", login="admin", nome="Admin Geral", senha=SENHA, verbosity=0)
        call_command("carregar_rg2025", abrir_2026=True, verbosity=0)
        g = lambda s: Setor.objects.get(sigla=s)
        cls.dppg, _ = CS.criar_usuario(login="dppg", nome="Paulo DPPG", setores=[g("DPPG")], senha=SENHA)
        cls.dae, _ = CS.criar_usuario(login="dae", nome="Bia DAE", setores=[g("DAE")], senha=SENHA)
        cls.master, _ = CS.criar_usuario(login="master", nome="Mara Master", e_master=True, senha=SENHA)
        Perfil.objects.update(troca_senha=False)
        cls.c26 = Ciclo.objects.get(ano=2026)
        Ciclo.objects.filter(pk=cls.c26.pk).update(situacao=Ciclo.COLETA)
        cls.c26.refresh_from_db()

    def setUp(self):
        self.sec = Secao.objects.get(ciclo__ano=2026, chave="pesquisa_inovacao")
        self.texto = self.sec.blocos.filter(tipo=Bloco.TEXTO).first()

    def entrar(self, login):
        self.client.post("/entrar/", {"username": login, "password": SENHA})

    def post(self, url, dados):
        return self.client.post(url, json.dumps(dados), content_type="application/json")


class NumerosVivosTests(Base):
    def test_texto_do_rg2025_mostra_valores_atuais(self):
        c25 = Ciclo.objects.get(ano=2025)
        b = Bloco.objects.get(secao__ciclo=c25, secao__chave="mensagem")
        html, problemas = renderizar(b.conteudo, Calculadora(c25))
        self.assertIn(">14.755<", html)
        self.assertIn(">4.588<", html)
        self.assertIn(">R$ 4.457.663,20<", html)
        self.assertEqual(problemas, [])

    def test_valor_muda_e_texto_acompanha(self):
        b = self.texto
        calc = Calculadora(self.c26)
        html, problemas = renderizar(b.conteudo, calc)
        self.assertIn(">xxxxx<", html)
        self.assertTrue(problemas)
        # DPPG preenche os bolsistas de 2026: o texto passa a mostrar o número
        from relatorio.models import Coluna, Linha
        li = Linha.objects.get(quadro__ciclo=self.c26, quadro__chave="pq_bolsistas", chave="bolsistas")
        Valor.objects.create(linha=li, coluna=Coluna.objects.get(quadro=li.quadro, ano=2026), numero=21)
        html, _ = renderizar(b.conteudo, Calculadora(self.c26))
        self.assertIn(">21<", html)

    def test_referencia_invalida(self):
        html, problemas = renderizar('<span class="sirg-num" data-ref="nao_existe.total">1</span>',
                                     Calculadora(self.c26))
        self.assertIn("[número inválido]", html)
        self.assertIn("não existe", problemas[0]["erro"])

    def test_opcoes_de_numeros(self):
        self.entrar("dppg")
        j = self.client.get("/ciclos/2025/numeros/").json()
        ga = next(g for g in j["grupos"] if g["chave"] == "ga_matriculados")
        tot = next(i for i in ga["itens"] if i["ref"] == "ga_matriculados.total")
        self.assertEqual(tot["valor"], "14.755")
        pos = next(g for g in j["grupos"] if g["chave"] == "pos_numeros")
        self.assertTrue(any(i["col"] == "total" for i in pos["itens"]))


class EdicaoTests(Base):
    def test_setor_edita_o_proprio_texto(self):
        self.entrar("dppg")
        r = self.post(f"/ciclos/2026/blocos/{self.texto.pk}/travar/", {})
        self.assertTrue(r.json()["ok"])
        versao = r.json()["versao"]
        antes = self.texto.conteudo
        html = antes.replace("</p>", ' <ins data-s="d1">Novo texto <script>x</script></ins></p>', 1)
        r = self.post(f"/ciclos/2026/blocos/{self.texto.pk}/texto/", {"html": html, "versao": versao, "liberar": True})
        j = r.json()
        self.assertTrue(j["ok"], j)
        self.texto.refresh_from_db()
        self.assertIn(">Novo texto </ins>", self.texto.conteudo)            # entra como alteração, sem o script
        self.assertNotIn("<script", self.texto.conteudo)
        self.assertNotIn("herdado_de", self.texto.config)
        self.assertIsNone(self.texto.editando_por)
        self.sec.refresh_from_db()
        self.assertEqual(self.sec.situacao, Secao.PREENCHIMENTO)

    def test_outro_setor_nao_edita(self):
        self.entrar("dae")
        r = self.post(f"/ciclos/2026/blocos/{self.texto.pk}/travar/", {})
        self.assertEqual(r.status_code, 403)
        r = self.post(f"/ciclos/2026/blocos/{self.texto.pk}/texto/", {"html": "<p>x</p>"})
        self.assertEqual(r.status_code, 400)

    def test_trava_impede_edicao_simultanea(self):
        F.travar(self.master, self.texto)
        self.entrar("dppg")
        r = self.post(f"/ciclos/2026/blocos/{self.texto.pk}/travar/", {})
        self.assertEqual(r.status_code, 409)
        self.assertIn("Mara Master", r.json()["erro"])

    def test_conflito_de_versao(self):
        self.entrar("dppg")
        v = self.post(f"/ciclos/2026/blocos/{self.texto.pk}/travar/", {}).json()["versao"]
        F.destravar(self.dppg, self.texto)
        F.salvar_texto(self.master, self.texto, "<p>do master</p>")
        F.destravar(self.master, self.texto)
        r = self.post(f"/ciclos/2026/blocos/{self.texto.pk}/texto/", {"html": "<p>meu</p>", "versao": v})
        self.assertIn("alterado por outra pessoa", r.json()["erro"])

    def test_criar_mover_excluir_bloco(self):
        self.entrar("master")            # 2.12: blocos novos são do Master
        n = self.sec.blocos.count()
        r = self.client.post("/ciclos/2026/blocos/novo/", {"secao": self.sec.pk, "tipo": "grafico",
                                                           "depois": self.texto.pk})
        b = self.sec.blocos.order_by("-id").first()
        self.assertRedirects(r, f"/ciclos/2026/blocos/{b.pk}/configurar/")
        self.assertEqual(self.sec.blocos.count(), n + 1)
        ordem = list(self.sec.blocos.order_by("ordem").values_list("pk", flat=True))
        self.assertEqual(ordem.index(b.pk), ordem.index(self.texto.pk) + 1)
        q = self.c26.quadros.get(chave="pq_pi")
        r = self.client.post(f"/ciclos/2026/blocos/{b.pk}/configurar/", {"titulo": "PI", "quadro": q.pk})
        r = self.client.post(f"/ciclos/2026/blocos/{b.pk}/configurar/", {
            "titulo": "PI", "quadro": q.pk, "tipo_grafico": "linhas", "linhas": ["patentes"], "rotulos": "on",
            "concluir": "1"})
        b.refresh_from_db()
        self.assertEqual(b.config["tipo"], "linhas")
        self.assertEqual(b.config["linhas"], ["patentes"])
        self.client.post(f"/ciclos/2026/blocos/{b.pk}/subir/")
        ordem2 = list(self.sec.blocos.order_by("ordem").values_list("pk", flat=True))
        self.assertLess(ordem2.index(b.pk), ordem2.index(self.texto.pk))
        self.client.post(f"/ciclos/2026/blocos/{b.pk}/excluir/")
        self.assertFalse(Bloco.objects.filter(pk=b.pk).exists())

    def test_historico_e_restaurar(self):
        F.salvar_texto(self.master, self.texto, "<p>versão A</p>")
        F.salvar_texto(self.master, self.texto, "<p>versão B</p>")
        F.destravar(self.master, self.texto)
        self.entrar("master")
        j = self.client.get(f"/ciclos/2026/blocos/{self.texto.pk}/historico/").json()
        self.assertIn("<ins>B</ins>", j["itens"][0]["diff"])
        hid = j["itens"][1]["id"]
        self.client.post(f"/ciclos/2026/blocos/{self.texto.pk}/restaurar/{hid}/")
        self.texto.refresh_from_db()
        self.assertEqual(self.texto.conteudo, "<p>versão A</p>")


class SugestaoTests(Base):
    def test_master_sugere_setor_aceita(self):
        self.entrar("master")
        r = self.post(f"/ciclos/2026/blocos/{self.texto.pk}/texto/",
                      {"html": "<p>Texto revisado pelo Master</p>", "sugestao": True, "comentario": "Atualizei"})
        self.assertTrue(r.json()["ok"])
        s = Sugestao.objects.get(bloco=self.texto)
        self.texto.refresh_from_db()
        self.assertNotEqual(self.texto.conteudo, "<p>Texto revisado pelo Master</p>")   # não mudou ainda
        self.client.logout()
        self.entrar("dae")       # outro setor não responde
        self.client.post(f"/ciclos/2026/sugestoes/{s.pk}/aceitar/")
        s.refresh_from_db()
        self.assertEqual(s.situacao, Sugestao.PENDENTE)
        self.client.logout()
        self.entrar("dppg")
        r = self.client.get(f"/ciclos/2026/secoes/{self.sec.chave}/")
        self.assertContains(r, "Sugestão de Mara Master")
        self.client.post(f"/ciclos/2026/sugestoes/{s.pk}/aceitar/")
        s.refresh_from_db()
        self.texto.refresh_from_db()
        self.assertEqual(s.situacao, Sugestao.ACEITA)
        self.assertEqual(self.texto.conteudo, "<p>Texto revisado pelo Master</p>")

    def test_setor_recusa(self):
        s = F.sugerir(self.master, self.texto, "<p>outra coisa</p>")
        F.responder_sugestao(self.dppg, s, False, "Prefiro o original")
        s.refresh_from_db()
        self.assertEqual(s.situacao, Sugestao.RECUSADA)
        self.assertEqual(s.resposta, "Prefiro o original")

    def test_so_master_sugere(self):
        with self.assertRaises(F.Recusado):
            F.sugerir(self.dppg, self.texto, "<p>x</p>")


class FluxoTests(Base):
    def test_enviar_bloqueado_com_pendencias(self):
        with self.assertRaises(F.Recusado) as cm:
            F.acao_secao(self.dppg, self.sec, "enviar")
        self.assertIn("a preencher", str(cm.exception))

    def test_ciclo_completo_de_uma_secao(self):
        sec = Secao.objects.get(ciclo=self.c26, chave="desenvolvimento_carreiras")
        sec.setores.set([Setor.objects.get(sigla="DPPG")])
        from relatorio.models import Coluna
        for li in sec.quadros.get().linhas.all():
            Valor.objects.create(linha=li, coluna=Coluna.objects.get(quadro=li.quadro, ano=2026), numero=1)
        self.entrar("dppg")
        self.client.post(f"/ciclos/2026/secoes/{sec.chave}/acao/", {"acao": "enviar"})
        sec.refresh_from_db()
        self.assertEqual(sec.situacao, Secao.ENVIADA)
        # enviada: setor não edita mais texto nem dados
        self.assertFalse(F.pode_editar_texto(self.dppg, sec))
        from relatorio import permissoes as RP
        self.assertFalse(RP.pode_editar_quadro(self.dppg, sec.quadros.get()))
        # Master devolve (com comentário obrigatório)
        self.client.logout()
        self.entrar("master")
        self.client.post(f"/ciclos/2026/secoes/{sec.chave}/acao/", {"acao": "devolver", "comentario": ""})
        sec.refresh_from_db()
        self.assertEqual(sec.situacao, Secao.ENVIADA)
        self.client.post(f"/ciclos/2026/secoes/{sec.chave}/acao/", {"acao": "devolver", "comentario": "Rever"})
        sec.refresh_from_db()
        self.assertEqual(sec.situacao, Secao.PREENCHIMENTO)
        self.assertTrue(sec.comentarios.filter(texto__contains="Rever").exists())
        F.acao_secao(self.dppg, sec, "enviar")
        F.acao_secao(self.master, sec, "aprovar")
        sec.refresh_from_db()
        self.assertEqual(sec.situacao, Secao.APROVADA)
        self.assertEqual(MovimentoSecao.objects.filter(secao=sec).count(), 4)

    def test_setor_nao_aprova(self):
        with self.assertRaises(F.Recusado):
            F.acao_secao(self.dppg, self.sec, "aprovar")

    def test_comentarios(self):
        self.entrar("dae")
        self.client.post(f"/ciclos/2026/secoes/{self.sec.chave}/comentar/", {"texto": "Faltou citar o Compete",
                                                                              "bloco": self.texto.pk})
        c = self.sec.comentarios.get()
        self.assertEqual(c.bloco, self.texto)
        self.client.post(f"/ciclos/2026/comentarios/{c.pk}/resolver/")
        c.refresh_from_db()
        self.assertTrue(c.resolvido)


class TelasTextoTests(Base):
    def test_paginas(self):
        self.entrar("dppg")
        for url in ("/ciclos/2025/documento/", "/ciclos/2026/documento/", f"/ciclos/2026/secoes/{self.sec.chave}/",
                    "/ciclos/2026/secoes/pesquisa_inovacao/?aba=dados", "/ciclos/2025/secoes/inclusao/",
                    f"/ciclos/2026/blocos/{self.sec.blocos.filter(tipo='destaques').first().pk}/configurar/"):
            self.assertEqual(self.client.get(url).status_code, 200, url)

    def test_documento_tem_graficos_e_texto(self):
        self.entrar("dppg")
        r = self.client.get("/ciclos/2025/documento/")
        self.assertContains(r, "grafico-svg")
        self.assertContains(r, "14.755")
        self.assertContains(r, "Gestão Acadêmica")

    def test_copia_de_ciclo_leva_os_blocos(self):
        c25 = Ciclo.objects.get(ano=2025)
        self.assertEqual(Bloco.objects.filter(secao__ciclo=c25).count(),
                         Bloco.objects.filter(secao__ciclo=self.c26).count())
        self.assertEqual(self.texto.config.get("herdado_de"), 2025)


class GraficosTests(Base):
    def test_todos_os_graficos_do_rg2025_desenham(self):
        c25 = Ciclo.objects.get(ano=2025)
        calc = Calculadora(c25)
        for b in Bloco.objects.filter(secao__ciclo=c25, tipo=Bloco.GRAFICO).exclude(quadro__chave="frota_km") \
                .select_related("quadro"):
            svg, avisos = graficos.desenhar(calc, calc.quadros[b.quadro.chave], b.config)
            self.assertTrue(svg and svg.startswith("<svg"), f"{b.quadro.chave}: {avisos}")
            png, _ = graficos.desenhar(calc, calc.quadros[b.quadro.chave], b.config, formato_saida="png")
            self.assertTrue(png.startswith(b"\x89PNG"))

    def test_unidades_diferentes_nao_misturam(self):
        c25 = Ciclo.objects.get(ano=2025)
        calc = Calculadora(c25)
        _, series, tipo, avisos = graficos.dados(calc, calc.quadros["pq_ic"], {"linhas": ["alunos", "recursos"]})
        self.assertEqual(len(series), 1)
        self.assertTrue(avisos)

    def test_abreviar(self):
        from relatorio.models import Quadro
        self.assertEqual(graficos.abreviar(4457663.2, Quadro.MOEDA), "R$ 4,46 mi")
        self.assertEqual(graficos.abreviar(14755, Quadro.INTEIRO), "14.755")
        self.assertEqual(graficos.abreviar(42.34, Quadro.PERCENTUAL), "42,3%")


class PendenciasTextoTests(Base):
    def test_textos_aparecem_nas_inconsistencias(self):
        self.entrar("dppg")
        r = self.client.get("/ciclos/2026/pendencias/")
        self.assertTrue(any("Número no texto" in t["mensagem"] for t in r.context["textos"]))
        F.salvar_texto(self.master, self.texto, "<p>Foram 14.755 alunos.</p>")
        r = self.client.get("/ciclos/2026/pendencias/?setor=DPPG")
        self.assertFalse(any("digitado à mão" in t["mensagem"] for t in r.context["textos"]))  # 2026 vazio
        r = self.client.get("/ciclos/2025/pendencias/")
        self.assertEqual(r.status_code, 200)
