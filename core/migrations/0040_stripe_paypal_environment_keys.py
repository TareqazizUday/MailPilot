from django.db import migrations, models


def _split_stripe_test_keys(apps, schema_editor):
    try:
        from core.crypto import decrypt_str
    except Exception:
        return

    Stripe = apps.get_model("core", "Stripe")
    for row in Stripe.objects.all():
        secret = decrypt_str(row.stripe_secret_key_enc or "").strip()
        restricted = decrypt_str(row.stripe_restricted_key_enc or "").strip()
        changed = False
        if secret.startswith("sk_test_"):
            row.stripe_test_secret_key_enc = row.stripe_secret_key_enc
            row.stripe_secret_key_enc = ""
            changed = True
        if restricted.startswith("rk_test_"):
            row.stripe_test_restricted_key_enc = row.stripe_restricted_key_enc
            row.stripe_restricted_key_enc = ""
            changed = True
        if changed:
            row.save(
                update_fields=[
                    "stripe_secret_key_enc",
                    "stripe_restricted_key_enc",
                    "stripe_test_secret_key_enc",
                    "stripe_test_restricted_key_enc",
                ]
            )


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0039_stripe_restricted_key"),
    ]

    operations = [
        migrations.AddField(
            model_name="stripe",
            name="stripe_key_environment",
            field=models.CharField(
                choices=[
                    ("auto", "Auto — test keys when DEBUG, live keys on production"),
                    ("test", "Force test keys (localhost / staging)"),
                    ("live", "Force live keys (production)"),
                ],
                default="auto",
                help_text="Which key set Checkout uses. Auto follows DEBUG (local=test, production=live).",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="stripe",
            name="stripe_test_secret_key_enc",
            field=models.TextField(blank=True, default="", help_text="Encrypted test secret key (sk_test_)."),
        ),
        migrations.AddField(
            model_name="stripe",
            name="stripe_test_restricted_key_enc",
            field=models.TextField(blank=True, default="", help_text="Encrypted test restricted key (rk_test_)."),
        ),
        migrations.AlterField(
            model_name="stripe",
            name="stripe_restricted_key_enc",
            field=models.TextField(
                blank=True,
                default="",
                help_text="Encrypted live restricted key (rk_live_).",
            ),
        ),
        migrations.AlterField(
            model_name="stripe",
            name="stripe_secret_key_enc",
            field=models.TextField(
                blank=True,
                default="",
                help_text="Encrypted live secret key (sk_live_).",
            ),
        ),
        migrations.AddField(
            model_name="paypal",
            name="paypal_environment",
            field=models.CharField(
                choices=[
                    ("auto", "Auto — sandbox when DEBUG, live on production"),
                    ("sandbox", "Force sandbox (localhost / staging)"),
                    ("live", "Force live (production)"),
                ],
                default="auto",
                help_text="Which PayPal API to use. Auto follows DEBUG (local=sandbox, production=live).",
                max_length=16,
            ),
        ),
        migrations.RunPython(_split_stripe_test_keys, migrations.RunPython.noop),
    ]
