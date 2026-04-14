from django.db import migrations, models


def set_existing_fitting_mastery_levels_to_inherit(apps, schema_editor):
    FittingSkillsetMap = apps.get_model("mastery", "FittingSkillsetMap")
    FittingSkillsetMap.objects.all().update(mastery_level=None)


class Migration(migrations.Migration):
    dependencies = [
        ("mastery", "0002_doctrineskillsetgroupmap_default_mastery_level_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="fittingskillsetmap",
            name="mastery_level",
            field=models.PositiveIntegerField(blank=True, null=True, verbose_name="mastery level"),
        ),
        migrations.RunPython(
            set_existing_fitting_mastery_levels_to_inherit,
            migrations.RunPython.noop,
        ),
    ]

