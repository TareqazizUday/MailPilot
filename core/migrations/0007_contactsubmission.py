from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0006_fix_queueitem_schema"),
    ]

    operations = [
        migrations.CreateModel(
            name="ContactSubmission",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("name", models.CharField(max_length=120)),
                ("email", models.EmailField(max_length=254)),
                ("phone", models.CharField(blank=True, default="", max_length=32)),
                ("message", models.TextField()),
                ("ip_address", models.GenericIPAddressField(blank=True, null=True)),
                ("notified_team", models.BooleanField(default=False)),
                ("notified_user", models.BooleanField(default=False)),
            ],
            options={
                "db_table": "core_contactsubmission",
                "ordering": ["-created_at"],
            },
        ),
    ]
