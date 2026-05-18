import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "mailpilot.settings")

import django

django.setup()

from django.contrib.auth.models import User

from core import runtime
from core.models import ProcessedMeta
from core.user_settings import build_effective_settings
from email_automation.imap_mailbox import ImapMailbox
from email_automation.worker import _should_consider_email

u = User.objects.get(username="sohelrananull")
e = build_effective_settings(u)
print("User:", u.email)
print("Keywords:", e.SERVICE_KEYWORDS)
print("Threshold:", e.RELEVANCE_THRESHOLD, "Reply:", e.REPLY_MODE)
print("SMTP:", e.SMTP_HOST, e.SMTP_PORT, "SSL", e.SMTP_USE_SSL)

mb = ImapMailbox(settings=e)
threads = mb.list_inbox_summaries(max_threads=10)
print("Inbox threads:", len(threads))
for t in threads:
    subj = (t.get("subject") or "")[:70]
    frm = (t.get("from") or "")[:50]
    print(f"  [{t.get('thread_id')}] {subj} | {frm}")

st = runtime.state_store_for_user(u)
for t in threads:
    uid = t.get("thread_id")
    if uid is None:
        continue
    det = mb.get_thread_for_ui(int(uid))
    msgs = det.get("messages") or []
    if not msgs:
        continue
    last = msgs[-1]
    mid = f"imap:{last.get('id')}"
    subj = str(last.get("subject") or "")
    body = str(last.get("body_text") or last.get("snippet") or "")
    kw_ok = _should_consider_email(e, from_email=last.get("from", ""), subject=subj, body=body)
    meta = st.get_processed_meta(mid)
    print(f"\nUID {uid} mid={mid}")
    print("  subject:", subj[:80])
    print("  keyword_prefilter:", kw_ok)
    print("  already_processed:", meta is not None, meta if meta else "")

print("\n--- trigger poll ---")
r = runtime.trigger_poll_fn(user=u)
print("POLL:", r)
ws = runtime.worker_state()
print("last_error:", ws.last_error)
print("last_result:", ws.last_result)
