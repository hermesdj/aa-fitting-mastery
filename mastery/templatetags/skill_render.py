"""Template tags and filters for rendering skill progress data."""
from django import template
from django.utils.safestring import mark_safe

register = template.Library()

MAX_SKILL_LEVEL = 5


def _render_skill_pip(is_active: bool) -> str:
    """Render a single square pip for a skill-level indicator."""
    active_style = (
        "display:inline-block;width:10px;height:10px;"
        "border-radius:2px;background:#3d8bfd;border:1px solid #3d8bfd;"
    )
    inactive_style = (
        "display:inline-block;width:10px;height:10px;"
        "border-radius:2px;background:transparent;border:1px solid #6c757d;opacity:.7;"
    )
    style = active_style if is_active else inactive_style
    return f'<span style="{style}"></span>'

@register.filter
def skill_render(value):
    """Skill render."""
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


@register.filter
def group_has_active_skills(skills):
    """Return True when at least one skill row is not blacklisted."""
    if not skills:
        return False
    for skill in skills:
        if not skill.get("is_blacklisted"):
            return True
    return False


@register.filter
def group_has_blacklisted_skills(skills):
    """Return True when at least one skill row is blacklisted."""
    if not skills:
        return False
    for skill in skills:
        if skill.get("is_blacklisted"):
            return True
    return False
