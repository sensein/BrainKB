# Generated by Django 3.2.18 on 2024-05-10 18:40

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('Web', '0007_alter_queryendpoint_default_kb'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='queryendpoint',
            name='default_kb',
        ),
        migrations.AddField(
            model_name='knowledgebaseviewermodel',
            name='default_kb',
            field=models.BooleanField(default=False, unique=True),
        ),
    ]
