"""Tela do administrador para preencher os atributos dos blocos de texto: setor responsável, conteúdo esperado e
tamanho (mínimo e máximo de caracteres). Uma tabela com um formulário por bloco, filtrada por seção ou página."""
from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.forms import modelformset_factory
from django.shortcuts import get_object_or_404, redirect, render

from contas import permissoes as P
from contas.models import Setor

from . import permissoes as RP
from .html_seguro import texto_puro
from .models import Bloco, Ciclo

CAMPOS = ["setor", "descricao", "min_caracteres", "max_caracteres"]


class BlocoAtributosForm(forms.ModelForm):
    class Meta:
        model = Bloco
        fields = CAMPOS
        widgets = {"descricao": forms.Textarea(attrs={"rows": 2, "class": "form-control form-control-sm"}),
                   "min_caracteres": forms.NumberInput(attrs={"class": "form-control form-control-sm", "min": 0}),
                   "max_caracteres": forms.NumberInput(attrs={"class": "form-control form-control-sm", "min": 0})}

    def __init__(self, *args, **kw):
        super().__init__(*args, **kw)
        self.fields["setor"].queryset = Setor.objects.filter(ativo=True).order_by("ordem", "sigla")
        self.fields["setor"].empty_label = "(o da seção)"
        self.fields["setor"].widget.attrs["class"] = "form-select form-select-sm"

    def clean(self):
        d = super().clean()
        mn, mx = d.get("min_caracteres"), d.get("max_caracteres")
        if mn and mx and mn > mx:
            raise forms.ValidationError("O mínimo de caracteres não pode ser maior que o máximo.")
        return d


def pode_definir_atributos(user):
    return RP.pode_estruturar(user) or P.e_master(user)


@login_required
def blocos_atributos(request, ano):
    c = get_object_or_404(Ciclo, ano=ano)
    if not pode_definir_atributos(request.user):
        raise PermissionDenied("Só o administrador e o Editor-chefe definem os atributos dos blocos.")
    if c.situacao == Ciclo.ENCERRADO:
        raise PermissionDenied("O ciclo está encerrado.")
    secoes = list(c.secoes.order_by("ordem", "id"))
    chave = request.GET.get("secao", "")
    numero = request.GET.get("pagina", "")
    if not chave and not numero.isdigit():
        # o relatório tem mais de mil trechos: a tela sempre abre filtrada (na primeira página do RG)
        primeira = c.paginas.order_by("numero").first()
        if primeira:
            return redirect(f"{request.path}?pagina={primeira.numero}")
        if secoes:
            return redirect(f"{request.path}?secao={secoes[0].chave}")
    numeros = list(c.paginas.order_by("numero").values_list("numero", flat=True))
    anterior = proxima = None
    if numero.isdigit() and int(numero) in numeros:
        i = numeros.index(int(numero))
        anterior = numeros[i - 1] if i > 0 else None
        proxima = numeros[i + 1] if i + 1 < len(numeros) else None
    qs = Bloco.objects.filter(secao__ciclo=c, tipo=Bloco.TEXTO).select_related("secao", "pagina", "setor")
    if chave:
        qs = qs.filter(secao__chave=chave)
    if numero.isdigit():
        qs = qs.filter(pagina__numero=int(numero))
    qs = qs.order_by("pagina__numero", "secao__ordem", "ordem", "id")
    Formset = modelformset_factory(Bloco, form=BlocoAtributosForm, extra=0)
    if request.method == "POST":
        fs = Formset(request.POST, queryset=qs)
        if fs.is_valid():
            n = 0
            for f in fs.forms:
                if f.has_changed():
                    b = f.save(commit=False)
                    # só os atributos: o texto e a data de alteração (usada para detectar conflito) ficam como estão
                    b.save(update_fields=CAMPOS)
                    n += 1
            messages.success(request, f"{n} bloco{'s' if n != 1 else ''} atualizado{'s' if n != 1 else ''}."
                             if n else "Nada mudou.")
            return redirect(request.get_full_path())
        messages.error(request, "Corrija os campos destacados.")
    else:
        fs = Formset(queryset=qs)
    linhas = [{"f": f, "b": f.instance, "previa": texto_puro(f.instance.conteudo)[:110]} for f in fs.forms]
    return render(request, "relatorio/blocos_atributos.html", {
        "ciclo": c, "fs": fs, "linhas": linhas, "secoes": secoes, "chave": chave, "numero": numero,
        "anterior": anterior, "proxima": proxima})
