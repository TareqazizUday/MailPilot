from __future__ import annotations

from django.db import migrations

EM = "\u2014"
EN = "\u2013"


def _clean(value: str) -> str:
    if not value or (EM not in value and EN not in value):
        return value
    text = value.replace(f"MailPilot {EM} ", "MailPilot | ")
    text = text.replace(f" {EM} MailPilot", " | MailPilot")
    text = text.replace(f" {EM} ", " - ")
    text = text.replace(EM, "-")
    text = text.replace(f" {EN} ", " - ")
    text = text.replace(EN, "-")
    return text


def _clean_model_fields(apps, model_name: str) -> None:
    model = apps.get_model("core", model_name)
    text_field_types = ("CharField", "TextField")
    fields = [
        f.name
        for f in model._meta.get_fields()
        if getattr(f, "max_length", None) is not None or f.get_internal_type() in text_field_types
    ]
    fields = [
        name
        for name in fields
        if name not in {"id"}
        and model._meta.get_field(name).get_internal_type() in {"CharField", "TextField"}
    ]
    for row in model.objects.all().iterator():
        updates: dict[str, str] = {}
        for name in fields:
            raw = getattr(row, name, "") or ""
            cleaned = _clean(str(raw))
            if cleaned != raw:
                updates[name] = cleaned
        if updates:
            model.objects.filter(pk=row.pk).update(**updates)


def forwards(apps, schema_editor) -> None:
    for model_name in (
        "MarketingFeature",
        "HowItWorksStep",
        "MarketingReview",
        "MarketingPricingSettings",
        "MarketingPricingPlan",
        "MarketingHeroSettings",
        "MarketingHeroInboxItem",
        "MarketingFaqSettings",
        "MarketingFaqItem",
        "LegalTermsSettings",
        "LegalTermsSection",
        "LegalPrivacySettings",
    ):
        _clean_model_fields(apps, model_name)


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0034_custom_plan_card_features"),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
