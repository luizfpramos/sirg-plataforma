from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("relatorio", "0016_secao_pagina_inicio"),
    ]

    operations = [
        migrations.AddField(
            model_name="pagina",
            name="ajustes_fundo",
            field=models.JSONField(blank=True, default=list, help_text='Áreas apagadas ou com o texto do PDF mantido no fundo, em pontos: [{"tipo": "apagar" ou "manter", "x", "y", "w", "h"}].', verbose_name="ajustes no fundo"),
        ),
    ]
