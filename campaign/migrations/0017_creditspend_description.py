# Generated by Django 5.0.4 on 2025-04-29 03:36

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('campaign', '0016_alter_creditspend_spend_type'),
    ]

    operations = [
        migrations.AddField(
            model_name='creditspend',
            name='description',
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
    ]
