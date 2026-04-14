from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("mastery", "0007_general"),
    ]

    operations = [
        migrations.CreateModel(
            name="SummaryAudienceGroup",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=120, unique=True)),
                ("description", models.CharField(blank=True, max_length=255)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "ordering": ["name"],
            },
        ),
        migrations.CreateModel(
            name="SummaryAudienceEntity",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("entity_type", models.CharField(choices=[("corporation", "Corporation"), ("alliance", "Alliance")], max_length=16)),
                ("entity_id", models.PositiveIntegerField()),
                ("label", models.CharField(blank=True, max_length=120)),
                ("group", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="entries", to="mastery.summaryaudiencegroup")),
            ],
            options={
                "ordering": ["entity_type", "entity_id"],
                "indexes": [models.Index(fields=["entity_type", "entity_id"], name="mastery_sum_entity__266254_idx")],
                "unique_together": {("group", "entity_type", "entity_id")},
            },
        ),
        migrations.AlterModelOptions(
            name="general",
            options={
                "default_permissions": (),
                "managed": False,
                "permissions": (
                    ("basic_access", "Can access the Fitting Mastery app"),
                    ("manage_fittings", "Can manage fitting skill plans"),
                    ("doctrine_summary", "Can view doctrine summaries"),
                    ("manage_summary_groups", "Can manage doctrine summary groups"),
                ),
            },
        ),
    ]


