# Generated by Django 5.0.4 on 2025-01-31 20:40

import datetime
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0015_alter_verificationcode_expires_at'),
    ]

    operations = [
        migrations.AlterField(
            model_name='verificationcode',
            name='expires_at',
            field=models.DateTimeField(default=datetime.datetime(2025, 1, 31, 20, 50, 33, 385154, tzinfo=datetime.timezone.utc)),
        ),
    ]
