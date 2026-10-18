from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0053_notifications_push_devices"),
    ]

    operations = [
        migrations.CreateModel(
            name="SocialAppHandoff",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("state_hash", models.CharField(max_length=64, unique=True)),
                ("code", models.TextField(blank=True, default="")),
                ("error", models.CharField(blank=True, default="", max_length=64)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
            ],
            options={
                "db_table": "core_social_app_handoff",
            },
        ),
    ]
