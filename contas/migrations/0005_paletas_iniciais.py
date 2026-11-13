from django.db import migrations

# as paletas que vinham escritas no código passam para o banco, onde podem ser editadas
INICIAIS = [
    ("rg", "Institucional (RG 2025)", "As cores do Relatório de Gestão publicado: azul-marinho e laranja, com verde, amarelo e rosa.",
     ["#17375E", "#F5A23C", "#8DBB89", "#F7CE1E", "#EE93BF", "#E4572E", "#4BB4C4", "#9B7BC4"]),
    ("ufcimg", "UFCIMG (azul e verde-água)", "As cores da marca UFCIMG (azul e verde-água), com laranja, roxo e cores de apoio. Conferida para daltonismo.",
     ["#285C98", "#2A9C8E", "#E0802A", "#8C6BB8", "#C9A227", "#C2457F", "#5E9E4A", "#A9473B"]),
    ("acessivel", "Acessível (daltonismo)", "Cores fortes e bem separadas, fáceis de distinguir também por quem tem daltonismo.",
     ["#2971C6", "#E18528", "#2C965D", "#C04688", "#17BAC8", "#A43B38", "#C0AC2E", "#7F5BB6"]),
    ("sobria", "Sóbria (azuis e terrosos)", "Tons mais discretos, para um relatório de aparência formal.",
     ["#215D96", "#D18E46", "#0099A0", "#7C61A8", "#57AFE0", "#448C56", "#984649", "#A2933B"]),
]


def criar(apps, schema_editor):
    Paleta = apps.get_model("contas", "Paleta")
    for i, (chave, nome, desc, cores) in enumerate(INICIAIS, start=1):
        Paleta.objects.get_or_create(chave=chave, defaults={"nome": nome, "descricao": desc, "cores": cores,
                                                            "sistema": True, "ordem": i * 10})


class Migration(migrations.Migration):
    dependencies = [("contas", "0004_historicalperfil_e_diagramacao_perfil_e_diagramacao_and_more")]
    operations = [migrations.RunPython(criar, migrations.RunPython.noop)]
