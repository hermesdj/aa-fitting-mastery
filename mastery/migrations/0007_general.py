from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('mastery', '0006_fittingskillcontrol_is_manual'),
    ]

    operations = [
        migrations.CreateModel(
            name='General',
            fields=[
            ],
            options={
                'managed': False,
                'default_permissions': (),
                'permissions': (
                    ('basic_access', 'Can access the Fitting Mastery app'),
                    ('manage_fittings', 'Can manage fitting skill plans'),
                    ('doctrine_summary', 'Can view doctrine summaries'),
                ),
            },
        ),
    ]

