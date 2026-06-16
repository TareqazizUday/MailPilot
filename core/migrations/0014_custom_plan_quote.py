import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0013_starter_trial_lifetime"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="CustomPlanQuote",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("tokens", models.PositiveIntegerField()),
                ("inboxes", models.PositiveIntegerField()),
                ("price_cents", models.PositiveIntegerField()),
                ("daily_send_limit", models.PositiveIntegerField(default=100)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("draft", "Draft"),
                            ("pending", "Pending payment"),
                            ("paid", "Paid"),
                            ("expired", "Expired"),
                            ("canceled", "Canceled"),
                        ],
                        db_index=True,
                        default="draft",
                        max_length=24,
                    ),
                ),
                ("stripe_session_id", models.CharField(blank=True, default="", max_length=255)),
                ("expires_at", models.DateTimeField(blank=True, null=True)),
                ("paid_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="custom_plan_quotes",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "db_table": "core_customplanquote",
                "ordering": ["-created_at"],
                "indexes": [models.Index(fields=["user", "-created_at"], name="idx_customquote_user_created")],
            },
        ),
    ]
