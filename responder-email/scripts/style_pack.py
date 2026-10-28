"""Build the "style pack": the owner's model emails that define tone and formatting.

Primary source: sent emails carrying the Gmail label EMAIL_STYLE_LABEL. The label counts only
when it has at least MIN_LABEL_SAMPLES (8) sent emails. Otherwise the pack falls back to the
latest FALLBACK_COUNT (10) sent emails; any labelled samples found are kept first.

Fallback reasons: label not set, label not found, fewer than 8 labelled sent emails.
Credential errors are not a fallback reason: without Gmail access nothing can be read.

Only messages sent by the owner are used (if a whole thread is labelled, the other party's
messages are skipped). Quoted history is removed, so each sample is exactly what the owner
wrote, in its original Gmail HTML.

Usage:
  python style_pack.py                  # label from EMAIL_STYLE_LABEL
  python style_pack.py --label "Style"  # override the label
  python style_pack.py --max 30         # max labelled samples (default 20, newest first)

Writes <workdir>/style-pack.json and <workdir>/style-pack.md and prints a JSON summary.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from google_client import MIN_LABEL_SAMPLES, emit, env, fail, find_label, gmail, gmail_user, workdir  # noqa: E402
from gmail_read import get_message, summarize  # noqa: E402

MAX_SAMPLE_CHARS = 15000
FALLBACK_COUNT = 10


def sent_samples(svc, user: str, label_ids: list, query: str | None, limit: int, skip: set) -> list:
    """Newest-first sent emails matching label_ids/query, skipping empty bodies and ids in skip."""
    samples, token = [], None
    while len(samples) < limit:
        resp = svc.users().messages().list(
            userId=user, labelIds=label_ids, q=query, maxResults=100, pageToken=token
        ).execute()
        for ref in resp.get("messages", []):
            if len(samples) >= limit:
                break
            if ref["id"] in skip:
                continue
            item = summarize(get_message(svc, user, ref["id"]), with_html=True)
            if not (item["html"] or item["text"]):
                continue
            samples.append({
                "title": item["subject"],
                "message_id": item["id"],
                "thread_id": item["thread_id"],
                "date": item["date"],
                "to": item["to"],
                "html": item["html"][:MAX_SAMPLE_CHARS],
                "html_truncated": len(item["html"]) > MAX_SAMPLE_CHARS,
                "text": item["text"],
            })
        token = resp.get("nextPageToken")
        if not token:
            break
    return samples


def markdown(pack: dict) -> str:
    if pack["fallback"]:
        head = f"# Style pack: FALLBACK to latest sent emails ({pack['fallback_reason']})"
    else:
        head = f"# Style pack: Gmail label \"{pack['label']}\""
    out = [head, ""]
    for i, sample in enumerate(pack["samples"], 1):
        out += [f"## Sample {i} [{sample['origin']}]: {sample['title']}", f"{sample['date']} · to {sample['to']}", "",
                "```html", sample["html"] or sample["text"], "```", ""]
    return "\n".join(out)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--label", help="Gmail label name (overrides EMAIL_STYLE_LABEL)")
    parser.add_argument("--max", type=int, default=20, help="Max labelled samples, newest first (default 20)")
    parser.add_argument("--out", help="Output folder (default $EMAIL_WORKDIR or ./email-runs/<timestamp>)")
    args = parser.parse_args()

    svc, user = gmail(), gmail_user()
    name = args.label or env("EMAIL_STYLE_LABEL")
    label = find_label(svc, user, name) if name else None
    labelled = sent_samples(svc, user, [label["id"], "SENT"], None, max(args.max, MIN_LABEL_SAMPLES), set()) if label else []
    for sample in labelled:
        sample["origin"] = "label"

    reason = None
    if not name:
        reason = "EMAIL_STYLE_LABEL is not set"
    elif not label:
        reason = f"Gmail label not found: {name}"
    elif len(labelled) < MIN_LABEL_SAMPLES:
        reason = f"label {label['name']} has {len(labelled)} sent emails, needs at least {MIN_LABEL_SAMPLES}"

    samples = labelled
    if reason:
        recent = sent_samples(svc, user, ["SENT"], "-in:chats", FALLBACK_COUNT,
                              {s["message_id"] for s in labelled})
        for sample in recent:
            sample["origin"] = "recent-sent"
        samples = labelled + recent
    if not samples:
        fail("No sent emails found to learn the style from", fallback_reason=reason)

    pack = {
        "label": label["name"] if label else name,
        "fallback": bool(reason),
        "fallback_reason": reason,
        "samples": samples,
    }
    out = workdir(args.out)
    (out / "style-pack.json").write_text(json.dumps(pack, indent=2, ensure_ascii=False), encoding="utf-8")
    (out / "style-pack.md").write_text(markdown(pack), encoding="utf-8")
    emit({
        "style_pack_json": str(out / "style-pack.json"),
        "style_pack_md": str(out / "style-pack.md"),
        "label": pack["label"],
        "fallback": pack["fallback"],
        "fallback_reason": reason,
        "label_samples": len(labelled),
        "recent_sent_samples": len(samples) - len(labelled),
        "help": "Ver SKILL.md, seção 'Pacote de estilo', para montar o marcador" if reason else None,
    })


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001
        fail("style_pack failed", detail=f"{type(exc).__name__}: {exc}")
