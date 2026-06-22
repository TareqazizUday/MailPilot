from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0012_payment_gateway_config"),
    ]

    operations = [
        migrations.AddField(
            model_name="usersubscription",
            name="starter_lifetime_sends",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="usersubscription",
            name="starter_expired_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="usersubscription",
            name="paid_at",
            field=models.DateTimeField(
                blank=True,
                null=True,
                help_text="Set when Pro/Custom payment is confirmed (Stripe webhook or admin).",
            ),
        ),
    ]
