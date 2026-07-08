from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0046_profit_llm_analyze_cost"),
    ]

    operations = [
        migrations.AddField(
            model_name="usersubscription",
            name="token_auto_renew_enabled",
            field=models.BooleanField(
                default=True,
                help_text="When enabled, paid plans attempt an automatic token top-up after token exhaustion.",
            ),
        ),
        migrations.AddField(
            model_name="usersubscription",
            name="token_topup_count",
            field=models.PositiveIntegerField(
                default=0,
                help_text="Number of automatic token top-ups completed in the current usage period.",
            ),
        ),
        migrations.AddField(
            model_name="usersubscription",
            name="token_topup_period_key",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Usage period key (YYYY-MM) for token_topup_tokens/token_topup_count.",
                max_length=7,
            ),
        ),
        migrations.AddField(
            model_name="usersubscription",
            name="token_topup_tokens",
            field=models.PositiveIntegerField(
                default=0,
                help_text="Bonus tokens purchased for the current usage period.",
            ),
        ),
    ]
