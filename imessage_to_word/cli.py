"""Command-line interface: python3 -m imessage_to_word "+1 555 123 4567"."""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from . import chatdb, contacts, phones, preflight
from .export import (
    ExportError,
    ExportOptions,
    NoMessagesFound,
    export_to_word,
    format_date_time,
    large_document_note,
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
    parser.add_argument("--check", action="store_true", help="check this Mac is set up correctly and exit")
    parser.add_argument("--interactive", action="store_true", help="ask for the details instead of taking flags")
    parser.add_argument("--no-copy", action="store_true", help="read chat.db in place instead of copying it first")
    parser.add_argument("--text", action="store_true", help="also save a plain-text copy next to the .docx")
    parser.add_argument("--no-placeholders", action="store_true", help="drop messages that carry no readable text")
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


def _ask(prompt: str, default: str = "") -> str:
    try:
        answer = input(prompt).strip()
    except EOFError:
        return default
    return answer or default


def _ask_yes_no(prompt: str, default: bool = False) -> bool:
    answer = _ask("{} [{}]: ".format(prompt, "y/N" if not default else "Y/n"))
    if not answer:
        return default
    return answer.lower().startswith("y")


def interactive(args) -> int:
    """A question-and-answer version of the app, for when there is no window."""
    print("Save an iMessage conversation as a Word document")
    print("-" * 48)
    number = ""
    while not number:
        number = _ask("Phone number (or Apple ID email): ")
        problem = phones.looks_like_handle(number)
        if problem:
            print("  {}".format(problem))
            if not _ask_yes_no("  Try again?", True):
                return 1
            number = ""

    args.number = number
    args.name = _ask("Their name (Return to use Contacts / the number): ") or None
    args.me = _ask("Your name [Me]: ", "Me")
    args.groups = _ask_yes_no("Include group chats they are in?", False)
    args.text = True   # always write the plain-text copy in this mode
    print()
    return None


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)

    try:
        if args.check:
            return preflight.main(Path(args.db) if args.db else None)

        if args.list:
            return _print_list(args.db, use_contacts=not args.no_contacts)

        if args.interactive:
            outcome = interactive(args)
            if outcome is not None:
                return outcome

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
            copy_database=not args.no_copy,
            also_text=args.text,
            include_untexted=not args.no_placeholders,
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
    if result.text_path:
        print("Saved {}".format(result.text_path))
    print("  {} messages  ({} from {}, {} from {})".format(
        result.message_count, result.from_them, result.their_name,
        result.from_me, result.my_name,
    ))
    if result.first_date and result.last_date:
        print("  {}  to  {}".format(
            format_date_time(result.first_date), format_date_time(result.last_date)
        ))
    if result.completeness():
        print("  {}".format(result.completeness()))
    note = large_document_note(result.message_count)
    if note:
        print("\n{}".format(note))

    if args.interactive and not args.open:
        args.open = _ask_yes_no("Open the document now?", True)

    if args.open:
        try:
            subprocess.run(["open", str(result.path)], check=False)
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
