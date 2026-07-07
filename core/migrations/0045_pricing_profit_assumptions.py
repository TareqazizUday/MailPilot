from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0044_support_tickets"),
    ]

    operations = [
        migrations.AddField(
            model_name="marketingpricingsettings",
            name="profit_api_cost_per_send_usd",
            field=models.DecimalField(
                decimal_places=4,
                default=0.03,
                help_text="Estimated variable API cost per auto-sent message (USD).",
                max_digits=8,
            ),
        ),
        migrations.AddField(
            model_name="marketingpricingsettings",
            name="profit_token_cost_per_1k_usd",
            field=models.DecimalField(
                decimal_places=4,
                default=0.0,
                help_text="Optional internal token cost per 1,000 plan tokens (USD).",
                max_digits=8,
            ),
        ),
    ]
