# Generated by Django 4.2.11 on 2024-05-02 13:32

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("Web", "0006_auto_20240502_0205"),
    ]

    operations = [
        migrations.RenameField(
            model_name="jwtuser",
            old_name="hashed_password",
            new_name="password",
        ),
        migrations.RemoveField(
            model_name="jwtuser",
            name="username",
        ),
        migrations.AlterField(
            model_name="scope",
            name="description",
            field=models.TextField(default="Provides read access to this scope"),
        ),
        migrations.AlterField(
            model_name="scope",
            name="name",
            field=models.CharField(default="read", max_length=100, unique=True),
        ),
    ]
