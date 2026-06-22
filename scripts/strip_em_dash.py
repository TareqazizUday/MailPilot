from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET_DIRS = [ROOT / "templates", ROOT / "static" / "js", ROOT / "static" / "css"]
EXTRA_FILES = [
    ROOT / "core" / "marketing.py",
    ROOT / "core" / "views.py",
    ROOT / "core" / "contact_mail.py",
    ROOT / "core" / "legal_content.py",
    ROOT / "core" / "telegram_mail_stats.py",
    ROOT / "core" / "telegram_inbox.py",
    ROOT / "core" / "admin.py",
    ROOT / "core" / "models.py",
]
EM = "\u2014"
EN = "\u2013"


def transform(text: str) -> str:
    text = text.replace(f"MailPilot {EM} ", "MailPilot | ")
    text = text.replace(f" {EM} MailPilot", " | MailPilot")
    text = text.replace(f"Choose payment {EM} MailPilot", "Choose payment | MailPilot")
    text = text.replace('|default:"—"', '|default:"-"')
    text = text.replace("|| '—'", "|| '-'")
    text = text.replace('|| "—"', '|| "-"')
    text = text.replace("=== '—'", "=== '-'")
    text = text.replace('=== "—"', '=== "-"')
    text = text.replace("!== '—'", "!== '-'")
    text = text.replace('textContent === "—"', 'textContent === "-"')
    text = text.replace(">—<", ">-<")
    text = text.replace('"—"', '"-"')
    text = text.replace("'—'", "'-'")
    text = text.replace(f" {EM} ", " - ")
    text = text.replace(EM, "-")
    text = text.replace(f" {EN} ", " - ")
    text = text.replace(EN, "-")
    return text


def main() -> None:
    changed: list[str] = []
    for path in EXTRA_FILES:
        if not path.is_file():
            continue
        original = path.read_text(encoding="utf-8")
        updated = transform(original)
        if updated != original:
            path.write_text(updated, encoding="utf-8", newline="\n")
            changed.append(str(path.relative_to(ROOT)))
    for base in TARGET_DIRS:
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix not in {".html", ".js", ".txt", ".css"}:
                continue
            original = path.read_text(encoding="utf-8")
            updated = transform(original)
            if updated != original:
                path.write_text(updated, encoding="utf-8", newline="\n")
                changed.append(str(path.relative_to(ROOT)))
    print(f"changed {len(changed)}")
    for item in changed:
        print(item)


if __name__ == "__main__":
    main()
