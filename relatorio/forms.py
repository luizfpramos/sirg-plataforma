import re
import unicodedata

from django import forms
from django.forms import inlineformset_factory

from contas.models import Setor

from .calculo import ErroFormula, analisar
from .models import Ciclo, Coluna, Linha, Quadro, Regra, Secao


def gerar_chave(texto, limite=40):
    t = unicodedata.normalize("NFD", (texto or "").lower())
    t = "".join(ch for ch in t if unicodedata.category(ch) != "Mn")
    t = re.sub(r"[^a-z0-9]+", "_", t).strip("_")
    if not t or not t[0].isalpha():
        t = "x_" + t
    return t[:limite].rstrip("_")


class CicloNovoForm(forms.Form):
    ano = forms.IntegerField(label="Ano-base", min_value=2000, max_value=2100)
    titulo = forms.CharField(label="Título", max_length=200, required=False,
                             help_text="Vazio = “Relatório de Gestão <ano>”.")
    origem = forms.ModelChoiceField(label="Copiar estrutura e séries de", queryset=Ciclo.objects.all(),
                                    required=False, empty_label="(começar em branco)")
    anos_serie = forms.IntegerField(label="Anos na série histórica", min_value=1, max_value=10, initial=5)
    prazo = forms.DateField(label="Prazo da coleta", required=False, widget=forms.DateInput(attrs={"type": "date"}))

    def clean_ano(self):
        ano = self.cleaned_data["ano"]
        if Ciclo.objects.filter(ano=ano).exists():
            raise forms.ValidationError("Já existe um ciclo para este ano.")
        return ano

    def clean(self):
        d = super().clean()
        o, ano = d.get("origem"), d.get("ano")
        if o and ano and ano <= o.ano:
            self.add_error("origem", "O ciclo de origem precisa ser de um ano anterior.")
        return d


class CicloForm(forms.ModelForm):
    class Meta:
        model = Ciclo
        fields = ["titulo", "situacao", "prazo", "observacao"]
        widgets = {"prazo": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
                   "observacao": forms.Textarea(attrs={"rows": 3})}


class SetoresMultiplos(forms.ModelMultipleChoiceField):
    widget = forms.CheckboxSelectMultiple

    def label_from_instance(self, obj):
        return f"{obj.sigla} — {obj.nome}"


class SecaoForm(forms.ModelForm):
    setores = SetoresMultiplos(queryset=Setor.objects.filter(ativo=True), required=False,
                               label="Setores responsáveis")

    class Meta:
        model = Secao
        fields = ["titulo", "pai", "ordem", "chave", "setores", "orientacao"]
        widgets = {"orientacao": forms.Textarea(attrs={"rows": 4})}
        labels = {"orientacao": "O que escrever aqui"}
        help_texts = {"orientacao": "Uma ou duas frases que aparecem para o setor no alto da seção, no documento."}
        help_texts = {"chave": "Identificador interno. Vazio = gerado a partir do título.",
                      "ordem": "Posição dentro do capítulo."}

    def __init__(self, *args, ciclo=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.ciclo = ciclo
        self.fields["chave"].required = False
        qs = Secao.objects.filter(ciclo=ciclo, pai__isnull=True)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        self.fields["pai"].queryset = qs
        self.fields["pai"].empty_label = "(é um capítulo)"
        self.fields["pai"].label = "Capítulo"
        if self.instance.pk and self.instance.filhas.exists():
            self.fields["pai"].disabled = True
            self.fields["pai"].help_text = "Este capítulo tem seções: não pode virar seção de outro capítulo."

    def clean_chave(self):
        ch = self.cleaned_data.get("chave") or gerar_chave(self.cleaned_data.get("titulo") or self.data.get("titulo"))
        qs = Secao.objects.filter(ciclo=self.ciclo, chave=ch)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError("Já existe uma seção com esta chave neste ciclo.")
        return ch


class QuadroForm(forms.ModelForm):
    class Meta:
        model = Quadro
        fields = ["titulo", "chave", "secao", "ordem", "setor", "descricao", "fonte", "tipo_valor", "casas_decimais",
                  "modo_colunas", "anos_exibidos", "linha_total", "coluna_total", "rotulo_total", "obrigatorio",
                  "variacao_alerta"]
        widgets = {"descricao": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, ciclo=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.ciclo = ciclo
        self.fields["chave"].required = False
        self.fields["chave"].help_text = "Usada nas fórmulas de outros quadros. Vazio = gerada a partir do título."
        self.fields["secao"].queryset = Secao.objects.filter(ciclo=ciclo).select_related("pai")
        self.fields["secao"].label_from_instance = lambda s: (f"{s.pai.titulo} › {s.titulo}" if s.pai else s.titulo)
        self.fields["setor"].queryset = Setor.objects.filter(ativo=True)
        self.fields["setor"].empty_label = "(os setores da seção)"
        if self.instance.pk:
            self.fields["modo_colunas"].disabled = True
            self.fields["modo_colunas"].help_text = "O tipo de coluna não muda depois de criado o quadro."

    def clean_chave(self):
        ch = self.cleaned_data.get("chave") or gerar_chave(self.cleaned_data.get("titulo") or self.data.get("titulo"))
        qs = Quadro.objects.filter(ciclo=self.ciclo, chave=ch)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError("Já existe um quadro com esta chave neste ciclo.")
        return ch


class LinhaForm(forms.ModelForm):
    class Meta:
        model = Linha
        fields = ["ordem", "rotulo", "chave", "formula", "tipo_valor", "minimo", "maximo", "soma_no_total"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["chave"].required = False
        self.fields["ordem"].required = False
        if not self.instance.pk:
            self.initial.setdefault("ordem", None)
        for campo in ("minimo", "maximo"):
            v = self.initial.get(campo)
            if v is not None:
                v = v.normalize()
                self.initial[campo] = format(v, "f")

    def clean_ordem(self):
        return self.cleaned_data.get("ordem") or 0

    def clean_formula(self):
        f = (self.cleaned_data.get("formula") or "").strip()
        if f:
            try:
                analisar(f)
            except ErroFormula as ex:
                raise forms.ValidationError(str(ex))
        return f

    def clean(self):
        d = super().clean()
        if d.get("rotulo") and not d.get("chave"):
            d["chave"] = gerar_chave(d["rotulo"])
            self.instance.chave = d["chave"]
        return d


class BaseLinhas(forms.BaseInlineFormSet):
    def clean(self):
        super().clean()
        vistas = set()
        for f in self.forms:
            if not hasattr(f, "cleaned_data") or f.cleaned_data.get("DELETE") or not f.cleaned_data.get("rotulo"):
                continue
            ch = f.cleaned_data.get("chave")
            if ch == "total":
                f.add_error("chave", "“total” é reservado para a linha de total.")
            if ch in vistas:
                f.add_error("chave", "Chave repetida neste quadro.")
            vistas.add(ch)


LinhasFormSet = inlineformset_factory(Quadro, Linha, form=LinhaForm, formset=BaseLinhas, extra=2, can_delete=True)


class ColunaForm(forms.ModelForm):
    class Meta:
        model = Coluna
        fields = ["ordem", "rotulo", "chave", "travada"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["chave"].required = False
        self.fields["ordem"].required = False

    def clean_ordem(self):
        return self.cleaned_data.get("ordem") or 0

    def clean(self):
        d = super().clean()
        if d.get("rotulo") and not d.get("chave"):
            d["chave"] = gerar_chave(d["rotulo"])
            self.instance.chave = d["chave"]
        return d


ColunasFormSet = inlineformset_factory(Quadro, Coluna, form=ColunaForm, extra=1, can_delete=True)


class RegraForm(forms.ModelForm):
    class Meta:
        model = Regra
        fields = ["descricao", "esquerda", "operador", "direita", "tolerancia", "escopo", "severidade", "ativa"]

    def clean_esquerda(self):
        return _expr(self.cleaned_data.get("esquerda"))

    def clean_direita(self):
        return _expr(self.cleaned_data.get("direita"))


def _expr(v):
    v = (v or "").strip()
    if v:
        try:
            analisar(v)
        except ErroFormula as ex:
            raise forms.ValidationError(str(ex))
    return v


RegrasFormSet = inlineformset_factory(Quadro, Regra, form=RegraForm, extra=1, can_delete=True)
