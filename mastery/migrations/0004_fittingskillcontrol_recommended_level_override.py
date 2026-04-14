from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("mastery", "0003_make_fitting_mastery_override_nullable"),
    ]

    operations = [
        migrations.AddField(
            model_name="fittingskillcontrol",
            name="recommended_level_override",
            field=models.PositiveIntegerField(
                blank=True,
                null=True,
                verbose_name="recommended level override",
            ),
        ),
    ]

