from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0042_clear_pro_demo_ribbon"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="BillingPaymentEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "event_type",
                    models.CharField(
                        choices=[
                            ("checkout_started", "Checkout started"),
                            ("checkout_completed", "Checkout completed"),
                            ("checkout_failed", "Checkout failed"),
                            ("webhook", "Webhook"),
                        ],
                        db_index=True,
                        max_length=32,
                    ),
                ),
                ("provider", models.CharField(blank=True, db_index=True, default="", max_length=16)),
                ("plan_code", models.CharField(blank=True, db_index=True, default="", max_length=24)),
                ("amount_cents", models.PositiveIntegerField(blank=True, null=True)),
                ("currency", models.CharField(blank=True, default="", max_length=3)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pending"),
                            ("succeeded", "Succeeded"),
                            ("failed", "Failed"),
                            ("canceled", "Canceled"),
                        ],
                        db_index=True,
                        default="pending",
                        max_length=24,
                    ),
                ),
                ("external_id", models.CharField(blank=True, db_index=True, default="", max_length=255)),
                ("ip_address", models.GenericIPAddressField(blank=True, null=True)),
                ("user_agent", models.CharField(blank=True, default="", max_length=255)),
                ("detail", models.CharField(blank=True, default="", max_length=512)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                (
                    "user",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="billing_payment_events",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "db_table": "core_billingpaymentevent",
                "ordering": ["-created_at"],
                "indexes": [
                    models.Index(fields=["provider", "-created_at"], name="idx_bp_provider_created"),
                    models.Index(fields=["user", "-created_at"], name="idx_bp_user_created"),
                ],
            },
        ),
    ]
