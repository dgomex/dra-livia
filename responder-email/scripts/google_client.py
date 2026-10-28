"""Shared Google auth for the responder-email scripts. All configuration comes from environment variables.

Required:
  GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REFRESH_TOKEN
Optional:
  EMAIL_STYLE_LABEL     Gmail label on the sent emails that define tone and formatting
  GMAIL_USER            Gmail user id (default "me")
  EMAIL_WORKDIR         working folder for attachments, specs and style packs

No file is read for configuration: set the variables in your shell profile, your secret
manager, or Claude Code's settings.json "env" block. Nothing here ever sends email
(the gmail.send scope is never requested).

Usage: python google_client.py --check
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.compose",
]
REQUIRED_ENV = ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_REFRESH_TOKEN")
TOKEN_URI = "https://oauth2.googleapis.com/token"
MIN_LABEL_SAMPLES = 8
RENEW_HELP = (
    "Renovar o token: rodar scripts/get_refresh_token.py --save (abre o navegador para entrar no Google "
    "e grava o token no perfil do shell). Ver SKILL.md, seção 'Token inválido ou ausente'."
)
# A query that already names a place (in:sent, in:anywhere, label:x) is left alone.
_FOLDER_OPERATOR = re.compile(r"(^|[\s(])(in|label):", re.I)


def emit(obj) -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(obj, indent=2, ensure_ascii=False))


def fail(message: str, **extra) -> None:
    emit({"error": message, **extra})
    sys.exit(1)


def env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    return value if value else default


def gmail_user() -> str:
    return env("GMAIL_USER", "me")


def workdir(override: str | None = None) -> Path:
    """Folder for run artifacts. Holds personal data: never commit it."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = Path(override or env("EMAIL_WORKDIR") or Path.cwd() / "email-runs" / stamp).resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


def scope_query(query: str, all_folders: bool = False) -> str:
    """Searches look only in the inbox unless the query names a folder or all_folders is set."""
    if all_folders or _FOLDER_OPERATOR.search(query):
        return query
    return f"in:inbox ({query})" if query.strip() else "in:inbox"


def find_label(svc, user: str, name: str) -> dict | None:
    """Gmail label by name, case-insensitive (Gmail treats label names that way)."""
    labels = svc.users().labels().list(userId=user).execute().get("labels", [])
    return next((lb for lb in labels if lb["name"].lower() == name.strip().lower()), None)


_creds = None


def credentials():
    global _creds
    if _creds is not None:
        return _creds
    missing = [name for name in REQUIRED_ENV if not env(name)]
    if missing == ["GOOGLE_REFRESH_TOKEN"]:
        fail("Missing Google credentials in the environment", missing=missing, renew_token=True, help=RENEW_HELP)
    if missing:
        fail(
            "Missing Google credentials in the environment",
            missing=missing,
            help="Ver SKILL.md, seção 'Configuração do Google'. GOOGLE_CLIENT_ID e GOOGLE_CLIENT_SECRET vêm do escritório.",
        )
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
    except ImportError:
        fail("Missing Python dependencies", help="pip install -r requirements.txt")

    creds = Credentials(
        None,
        refresh_token=env("GOOGLE_REFRESH_TOKEN"),
        client_id=env("GOOGLE_CLIENT_ID"),
        client_secret=env("GOOGLE_CLIENT_SECRET"),
        token_uri=TOKEN_URI,
    )
    try:
        creds.refresh(Request())
    except Exception as exc:  # noqa: BLE001 - any auth failure comes out as JSON
        # invalid_grant = token expired or revoked; a new consent fixes it.
        renew = "invalid_grant" in str(exc) or "unauthorized_client" in str(exc)
        fail("Could not refresh the Google access token", detail=str(exc),
             renew_token=renew, **({"help": RENEW_HELP} if renew else {}))
    _creds = creds
    return creds


def gmail():
    from googleapiclient.discovery import build

    return build("gmail", "v1", credentials=credentials(), cache_discovery=False)


def main() -> None:
    parser = argparse.ArgumentParser(description="Check the credentials, Gmail access and the style label.")
    parser.add_argument("--check", action="store_true", help="Check access")
    args = parser.parse_args()
    if not args.check:
        parser.print_help()
        return
    creds = credentials()
    svc, user = gmail(), gmail_user()
    profile = svc.users().getProfile(userId=user).execute()
    result = {"ok": True, "gmail_account": profile.get("emailAddress")}
    granted = getattr(creds, "granted_scopes", None)
    if granted:
        result["missing_scopes"] = [s for s in SCOPES if s not in granted]
        result["ok"] = not result["missing_scopes"]
        if result["missing_scopes"]:
            result["renew_token"], result["help"] = True, RENEW_HELP

    # A weak label is a warning, not a failure: style_pack.py falls back to recent sent emails.
    name = env("EMAIL_STYLE_LABEL")
    label = find_label(svc, user, name) if name else None
    if not name:
        result["style_label_warning"] = "EMAIL_STYLE_LABEL is not set"
    elif not label:
        result["style_label_warning"] = f"Gmail label not found: {name}"
    else:
        sent = svc.users().messages().list(userId=user, labelIds=[label["id"], "SENT"], maxResults=50).execute()
        result["style_label"] = label["name"]
        result["style_label_sent_messages"] = len(sent.get("messages", []))
        if result["style_label_sent_messages"] < MIN_LABEL_SAMPLES:
            result["style_label_warning"] = (
                f"label {label['name']} has {result['style_label_sent_messages']} sent emails, "
                f"needs at least {MIN_LABEL_SAMPLES}"
            )
    if "style_label_warning" in result:
        result["style_fallback"] = "serão usados os últimos 10 e-mails enviados; ver SKILL.md, seção 'Pacote de estilo'"
    emit(result)


if __name__ == "__main__":
    main()
