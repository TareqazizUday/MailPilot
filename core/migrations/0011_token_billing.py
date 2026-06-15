from __future__ import annotations

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0010_usermailsettings_whatsapp_access_token"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="UserSubscription",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "plan_code",
                    models.CharField(
                        choices=[("starter", "Starter"), ("pro", "Pro"), ("custom", "Custom")],
                        db_index=True,
                        default="starter",
                        max_length=24,
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("active", "Active"),
                            ("trialing", "Trialing"),
                            ("past_due", "Past due"),
                            ("canceled", "Canceled"),
                        ],
                        db_index=True,
                        default="active",
                        max_length=24,
                    ),
                ),
                ("current_period_start", models.DateTimeField(blank=True, null=True)),
                ("current_period_end", models.DateTimeField(blank=True, null=True)),
                ("monthly_token_limit", models.PositiveIntegerField(blank=True, null=True)),
                ("active_inbox_limit", models.PositiveIntegerField(blank=True, null=True)),
                ("daily_send_limit", models.PositiveIntegerField(blank=True, null=True)),
                ("kb_source_limit", models.PositiveIntegerField(blank=True, null=True)),
                ("telegram_enabled", models.BooleanField(blank=True, null=True)),
                ("whatsapp_enabled", models.BooleanField(blank=True, null=True)),
                ("stripe_customer_id", models.CharField(blank=True, db_index=True, default="", max_length=128)),
                ("stripe_subscription_id", models.CharField(blank=True, db_index=True, default="", max_length=128)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "user",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="subscription",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={"db_table": "core_usersubscription"},
        ),
        migrations.CreateModel(
            name="UsageCounter",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("period_key", models.CharField(db_index=True, max_length=7)),
                ("tokens_used", models.PositiveIntegerField(default=0)),
                ("auto_sent_count", models.PositiveIntegerField(default=0)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="usage_counters",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={"db_table": "core_usagecounter"},
        ),
        migrations.CreateModel(
            name="DailySendCounter",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("date", models.DateField(db_index=True)),
                (
                    "provider_profile",
                    models.CharField(
                        choices=[
                            ("gmail_personal", "Gmail personal"),
                            ("google_workspace", "Google Workspace"),
                            ("smtp_personal", "SMTP personal"),
                            ("smtp_business", "SMTP business"),
                        ],
                        default="gmail_personal",
                        max_length=32,
                    ),
                ),
                ("sends_used", models.PositiveIntegerField(default=0)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "mail_account",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="daily_send_counters",
                        to="core.mailaccount",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="daily_send_counters",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={"db_table": "core_dailysendcounter"},
        ),
        migrations.CreateModel(
            name="UsageEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("message_id", models.CharField(max_length=255)),
                ("event_type", models.CharField(choices=[("auto_send", "Auto-send")], default="auto_send", max_length=32)),
                ("units", models.PositiveSmallIntegerField(default=1)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("reserved", "Reserved"),
                            ("committed", "Committed"),
                            ("failed", "Failed"),
                            ("refunded", "Refunded"),
                        ],
                        db_index=True,
                        default="reserved",
                        max_length=24,
                    ),
                ),
                ("period_key", models.CharField(db_index=True, max_length=7)),
                ("date", models.DateField(db_index=True)),
                ("meta_json", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("committed_at", models.DateTimeField(blank=True, null=True)),
                (
                    "mail_account",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="usage_events",
                        to="core.mailaccount",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="usage_events",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={"db_table": "core_usageevent"},
        ),
        migrations.AddConstraint(
            model_name="usagecounter",
            constraint=models.UniqueConstraint(fields=("user", "period_key"), name="uq_usagecounter_user_period"),
        ),
        migrations.AddConstraint(
            model_name="dailysendcounter",
            constraint=models.UniqueConstraint(fields=("mail_account", "date"), name="uq_dailysendcounter_account_date"),
        ),
        migrations.AddIndex(
            model_name="dailysendcounter",
            index=models.Index(fields=["user", "-date"], name="idx_dailysendcounter_user_date"),
        ),
        migrations.AddConstraint(
            model_name="usageevent",
            constraint=models.UniqueConstraint(
                fields=("mail_account", "message_id", "event_type"),
                name="uq_usageevent_account_message_type",
            ),
        ),
        migrations.AddIndex(
            model_name="usageevent",
            index=models.Index(fields=["user", "period_key", "status"], name="idx_usageevent_user_period"),
        ),
    ]
