# Generated by Django 5.0.4 on 2025-01-31 21:04

import datetime
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0016_alter_verificationcode_expires_at'),
    ]

    operations = [
        migrations.AlterField(
            model_name='verificationcode',
            name='expires_at',
            field=models.DateTimeField(default=datetime.datetime(2025, 1, 31, 21, 14, 36, 99937, tzinfo=datetime.timezone.utc)),
        ),
    ]
