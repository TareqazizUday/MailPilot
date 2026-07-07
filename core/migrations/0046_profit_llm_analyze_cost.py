from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0045_pricing_profit_assumptions"),
    ]

    operations = [
        migrations.AddField(
            model_name="marketingpricingsettings",
            name="profit_llm_cost_per_analyze_usd",
            field=models.DecimalField(
                decimal_places=4,
                default=0.0020,
                help_text="Estimated LLM cost per mailbox analyze (read → relevance + draft), excluding auto-send.",
                max_digits=8,
            ),
        ),
    ]
