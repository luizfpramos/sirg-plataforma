"""2.11: controle de alterações (sugestões no próprio texto) e comentários presos a um trecho."""
import json

from django.core.management import call_command
from django.test import TestCase

from contas import servicos as CS
from contas.models import Perfil, Setor
from relatorio import fluxo as F
from relatorio import revisao as R
from relatorio.html_seguro import limpar
from relatorio.models import Bloco, Ciclo, Comentario, Secao

SENHA = "Senha-forte-2026"


def ins(sid, texto, u=1, a="Fulano"):
    return f'<ins data-s="{sid}" data-u="{u}" data-a="{a}" data-d="2026-11-10T09:00:00Z">{texto}</ins>'


def dele(sid, texto, u=1, a="Fulano"):
    return f'<del data-s="{sid}" data-u="{u}" data-a="{a}" data-d="2026-11-10T09:00:00Z">{texto}</del>'


class RevisaoUnidadeTests(TestCase):
    def test_aceitar_recusar_e_texto_oficial(self):
        h = limpar(f"<p>O {dele('a1', 'velho')}{ins('a1', 'novo <strong>texto</strong>')} fica. "
                   f"{ins('b2', 'Mais.')}</p><p>{ins('c3', 'Parágrafo novo')}</p>")
        its = R.itens(h)
        self.assertEqual([i["id"] for i in its], ["a1", "b2", "c3"])
        self.assertEqual((its[0]["removido"], its[0]["inserido"]), ("velho", "novo texto"))
        self.assertEqual(R.base(h), "<p>O velho fica. </p>")                       # pendente não vale
        self.assertEqual(R.aplicar(h, ["a1"], True),
                         f"<p>O novo <strong>texto</strong> fica. {ins('b2', 'Mais.')}</p><p>{ins('c3', 'Parágrafo novo')}</p>")
        self.assertEqual(R.aplicar(h, ["a1", "c3"], False), f"<p>O velho fica. {ins('b2', 'Mais.')}</p>")
        self.assertEqual(R.aplicar(h), "<p>O novo <strong>texto</strong> fica. Mais.</p><p>Parágrafo novo</p>")

    def test_numero_vivo_dentro_da_sugestao(self):
        h = limpar('<p>Total de ' + ins("n1", '<span class="sirg-num" data-ref="ga_matriculados.total">7.012</span> alunos')
                   + "</p>")
        self.assertIn('class="sirg-num"', h)
        self.assertEqual(R.base(h), "<p>Total de </p>")
        self.assertIn('data-ref="ga_matriculados.total"', R.aplicar(h, None, True))

    def test_limpeza_mantem_so_marcas_com_id(self):
        h = limpar('<p><ins>colado do Word</ins> <del data-s="x" onclick="alert(1)" data-a="A&quot;B">ok</del></p>')
        self.assertEqual(h, '<p>colado do Word <del data-s="x" data-a="A&quot;B">ok</del></p>')


class RevisaoBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("inicializar", verbosity=0)
        call_command("preparar_rg2026", sem_backup=True, verbosity=0)
        g = lambda s: Setor.objects.get(sigla=s)
        cls.grad, _ = CS.criar_usuario(login="grad", nome="Ana DIRGRAD", setores=[g("DIRGRAD")], senha=SENHA)
        cls.grad2, _ = CS.criar_usuario(login="grad2", nome="Bia DIRGRAD", setores=[g("DIRGRAD")], senha=SENHA)
        cls.dppg, _ = CS.criar_usuario(login="dppg", nome="Paulo DPPG", setores=[g("DPPG")], senha=SENHA)
        cls.master, _ = CS.criar_usuario(login="master", nome="Mara Master", e_master=True, senha=SENHA)
        Perfil.objects.update(troca_senha=False)
        cls.c = Ciclo.objects.get(ano=2026)
        cls.sec = Secao.objects.get(ciclo=cls.c, chave="ensino_graduacao")
        cls.bloco = Bloco.objects.filter(secao=cls.sec, tipo=Bloco.TEXTO).order_by("ordem").first()

    def entrar(self, u):
        self.client.force_login(u)

    def post(self, url, dados):
        return self.client.post(url, json.dumps(dados), content_type="application/json")

    def gravar(self, user, html):
        b = Bloco.objects.get(pk=self.bloco.pk)
        F.destravar(b.editando_por or user, b)
        return F.salvar_texto(user, Bloco.objects.get(pk=b.pk), html)


class AutoriaEFluxoTests(RevisaoBase):
    def test_autoria_vem_de_quem_grava(self):
        # o navegador manda outro nome numa sugestão nova: vale quem gravou
        b = self.gravar(self.master, f"<p>Base {ins('m1', 'do Master', u=self.grad.pk, a='Ana DIRGRAD')}</p>")
        it = R.itens(b.conteudo)[0]
        self.assertEqual((it["autor_id"], it["autor"]), (self.master.pk, "Mara Master"))
        # outra pessoa grava de novo: a sugestão antiga continua sendo do Master, a nova é dela
        b = self.gravar(self.grad, b.conteudo.replace("</p>", "") + f" {ins('g1', 'da Ana', u=self.master.pk)}</p>")
        autores = {i["id"]: i["autor"] for i in R.itens(b.conteudo)}
        self.assertEqual(autores, {"m1": "Mara Master", "g1": "Ana DIRGRAD"})

    def test_aceitar_e_recusar_pelo_servidor(self):
        self.gravar(self.master, f"<p>O {dele('t1', 'antigo')}{ins('t1', 'novo')} e {ins('t2', 'mais')}.</p>")
        F.destravar(self.master, self.bloco)
        self.entrar(self.grad)            # 2.12: quem aceita é o Master
        r = self.post(f"/ciclos/{self.c.ano}/revisao/resolver/", {"bloco": self.bloco.pk, "ids": ["t1"], "aceitar": True})
        self.assertEqual(r.status_code, 400)
        self.entrar(self.master)
        r = self.post(f"/ciclos/{self.c.ano}/revisao/resolver/", {"bloco": self.bloco.pk, "ids": ["t1"], "aceitar": True})
        self.assertEqual(r.status_code, 200, r.content)
        b = Bloco.objects.get(pk=self.bloco.pk)
        self.assertTrue(b.conteudo.startswith('<p>O novo e <ins data-s="t2"'), b.conteudo)
        self.assertNotIn("antigo", b.conteudo)
        self.assertEqual([i["id"] for i in R.itens(b.conteudo)], ["t2"])
        self.assertIn("aceita", b.history.first().history_change_reason)
        # recusar o resto da seção
        r = self.post(f"/ciclos/{self.c.ano}/revisao/resolver/", {"secao": self.sec.pk, "aceitar": False})
        self.assertEqual(r.json()["n"], 1)
        self.assertEqual(Bloco.objects.get(pk=self.bloco.pk).conteudo, "<p>O novo e .</p>")

    def test_quem_nao_escreve_a_secao_nao_resolve(self):
        self.gravar(self.master, f"<p>{ins('x1', 'teste')}</p>")
        F.destravar(self.master, self.bloco)
        self.entrar(self.dppg)
        r = self.post(f"/ciclos/{self.c.ano}/revisao/resolver/", {"bloco": self.bloco.pk, "aceitar": True})
        self.assertEqual(r.status_code, 400)
        self.assertIn("<ins", Bloco.objects.get(pk=self.bloco.pk).conteudo)

    def test_trecho_aberto_por_outra_pessoa(self):
        self.gravar(self.master, f"<p>{ins('x1', 'teste')}</p>")
        F.destravar(self.master, self.bloco)
        F.travar(self.grad2, self.bloco)
        self.entrar(self.master)
        r = self.post(f"/ciclos/{self.c.ano}/revisao/resolver/", {"bloco": self.bloco.pk, "aceitar": True})
        self.assertEqual(r.status_code, 400)
        self.assertIn("Bia DIRGRAD está escrevendo", r.json()["erro"])

    def test_enviar_e_aprovar_com_alteracoes_pendentes(self):
        # sugestão do próprio setor não impede o envio; a do Master, sim
        self.gravar(self.grad, self.bloco.conteudo.replace("</p>", f" {ins('s1', 'do setor')}</p>", 1))
        self.assertEqual(F.alteracoes_de_fora(self.sec), [])
        self.gravar(self.master, Bloco.objects.get(pk=self.bloco.pk).conteudo.replace("</p>", f" {ins('m1', 'do Master')}</p>"))
        fora = F.alteracoes_de_fora(self.sec)
        self.assertEqual([a["id"] for a in fora], ["m1"])
        Secao.objects.filter(pk=self.sec.pk).update(situacao=Secao.ENVIADA)
        sec = Secao.objects.get(pk=self.sec.pk)
        with self.assertRaisesMessage(F.Recusado, "Antes de aprovar, aceite ou recuse as 2 alterações"):
            F.acao_secao(self.master, sec, "aprovar")

    def test_setor_desfaz_a_propria_e_nao_aceita(self):
        b = self.gravar(self.grad, self.bloco.conteudo.replace("</p>", f" {ins('a1', 'da Ana')}</p>", 1))
        F.destravar(self.grad, b)
        with self.assertRaises(F.Recusado):
            F.resolver_alteracoes(self.grad, b, ["a1"], aceitar=True)
        b, n = F.resolver_alteracoes(self.grad, b, ["a1"], aceitar=False)       # desfazer a própria
        self.assertEqual(n, 1)
        self.assertNotIn("da Ana", b.conteudo)

    def test_envio_espera_os_xxxxx(self):
        from unittest import mock
        b = Bloco.objects.get(pk=self.bloco.pk)
        Bloco.objects.filter(pk=b.pk).update(conteudo='<p>Foram <span class="sirg-campo" data-c="c1" data-orig="5">5</span>.</p>')
        outros = Bloco.objects.filter(secao=self.sec, tipo=Bloco.TEXTO).exclude(pk=b.pk)
        outros.update(conteudo="<p>Texto.</p>")          # só o xxxxx deste trecho falta
        with mock.patch.object(F, "pendencias_da_secao", return_value=[]):
            with self.assertRaisesMessage(F.Recusado, "preencha os 1 número do texto"):
                F.acao_secao(self.grad, Secao.objects.get(pk=self.sec.pk), "enviar")
        F.preencher_campo(self.grad, Bloco.objects.get(pk=b.pk), "c1", "7")
        self.assertEqual(F.campos_vazios_da_secao(self.sec), 0)

    def test_leitura_mostra_so_o_que_foi_aceito(self):
        self.gravar(self.master, f"<p>Texto {dele('k1', 'apagado-pendente')}{ins('k1', 'inserido-pendente')}.</p>")
        self.entrar(self.grad)
        r = self.client.get(f"/ciclos/{self.c.ano}/ler/")
        html = r.content.decode()
        self.assertIn("apagado-pendente", html)
        self.assertNotIn("inserido-pendente", html)
        self.assertIn("alteração sugerida", html)
        r = self.client.get(f"/ciclos/{self.c.ano}/escrever/")
        self.assertIn('data-s="k1"', r.content.decode())       # no editor, as marcas aparecem


class ComentariosTests(RevisaoBase):
    def test_comentario_no_trecho_respostas_e_resolver(self):
        self.entrar(self.master)
        r = self.post(f"/ciclos/{self.c.ano}/revisao/comentar/", {
            "secao": self.sec.pk, "bloco": self.bloco.pk, "trecho": "  um   trecho\n escolhido ", "antes": "antes do ",
            "texto": "Confira este número."})
        self.assertTrue(r.json()["ok"], r.content)
        c = Comentario.objects.get(pk=r.json()["id"])
        self.assertEqual((c.trecho, c.antes, c.bloco_id), ("um trecho escolhido", "antes do ", self.bloco.pk))
        # resposta do setor; resposta da resposta entra na mesma conversa
        self.entrar(self.grad)
        r1 = self.post(f"/ciclos/{self.c.ano}/revisao/comentar/", {"secao": self.sec.pk, "pai": c.pk, "texto": "Conferido."})
        r2 = self.post(f"/ciclos/{self.c.ano}/revisao/comentar/", {"secao": self.sec.pk, "pai": r1.json()["id"], "texto": "Ok!"})
        self.assertEqual(Comentario.objects.get(pk=r2.json()["id"]).pai_id, c.pk)
        lista = self.client.get(f"/ciclos/{self.c.ano}/revisao/comentarios/").json()["comentarios"]
        meu = [x for x in lista if x["id"] == c.pk][0]
        self.assertEqual([x["texto"] for x in meu["respostas"]], ["Conferido.", "Ok!"])
        self.assertNotIn(r1.json()["id"], [x["id"] for x in lista])          # respostas não viram comentários soltos
        # resolver e reabrir
        self.assertTrue(self.post(f"/ciclos/{self.c.ano}/revisao/comentarios/{c.pk}/resolver/", {}).json()["ok"])
        self.assertTrue(Comentario.objects.get(pk=c.pk).resolvido)
        self.post(f"/ciclos/{self.c.ano}/revisao/comentar/", {"secao": self.sec.pk, "pai": c.pk, "texto": "Reabrindo"})
        self.assertFalse(Comentario.objects.get(pk=c.pk).resolvido)          # responder reabre a conversa
        # só quem escreveu apaga, e só sem respostas
        r = self.post(f"/ciclos/{self.c.ano}/revisao/comentarios/{c.pk}/excluir/", {})
        self.assertEqual(r.status_code, 400)

    def test_quem_nao_tem_setor_nem_e_master_nao_comenta(self):
        leitor, _ = CS.criar_usuario(login="leitor", nome="Lia", senha=SENHA)
        Perfil.objects.filter(usuario=leitor).update(troca_senha=False)
        self.entrar(leitor)
        r = self.post(f"/ciclos/{self.c.ano}/revisao/comentar/", {"secao": self.sec.pk, "texto": "oi"})
        self.assertEqual(r.status_code, 403)

    def test_tela_escrever_tem_o_painel(self):
        self.entrar(self.grad)
        h = self.client.get(f"/ciclos/{self.c.ano}/escrever/").content.decode()
        self.assertIn('id="doc-revisao"', h)
        self.assertIn("Controle de alterações ligado", h)          # para o setor, sempre ligado
        self.assertIn("rastreioObrigatorio: true", h)
        self.assertIn("js/revisao.js", h)
        self.assertNotIn('id="modo-sugerir"', h)
