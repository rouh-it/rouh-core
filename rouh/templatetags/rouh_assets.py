"""``{% asset "app.js" %}``: a front-end file's hashed address, in a template.

The page names its files by their plain names and this turns each into the
address it is served at, ``/a/<hash>/app.js``, the hash being that file's own
content's (`rouh/web/assets.py` says why). ``{% build %}`` is the build as a
whole, which the page compares with the server's on every connect.
"""
from django import template

from django.utils.safestring import mark_safe

from rouh.web.assets import ASSETS, address, import_map, module_addresses

register = template.Library()


@register.simple_tag
def asset(name: str) -> str:
    return address(name)


@register.simple_tag
def build() -> str:
    return ASSETS


@register.simple_tag
def importmap() -> str:
    """The page's import map: every module under rouh/static/app/ by the name
    the others import it by, ``app/socket.js``, to its hashed address."""
    return mark_safe(import_map())


@register.simple_tag
def modulepreload() -> str:
    """A ``<link rel="modulepreload">`` for every module, so the browser fetches
    them all at once rather than finding each one only when the module before
    it has arrived, a round trip at a time."""
    return mark_safe("\n".join(f'<link rel="modulepreload" href="{url}">'
                                for url in module_addresses()))
