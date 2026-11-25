"""{% carimbo 'js/arquivo.js' %}: marca de versão do arquivo estático para o fim da URL (?v=...).

Muda sempre que o arquivo muda (versão do SiRG + data do arquivo), para o navegador e o Cloudflare não servirem a
cópia antiga depois de uma atualização na mesma versão (2.21)."""
from functools import lru_cache

from django import template
from django.conf import settings
from django.contrib.staticfiles import finders

register = template.Library()


@lru_cache(maxsize=256)
def _marca(caminho, versao):
    achado = finders.find(caminho)
    if not achado:
        return versao
    import os
    return f"{versao}-{int(os.path.getmtime(achado))}"


@register.simple_tag
def carimbo(caminho):
    marca = _marca(caminho, settings.SIRG_VERSAO)
    if settings.DEBUG:
        _marca.cache_clear()
    return marca
