# Generated by Django 5.0.4 on 2025-04-25 23:10

import datetime
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0052_alter_verificationcode_expires_at'),
    ]

    operations = [
        migrations.AlterField(
            model_name='verificationcode',
            name='expires_at',
            field=models.DateTimeField(default=datetime.datetime(2025, 4, 25, 23, 20, 54, 984831, tzinfo=datetime.timezone.utc)),
        ),
    ]
