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

import datetime as dt
import plistlib
from dataclasses import dataclass
from pathlib import Path

from bs4 import BeautifulSoup
from bs4.element import NavigableString, Tag

try:
    from zoneinfo import ZoneInfo  # py39+
except Exception:
    ZoneInfo = None

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


# --- Stickies models & reader ---
@dataclass
class StickyNote:
    title: str
    created: dt.datetime
    modified: dt.datetime
    html: Optional[str]
    plain: str
    source_id: str


def _extract_note_candidates(obj) -> list[dict]:
    import re as _re

    found = []

    def visit(x):
        if isinstance(x, dict):
            rtf_keys = [k for k in x.keys() if _re.search(r"rtf|nsrtf|rtfd|textdata", k, _re.I)]
            if rtf_keys:
                found.append(x)
            for v in x.values():
                visit(v)
        elif isinstance(x, list):
            for v in x:
                visit(v)

    visit(obj)
    return found


def _get_bytes_from_candidate(d: dict) -> Optional[bytes]:
    for k in ["NSRTFData", "NSRTF", "RTF", "RTFD", "TextData", "Data", "NoteData"]:
        if k in d:
            v = d[k]
            if isinstance(v, (bytes, bytearray)):
                return bytes(v)
            if isinstance(v, dict):
                for kk in ("NS.data", "data", "bytes"):
                    if kk in v and isinstance(v[kk], (bytes, bytearray)):
                        return bytes(v[kk])
    return None


def _get_dt(d: dict, hint: str, tz: Optional["ZoneInfo"]) -> Optional[dt.datetime]:
    import re as _re

    for k, v in d.items():
        if _re.search(hint, k, _re.I):
            if isinstance(v, dt.datetime):
                return v if v.tzinfo or not tz else v.replace(tzinfo=tz)
            if isinstance(v, (int, float)):
                return dt.datetime.fromtimestamp(float(v), tz=tz)
            if isinstance(v, str):
                try:
                    t = dt.datetime.fromisoformat(v)
                    return t if t.tzinfo or not tz else t.replace(tzinfo=tz)
                except Exception:
                    pass
    return None


def read_stickies_db(db_path: Path, tz_str: str) -> list[StickyNote]:
    tz = ZoneInfo(tz_str) if ZoneInfo else None
    with open(db_path, "rb") as f:
        data = plistlib.load(f)
    notes: list[StickyNote] = []
    for idx, cand in enumerate(_extract_note_candidates(data)):
        rtf = _get_bytes_from_candidate(cand)
        if not rtf:
            continue
        html, plain = rtf_to_html_and_text(rtf)
        created = _get_dt(cand, r"create|birth", tz) or dt.datetime.now(tz)
        modified = _get_dt(cand, r"modif|update", tz) or created
        title = truncate_title(first_nonempty_line(plain))
        notes.append(StickyNote(title, created, modified, html, plain, f"db#{idx}"))
    return notes


# --- HTML → Notion blocks ---
def _text_obj(content: str, **ann):
    return {
        "type": "text",
        "text": {"content": content, "link": None},
        "annotations": {
            "bold": bool(ann.get("bold")),
            "italic": bool(ann.get("italic")),
            "strikethrough": False,
            "underline": bool(ann.get("underline")),
            "code": bool(ann.get("code")),
            "color": "default",
        },
        "plain_text": content,
        "href": None,
    }


def _inline_from_node(node: Tag | NavigableString):
    out = []

    def push(txt):
        for c in chunk_text(txt):
            out.append(_text_obj(c))

    if isinstance(node, NavigableString):
        push(str(node))
        return out
    tag = node.name.lower()
    ann = {
        "bold": tag in ("strong", "b"),
        "italic": tag in ("em", "i"),
        "underline": tag == "u",
        "code": tag == "code",
    }
    for child in node.children:
        out.extend(_inline_from_node(child))
    if any(ann.values()):
        for i in out:
            for k, v in ann.items():
                if v:
                    i["annotations"][k] = True
    return out


def html_to_blocks(html: str):
    soup = BeautifulSoup(html, "html.parser")
    body = soup.body or soup
    blocks = []
    for node in body.children:
        if isinstance(node, NavigableString):
            txt = normalize_ws(str(node))
            if txt:
                blocks.append(
                    {
                        "object": "block",
                        "type": "paragraph",
                        "paragraph": {"rich_text": [_text_obj(txt)]},
                    }
                )
            continue
        if not isinstance(node, Tag):
            continue
        tag = node.name.lower()
        if tag in ("h1", "h2", "h3"):
            level = {"h1": "heading_1", "h2": "heading_2", "h3": "heading_3"}[tag]
            blocks.append(
                {"object": "block", "type": level, level: {"rich_text": _inline_from_node(node)}}
            )
        elif tag in ("ul", "ol"):
            ordered = tag == "ol"
            for li in node.find_all("li", recursive=False):
                t = "numbered_list_item" if ordered else "bulleted_list_item"
                blocks.append(
                    {"object": "block", "type": t, t: {"rich_text": _inline_from_node(li)}}
                )
        elif tag in ("pre",):
            code_text = node.get_text("\n")
            blocks.append(
                {
                    "object": "block",
                    "type": "code",
                    "code": {"language": "plain text", "rich_text": [_text_obj(code_text)]},
                }
            )
        elif tag in ("blockquote",):
            blocks.append(
                {
                    "object": "block",
                    "type": "quote",
                    "quote": {"rich_text": _inline_from_node(node)},
                }
            )
        else:
            blocks.append(
                {
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {"rich_text": _inline_from_node(node) or [_text_obj("")]},
                }
            )
    if not blocks:
        blocks.append(
            {"object": "block", "type": "paragraph", "paragraph": {"rich_text": [_text_obj("")]}}
        )
    return blocks
