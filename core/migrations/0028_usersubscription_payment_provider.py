from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0027_rename_payment_models"),
    ]

    operations = [
        migrations.AddField(
            model_name="usersubscription",
            name="payment_provider",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Last successful checkout provider: stripe or paypal.",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="usersubscription",
            name="paypal_subscription_id",
            field=models.CharField(blank=True, db_index=True, default="", max_length=128),
        ),
    ]
