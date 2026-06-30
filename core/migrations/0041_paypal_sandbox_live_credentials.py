from django.db import migrations, models


def _migrate_paypal_credentials_to_sandbox(apps, schema_editor):
    PayPal = apps.get_model("core", "PayPal")
    for row in PayPal.objects.all():
        changed = False
        if (row.client_id or "").strip() and not (row.sandbox_client_id or "").strip():
            row.sandbox_client_id = row.client_id
            changed = True
        if (row.client_secret_enc or "").strip() and not (row.sandbox_client_secret_enc or "").strip():
            row.sandbox_client_secret_enc = row.client_secret_enc
            changed = True
        if changed:
            row.save(
                update_fields=[
                    "sandbox_client_id",
                    "sandbox_client_secret_enc",
                ]
            )


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0040_stripe_paypal_environment_keys"),
    ]

    operations = [
        migrations.AddField(
            model_name="paypal",
            name="sandbox_client_id",
            field=models.CharField(
                blank=True,
                default="",
                help_text="PayPal Sandbox Client ID from developer.paypal.com.",
                max_length=255,
            ),
        ),
        migrations.AddField(
            model_name="paypal",
            name="live_client_id",
            field=models.CharField(
                blank=True,
                default="",
                help_text="PayPal Live Client ID for production checkout.",
                max_length=255,
            ),
        ),
        migrations.AddField(
            model_name="paypal",
            name="sandbox_client_secret_enc",
            field=models.TextField(
                blank=True,
                default="",
                help_text="Encrypted PayPal Sandbox client secret.",
            ),
        ),
        migrations.AddField(
            model_name="paypal",
            name="live_client_secret_enc",
            field=models.TextField(
                blank=True,
                default="",
                help_text="Encrypted PayPal Live client secret.",
            ),
        ),
        migrations.AlterField(
            model_name="paypal",
            name="client_id",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Legacy sandbox client ID; prefer sandbox_client_id.",
                max_length=255,
            ),
        ),
        migrations.AlterField(
            model_name="paypal",
            name="client_secret_enc",
            field=models.TextField(
                blank=True,
                default="",
                help_text="Legacy encrypted secret; prefer sandbox_client_secret_enc.",
            ),
        ),
        migrations.RunPython(_migrate_paypal_credentials_to_sandbox, migrations.RunPython.noop),
    ]
