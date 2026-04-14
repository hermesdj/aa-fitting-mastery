from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("mastery", "0004_fittingskillcontrol_recommended_level_override"),
    ]

    operations = [
        migrations.AddField(
            model_name="fittingskillsetmap",
            name="last_synced_at",
            field=models.DateTimeField(blank=True, null=True, verbose_name="last synced at"),
        ),
    ]

