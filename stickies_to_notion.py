import argparse
import hashlib
import os
import re
from typing import Optional, Tuple

from dotenv import load_dotenv
from notion_client import Client
from notion_client.errors import APIResponseError

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

VERSION = "0.1.0"
parser = argparse.ArgumentParser(
    prog="stickies_to_notion.py",
    description=(
        "Import macOS Stickies into a Notion database, preserving title, created/modified dates, "
        "and full content as page body blocks."
    ),
    epilog="""Examples:
  Dry-run (no writes, just preview 5 notes):
    python stickies_to_notion.py --dry-run --verbose

  Import full Stickies database (default location):
    python stickies_to_notion.py --mode db --verbose

  Import Stickies from a copied DB file:
    python stickies_to_notion.py --db-path /tmp/StickiesDatabase --verbose

Notes:
  • Requires NOTION_TOKEN and NOTION_DB_ID set in your .env
  • Quit Stickies.app before running, or copy the DB to /tmp if locked
""",
    formatter_class=argparse.RawDescriptionHelpFormatter,
)

parser.add_argument(
    "--tz",
    default=default_tz,
    help="IANA timezone (e.g. America/Los_Angeles). Defaults to TZ env var or America/New_York.",
)
parser.add_argument(
    "--verbose",
    action="store_true",
    help="Enable verbose logging (prints Notion DB title, number of notes, upsert actions, etc.).",
)
parser.add_argument(
    "--mode",
    choices=["db", "rtf_dir"],
    default="db",
    help="Source mode: supports 'db' (StickiesDatabase plist) and 'rtf_dir' (RTF files).",
)
parser.add_argument(
    "--db-path",
    default=default_db_path(),
    help="Path to StickiesDatabase file (DB mode). Defaults to ~/Library/StickiesDatabase or the Containers path if present.",
)
parser.add_argument(
    "--rtf-dir",
    default="~/Library/Containers/com.apple.Stickies/Data/Library",
    help="Folder containing Stickies .rtf/.rtfd files (RTF dir mode).",
)


def default_db_path() -> str:
    """Return the most likely StickiesDatabase path."""
    candidates = [
        "~/Library/StickiesDatabase",  # modern macOS
        "~/Library/Containers/com.apple.Stickies/Data/Library/StickiesDatabase",  # older sandboxed
    ]
    for c in candidates:
        if Path(os.path.expanduser(c)).exists():
            return c
    # Fall back to the modern location even if it doesn't exist yet
    return candidates[0]


parser.add_argument(
    "--db-path",
    default=default_db_path(),
    help="Path to StickiesDatabase file. Defaults to ~/Library/StickiesDatabase "
    "or the Containers path if present.",
)
parser.add_argument(
    "--show-db-path",
    action="store_true",
    help="Print the Stickies database path the script will use and exit.",
)
parser.add_argument(
    "--limit", type=int, default=None, help="Import at most N notes (useful for testing)."
)
parser.add_argument(
    "--dry-run",
    action="store_true",
    help="Parse and show preview without writing anything to Notion.",
)
parser.add_argument(
    "--version",
    action="version",
    version=f"%(prog)s {VERSION}",
    help="Show script version and exit.",
)


def main():
    args = parser.parse_args()
    notion = Client(auth=token)

    if args.verbose:
        print(f"Using database ID: {database_id}")
        print(f"Using TZ: {args.tz}")

    db = notion.databases.retrieve(database_id=database_id)  # connectivity check
    if args.verbose:
        title = "".join([t.get("plain_text", "") for t in db.get("title", [])]) or "(untitled)"
        print(f"Connected to Notion DB: {title} ({database_id})")
        print(f"Using TZ: {args.tz}")

    if args.show_db_path:
        print(f"Stickies DB path: {os.path.expanduser(args.db_path)}")
        return

    # Read Stickies notes
    if args.mode == "db":
        db_path = Path(os.path.expanduser(args.db_path))
        if not db_path.exists():
            # If DB file doesn't exist, try container folder (auto-fallback to rtf_dir mode)
            rtf_folder = Path(os.path.expanduser(args.rtf_dir))
            rtf_candidates = list(rtf_folder.glob("*.rtf")) + list(rtf_folder.glob("*.rtfd"))
            if rtf_candidates:
                if args.verbose:
                    print(
                        f"No DB file at {db_path}, but found {len(rtf_candidates)} RTF files in {rtf_folder}. Falling back to rtf_dir mode."
                    )
                args.mode = "rtf_dir"
            else:
                # Friendly guidance if nothing is found at the chosen path
                candidates = [
                    Path(os.path.expanduser("~/Library/StickiesDatabase")),
                    Path(
                        os.path.expanduser(
                            "~/Library/Containers/com.apple.Stickies/Data/Library/StickiesDatabase"
                        )
                    ),
                ]
                existing = [str(p) for p in candidates if p.exists()]
                msg_lines = [
                    f"ERROR: Stickies database not found at: {db_path}",
                    "",
                    "Troubleshooting tips:",
                    "  • Make sure Stickies.app has at least one note saved.",
                    "  • Quit Stickies.app before running this script (the DB can be locked).",
                    "  • Try copying the DB if locked, then point --db-path at the copy:",
                    "      cp ~/Library/StickiesDatabase /tmp/StickiesDatabase",
                    "      python stickies_to_notion.py --db-path /tmp/StickiesDatabase --verbose",
                    "",
                    "Common locations checked:",
                    f"  - {candidates[0]}",
                    f"  - {candidates[1]}",
                ]
                if existing:
                    msg_lines.append("")
                    msg_lines.append("Found a database at:")
                    for p in existing:
                        msg_lines.append(f"  • {p}")
                    msg_lines.append("Re-run with:  --db-path <one of the above>")
                else:
                    msg_lines.append("")
                    msg_lines.append("No Stickies database was found in the common locations.")
                    msg_lines.append("Open Stickies.app, create a sample note, then run:")
                    msg_lines.append("  python stickies_to_notion.py --show-db-path")
                raise SystemExit("\n".join(msg_lines))
            try:
                notes = read_stickies_db(db_path, args.tz)
            except PermissionError as e:
                raise SystemExit(
                    f"ERROR: Could not open Stickies database at {db_path} — it may be locked.\n"
                    f"Tip: Quit Stickies.app, or copy the database somewhere else (e.g. /tmp) and run with --db-path.\n\n{e}"
                )

    elif args.mode == "rtf_dir":
        rtf_dir = Path(os.path.expanduser(args.rtf_dir))
        if not rtf_dir.exists():
            raise SystemExit(f"ERROR: RTF directory not found at: {rtf_dir}")
        notes = read_rtf_dir(rtf_dir, args.tz)

    else:
        notes = []

    if args.limit:
        notes = notes[: args.limit]

    if not notes:
        print("No notes found.")
        return

    # Build stable hashes (content + created)
    items = []
    for n in notes:
        h = sha256_hex(normalize_ws(n.plain) + "|" + n.created.isoformat())
        items.append((n, h))

    if args.dry_run:
        print(f"[DRY RUN] Would import {len(items)} notes. Showing first 5:")
        for n, h in items[:5]:
            print(f"— {n.title} | created {n.created} | modified {n.modified} | hash {h[:10]}…")
        return

    existing = fetch_existing_hashes(notion, database_id)
    if args.verbose:
        print(f"Found {len(existing)} existing Import Hashes; upserting {len(items)} notes.")

    for n, h in items:
        page_id = existing.get(h)
        create_or_update_page(notion, database_id, n, page_id, h, verbose=args.verbose)


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


def read_rtf_dir(folder: Path, tz_str: str) -> list[StickyNote]:
    tz = ZoneInfo(tz_str) if ZoneInfo else None
    notes: list[StickyNote] = []
    if not folder.exists():
        return notes
    for p in sorted(list(folder.glob("*.rtf")) + list(folder.glob("*.rtfd"))):
        try:
            raw = p.read_bytes() if p.suffix.lower() == ".rtf" else None
        except Exception:
            continue
        html, plain = rtf_to_html_and_text(raw or b"")
        # Use file timestamps since per-file metadata varies
        st = p.stat()
        created = dt.datetime.fromtimestamp(getattr(st, "st_birthtime", st.st_mtime), tz=tz)
        modified = dt.datetime.fromtimestamp(st.st_mtime, tz=tz)
        title = truncate_title(first_nonempty_line(plain) or p.stem)
        notes.append(StickyNote(title, created, modified, html, plain, str(p)))
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


# --- Notion upsert ---
def fetch_existing_hashes(notion: Client, database_id: str) -> dict[str, str]:
    hashes: dict[str, str] = {}
    cursor = None
    while True:
        resp = notion.databases.query(
            **(
                {"database_id": database_id, "start_cursor": cursor}
                if cursor
                else {"database_id": database_id}
            )
        )
        for page in resp.get("results", []):
            props = page.get("properties", {})
            ih = props.get("Import Hash")
            if ih and ih.get("type") == "rich_text":
                rts = ih.get("rich_text") or []
                if rts:
                    h = rts[0].get("plain_text")
                    if h:
                        hashes[h] = page["id"]
        cursor = resp.get("next_cursor")
        if not resp.get("has_more"):
            break
    return hashes


def create_or_update_page(
    notion: Client,
    database_id: str,
    note,
    page_id: str | None,
    content_hash: str,
    verbose: bool = False,
):
    props = {
        "Name": {"title": [{"type": "text", "text": {"content": note.title}}]},
        "Created": {"date": {"start": note.created.isoformat()}},
        "Modified": {"date": {"start": note.modified.isoformat()}},
        "Import Hash": {"rich_text": [{"type": "text", "text": {"content": content_hash}}]},
    }
    children = (
        html_to_blocks(note.html)
        if note.html
        else [
            {
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [{"type": "text", "text": {"content": note.plain or ""}}]
                },
            }
        ]
    )
    try:
        if page_id:
            if verbose:
                print(f"Updating page {page_id}: {note.title}")
            notion.pages.update(page_id=page_id, properties=props)
            # Append a divider and new content (simple, safe approach)
            notion.blocks.children.append(
                block_id=page_id, children=[{"object": "block", "type": "divider", "divider": {}}]
            )
            BATCH = 80
            for i in range(0, len(children), BATCH):
                notion.blocks.children.append(block_id=page_id, children=children[i : i + BATCH])
        else:
            if verbose:
                print(f"Creating page: {note.title}")
            notion.pages.create(
                parent={"database_id": database_id}, properties=props, children=children
            )
    except APIResponseError as e:
        print(f"ERROR: Notion API failed: {e}")
