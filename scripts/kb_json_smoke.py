from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def _ensure_repo_on_path() -> None:
    # Match how manage.py makes local packages importable.
    repo_root = Path(__file__).resolve().parent.parent
    os.chdir(repo_root)
    sys.path.insert(0, str(repo_root))
    try:
        from mailpilot.path_setup import ensure_email_automation_on_path

        ensure_email_automation_on_path(str(repo_root))
    except Exception:
        # Best-effort; direct sys.path insert above is usually enough.
        pass


_ensure_repo_on_path()

from email_automation.kb.extract import chunk_text, documents_from_json_upload  # noqa: E402


def main() -> int:
    p = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("docs/sample_kb_dict.json")
    data = json.loads(p.read_text(encoding="utf-8"))
    docs = documents_from_json_upload(data, source_name=p.name)
    if not docs:
        print("ERROR: 0 documents produced")
        return 2
    ch = chunk_text(docs[0].text)
    print(f"docs={len(docs)} first_title={docs[0].title!r} first_url={docs[0].url!r} chunks={len(ch)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

