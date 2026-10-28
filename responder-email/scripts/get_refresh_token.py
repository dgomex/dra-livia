"""Run the OAuth consent flow locally and get a new GOOGLE_REFRESH_TOKEN.

Needs GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in the environment, from a Google Cloud
OAuth client of type "Desktop app". Opens a browser for consent (if it does not open, the
sign-in URL is printed so it can be opened by hand).

Usage:
  python get_refresh_token.py                     print the export line (copy it yourself)
  python get_refresh_token.py --save              write it to the shell profile (~/.zshrc for zsh)
  python get_refresh_token.py --save --copy       ...and put the token on the clipboard (macOS),
                                                  to paste into a cloud environment's variables
  python get_refresh_token.py --save --profile ~/.bash_profile

With --save the token is never printed: the profile line is replaced (or added) and a backup
of the profile is kept next to it. The output is JSON.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from google_client import SCOPES, TOKEN_URI, emit, env, fail  # noqa: E402

TOKEN_LINE = re.compile(r"^\s*(export\s+)?GOOGLE_REFRESH_TOKEN=.*$", re.M)


def default_profile() -> Path:
    shell = Path(os.environ.get("SHELL", "")).name
    if shell == "bash":
        return Path.home() / (".bash_profile" if sys.platform == "darwin" else ".bashrc")
    return Path.home() / ".zshrc"


def save_to_profile(profile: Path, token: str) -> dict:
    line = f"export GOOGLE_REFRESH_TOKEN='{token}'"
    text = profile.read_text(encoding="utf-8") if profile.exists() else ""
    backup = None
    if text:
        backup = profile.with_name(profile.name + ".bak-responder-email")
        shutil.copy2(profile, backup)
    if TOKEN_LINE.search(text):
        # Keep only the first line, so an older token further down can't override the new one.
        text = TOKEN_LINE.sub(line, text, count=1)
        first = TOKEN_LINE.search(text).end()
        text = text[:first] + TOKEN_LINE.sub("", text[first:])
        action = "replaced"
    else:
        text = text + ("" if not text or text.endswith("\n") else "\n") + line + "\n"
        action = "added"
    profile.write_text(text, encoding="utf-8")
    profile.chmod(0o600)
    return {"profile": str(profile), "action": action, "backup": str(backup) if backup else None}


def copy_to_clipboard(token: str) -> bool:
    if not shutil.which("pbcopy"):
        return False
    subprocess.run(["pbcopy"], input=token.encode(), check=True)
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--save", action="store_true", help="Write the token to the shell profile instead of printing it")
    parser.add_argument("--profile", help="Shell profile to write (default: ~/.zshrc, or the bash profile for bash)")
    parser.add_argument("--copy", action="store_true", help="Also copy the token to the clipboard (macOS)")
    args = parser.parse_args()

    client_id, client_secret = env("GOOGLE_CLIENT_ID"), env("GOOGLE_CLIENT_SECRET")
    if not client_id or not client_secret:
        fail("Defina GOOGLE_CLIENT_ID e GOOGLE_CLIENT_SECRET primeiro (ver SKILL.md, seção 'Configuração do Google')")

    from google_auth_oauthlib.flow import InstalledAppFlow

    flow = InstalledAppFlow.from_client_config(
        {
            "installed": {
                "client_id": client_id,
                "client_secret": client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": TOKEN_URI,
                "redirect_uris": ["http://localhost"],
            }
        },
        SCOPES,
    )
    creds = flow.run_local_server(port=0, access_type="offline", prompt="consent",
                                  authorization_prompt_message="Abra este link para entrar no Google: {url}")
    if not creds.refresh_token:
        fail("Google did not return a refresh token; remove the app's access at myaccount.google.com/permissions and retry")

    if not args.save:
        print("Add this to your environment (keep it secret, never commit it):")
        print(f"export GOOGLE_REFRESH_TOKEN='{creds.refresh_token}'")
        return

    profile = Path(args.profile).expanduser() if args.profile else default_profile()
    result = {"ok": True, **save_to_profile(profile, creds.refresh_token)}
    if args.copy:
        result["copied_to_clipboard"] = copy_to_clipboard(creds.refresh_token)
    result["reload"] = f"source {profile}"
    emit(result)


if __name__ == "__main__":
    main()
