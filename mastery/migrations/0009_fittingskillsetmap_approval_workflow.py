from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("mastery", "0008_summary_audience_groups"),
    ]

    operations = [
        migrations.AddField(
            model_name="fittingskillsetmap",
            name="approved_at",
            field=models.DateTimeField(blank=True, null=True, verbose_name="approved at"),
        ),
        migrations.AddField(
            model_name="fittingskillsetmap",
            name="approved_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="approved_mastery_fitting_maps",
                to=settings.AUTH_USER_MODEL,
                verbose_name="approved by",
            ),
        ),
        migrations.AddField(
            model_name="fittingskillsetmap",
            name="modified_at",
            field=models.DateTimeField(blank=True, null=True, verbose_name="modified at"),
        ),
        migrations.AddField(
            model_name="fittingskillsetmap",
            name="modified_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="modified_mastery_fitting_maps",
                to=settings.AUTH_USER_MODEL,
                verbose_name="modified by",
            ),
        ),
        migrations.AddField(
            model_name="fittingskillsetmap",
            name="status",
            field=models.CharField(
                choices=[
                    ("in_progress", "In progress"),
                    ("not_approved", "Not approved"),
                    ("approved", "Approved"),
                ],
                default="not_approved",
                max_length=24,
                verbose_name="approval status",
            ),
        ),
    ]

