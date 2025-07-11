# Generated by Django 5.0.4 on 2025-02-28 10:37

import datetime
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0042_alter_verificationcode_expires_at_reportgenericissue'),
    ]

    operations = [
        migrations.AlterField(
            model_name='verificationcode',
            name='expires_at',
            field=models.DateTimeField(default=datetime.datetime(2025, 2, 28, 10, 47, 48, 678775, tzinfo=datetime.timezone.utc)),
        ),
        migrations.CreateModel(
            name='SocialMediaLink',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('platform', models.CharField(help_text='Name of the social media platform (e.g., Instagram, TikTok, etc.).', max_length=50)),
                ('url', models.URLField(help_text='URL for the social media profile.')),
                ('created_at', models.DateTimeField(auto_now_add=True, help_text='The date and time when this link was created.')),
                ('updated_at', models.DateTimeField(auto_now=True, help_text='The date and time when this link was last updated.')),
                ('user', models.ForeignKey(help_text='The user who owns this social media link.', on_delete=django.db.models.deletion.CASCADE, related_name='social_links', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'Social Media Link',
                'verbose_name_plural': 'Social Media Links',
                'ordering': ['-created_at'],
            },
        ),
    ]
