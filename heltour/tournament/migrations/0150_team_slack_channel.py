# -*- coding: utf-8 -*-
# Generated by Django 1.9.7 on 2017-03-08 22:41
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tournament', '0149_auto_20170307_1700'),
    ]

    operations = [
        migrations.AddField(
            model_name='team',
            name='slack_channel',
            field=models.CharField(blank=True, max_length=255),
        ),
    ]
