from __future__ import annotations

from django.contrib.auth.models import User
from django.test import Client, SimpleTestCase, TestCase

from core.billing import (
    STARTER_LIFETIME_SEND_LIMIT,
    can_enable_mailbox,
    can_use_integration,
    commit_auto_send,
    get_or_create_subscription,
    is_starter_expired,
    reserve_auto_send,
    set_subscription_plan,
    tokens_per_auto_send_for_plan,
    TOKENS_PER_AUTO_SEND,
    usage_summary,
)
from core.models import MailAccount, UsageEvent, UserSubscription
from core.mail_chat_assistant import _limit_from_query, _split_scoped_ref, detect_mail_intent
from core.whatsapp_webhook import _extract_inbound_messages


class MailChatAssistantTests(SimpleTestCase):
    def test_common_intents_and_counts(self) -> None:
        cases = {
            "last mail konta asche": "recent",
            "last duita mail daw": "recent",
            "mail body show": "thread",
            "ei mail er reply ki dicho": "reply",
            "account gula dekhao": "accounts",
            "recent important mail": "important",
        }
        for text, intent in cases.items():
            with self.subTest(text=text):
                self.assertEqual(detect_mail_intent(text)[0], intent)

        self.assertEqual(_limit_from_query("last mail"), 1)
        self.assertEqual(_limit_from_query("last duita mail daw"), 2)
        self.assertEqual(_limit_from_query("show all mail"), 20)

    def test_scoped_ref_prefers_requested_command(self) -> None:
        context = "Next: /thread 3:44 | /reply 3:55"

        self.assertEqual(_split_scoped_ref(context, command="thread"), ("3", "44"))
        self.assertEqual(_split_scoped_ref(context, command="reply"), ("3", "55"))


class WhatsAppWebhookTests(SimpleTestCase):
    def test_extracts_quoted_context_text_when_available(self) -> None:
        payload = {
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "metadata": {"phone_number_id": "phone-1"},
                                "messages": [
                                    {
                                        "type": "text",
                                        "from": "8801000000000",
                                        "id": "wa-1",
                                        "text": {"body": "reply show"},
                                        "context": {"id": "old", "text": {"body": "Next: /reply 3:55"}},
                                    }
                                ],
                            }
                        }
                    ]
                }
            ]
        }

        rows = _extract_inbound_messages(payload)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["context_text"], "Next: /reply 3:55")


class BillingTests(TestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_user(username="u1", email="u1@example.com", password="pass12345")

    def test_starter_subscription_defaults(self) -> None:
        sub = get_or_create_subscription(self.user)

        self.assertEqual(sub.plan_code, UserSubscription.PLAN_STARTER)
        summary = usage_summary(self.user)
        self.assertEqual(summary["tokens"]["limit"], 80)
        self.assertEqual(summary["active_inboxes"]["limit"], 1)
        self.assertFalse(summary["features"]["telegram"])
        self.assertFalse(summary["features"]["whatsapp"])

    def test_starter_inbox_limit(self) -> None:
        MailAccount.objects.create(
            user=self.user,
            slot=1,
            transport=MailAccount.TRANSPORT_GMAIL,
            label="Gmail 1",
            is_enabled=True,
        )

        gate = can_enable_mailbox(self.user)

        self.assertFalse(gate.allowed)
        self.assertEqual(gate.reason, "plan_inbox_limit_reached")

    def test_pro_inbox_limit_allows_three(self) -> None:
        sub = get_or_create_subscription(self.user)
        set_subscription_plan(sub, UserSubscription.PLAN_PRO)
        for slot in range(1, 4):
            MailAccount.objects.create(
                user=self.user,
                slot=slot,
                transport=MailAccount.TRANSPORT_GMAIL,
                label=f"Gmail {slot}",
                is_enabled=True,
            )

        gate = can_enable_mailbox(self.user)

        self.assertFalse(gate.allowed)
        self.assertEqual(gate.summary["active_inboxes"]["used"], 3)

    def test_auto_send_reservation_commit_is_idempotent(self) -> None:
        acc = MailAccount.objects.create(
            user=self.user,
            slot=1,
            transport=MailAccount.TRANSPORT_GMAIL,
            label="Gmail 1",
            is_enabled=True,
        )

        reservation = reserve_auto_send(self.user, acc, "msg-1")
        self.assertTrue(reservation.allowed)
        commit_auto_send(reservation)
        commit_auto_send(reservation)

        summary = usage_summary(self.user, account=acc)
        self.assertEqual(summary["tokens"]["used"], tokens_per_auto_send_for_plan(UserSubscription.PLAN_STARTER))
        self.assertEqual(summary["daily"]["used"], 1)
        self.assertEqual(UsageEvent.objects.get(pk=reservation.event_id).status, UsageEvent.STATUS_COMMITTED)

    def test_failed_reservation_does_not_consume_token(self) -> None:
        from core.billing import fail_auto_send

        acc = MailAccount.objects.create(
            user=self.user,
            slot=1,
            transport=MailAccount.TRANSPORT_SMTP,
            label="SMTP 1",
            is_enabled=True,
        )

        reservation = reserve_auto_send(self.user, acc, "msg-2")
        self.assertTrue(reservation.allowed)
        fail_auto_send(reservation, "smtp failed")

        summary = usage_summary(self.user, account=acc)
        self.assertEqual(summary["tokens"]["used"], 0)
        self.assertEqual(summary["daily"]["used"], 0)

    def test_starter_blocks_chat_integrations(self) -> None:
        self.assertFalse(can_use_integration(self.user, "telegram").allowed)
        self.assertFalse(can_use_integration(self.user, "whatsapp").allowed)

        sub = get_or_create_subscription(self.user)
        set_subscription_plan(sub, UserSubscription.PLAN_PRO)
        sub.paid_at = sub.updated_at
        sub.save(update_fields=["paid_at"])

        self.assertTrue(can_use_integration(self.user, "telegram").allowed)
        self.assertTrue(can_use_integration(self.user, "whatsapp").allowed)

    def test_starter_expires_after_lifetime_send_limit(self) -> None:
        acc = MailAccount.objects.create(
            user=self.user,
            slot=1,
            transport=MailAccount.TRANSPORT_GMAIL,
            label="Gmail 1",
            is_enabled=True,
        )
        sub = get_or_create_subscription(self.user)
        for i in range(STARTER_LIFETIME_SEND_LIMIT):
            reservation = reserve_auto_send(self.user, acc, f"msg-{i}")
            self.assertTrue(reservation.allowed, f"send {i}")
            commit_auto_send(reservation)

        sub.refresh_from_db()
        self.assertTrue(is_starter_expired(sub))
        self.assertIsNotNone(sub.starter_expired_at)

        blocked = reserve_auto_send(self.user, acc, "msg-over")
        self.assertFalse(blocked.allowed)
        self.assertEqual(blocked.reason, "starter_trial_expired")

        gate = can_enable_mailbox(self.user)
        self.assertFalse(gate.allowed)
        self.assertEqual(gate.reason, "starter_trial_expired")


class CustomPlanPricingTests(SimpleTestCase):
    def test_preset_bundle_prices(self) -> None:
        from core.billing import calculate_custom_price_cents

        self.assertEqual(calculate_custom_price_cents(2000, 4), 3000)
        self.assertEqual(calculate_custom_price_cents(3000, 6), 4000)

    def test_min_price_floor(self) -> None:
        from core.billing import calculate_custom_price_cents

        self.assertEqual(calculate_custom_price_cents(1000, 1), 2000)

    def test_quote_summary_clamps_inputs(self) -> None:
        from core.billing import custom_plan_quote_summary

        q = custom_plan_quote_summary(999, 0)
        self.assertEqual(q["tokens"], 1000)
        self.assertEqual(q["inboxes"], 1)


class AdminLoginRedirectTests(TestCase):
    def test_admin_without_trailing_slash_redirects(self) -> None:
        client = Client()
        response = client.get("/admin", follow=False, secure=True)
        self.assertEqual(response.status_code, 301)
        self.assertEqual(response["Location"], "/admin/")

    def setUp(self) -> None:
        self.staff = User.objects.create_user(username="staffadmin", password="testpass1234")
        self.staff.is_staff = True
        self.staff.is_active = True
        self.staff.save(update_fields=["is_staff", "is_active"])

    def test_admin_login_redirects_to_dashboard(self) -> None:
        client = Client()
        response = client.post(
            "/admin/login/",
            {"username": "staffadmin", "password": "testpass1234"},
            follow=False,
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "/admin/")

    def test_custom_login_staff_redirects_to_admin(self) -> None:
        client = Client()
        response = client.post(
            "/login",
            {"username": "staffadmin", "password": "testpass1234"},
            follow=False,
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "/admin/")

    def test_post_login_rejects_admin_login_next_loop(self) -> None:
        from django.test import RequestFactory

        from core.auth_views import post_login_redirect_url

        request = RequestFactory().get("/")
        request.META["HTTP_HOST"] = "127.0.0.1:8000"
        url = post_login_redirect_url(request, self.staff, next_url="/admin/login/?next=/admin/")
        self.assertEqual(url, "/admin/")


class DemoStripeCredentialTests(SimpleTestCase):
    def test_demo_placeholders_not_checkout_ready(self) -> None:
        from core.payment_gateway import DEMO_STRIPE_REFERENCE, is_demo_stripe_credentials

        ref = DEMO_STRIPE_REFERENCE
        self.assertTrue(
            is_demo_stripe_credentials(
                secret_key=ref["secret_key"],
                price_pro_monthly=ref["price_pro_monthly"],
                publishable_key=ref["publishable_key"],
            )
        )
        self.assertFalse(
            is_demo_stripe_credentials(
                secret_key="sk_test_51RealKeyFromStripe",
                price_pro_monthly="price_1RealFromStripe",
            )
        )


class DemoPayPalCredentialTests(SimpleTestCase):
    def test_demo_placeholders_not_checkout_ready(self) -> None:
        from core.payment_gateway import DEMO_PAYPAL_REFERENCE, is_demo_paypal_credentials

        ref = DEMO_PAYPAL_REFERENCE
        self.assertTrue(
            is_demo_paypal_credentials(
                client_id=ref["client_id"],
                client_secret=ref["client_secret"],
                plan_pro_monthly=ref["plan_pro_monthly"],
            )
        )
        self.assertFalse(
            is_demo_paypal_credentials(
                client_id="real_client_id_from_paypal",
                client_secret="real_secret_from_paypal",
                plan_pro_monthly="P-RealPlanFromPayPal",
            )
        )


class PaymentProviderChoiceTests(SimpleTestCase):
    def test_demo_mode_exposes_both_providers_when_no_live_keys(self) -> None:
        from unittest.mock import patch

        from django.test import override_settings

        from core.payment_gateway import PAYMENT_PAYPAL, PAYMENT_STRIPE, available_payment_providers

        with override_settings(BILLING_DEMO_MODE=True):
            with patch("core.payment_gateway.stripe_checkout_ready", return_value=False):
                with patch("core.payment_gateway.paypal_checkout_ready", return_value=False):
                    providers = available_payment_providers()
        self.assertEqual(providers, [PAYMENT_STRIPE, PAYMENT_PAYPAL])

    def test_production_shows_paypal_when_configured(self) -> None:
        from unittest.mock import patch

        from django.test import override_settings

        from core.payment_gateway import PAYMENT_PAYPAL, PAYMENT_STRIPE, available_payment_providers

        with override_settings(BILLING_DEMO_MODE=False, DEBUG=False):
            with patch("core.payment_gateway.stripe_checkout_ready", return_value=True):
                with patch("core.payment_gateway.stripe_is_configured", return_value=True):
                    with patch("core.payment_gateway.paypal_checkout_ready", return_value=True):
                        providers = available_payment_providers()
        self.assertIn(PAYMENT_STRIPE, providers)
        self.assertIn(PAYMENT_PAYPAL, providers)

    def test_debug_uses_local_checkout_form(self) -> None:
        from django.test import override_settings

        from core.payment_gateway import billing_use_local_checkout

        with override_settings(DEBUG=True):
            self.assertTrue(billing_use_local_checkout())


class StripeEnvironmentTests(SimpleTestCase):
    def test_auto_uses_test_when_debug_and_test_key(self) -> None:
        import os
        from unittest.mock import patch

        from django.test import override_settings

        from core.payment_gateway import stripe_resolved_environment

        with override_settings(DEBUG=True):
            with patch.dict(
                os.environ,
                {"STRIPE_KEY_ENVIRONMENT": "auto", "STRIPE_TEST_SECRET_KEY": "sk_test_abc"},
                clear=False,
            ):
                self.assertEqual(stripe_resolved_environment(), "test")

    def test_auto_falls_back_to_live_on_debug_when_only_live_key(self) -> None:
        import os
        from unittest.mock import patch

        from django.test import override_settings

        from core.payment_gateway import stripe_resolved_environment

        with override_settings(DEBUG=True):
            with patch.dict(
                os.environ,
                {
                    "STRIPE_KEY_ENVIRONMENT": "auto",
                    "STRIPE_LIVE_SECRET_KEY": "sk_live_abc",
                    "STRIPE_TEST_SECRET_KEY": "",
                },
                clear=False,
            ):
                self.assertEqual(stripe_resolved_environment(), "live")

    def test_auto_uses_live_when_not_debug(self) -> None:
        import os
        from unittest.mock import patch

        from django.test import override_settings

        from core.payment_gateway import stripe_resolved_environment

        with override_settings(DEBUG=False):
            with patch.dict(os.environ, {"STRIPE_KEY_ENVIRONMENT": "auto"}, clear=False):
                self.assertEqual(stripe_resolved_environment(), "live")


class BillingDeployChecksTests(SimpleTestCase):
    def test_site_url_required_on_production(self) -> None:
        from django.test import override_settings

        from core.payment_gateway import billing_site_url_missing

        with override_settings(DEBUG=True, SITE_URL=""):
            self.assertFalse(billing_site_url_missing())
        with override_settings(DEBUG=False, SITE_URL=""):
            self.assertTrue(billing_site_url_missing())
        with override_settings(DEBUG=False, SITE_URL="https://app.example.com"):
            self.assertFalse(billing_site_url_missing())
