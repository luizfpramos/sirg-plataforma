"""Testes da etapa 1: login, perfis, setores, vínculos e auditoria."""
import ipaddress

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from contas import permissoes as P
from contas import servicos as S
from contas.models import EventoAuditoria, Perfil, Setor, VinculoSetor

User = get_user_model()
SENHA = "Senha-forte-2026"


class Base(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("inicializar", verbosity=0)
        call_command("criar_admin", login="admin", nome="Admin Geral", senha=SENHA, verbosity=0)
        cls.admin = User.objects.get(username="admin")
        cls.dirgrad = Setor.objects.get(sigla="DIRGRAD")
        cls.dppg = Setor.objects.get(sigla="DPPG")
        cls.editor, _ = S.criar_usuario(login="maria", nome="Maria Souza", setores=[cls.dirgrad], senha=SENHA)
        cls.master, _ = S.criar_usuario(login="mestre", nome="Ana Master", e_master=True, senha=SENHA)
        cls.leitor, _ = S.criar_usuario(login="leitor", nome="Leo Leitor", senha=SENHA)
        Perfil.objects.update(troca_senha=False)

    def entrar(self, login, senha=SENHA):
        return self.client.post("/entrar/", {"username": login, "password": senha})


class LoginTests(Base):
    def test_exige_login(self):
        r = self.client.get("/")
        self.assertEqual(r.status_code, 302)
        self.assertIn("/entrar/", r["Location"])

    def test_login_ok_registra_auditoria(self):
        r = self.entrar("maria")
        self.assertEqual(r.status_code, 302)
        self.assertTrue(EventoAuditoria.objects.filter(acao="login", ator=self.editor).exists())
        self.assertEqual(self.client.get("/").status_code, 200)

    def test_login_ignora_maiusculas(self):
        self.assertEqual(self.entrar("MARIA").status_code, 302)

    def test_bloqueio_apos_tentativas(self):
        for _ in range(5):
            r = self.entrar("maria", "errada")
        self.assertContains(r, "bloqueado")
        # mesmo com a senha certa continua bloqueado
        r = self.entrar("maria")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "bloqueado temporariamente")
        self.assertTrue(EventoAuditoria.objects.filter(acao="bloqueio", usuario_alvo=self.editor).exists())
        # administrador desbloqueia
        S.desbloquear(self.editor, ator=self.admin)
        self.assertEqual(self.entrar("maria").status_code, 302)

    def test_bloqueio_expira(self):
        p = self.editor.perfil_sirg
        p.bloqueado_ate = timezone.now() - timezone.timedelta(minutes=1)
        p.save()
        self.assertEqual(self.entrar("maria").status_code, 302)

    def test_usuario_inativo_nao_entra(self):
        S.ativar(self.leitor, False, ator=self.admin)
        r = self.entrar("leitor")
        self.assertEqual(r.status_code, 200)

    def test_senha_provisoria_obriga_troca(self):
        u, senha = S.criar_usuario(login="novo", nome="Novo Usuário", setores=[self.dppg], ator=self.admin)
        self.assertEqual(self.entrar("novo", senha).status_code, 302)
        r = self.client.get("/")
        self.assertRedirects(r, "/senha/")
        self.assertEqual(self.client.get("/setores/").status_code, 302)
        r = self.client.post("/senha/", {"old_password": senha, "new_password1": "Minha-senha-nova-9",
                                         "new_password2": "Minha-senha-nova-9"})
        self.assertEqual(r.status_code, 302)
        u.perfil_sirg.refresh_from_db()
        self.assertFalse(u.perfil_sirg.troca_senha)
        self.assertEqual(self.client.get("/").status_code, 200)

    def test_senha_provisoria_tem_formato_forte(self):
        for _ in range(20):
            s = S.gerar_senha_provisoria()
            self.assertEqual(len(s), 14)
            self.assertTrue(any(c.isdigit() for c in s))
            self.assertFalse(set(s) & set("0O1lI"))


class PermissoesTests(Base):
    def test_papeis(self):
        self.assertEqual(P.papeis(self.admin), ["Administrador", "Master"])
        self.assertEqual(P.papeis(self.editor), ["Editor"])
        self.assertEqual(P.papeis(self.master), ["Master"])
        self.assertEqual(P.papeis(self.leitor), ["Leitor"])

    def test_editor_so_edita_o_proprio_setor(self):
        self.assertTrue(P.pode_editar_setor(self.editor, self.dirgrad))
        self.assertFalse(P.pode_editar_setor(self.editor, self.dppg))
        self.assertTrue(P.pode_editar_algum(self.editor, [self.dppg, self.dirgrad]))
        self.assertFalse(P.pode_editar_setor(self.leitor, self.dirgrad))

    def test_master_edita_tudo(self):
        self.assertTrue(P.pode_editar_setor(self.master, self.dppg))
        self.assertTrue(P.pode_editar_setor(self.master, None))

    def test_admin_sem_master_nao_edita_conteudo(self):
        u, _ = S.criar_usuario(login="soadmin", nome="Só Admin", e_admin=True, senha=SENHA)
        self.assertTrue(P.e_admin(u))
        self.assertFalse(P.pode_editar_setor(u, self.dppg))

    def test_setor_inativo_nao_edita(self):
        self.dirgrad.ativo = False
        self.dirgrad.save()
        self.assertFalse(P.pode_editar_setor(self.editor, self.dirgrad))
        self.assertEqual(P.papeis(self.editor), ["Leitor"])

    def test_usuario_em_dois_setores(self):
        S.definir_setores(self.editor, [self.dirgrad, self.dppg], ator=self.admin)
        self.assertTrue(P.pode_editar_setor(self.editor, self.dppg))
        self.assertTrue(P.pode_editar_setor(self.editor, self.dirgrad))

    def test_areas_de_admin_bloqueadas(self):
        for login in ("maria", "mestre", "leitor"):
            self.client.logout()
            self.entrar(login)
            for url in ("/usuarios/", "/usuarios/novo/", f"/usuarios/{self.editor.pk}/", "/instituicao/",
                        "/auditoria/", "/setores/novo/"):
                self.assertEqual(self.client.get(url).status_code, 403, f"{login} {url}")
            # consulta de setores é livre
            self.assertEqual(self.client.get("/setores/").status_code, 200)
            self.assertEqual(self.client.get(f"/setores/{self.dirgrad.pk}/").status_code, 200)

    def test_nao_admin_nao_altera_setor_por_post(self):
        self.entrar("maria")
        self.client.post(f"/setores/{self.dirgrad.pk}/", {"sigla": "XX", "nome": "Hack", "ordem": 1, "ativo": "on"})
        self.dirgrad.refresh_from_db()
        self.assertEqual(self.dirgrad.sigla, "DIRGRAD")


class VinculosTests(Base):
    def test_mudar_de_setor_encerra_vinculo_e_mantem_historico(self):
        inc, enc = S.definir_setores(self.editor, [self.dppg], ator=self.admin)
        self.assertEqual([s.sigla for s in inc], ["DPPG"])
        self.assertEqual([s.sigla for s in enc], ["DIRGRAD"])
        antigo = VinculoSetor.objects.get(usuario=self.editor, setor=self.dirgrad)
        self.assertIsNotNone(antigo.fim)
        self.assertEqual(antigo.encerrado_por, self.admin)
        self.assertFalse(P.pode_editar_setor(self.editor, self.dirgrad))
        self.assertTrue(P.pode_editar_setor(self.editor, self.dppg))
        # voltar ao setor cria um vínculo NOVO (o antigo continua no histórico)
        S.definir_setores(self.editor, [self.dirgrad], ator=self.admin)
        self.assertEqual(VinculoSetor.objects.filter(usuario=self.editor, setor=self.dirgrad).count(), 2)
        self.assertEqual(EventoAuditoria.objects.filter(usuario_alvo=self.editor, acao="setor_vinculado").count(), 3)

    def test_desativar_encerra_vinculos(self):
        S.ativar(self.editor, False, ator=self.admin)
        self.assertFalse(VinculoSetor.objects.filter(usuario=self.editor, fim__isnull=True).exists())
        self.assertFalse(P.e_editor(self.editor))

    def test_tela_editar_usuario_troca_setor(self):
        self.entrar("admin")
        r = self.client.post(f"/usuarios/{self.editor.pk}/", {
            "nome": "Maria Souza", "email": "maria@x.br", "setores": [self.dppg.pk, self.dirgrad.pk]})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(set(P.setores_ativos(self.editor).values_list("sigla", flat=True)), {"DPPG", "DIRGRAD"})
        r = self.client.get(f"/usuarios/{self.editor.pk}/")
        self.assertContains(r, "Histórico de setores")


class AdminTelasTests(Base):
    def test_criar_usuario_pela_tela(self):
        self.entrar("admin")
        r = self.client.post("/usuarios/novo/", {"nome": "José da Silva", "login": "jose.silva", "email": "",
                                                 "setores": [self.dppg.pk], "e_master": "on"})
        self.assertEqual(r.status_code, 200)
        senha = r.context["senha"]
        self.assertContains(r, senha)
        u = User.objects.get(username="jose.silva")
        self.assertEqual(u.first_name, "José")
        self.assertEqual(u.last_name, "da Silva")
        self.assertTrue(u.perfil_sirg.e_master)
        self.assertTrue(u.perfil_sirg.troca_senha)
        self.assertTrue(u.check_password(senha))
        self.assertTrue(P.pode_editar_setor(u, self.dppg))

    def test_login_duplicado_recusado(self):
        self.entrar("admin")
        r = self.client.post("/usuarios/novo/", {"nome": "Outra Maria", "login": "Maria"})
        self.assertContains(r, "Já existe um usuário com esse login")

    def test_login_invalido_recusado(self):
        self.entrar("admin")
        r = self.client.post("/usuarios/novo/", {"nome": "Fulano", "login": "com espaço"})
        self.assertContains(r, "sem espaços")

    def test_redefinir_senha(self):
        self.entrar("admin")
        r = self.client.post(f"/usuarios/{self.editor.pk}/senha/")
        senha = r.context["senha"]
        self.editor.refresh_from_db()
        self.assertTrue(self.editor.check_password(senha))
        self.assertTrue(self.editor.perfil_sirg.troca_senha)

    def test_nao_fica_sem_admin(self):
        self.entrar("admin")
        # o admin não pode se desativar
        self.client.post(f"/usuarios/{self.admin.pk}/desativar/")
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_active)
        # outro admin comum: não pode tirar o perfil do único admin não-superusuário restante
        u, _ = S.criar_usuario(login="adm2", nome="Adm Dois", e_admin=True, senha=SENHA)
        self.admin.is_superuser = False
        self.admin.save()
        Perfil.objects.filter(usuario=self.admin).update(e_admin=False)
        self.assertFalse(S.pode_remover_admin(u))

    def test_setores_crud(self):
        self.entrar("admin")
        r = self.client.post("/setores/novo/", {"sigla": "prograd", "nome": "Pró-Reitoria de Graduação",
                                                "ordem": 5, "ativo": "on", "descricao": ""})
        s = Setor.objects.get(sigla="PROGRAD")
        self.assertRedirects(r, f"/setores/{s.pk}/")
        # renomear DIRGRAD mantém os vínculos
        self.client.post(f"/setores/{self.dirgrad.pk}/", {"sigla": "DIRGRAD", "nome": "Pró-Reitoria de Graduação",
                                                          "ordem": 30, "ativo": "on", "descricao": ""})
        self.dirgrad.refresh_from_db()
        self.assertEqual(self.dirgrad.nome, "Pró-Reitoria de Graduação")
        self.assertTrue(P.pode_editar_setor(self.editor, self.dirgrad))
        r = self.client.post("/setores/novo/", {"sigla": "DPPG", "nome": "Duplicado", "ordem": 1, "ativo": "on"})
        self.assertContains(r, "Já existe um setor")

    def test_paginas_admin_abrem(self):
        self.entrar("admin")
        for url in ("/", "/usuarios/", "/usuarios/?situacao=todos&setor=sem", "/usuarios/novo/",
                    f"/usuarios/{self.editor.pk}/", "/setores/", "/setores/?inativos=1", "/setores/novo/",
                    f"/setores/{self.dirgrad.pk}/", "/instituicao/", "/auditoria/", "/auditoria/?acao=login",
                    "/minha-conta/", "/senha/", "/identidade/logo/", "/identidade/faixa/"):
            self.assertEqual(self.client.get(url).status_code, 200, url)

    def test_identidade_publica(self):
        self.assertEqual(self.client.get("/identidade/logo/").status_code, 200)
        self.assertEqual(self.client.get("/identidade/xyz/").status_code, 404)

    def test_instituicao_recusa_svg(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        self.entrar("admin")
        svg = SimpleUploadedFile("x.svg", b"<svg onload='alert(1)'/>", content_type="image/svg+xml")
        r = self.client.post("/instituicao/", {"nome": "Universidade", "sigla": "U", "cargo_dirigente": "Reitora",
                                               "unidade_gestora": "DGDI", "unidade_gestora_sigla": "DGDI",
                                               "logo": svg})
        self.assertContains(r, "PNG ou JPG")


class MiddlewareTests(Base):
    @override_settings(SIRG_REDES_PERMITIDAS=[ipaddress.ip_network("200.17.0.0/16")])
    def test_rede_nao_permitida(self):
        r = self.client.get("/entrar/", REMOTE_ADDR="8.8.8.8")
        self.assertEqual(r.status_code, 403)
        r = self.client.get("/entrar/", REMOTE_ADDR="200.17.146.10")
        self.assertEqual(r.status_code, 200)
        r = self.client.get("/entrar/", REMOTE_ADDR="127.0.0.1")
        self.assertEqual(r.status_code, 200)


class BackupTests(TestCase):
    def test_backup_sqlite(self):
        import tempfile
        from pathlib import Path
        from django.conf import settings
        if settings.DATABASES["default"]["ENGINE"] != "django.db.backends.sqlite3":
            self.skipTest("só SQLite")
        with tempfile.TemporaryDirectory() as d:
            # o banco de teste é em memória; o comando copia o arquivo configurado
            call_command("backup", destino=d, manter=2, verbosity=0)
            call_command("backup", destino=d, manter=2, verbosity=0)
            self.assertGreaterEqual(len(list(Path(d).glob("sirg_*"))), 1)


class ContagemTests(Base):
    def test_sem_setor_conta_quem_nao_tem_vinculo(self):
        self.entrar("admin")
        r = self.client.get("/")
        # admin, mestre e leitor não têm setor
        self.assertEqual(r.context["n_sem_setor"], 3)
        r = self.client.get("/usuarios/?setor=sem")
        self.assertEqual({u.username for u, _ in r.context["linhas"]}, {"admin", "mestre", "leitor"})

    def test_checkbox_dos_setores_marcado(self):
        self.entrar("admin")
        r = self.client.get(f"/usuarios/{self.editor.pk}/")
        self.assertContains(r, f'value="{self.dirgrad.pk}" id="id_setores_', html=False)
        self.assertRegex(r.content.decode(), rf'value="{self.dirgrad.pk}" id="id_setores_[0-9]+" checked')


class AjudaTests(TestCase):
    def test_manual_para_qualquer_usuario(self):
        from contas import servicos as CS2
        call_command("inicializar", verbosity=0)
        CS2.criar_usuario(login="leitor", nome="Lia Leitora", senha="Senha-forte-2026")
        Perfil.objects.update(troca_senha=False)
        self.assertEqual(self.client.get("/ajuda/").status_code, 302)
        self.client.post("/entrar/", {"username": "leitor", "password": "Senha-forte-2026"})
        r = self.client.get("/ajuda/")
        self.assertContains(r, "Inserir número")
        self.assertContains(r, 'href="#o-relatorio-uma-tela-so"')
        self.assertContains(r, "<table>")
