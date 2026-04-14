from django import template
from django.utils.safestring import mark_safe

register = template.Library()

MAX_SKILL_LEVEL = 5


def _render_skill_pip(is_active: bool) -> str:
    if is_active:
        style = "display:inline-block;width:10px;height:10px;border-radius:2px;background:#3d8bfd;border:1px solid #3d8bfd;"
    else:
        style = "display:inline-block;width:10px;height:10px;border-radius:2px;background:transparent;border:1px solid #6c757d;opacity:.7;"

    return f"<span style=\"{style}\"></span>"

@register.filter
def skill_render(value):
    try:
        level = int(value)
    except (TypeError, ValueError):
        level = 0

    level = max(0, min(MAX_SKILL_LEVEL, level))

    pips = []
    for index in range(MAX_SKILL_LEVEL):
        pips.append(_render_skill_pip(index < level))

    html = (
        "<span style=\"display:inline-flex;gap:3px;vertical-align:middle;\" "
        f"title=\"Skill level {level}/{MAX_SKILL_LEVEL}\">{''.join(pips)}</span>"
    )
    return mark_safe(html)
