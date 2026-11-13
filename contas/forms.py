import re

from django import forms
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm
from django.db.models import Q
from django.utils import timezone

from . import servicos as S
from .models import Instituicao, Setor

User = get_user_model()


class LoginForm(AuthenticationForm):
    error_messages = {
        "invalid_login": "Usuário ou senha incorretos.",
        "inactive": "Este usuário está desativado. Fale com um administrador da plataforma.",
    }

    def clean(self):
        login = (self.cleaned_data.get("username") or "").strip()
        u = User.objects.filter(username__iexact=login).first() if login else None
        if u is not None:
            p = S.obter_perfil(u)
            if p.bloqueado:
                minutos = max(1, int((p.bloqueado_ate - timezone.now()).total_seconds() // 60) + 1)
                raise forms.ValidationError(
                    f"Acesso bloqueado temporariamente por excesso de tentativas. Tente de novo em {minutos} "
                    f"minuto{'s' if minutos > 1 else ''} ou peça a um administrador para desbloquear.",
                    code="bloqueado")
            if u.username != login:   # aceita o login sem diferenciar maiúsculas
                self.cleaned_data["username"] = u.username
        try:
            return super().clean()
        except forms.ValidationError:
            p = S.falha_de_login(login, request=self.request) if login else None
            if p is not None and p.bloqueado:
                raise forms.ValidationError(
                    f"Senha incorreta {settings.SIRG_MAX_TENTATIVAS} vezes seguidas: o acesso foi bloqueado por "
                    f"{settings.SIRG_BLOQUEIO_MINUTOS} minutos. Se esqueceu a senha, peça a um administrador "
                    f"para redefini-la.", code="bloqueado")
            raise


class SetoresField(forms.ModelMultipleChoiceField):
    widget = forms.CheckboxSelectMultiple

    def label_from_instance(self, obj):
        return obj.rotulo + ("" if obj.ativo else " (inativo)")


class UsuarioForm(forms.Form):
    nome = forms.CharField(label="Nome completo", max_length=300)
    login = forms.CharField(label="Usuário (login)", max_length=150,
                            help_text="Letras, números e . _ - @. Ex.: maria.silva")
    email = forms.EmailField(label="E-mail", required=False)
    e_admin = forms.BooleanField(label="Administrador da plataforma", required=False,
                                 help_text="Cria usuários e setores, configura a plataforma e a estrutura do relatório.")
    e_master = forms.BooleanField(label="Master", required=False,
                                  help_text="Edita qualquer parte do relatório e aceita ou recusa as alterações dos setores.")
    e_diagramacao = forms.BooleanField(label="Diagramação", required=False,
                                       help_text="Cria e edita as paletas de cores dos gráficos e baixa o Word e o pacote.")
    setores = SetoresField(label="Setores", queryset=Setor.objects.none(), required=False,
                           help_text="Pode marcar mais de um. Quem não tem setor nem perfil é só Leitor.")
    observacao = forms.CharField(label="Observação", max_length=300, required=False)

    def __init__(self, *args, usuario=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.usuario = usuario
        atuais = []
        if usuario is not None:
            atuais = list(Setor.objects.filter(vinculos__usuario=usuario, vinculos__fim__isnull=True)
                          .values_list("pk", flat=True))
            self.fields["login"].disabled = True
            self.fields["login"].help_text = "O login não pode ser alterado."
        self.fields["setores"].queryset = Setor.objects.filter(
            Q(ativo=True) | Q(pk__in=atuais)).order_by("ordem", "sigla")

    def clean_login(self):
        if self.usuario is not None:
            return self.usuario.username
        v = (self.cleaned_data["login"] or "").strip()
        if not re.fullmatch(r"[\w.@+-]+", v):
            raise forms.ValidationError("Use só letras, números e os sinais . _ - @ (sem espaços).")
        if User.objects.filter(username__iexact=v).exists():
            raise forms.ValidationError("Já existe um usuário com esse login.")
        return v

    def clean(self):
        d = super().clean()
        u = self.usuario
        if u is not None and S.obter_perfil(u).e_admin and not d.get("e_admin") and not u.is_superuser:
            if not S.pode_remover_admin(u):
                self.add_error("e_admin", "Este é o único administrador ativo: a plataforma ficaria sem administrador.")
        return d


class SetorForm(forms.ModelForm):
    class Meta:
        model = Setor
        fields = ["sigla", "nome", "descricao", "ordem", "ativo"]
        widgets = {"descricao": forms.Textarea(attrs={"rows": 3})}
        help_texts = {"ordem": "Posição nas listas (menor aparece primeiro)."}

    def clean_sigla(self):
        v = (self.cleaned_data["sigla"] or "").strip().upper()
        if not re.fullmatch(r"[A-Z0-9ÁÉÍÓÚÂÊÔÃÕÇ_\-/]+", v):
            raise forms.ValidationError("Use letras maiúsculas, números, hífen ou barra, sem espaços.")
        qs = Setor.objects.filter(sigla__iexact=v)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError("Já existe um setor com essa sigla.")
        return v


EXTENSOES_IMAGEM = (".png", ".jpg", ".jpeg")


def _validar_imagem(arq):
    if not arq or not hasattr(arq, "name"):
        return arq
    nome = arq.name.lower()
    if not nome.endswith(EXTENSOES_IMAGEM):
        raise forms.ValidationError("Envie uma imagem PNG ou JPG.")
    if arq.size > 2 * 1024 * 1024:
        raise forms.ValidationError("A imagem deve ter no máximo 2 MB.")
    cabeca = arq.read(8)
    arq.seek(0)
    if not (cabeca.startswith(b"\x89PNG") or cabeca.startswith(b"\xff\xd8")):
        raise forms.ValidationError("O arquivo não parece ser uma imagem PNG ou JPG válida.")
    return arq


class InstituicaoForm(forms.ModelForm):
    class Meta:
        model = Instituicao
        fields = ["nome", "sigla", "cargo_dirigente", "nome_dirigente", "unidade_gestora", "unidade_gestora_sigla",
                  "logo", "faixa_unidade"]

    def clean_logo(self):
        return _validar_imagem(self.cleaned_data.get("logo"))

    def clean_faixa_unidade(self):
        return _validar_imagem(self.cleaned_data.get("faixa_unidade"))
