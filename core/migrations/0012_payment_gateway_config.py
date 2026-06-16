from __future__ import annotations

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0011_token_billing"),
    ]

    operations = [
        migrations.CreateModel(
            name="PaymentGatewayConfig",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("singleton_key", models.PositiveSmallIntegerField(default=1, unique=True)),
                (
                    "provider",
                    models.CharField(
                        choices=[("stripe", "Stripe")],
                        default="stripe",
                        max_length=32,
                    ),
                ),
                (
                    "is_enabled",
                    models.BooleanField(
                        default=False,
                        help_text="When enabled, stored credentials override STRIPE_* environment variables.",
                    ),
                ),
                ("stripe_publishable_key", models.CharField(blank=True, default="", max_length=255)),
                (
                    "stripe_price_pro_monthly",
                    models.CharField(
                        blank=True,
                        default="",
                        help_text="Stripe Price ID for Pro monthly (price_...).",
                        max_length=128,
                    ),
                ),
                ("stripe_secret_key_enc", models.TextField(blank=True, default="")),
                ("stripe_webhook_secret_enc", models.TextField(blank=True, default="")),
                ("notes", models.TextField(blank=True, default="")),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "payment gateway",
                "verbose_name_plural": "payment gateway",
                "db_table": "core_paymentgatewayconfig",
            },
        ),
    ]
