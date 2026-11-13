"""Identidade visual UFCIMG (v2.5): a paleta "ufcimg" (azul e verde-água da marca) passa a ser a padrão.
Instalações que estavam com a padrão anterior ("rg") passam para a nova; o Master pode voltar em
"Cores dos gráficos"."""
from django.db import migrations, models


def para_ufcimg(apps, schema_editor):
    apps.get_model("contas", "Instituicao").objects.filter(paleta_graficos="rg").update(paleta_graficos="ufcimg")


def volta(apps, schema_editor):
    pass


CAMPO = dict(default="ufcimg", help_text="Paleta usada em todos os gráficos (tela, Word e diagramação).",
             max_length=20, verbose_name="cores dos gráficos")


class Migration(migrations.Migration):
    dependencies = [("contas", "0002_ufcimg_paleta")]
    operations = [
        migrations.AlterField(model_name="instituicao", name="paleta_graficos", field=models.CharField(**CAMPO)),
        migrations.AlterField(model_name="historicalinstituicao", name="paleta_graficos", field=models.CharField(**CAMPO)),
        migrations.RunPython(para_ufcimg, volta),
    ]
