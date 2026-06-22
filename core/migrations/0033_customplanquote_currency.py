from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0032_custom_plan_feature_inboxes"),
    ]

    operations = [
        migrations.AddField(
            model_name="customplanquote",
            name="currency",
            field=models.CharField(
                default="usd",
                help_text="ISO currency for price_cents (usd, gbp, eur).",
                max_length=3,
            ),
        ),
    ]
