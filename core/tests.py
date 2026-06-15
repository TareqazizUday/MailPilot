from __future__ import annotations

from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase

from core.billing import (
    can_enable_mailbox,
    can_use_integration,
    commit_auto_send,
    get_or_create_subscription,
    reserve_auto_send,
    set_subscription_plan,
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
        self.assertEqual(summary["tokens"]["limit"], 20)
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
        self.assertEqual(summary["tokens"]["used"], TOKENS_PER_AUTO_SEND)
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

        self.assertTrue(can_use_integration(self.user, "telegram").allowed)
        self.assertTrue(can_use_integration(self.user, "whatsapp").allowed)
