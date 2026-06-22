from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0025_legal_privacy"),
    ]

    operations = [
        migrations.CreateModel(
            name="PayPalGatewayConfig",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("singleton_key", models.PositiveSmallIntegerField(default=1, unique=True)),
                (
                    "is_enabled",
                    models.BooleanField(
                        default=False,
                        help_text="When enabled, stored credentials override PAYPAL_* environment variables.",
                    ),
                ),
                (
                    "sandbox_mode",
                    models.BooleanField(
                        default=True,
                        help_text="Use PayPal Sandbox (api-m.sandbox.paypal.com). Disable for live payments.",
                    ),
                ),
                ("client_id", models.CharField(blank=True, default="", max_length=255)),
                (
                    "plan_pro_monthly",
                    models.CharField(
                        blank=True,
                        default="",
                        help_text="PayPal Plan ID for Pro monthly subscription (P-...).",
                        max_length=128,
                    ),
                ),
                ("client_secret_enc", models.TextField(blank=True, default="")),
                (
                    "webhook_id",
                    models.CharField(
                        blank=True,
                        default="",
                        help_text="PayPal Webhook ID from the Developer Dashboard.",
                        max_length=128,
                    ),
                ),
                ("notes", models.TextField(blank=True, default="")),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "PayPal gateway",
                "verbose_name_plural": "PayPal gateway",
                "db_table": "core_paypalgatewayconfig",
            },
        ),
    ]
