"""Create or update a Gmail draft, with attachments, in the thread of a message. NEVER sends.

Usage:
  python save_draft.py --spec <draft.json>

The spec is a JSON file (avoids quoting problems with HTML):
{
  "reply_to_message_id": "<id of the last message in the thread>",  # required
  "draft_id": "<id of an existing draft>",                          # optional: update it instead of creating
  "to": ["client@mail.com"],
  "cc": ["colleague@..."],                                          # optional
  "subject": "Re: ...",                                             # optional: defaults to the message's
  "html_body": "<div>...</div>",
  "text_body": "...",                                               # optional: derived from the HTML
  "attachments": ["/path/file.pdf"]                                 # optional: only what this reply needs
}

The draft stays in the same thread (threadId, In-Reply-To, References). The original message
is not quoted, so the draft never inherits earlier attachments. Updating replaces the whole
message: resend the full HTML and only the intended attachments.
"""
from __future__ import annotations

import argparse
import base64
import html
import json
import mimetypes
import re
import sys
from email.message import EmailMessage
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from google_client import emit, fail, gmail, gmail_user  # noqa: E402

MAX_ATTACH_BYTES = 24 * 1024 * 1024


def html_to_text(body: str) -> str:
    text = re.sub(r"(?i)<br\s*/?>|</p>|</li>|</div>", "\n", body)
    text = re.sub(r"(?i)<li[^>]*>", "- ", text)
    return html.unescape(re.sub(r"<[^>]+>", "", text)).strip()


def as_list(value) -> list:
    if not value:
        return []
    return [value] if isinstance(value, str) else list(value)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--spec", required=True, help="JSON file describing the draft")
    args = parser.parse_args()

    spec = json.loads(Path(args.spec).read_text(encoding="utf-8"))
    reply_id = spec.get("reply_to_message_id")
    draft_id = spec.get("draft_id")
    if not reply_id:
        fail("Missing reply_to_message_id: drafts are always replies in the existing thread")
    to = as_list(spec.get("to"))
    if not to:
        fail("Missing field: to")
    body_html = spec.get("html_body")
    if not body_html:
        fail("Missing field: html_body")

    svc, user = gmail(), gmail_user()
    original = svc.users().messages().get(
        userId=user, id=reply_id, format="metadata",
        metadataHeaders=["Subject", "Message-ID", "References"],
    ).execute()
    headers = {h["name"].lower(): h["value"] for h in original["payload"].get("headers", [])}
    subject = spec.get("subject") or headers.get("subject", "")
    if not subject.lower().startswith("re:"):
        subject = f"Re: {subject}".strip()

    msg = EmailMessage()
    msg["To"] = ", ".join(to)
    cc = as_list(spec.get("cc"))
    if cc:
        msg["Cc"] = ", ".join(cc)
    msg["Subject"] = subject
    if headers.get("message-id"):
        msg["In-Reply-To"] = headers["message-id"]
        msg["References"] = f"{headers.get('references', '')} {headers['message-id']}".strip()
    msg.set_content(spec.get("text_body") or html_to_text(body_html))
    msg.add_alternative(body_html, subtype="html")

    total, attached, too_big = 0, [], []
    for raw_path in as_list(spec.get("attachments")):
        path = Path(raw_path)
        if not path.is_file():
            fail("Attachment not found", path=str(path))
        size = path.stat().st_size
        if total + size > MAX_ATTACH_BYTES:
            too_big.append(path.name)
            continue
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        maintype, subtype = mime.split("/", 1)
        msg.add_attachment(path.read_bytes(), maintype=maintype, subtype=subtype, filename=path.name)
        total += size
        attached.append(path.name)

    message = {"raw": base64.urlsafe_b64encode(msg.as_bytes()).decode(), "threadId": original.get("threadId")}
    if draft_id:
        draft = svc.users().drafts().update(userId=user, id=draft_id, body={"message": message}).execute()
    else:
        draft = svc.users().drafts().create(userId=user, body={"message": message}).execute()

    emit({
        "action": "updated" if draft_id else "created",
        "draft_id": draft["id"],
        "message_id": draft["message"]["id"],
        "thread_id": draft["message"].get("threadId"),
        "link": f"https://mail.google.com/mail/u/0/#drafts?compose={draft['message']['id']}",
        "to": to,
        "cc": cc,
        "subject": subject,
        "attached": attached,
        "not_attached_too_large": too_big,
    })


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001
        fail("save_draft failed", detail=f"{type(exc).__name__}: {exc}")
