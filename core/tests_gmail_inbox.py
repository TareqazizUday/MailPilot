from __future__ import annotations

from unittest import mock

import httplib2
from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import SimpleTestCase, TestCase, override_settings
from googleapiclient.errors import HttpError
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from core.models import MailAccount
from email_automation import gmail_client as gc
from email_automation.gmail_client import GmailClient
from email_automation.settings import Settings


def _http_error(status: int) -> HttpError:
    return HttpError(httplib2.Response({"status": str(status)}), b"{}")


def _thread(tid: str) -> dict:
    return {
        "messages": [
            {
                "id": f"m-{tid}",
                "internalDate": "1700000000000",
                "labelIds": ["INBOX", "UNREAD"],
                "snippet": f"snippet {tid}",
                "payload": {
                    "headers": [
                        {"name": "From", "value": f"Sender {tid} <{tid}@example.com>"},
                        {"name": "Subject", "value": f"Subject {tid}"},
                        {"name": "Date", "value": "Tue, 14 Nov 2023 22:13:20 +0000"},
                    ]
                },
            }
        ]
    }


class _Req:
    def __init__(self, result=None):
        self._result = result

    def execute(self):
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


class _FakeGmail:
    """Just enough of the googleapiclient Gmail service for list_inbox_thread_summaries."""

    def __init__(self, tids, *, fail=None, batch_error=None):
        self.tids = list(tids)
        # thread id -> list of outcomes per attempt (Exception or "ok"); default always ok
        self.fail = fail or {}
        self.batch_error = batch_error
        self.batch_sizes: list[int] = []
        self.single_gets = 0

    # svc.users().threads().list(...) / .get(...)
    def users(self):
        return self

    def threads(self):
        return self

    def list(self, **kwargs):
        return _Req({"threads": [{"id": t, "snippet": f"list {t}"} for t in self.tids]})

    def get(self, *, userId, id, **kwargs):
        req = _Req()
        req.tid = id
        req.execute = self._count_single_get
        return req

    def _count_single_get(self):
        self.single_gets += 1
        raise AssertionError("threads.get must go through a batch")

    def new_batch_http_request(self, callback):
        return _FakeBatch(self, callback)


class _FakeBatch:
    def __init__(self, svc: _FakeGmail, callback):
        self.svc = svc
        self.callback = callback
        self.items: list[str] = []

    def add(self, request, request_id):
        self.items.append(request_id)

    def execute(self):
        self.svc.batch_sizes.append(len(self.items))
        if self.svc.batch_error is not None:
            raise self.svc.batch_error
        for tid in self.items:
            outcomes = self.svc.fail.get(tid)
            outcome = outcomes.pop(0) if outcomes else "ok"
            if isinstance(outcome, Exception):
                self.callback(tid, None, outcome)
            else:
                self.callback(tid, _thread(tid), None)


@mock.patch.object(gc.time, "sleep")
class GmailBatchListTests(SimpleTestCase):
    def _client(self, svc: _FakeGmail) -> GmailClient:
        client = GmailClient(Settings(GMAIL_ADDRESS="owner@example.com"))
        client._svc = svc
        return client

    def test_threads_fetched_in_batches_of_twenty_in_order(self, sleep):
        tids = [f"t{i}" for i in range(45)]
        svc = _FakeGmail(tids)
        out = self._client(svc).list_inbox_thread_summaries(max_threads=45)
        self.assertEqual(svc.batch_sizes, [20, 20, 5])
        self.assertEqual(svc.single_gets, 0)
        self.assertEqual([t["thread_id"] for t in out], tids)
        first = out[0]
        self.assertEqual((first["message_id"], first["subject"], first["unread"]), ("m-t0", "Subject t0", True))
        self.assertEqual(first["from"], "Sender t0 <t0@example.com>")
        sleep.assert_not_called()

    def test_rate_limited_threads_are_retried(self, sleep):
        svc = _FakeGmail(["a", "b", "c"], fail={"b": [_http_error(429)]})
        out = self._client(svc).list_inbox_thread_summaries(max_threads=3)
        self.assertEqual(svc.batch_sizes, [3, 1])
        self.assertEqual(out[1]["subject"], "Subject b")
        self.assertLessEqual(sleep.call_args[0][0], gc.THREAD_BATCH_MAX_WAIT_SECONDS)

    def test_thread_that_keeps_failing_becomes_stub(self, sleep):
        svc = _FakeGmail(["a", "b"], fail={"a": [_http_error(429)] * 5, "b": [_http_error(404)]})
        out = self._client(svc).list_inbox_thread_summaries(max_threads=2)
        self.assertEqual(len(svc.batch_sizes), 1 + gc.THREAD_BATCH_RETRY_ROUNDS)
        self.assertEqual([t["subject"] for t in out], ["(Could not load headers)"] * 2)
        self.assertEqual(out[0]["snippet"], "list a")

    def test_whole_batch_failure_gives_stubs(self, sleep):
        svc = _FakeGmail(["a", "b"], batch_error=OSError("network down"))
        out = self._client(svc).list_inbox_thread_summaries(max_threads=2)
        self.assertEqual([t["message_id"] for t in out], ["", ""])
        sleep.assert_not_called()

    def test_duplicate_thread_ids_listed_once(self, sleep):
        svc = _FakeGmail(["a", "a", "b"])
        out = self._client(svc).list_inbox_thread_summaries(max_threads=3)
        self.assertEqual([t["thread_id"] for t in out], ["a", "b"])


@override_settings(SECURE_SSL_REDIRECT=False)
class GmailInboxCacheTests(TestCase):
    def setUp(self) -> None:
        cache.clear()
        self.addCleanup(cache.clear)
        self.user = User.objects.create_user("inbox", "inbox@example.com", "pw-12345678")
        self.acc = MailAccount.objects.create(user=self.user, slot=1, transport=MailAccount.TRANSPORT_GMAIL)
        self.api = APIClient()
        self.api.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(self.user).access_token}")
        for target, value in (
            ("core.views.gmail_oauth_ready", True),
            ("email_automation.gmail_auth.gmail_oauth_matches_configured", (True, "me@gmail.com", "me@gmail.com")),
        ):
            p = mock.patch(target, return_value=value)
            self.addCleanup(p.stop)
            setattr(self, target.rsplit(".", 1)[1], p.start())
        p = mock.patch("core.views.GmailClient")
        self.addCleanup(p.stop)
        self.client_cls = p.start()
        self.listing = self.client_cls.return_value.list_inbox_thread_summaries
        self.listing.return_value = [{"thread_id": "t1", "message_id": "m1", "subject": "Hi"}]

    def _get(self, extra: str = ""):
        res = self.api.get(f"/api/v1/gmail/inbox?account_id={self.acc.id}{extra}")
        self.assertEqual(res.status_code, 200, res.content[:300])
        return res.json()

    def test_second_load_is_served_from_cache(self):
        first, second = self._get(), self._get()
        self.assertEqual(first["threads"], second["threads"])
        self.assertEqual(second["profile_email"], "me@gmail.com")
        self.assertEqual(self.listing.call_count, 1)
        self.assertEqual(self.gmail_oauth_matches_configured.call_count, 1)

    def test_refresh_param_bypasses_cache(self):
        self._get()
        self._get("&refresh=1")
        self.assertEqual(self.listing.call_count, 2)

    def test_email_mismatch_is_not_cached(self):
        self.gmail_oauth_matches_configured.return_value = (False, "other@gmail.com", "me@gmail.com")
        res = self.api.get(f"/api/v1/gmail/inbox?account_id={self.acc.id}")
        self.assertEqual(res.json()["error"], "oauth_email_mismatch")
        self.gmail_oauth_matches_configured.return_value = (True, "me@gmail.com", "me@gmail.com")
        self.assertEqual(self._get()["threads"][0]["thread_id"], "t1")
        self.listing.assert_called_once()
