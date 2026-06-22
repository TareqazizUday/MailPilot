from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0030_remove_customplanquote_orphan_currency"),
    ]

    operations = [
        migrations.AddField(
            model_name="customplanquote",
            name="billing_interval",
            field=models.CharField(default="monthly", max_length=8),
        ),
        migrations.AddField(
            model_name="stripe",
            name="stripe_price_pro_yearly",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Optional Stripe Price ID for Pro yearly (price_...). Falls back to dynamic checkout.",
                max_length=128,
            ),
        ),
    ]
