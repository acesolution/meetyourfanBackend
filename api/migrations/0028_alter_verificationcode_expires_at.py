# Generated by Django 5.0.4 on 2025-02-11 00:17

import datetime
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0027_alter_verificationcode_expires_at'),
    ]

    operations = [
        migrations.AlterField(
            model_name='verificationcode',
            name='expires_at',
            field=models.DateTimeField(default=datetime.datetime(2025, 2, 11, 0, 27, 54, 722974, tzinfo=datetime.timezone.utc)),
        ),
    ]
