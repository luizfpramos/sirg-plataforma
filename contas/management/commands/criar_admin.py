"""Cria (ou promove) o administrador da plataforma pelo terminal — usado pelo instalar.bat."""
import getpass

from django.contrib.auth import get_user_model, password_validation
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from contas.servicos import obter_perfil, registrar


class Command(BaseCommand):
    help = "Cria o usuário administrador da plataforma (também com perfil Master)."

    def add_arguments(self, parser):
        parser.add_argument("--login")
        parser.add_argument("--nome")
        parser.add_argument("--senha", help="Só para automação/testes. Sem isto, a senha é pedida no terminal.")

    def handle(self, *args, **o):
        User = get_user_model()
        login = o.get("login") or input("Login do administrador (ex.: luiz.ramos): ").strip()
        if not login:
            raise CommandError("Informe um login.")
        u = User.objects.filter(username__iexact=login).first()
        if u:
            self.stdout.write(f"O usuário '{u.username}' já existe: ele será promovido a Administrador e Master.")
        else:
            nome = o.get("nome") or input("Nome completo: ").strip()
            senha = o.get("senha")
            while not senha:
                s1 = getpass.getpass("Senha: ")
                s2 = getpass.getpass("Repita a senha: ")
                if s1 != s2:
                    self.stderr.write("As senhas não conferem. Tente de novo.")
                    continue
                try:
                    password_validation.validate_password(s1, User(username=login, first_name=nome))
                except ValidationError as ex:
                    self.stderr.write(" ".join(ex.messages))
                    continue
                senha = s1
            partes = nome.split(" ", 1)
            u = User.objects.create_user(username=login, password=senha, first_name=partes[0],
                                         last_name=partes[1] if len(partes) > 1 else "")
        u.is_staff = True
        u.is_superuser = True
        u.is_active = True
        u.save()
        p = obter_perfil(u)
        p.e_admin = p.e_master = True
        p.troca_senha = False
        p.save()
        registrar("usuario_alterado", None, u, descricao="Administrador criado/promovido pelo terminal")
        self.stdout.write(self.style.SUCCESS(f"Administrador '{u.username}' pronto."))
