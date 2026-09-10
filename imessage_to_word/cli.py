"""Command-line interface: python3 -m imessage_to_word "+1 555 123 4567"."""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from . import chatdb, contacts
from .export import (
    ExportError,
    ExportOptions,
    NoMessagesFound,
    export_to_word,
    format_date_time,
    parse_date_input,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="imessage-to-word",
        description="Save an iMessage conversation as a Word document.",
    )
    parser.add_argument("number", nargs="?", help="phone number or Apple ID email")
    parser.add_argument("-o", "--out", help="where to write the .docx")
    parser.add_argument("--name", help="what to call the other person (default: Contacts, else the number)")
    parser.add_argument("--me", default="Me", help='what to call yourself (default: "Me")')
    parser.add_argument("--from", dest="start", help="only messages on/after this date (YYYY-MM-DD)")
    parser.add_argument("--to", dest="end", help="only messages on/before this date (YYYY-MM-DD)")
    parser.add_argument("--groups", action="store_true", help="also include group chats they are in")
    parser.add_argument("--reactions", action="store_true", help="include tapbacks (Loved, Liked, ...)")
    parser.add_argument("--no-contacts", action="store_true", help="skip the Contacts lookup")
    parser.add_argument("--db", help="path to a chat.db (default: your Messages database)")
    parser.add_argument("--list", action="store_true", help="list the numbers found in Messages and exit")
    parser.add_argument("--open", action="store_true", help="open the document when it is finished")
    return parser


def _print_list(db_path, use_contacts: bool = True, limit: int = 40) -> int:
    with chatdb.open_chat_db(Path(db_path) if db_path else None) as conn:
        rows = chatdb.list_conversations(conn, limit=limit)
    if not rows:
        print("No conversations found in the Messages database.")
        return 1
    print("{:<28} {:>9}  {}".format("Handle", "Messages", "Last message"))
    print("-" * 72)
    for row in rows:
        last = format_date_time(row["last_date"]) if row["last_date"] else "unknown"
        name = (contacts.lookup_name(row["handle"]) or "") if use_contacts else ""
        label = "{}  {}".format(row["handle"], "({})".format(name) if name else "")
        print("{:<28} {:>9}  {}".format(label[:28], row["message_count"], last))
    return 0


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)

    try:
        if args.list:
            return _print_list(args.db, use_contacts=not args.no_contacts)

        if not args.number:
            build_parser().print_help()
            return 2

        options = ExportOptions(
            number=args.number,
            their_name=args.name,
            my_name=args.me or "Me",
            include_groups=args.groups,
            include_reactions=args.reactions,
            start=parse_date_input(args.start),
            end=parse_date_input(args.end, end_of_day=True),
            db_path=Path(args.db) if args.db else None,
            lookup_contact_name=not args.no_contacts,
            link_contact_handles=not args.no_contacts,
        )
        result = export_to_word(
            options,
            output_path=Path(args.out) if args.out else None,
            progress=lambda message: print(message, file=sys.stderr),
        )
    except NoMessagesFound as error:
        print(error, file=sys.stderr)
        return 1
    except (ExportError, chatdb.ChatDBError) as error:
        print("Error: {}".format(error), file=sys.stderr)
        return 1

    print("\nSaved {}".format(result.path))
    print("  {} messages  ({} from {}, {} from {})".format(
        result.message_count, result.from_them, result.their_name,
        result.from_me, result.my_name,
    ))
    if result.first_date and result.last_date:
        print("  {}  to  {}".format(
            format_date_time(result.first_date), format_date_time(result.last_date)
        ))

    if args.open:
        try:
            subprocess.run(["open", str(result.path)], check=False)
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
