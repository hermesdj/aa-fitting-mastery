from django.db import migrations


def _merge_blacklisted_overrides_into_controls(apps, schema_editor):
    """Preserve legacy blacklist rows before dropping the old override table."""
    FittingSkillOverride = apps.get_model("mastery", "FittingSkillOverride")
    FittingSkillControl = apps.get_model("mastery", "FittingSkillControl")

    for override in FittingSkillOverride.objects.filter(is_blacklisted=True).iterator():
        control, _created = FittingSkillControl.objects.get_or_create(
            fitting_id=override.fitting_id,
            skill_type_id=override.skill_type_id,
            defaults={"is_blacklisted": True},
        )
        if not control.is_blacklisted:
            control.is_blacklisted = True
            control.save(update_fields=["is_blacklisted"])


class Migration(migrations.Migration):

    dependencies = [
        ("mastery", "0009_fittingskillsetmap_approval_workflow"),
    ]

    operations = [
        migrations.RunPython(
            _merge_blacklisted_overrides_into_controls,
            reverse_code=migrations.RunPython.noop,
        ),
        migrations.DeleteModel(
            name="FittingSkillOverride",
        ),
    ]

