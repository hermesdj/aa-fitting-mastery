"""Add priority field to DoctrineSkillSetGroupMap and FittingSkillsetMap."""
from django.db import migrations, models
import django.core.validators


class Migration(migrations.Migration):

    dependencies = [
        ('mastery', '0010_remove_fittingskilloverride'),
    ]

    operations = [
        migrations.AddField(
            model_name='doctrineskillsetgroupmap',
            name='priority',
            field=models.PositiveSmallIntegerField(
                default=0,
                db_index=True,
                help_text='Doctrine training priority from 0 (default, no highlight) to 10 (highest).',
                validators=[django.core.validators.MinValueValidator(0), django.core.validators.MaxValueValidator(10)],
                verbose_name='priority',
            ),
        ),
        migrations.AddField(
            model_name='fittingskillsetmap',
            name='priority',
            field=models.PositiveSmallIntegerField(
                default=0,
                help_text='Fitting training priority from 0 (default, no highlight) to 10 (highest).',
                validators=[django.core.validators.MinValueValidator(0), django.core.validators.MaxValueValidator(10)],
                verbose_name='priority',
            ),
        ),
    ]

