from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0026_paypal_gateway_config"),
    ]

    operations = [
        migrations.RenameModel(
            old_name="PaymentGatewayConfig",
            new_name="Stripe",
        ),
        migrations.RenameModel(
            old_name="PayPalGatewayConfig",
            new_name="PayPal",
        ),
        migrations.AlterModelOptions(
            name="stripe",
            options={
                "verbose_name": "Stripe",
                "verbose_name_plural": "Stripe",
                "db_table": "core_paymentgatewayconfig",
            },
        ),
        migrations.AlterModelOptions(
            name="paypal",
            options={
                "verbose_name": "PayPal",
                "verbose_name_plural": "PayPal",
                "db_table": "core_paypalgatewayconfig",
            },
        ),
    ]
