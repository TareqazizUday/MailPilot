from __future__ import annotations

from django.test import SimpleTestCase

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
