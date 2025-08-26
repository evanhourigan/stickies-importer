import argparse
import hashlib
import os
import re
from typing import Optional, Tuple

from dotenv import load_dotenv
from notion_client import Client

# Optional converters
try:
    import pypandoc  # type: ignore

    HAS_PANDOC = True
except Exception:
    HAS_PANDOC = False

try:
    from striprtf.striprtf import rtf_to_text  # type: ignore

    HAS_STRIPRTF = True
except Exception:
    HAS_STRIPRTF = False

from bs4 import BeautifulSoup

load_dotenv()

token = os.environ.get("NOTION_TOKEN")
database_id = os.environ.get("NOTION_DB_ID")

default_tz = os.environ.get("TZ", "America/New_York")

if not token:
    raise SystemExit("ERROR: NOTION_TOKEN is not set (see .env.example).")

if not database_id:
    raise SystemExit("ERROR: NOTION_DB_ID is not set (see .env.example).")

parser = argparse.ArgumentParser()
parser.add_argument("--tz", default=default_tz, help="IANA timezone (e.g. America/Los_Angeles).")
parser.add_argument("--verbose", action="store_true", help="Verbose output.")


def main():
    args = parser.parse_args()
    notion = Client(auth=token)

    if args.verbose:
        print(f"Using database ID: {database_id}")
        print(f"Using TZ: {args.tz}")

    try:
        # Simple connectivity check: retrieve database metadata
        db = notion.databases.retrieve(database_id=database_id)
        if args.verbose:
            title = "".join([t.get("plain_text", "") for t in db.get("title", [])]) or "(untitled)"
            print(f"Connected to Notion DB: {title}")
        print("OK: Notion connection verified.")
    except Exception as e:
        print(f"ERROR: Failed to connect to Notion database")
        print(f"Database ID: {database_id}")
        print(f"Error: {e}")
        print("\nTroubleshooting:")
        print("1. Verify the NOTION_DB_ID is correct")
        print("2. Ensure your Notion integration has access to this database")
        print("3. Check that the database is shared with your integration")
        raise SystemExit(1)


if __name__ == "__main__":
    main()

# --- Utility helpers ---
MAX_TITLE_LEN = 200
MAX_TEXT_CHUNK = 1800


def normalize_ws(s: str) -> str:
    s = s.replace("\u00A0", " ")
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def first_nonempty_line(text: str) -> str:
    for line in text.splitlines():
        ln = normalize_ws(line)
        if ln:
            return ln
    return "(untitled)"


def truncate_title(s: str) -> str:
    s = s.strip()
    return (s[: MAX_TITLE_LEN - 1] + "…") if len(s) > MAX_TITLE_LEN else s


def chunk_text(s: str, n: int = MAX_TEXT_CHUNK):
    chunks, buf, count = [], [], 0
    for part in re.split(r"(\s+)", s):
        if count + len(part) > n:
            chunks.append("".join(buf))
            buf, count = [part], len(part)
        else:
            buf.append(part)
            count += len(part)
    if buf:
        chunks.append("".join(buf))
    return [c for c in chunks if c]


def sha256_hex(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def rtf_to_html_and_text(rtf_bytes: bytes) -> Tuple[Optional[str], str]:
    """Return (html or None, plain_text). Prefer Pandoc HTML; fallback to plain."""
    try:
        s = rtf_bytes.decode("utf-8", errors="ignore")
    except Exception:
        s = rtf_bytes.decode("latin-1", errors="ignore")

    html = None
    if HAS_PANDOC:
        try:
            html = pypandoc.convert_text(s, "html", format="rtf")
        except Exception:
            html = None

    if html:
        plain = BeautifulSoup(html, "html.parser").get_text("\n")
        plain = "\n".join([ln.rstrip() for ln in plain.splitlines()])
        return html, plain

    # Fallback: plain text via striprtf or crude regex strip
    if HAS_STRIPRTF:
        try:
            text = rtf_to_text(s)
        except Exception:
            text = ""
    else:
        import re as _re

        text = _re.sub(r"\\'[0-9a-fA-F]{2}", " ", s)
        text = _re.sub(r"\\[a-zA-Z]+-?\d*\s?", "", text)
        text = _re.sub(r"[{}]", "", text)
    text = "\n".join([ln.rstrip() for ln in text.splitlines()])
    return None, text
