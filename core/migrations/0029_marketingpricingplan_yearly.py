from django.db import migrations, models


PRO_YEARLY = {
    "yearly_price_display": "$200",
    "yearly_price_suffix": "/yr",
    "yearly_price_was": "$400",
    "yearly_price_save_label": "Save 50%",
    "yearly_period_text": "Billed annually · cancel anytime",
}

CUSTOM_YEARLY = {
    "yearly_period_text": "Annual or monthly in the builder",
}


def seed_yearly_defaults(apps, schema_editor):
    MarketingPricingPlan = apps.get_model("core", "MarketingPricingPlan")
    MarketingPricingPlan.objects.filter(plan_code="pro").update(**PRO_YEARLY)
    MarketingPricingPlan.objects.filter(plan_code="custom").update(**CUSTOM_YEARLY)


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0028_usersubscription_payment_provider"),
    ]

    operations = [
        migrations.AddField(
            model_name="marketingpricingplan",
            name="yearly_price_display",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Yearly price shown when toggle is on, e.g. $200. Leave blank to reuse monthly price.",
                max_length=40,
            ),
        ),
        migrations.AddField(
            model_name="marketingpricingplan",
            name="yearly_price_suffix",
            field=models.CharField(
                blank=True,
                default="/yr",
                help_text="Suffix when yearly toggle is on, e.g. /yr",
                max_length=24,
            ),
        ),
        migrations.AddField(
            model_name="marketingpricingplan",
            name="yearly_price_was",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Strikethrough compare price for yearly billing",
                max_length=24,
            ),
        ),
        migrations.AddField(
            model_name="marketingpricingplan",
            name="yearly_price_save_label",
            field=models.CharField(blank=True, default="", max_length=40),
        ),
        migrations.AddField(
            model_name="marketingpricingplan",
            name="yearly_period_text",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Period line when yearly toggle is on",
                max_length=160,
            ),
        ),
        migrations.RunPython(seed_yearly_defaults, migrations.RunPython.noop),
    ]
