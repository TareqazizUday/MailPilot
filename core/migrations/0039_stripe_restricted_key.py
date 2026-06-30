from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0038_pricing_feature_text_layout"),
    ]

    operations = [
        migrations.AddField(
            model_name="stripe",
            name="stripe_restricted_key_enc",
            field=models.TextField(
                blank=True,
                default="",
                help_text="Encrypted Stripe restricted key (rk_live_ / rk_test_).",
            ),
        ),
    ]
