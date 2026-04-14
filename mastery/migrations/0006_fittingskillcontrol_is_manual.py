from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("mastery", "0005_fittingskillsetmap_last_synced_at"),
    ]

    operations = [
        migrations.AddField(
            model_name="fittingskillcontrol",
            name="is_manual",
            field=models.BooleanField(default=False, verbose_name="is manual"),
        ),
    ]

