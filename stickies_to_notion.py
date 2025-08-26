import argparse
import os

from dotenv import load_dotenv
from notion_client import Client

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
