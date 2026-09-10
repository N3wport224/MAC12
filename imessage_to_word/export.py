"""Turn a conversation from chat.db into a formatted Word document."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, List, Optional

from . import chatdb, contacts, phones
from .docx_writer import INCH, Document, Run, Table
from .models import Conversation, Message

# One person's messages sit against the left margin, the other's are pushed
# right, and each side keeps its own colour throughout the document.
THEM_COLOR = "1B7F4B"
THEM_FILL = "EDF6F0"
ME_COLOR = "0B57D0"
ME_FILL = "E9F1FE"
MUTED = "6E6E73"
FAINT = "9A9AA0"
INK = "1D1D1F"
BUBBLE_INSET = int(1.7 * INCH)

ProgressCallback = Optional[Callable[[str], None]]


class ExportError(Exception):
    pass


class NoMessagesFound(ExportError):
    pass


@dataclass
class ExportOptions:
    number: str
    their_name: Optional[str] = None
    my_name: str = "Me"
    include_groups: bool = False
    include_reactions: bool = False
    start: Optional[datetime] = None
    end: Optional[datetime] = None
    db_path: Optional[Path] = None
    copy_database: bool = True
    lookup_contact_name: bool = True
    # Pull the person's other numbers / email addresses from Contacts so a
    # thread split across handles still exports as one conversation.
    link_contact_handles: bool = True
    extra_handles: List[str] = field(default_factory=list)


@dataclass
class ExportResult:
    path: Path
    conversation: Conversation
    their_name: str
    my_name: str
    message_count: int = 0
    from_me: int = 0
    from_them: int = 0
    first_date: Optional[datetime] = None
    last_date: Optional[datetime] = None
    handles: List[str] = field(default_factory=list)


# -- formatting helpers ----------------------------------------------------

def format_day(value: datetime) -> str:
    return "{}, {} {}, {}".format(
        value.strftime("%A"), value.strftime("%B"), value.day, value.year
    )


def format_time(value: datetime) -> str:
    return value.strftime("%I:%M %p").lstrip("0")


def format_date_time(value: datetime) -> str:
    return "{} at {}".format(format_day(value), format_time(value))


def format_size(total_bytes: int) -> str:
    if not total_bytes:
        return ""
    size = float(total_bytes)
    for unit in ("bytes", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            if unit in ("bytes", "KB"):
                return "{:.0f} {}".format(size, unit)
            return "{:.1f} {}".format(size, unit)
        size /= 1024
    return ""


DATE_FORMATS = ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%d %b %Y", "%B %d, %Y")


def parse_date_input(value: Optional[str], end_of_day: bool = False) -> Optional[datetime]:
    """Parse a date typed into the app; returns local-time midnight (or 23:59:59)."""
    value = (value or "").strip()
    if not value:
        return None
    for pattern in DATE_FORMATS:
        try:
            parsed = datetime.strptime(value, pattern)
        except ValueError:
            continue
        if end_of_day:
            parsed = parsed.replace(hour=23, minute=59, second=59, microsecond=999999)
        return parsed.astimezone()
    raise ExportError(
        "Could not read the date {!r}. Use YYYY-MM-DD, for example 2026-03-01.".format(value)
    )


def default_output_path(name: str) -> Path:
    folder = Path.home() / "Documents" / "iMessage Exports"
    stamp = datetime.now().strftime("%Y-%m-%d")
    return folder / "{} - iMessage {}.docx".format(phones.safe_filename(name), stamp)


# -- document composition --------------------------------------------------

def _summary_rows(conversation: Conversation, their_name: str, my_name: str):
    def label(text: str) -> List[Run]:
        return [Run(text, bold=True, color=MUTED, size=9)]

    def value(text: str) -> List[Run]:
        return [Run(text, color=INK, size=9)]

    rows = [[label("Participants"), value("{} and {}".format(my_name, their_name))]]
    if conversation.handles:
        rows.append([label("Phone / Apple ID"), value(", ".join(conversation.handles))])
    span = "No messages"
    if conversation.first_date and conversation.last_date:
        span = "{} - {}".format(
            format_date_time(conversation.first_date),
            format_date_time(conversation.last_date),
        )
    rows.append([label("Covering"), value(span)])
    rows.append([
        label("Messages"),
        value("{} total  ({} from {}, {} from {})".format(
            len(conversation.messages),
            conversation.count_from_them(), their_name,
            conversation.count_from_me(), my_name,
        )),
    ])
    # Only worth a row when the chat has a name of its own -- for a one-to-one
    # thread the "chat name" is just the phone number again.
    named_chats = [
        name for name in conversation.chat_names
        if phones.match_key(name) not in phones.match_keys(conversation.handles)
    ]
    if named_chats:
        kind = "Conversations" if len(named_chats) > 1 else "Conversation"
        rows.append([label(kind), value(", ".join(named_chats[:6]))])
    rows.append([label("Exported"), value(format_date_time(datetime.now().astimezone()))])
    return rows


def _add_header(document: Document, conversation: Conversation, their_name: str, my_name: str) -> None:
    document.add_paragraph(
        [Run("iMessage Conversation", bold=True, size=22, color=INK)],
        space_after=20,
    )
    document.add_paragraph(
        [Run("{} and {}".format(my_name, their_name), size=13, color=MUTED)],
        space_after=200,
        border_bottom="D8D8DD",
    )
    document.add(Table(_summary_rows(conversation, their_name, my_name), [1900, 8000]))
    document.add_paragraph(
        [
            Run("Who said what:  ", size=8, color=MUTED),
            Run(their_name, bold=True, size=8, color=THEM_COLOR),
            Run(" is on the left,  ", size=8, color=MUTED),
            Run(my_name, bold=True, size=8, color=ME_COLOR),
            Run(" is indented on the right.", size=8, color=MUTED),
        ],
        space_before=160,
        space_after=240,
    )


def _message_runs(message: Message, muted_color: str) -> List[Run]:
    runs: List[Run] = []
    if message.text:
        runs.append(Run(message.text, color=INK, size=10.5))
    for attachment in message.attachments:
        description = attachment.describe()
        size = format_size(attachment.total_bytes)
        if size:
            description += " ({})".format(size)
        runs.append(
            Run(description, italic=True, color=muted_color, size=9,
                break_before=bool(runs))
        )
    return runs


def _add_message(document: Document, message: Message, their_name: str, my_name: str) -> None:
    mine = message.is_from_me
    speaker = my_name if mine else (message.sender_handle_name or their_name)
    color = ME_COLOR if mine else THEM_COLOR
    fill = ME_FILL if mine else THEM_FILL
    indent_left = BUBBLE_INSET if mine else 0
    indent_right = 0 if mine else BUBBLE_INSET

    header = [Run(speaker, bold=True, size=9, color=color)]
    if message.date:
        header.append(Run("   " + format_time(message.date), size=8, color=FAINT))
    if message.is_edited:
        header.append(Run("   (edited)", size=8, italic=True, color=FAINT))
    if message.is_group and message.chat_name:
        header.append(Run("   in " + message.chat_name, size=8, italic=True, color=FAINT))

    document.add_paragraph(
        header,
        indent_left=indent_left,
        indent_right=indent_right,
        space_before=100,
        space_after=20,
        keep_next=True,
    )

    if message.is_reaction:
        document.add_paragraph(
            [Run(message.text or "Reaction", italic=True, color=MUTED, size=9.5)],
            indent_left=indent_left + 120,
            indent_right=indent_right,
            space_after=40,
        )
        return

    runs = _message_runs(message, MUTED)
    document.add_paragraph(
        runs or [Run("(no text)", italic=True, color=FAINT, size=9.5)],
        indent_left=indent_left,
        indent_right=indent_right,
        space_after=40,
        shading=fill,
        border_left=color,
    )


def build_document(conversation: Conversation, their_name: str, my_name: str = "Me") -> Document:
    document = Document(
        title="iMessage conversation with {}".format(their_name),
        author="iMessage to Word",
    )
    _add_header(document, conversation, their_name, my_name)

    current_day = None
    for message in conversation.messages:
        day = message.date.date() if message.date else None
        if day != current_day:
            current_day = day
            heading = format_day(message.date) if message.date else "Undated messages"
            document.add_paragraph(
                [Run(heading, bold=True, size=9, color=MUTED, caps=True)],
                style="Heading2",
                align="center",
                space_before=280,
                space_after=80,
                keep_next=True,
            )
        _add_message(document, message, their_name, my_name)

    if not conversation.messages:
        document.add_paragraph(
            [Run("No messages were found for this number.", italic=True, color=MUTED)]
        )
    return document


# -- orchestration ---------------------------------------------------------

def resolve_their_name(options: ExportOptions, contact=None) -> str:
    """What to call the other person in the document."""
    if options.their_name and options.their_name.strip():
        return options.their_name.strip()
    if options.lookup_contact_name and contact and contact.name:
        return contact.name
    return phones.format_pretty(options.number)


def export_to_word(
    options: ExportOptions,
    output_path: Optional[Path] = None,
    progress: ProgressCallback = None,
) -> ExportResult:
    """Read the conversation for ``options.number`` and write it to a .docx."""
    def report(message: str) -> None:
        if progress:
            progress(message)

    problem = phones.looks_like_handle(options.number)
    if problem:
        raise ExportError(problem)

    contact = None
    if options.lookup_contact_name or options.link_contact_handles:
        report("Checking Contacts...")
        contact = contacts.find_contact(options.number)

    extra_handles = list(options.extra_handles)
    if options.link_contact_handles and contact:
        extra_handles.extend(contact.identifiers)

    report("Opening your Messages database...")
    with chatdb.open_chat_db(options.db_path, copy=options.copy_database) as conn:
        report("Searching for messages with {}...".format(phones.format_pretty(options.number)))
        conversation = chatdb.fetch_conversation(
            conn,
            options.number,
            extra_handles=extra_handles,
            include_groups=options.include_groups,
            include_reactions=options.include_reactions,
            start=options.start,
            end=options.end,
        )

    their_name = resolve_their_name(options, contact)
    conversation.display_name = their_name

    if not conversation.messages:
        raise NoMessagesFound(
            "No messages found for {}.\n\n"
            "Things worth checking:\n"
            "  - the number is the one Messages actually uses for them\n"
            "  - try it with and without the country code\n"
            "  - if you only talk in a group chat, turn on \"Include group chats\"\n"
            "  - if you narrowed the dates, widen the range".format(
                phones.format_pretty(options.number)
            )
        )

    # Attach a per-message speaker label for group chats, where more than one
    # person can be on the "them" side.
    person_keys = phones.match_keys([options.number] + extra_handles)
    for message in conversation.messages:
        if message.is_group and not message.is_from_me and message.sender_handle:
            if phones.match_key(message.sender_handle) not in person_keys:
                message.sender_handle_name = phones.format_pretty(message.sender_handle)

    report("Writing {} messages to Word...".format(len(conversation.messages)))
    destination = Path(output_path) if output_path else default_output_path(their_name)
    document = build_document(conversation, their_name, options.my_name)
    document.save(destination)

    return ExportResult(
        path=destination,
        conversation=conversation,
        their_name=their_name,
        my_name=options.my_name,
        message_count=len(conversation.messages),
        from_me=conversation.count_from_me(),
        from_them=conversation.count_from_them(),
        first_date=conversation.first_date,
        last_date=conversation.last_date,
        handles=conversation.handles,
    )
