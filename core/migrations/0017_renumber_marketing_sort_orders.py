from django.db import migrations


def renumber_marketing_sort_orders(apps, schema_editor):
    for model_name in ("MarketingFeature", "HowItWorksStep"):
        Model = apps.get_model("core", model_name)
        for index, row in enumerate(Model.objects.order_by("sort_order", "id"), start=1):
            if row.sort_order != index:
                Model.objects.filter(pk=row.pk).update(sort_order=index)


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0016_how_it_works_step"),
    ]

    operations = [
        migrations.RunPython(renumber_marketing_sort_orders, migrations.RunPython.noop),
    ]
