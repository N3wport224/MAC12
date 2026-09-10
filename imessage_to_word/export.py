"""Turn a conversation from chat.db into a formatted Word document."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, List, Optional, Sequence, Tuple

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

# Word copes with transcripts this long, but takes its time opening them.
LARGE_DOCUMENT_MESSAGES = 20000

# How far the plain-text transcript will indent a wrapped line before it gives
# up and stops trying to align under a very long name.
MAX_TEXT_INDENT = 32


def large_document_note(message_count: int) -> Optional[str]:
    if message_count < LARGE_DOCUMENT_MESSAGES:
        return None
    return (
        "That is a big transcript ({:,} messages) -- Word may take a minute to "
        "open it. The plain-text copy opens instantly if you need it sooner."
    ).format(message_count)


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
    # Keep messages that carry no readable text (stickers, links, Apple Cash,
    # group events) as a labelled note, so the transcript stays complete.
    include_untexted: bool = True
    start: Optional[datetime] = None
    end: Optional[datetime] = None
    db_path: Optional[Path] = None
    copy_database: bool = True
    lookup_contact_name: bool = True
    # Write a plain .txt transcript alongside the .docx.
    also_text: bool = False
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
    text_path: Optional[Path] = None
    warnings: List[str] = field(default_factory=list)
    stats: Optional[object] = None

    def completeness(self) -> str:
        return self.stats.summary() if self.stats else ""


# -- formatting helpers ----------------------------------------------------

def format_day(value: datetime) -> str:
    return "{}, {} {}, {}".format(
        value.strftime("%A"), value.strftime("%B"), value.day, value.year
    )


def format_short_day(value: datetime) -> str:
    return "{} {}, {}".format(value.strftime("%b"), value.day, value.year)


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


def unique_path(path: Path) -> Path:
    """Add " (2)", " (3)"... rather than overwrite an earlier export."""
    path = Path(path)
    if not path.exists():
        return path
    for index in range(2, 1000):
        candidate = path.with_name("{} ({}){}".format(path.stem, index, path.suffix))
        if not candidate.exists():
            return candidate
    return path


def as_docx_path(path) -> Path:
    """Make sure the destination ends in .docx, so the .txt beside it lines up."""
    path = Path(path)
    if path.suffix.lower() != ".docx":
        path = path.with_name(path.name + ".docx")
    return path


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
        if not phones.matches_any(name, conversation.handles)
    ]
    if named_chats:
        kind = "Conversations" if len(named_chats) > 1 else "Conversation"
        rows.append([label(kind), value(", ".join(named_chats[:6]))])
    if conversation.stats and conversation.stats.rows_seen:
        rows.append([label("Completeness"), value(conversation.stats.summary())])
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

    if message.is_placeholder:
        document.add_paragraph(
            [Run(message.text, italic=True, color=MUTED, size=9.5)],
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


def build_document(
    conversation: Conversation,
    their_name: str,
    my_name: str = "Me",
    progress: ProgressCallback = None,
) -> Document:
    document = Document(
        title="iMessage conversation with {}".format(their_name),
        author="iMessage to Word",
    )
    _add_header(document, conversation, their_name, my_name)

    total = len(conversation.messages)
    current_day = None
    for index, message in enumerate(conversation.messages):
        # Long histories take a while; say where we are rather than look stuck.
        if progress and index and index % 2500 == 0:
            progress("Formatting message {:,} of {:,}...".format(index, total))
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


def transcript_header(
    conversation: Conversation,
    their_name: str,
    my_name: str = "Me",
    stamp_label: str = "Exported",
) -> List[str]:
    """The few summary lines that open a plain-text transcript."""
    lines: List[str] = [
        "iMessage conversation - {} and {}".format(my_name, their_name),
        "=" * 60,
    ]
    if conversation.handles:
        lines.append("Handles: {}".format(", ".join(conversation.handles)))
    if conversation.first_date and conversation.last_date:
        lines.append("Covering: {}  to  {}".format(
            format_date_time(conversation.first_date),
            format_date_time(conversation.last_date)))
    lines.append("Messages: {} total ({} from {}, {} from {})".format(
        len(conversation.messages), conversation.count_from_them(), their_name,
        conversation.count_from_me(), my_name))
    if conversation.stats and conversation.stats.rows_seen:
        lines.append("Completeness: {}".format(conversation.stats.summary()))
    lines.append("{}: {}".format(
        stamp_label, format_date_time(datetime.now().astimezone())))
    return lines


def transcript_lines(
    messages: Sequence[Message], their_name: str, my_name: str = "Me"
) -> List[str]:
    """Render messages as plain text, with a heading each time the day changes."""
    lines: List[str] = []
    current_day = None
    for message in messages:
        day = message.date.date() if message.date else None
        if day != current_day:
            current_day = day
            heading = format_day(message.date) if message.date else "Undated messages"
            lines.extend(["", "--- {} ---".format(heading), ""])

        speaker = my_name if message.is_from_me else (
            message.sender_handle_name or their_name)
        stamp = format_time(message.date) if message.date else "--:--"
        prefix = "[{}] {}: ".format(stamp, speaker)
        # Continuation lines sit under the start of the message text.
        indent = " " * min(len(prefix), MAX_TEXT_INDENT)
        pieces = []
        for attachment in message.attachments:
            size = format_size(attachment.total_bytes)
            pieces.append("<{}{}>".format(
                attachment.describe(), " ({})".format(size) if size else ""))
        body = message.text or ""
        if not body and pieces:
            body = pieces.pop(0)   # an attachment-only message reads better inline
        first, _, rest = body.partition("\n")
        lines.append(prefix + first)
        for line in (rest.split("\n") if rest else []):
            lines.append(indent + line)
        for piece in pieces:
            lines.append(indent + piece)
    return lines


def write_text_transcript(
    conversation: Conversation, path: Path, their_name: str, my_name: str = "Me"
) -> Path:
    """Write the transcript as plain UTF-8 text.

    Handy for searching, grepping, or pasting somewhere that will not take a
    Word file -- and a fallback if anything about the .docx ever misbehaves.
    """
    lines = transcript_header(conversation, their_name, my_name) + [""]
    lines.extend(transcript_lines(conversation.messages, their_name, my_name))
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def preview_selection(
    messages: Sequence[Message], limit: Optional[int] = None
) -> Tuple[List[Message], List[Message], int]:
    """Split messages into (beginning, end, number left out) for a preview.

    A long history previews as its start and its finish, which is what tells
    you whether you have the right conversation; the export still gets all of
    them.
    """
    messages = list(messages)
    if not limit or limit <= 0 or len(messages) <= limit:
        return messages, [], 0
    head = limit // 2
    tail = limit - head
    return messages[:head], messages[-tail:], len(messages) - limit


def gap_note(omitted: int) -> str:
    return "... {:,} messages not shown here -- all of them are in the export ...".format(
        omitted)


# -- orchestration ---------------------------------------------------------

def resolve_their_name(options: ExportOptions, contact=None) -> str:
    """What to call the other person in the document."""
    if options.their_name and options.their_name.strip():
        return options.their_name.strip()
    if options.lookup_contact_name and contact and contact.name:
        return contact.name
    return phones.format_pretty(options.number)


@dataclass
class LoadedConversation:
    """Everything gathered for one export, before anything is written.

    The preview and the export both work from one of these, so what you see is
    exactly what lands in the document.
    """
    conversation: Conversation
    their_name: str
    my_name: str = "Me"
    warnings: List[str] = field(default_factory=list)

    @property
    def messages(self) -> List[Message]:
        return self.conversation.messages

    def summary_lines(self, stamp_label: str = "Exported") -> List[str]:
        return transcript_header(
            self.conversation, self.their_name, self.my_name, stamp_label)

    def headline(self) -> str:
        """Who said how much, for a preview window or a status line."""
        return "{:,} messages ({:,} from {}, {:,} from {})".format(
            len(self.messages), self.conversation.count_from_them(), self.their_name,
            self.conversation.count_from_me(), self.my_name)

    def date_span(self) -> str:
        """The period the conversation covers, kept short enough to fit."""
        first, last = self.conversation.first_date, self.conversation.last_date
        if not first or not last:
            return ""
        if first.date() == last.date():
            return format_short_day(first)
        return "{} - {}".format(format_short_day(first), format_short_day(last))


def load_conversation(
    options: ExportOptions, progress: ProgressCallback = None
) -> LoadedConversation:
    """Find every message for ``options.number``, without writing anything."""
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

    warnings: List[str] = []

    def note(message: str) -> None:
        warnings.append(message)
        report(message)

    report("Opening your Messages database...")
    with chatdb.open_chat_db(
        options.db_path, copy=options.copy_database, on_warning=note
    ) as conn:
        report("Searching for messages with {}...".format(phones.format_pretty(options.number)))
        conversation = chatdb.fetch_conversation(
            conn,
            options.number,
            extra_handles=extra_handles,
            include_groups=options.include_groups,
            include_reactions=options.include_reactions,
            include_untexted=options.include_untexted,
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
    person_handles = [options.number] + extra_handles
    for message in conversation.messages:
        if message.is_group and not message.is_from_me and message.sender_handle:
            if not phones.matches_any(message.sender_handle, person_handles):
                message.sender_handle_name = phones.format_pretty(message.sender_handle)

    return LoadedConversation(
        conversation=conversation,
        their_name=their_name,
        my_name=options.my_name,
        warnings=warnings,
    )


def export_loaded(
    loaded: LoadedConversation,
    options: ExportOptions,
    output_path: Optional[Path] = None,
    progress: ProgressCallback = None,
) -> ExportResult:
    """Write an already-loaded conversation out as a Word document."""
    def report(message: str) -> None:
        if progress:
            progress(message)

    conversation = loaded.conversation
    their_name = loaded.their_name

    report("Writing {:,} messages to Word...".format(len(conversation.messages)))
    if output_path:
        destination = as_docx_path(output_path)
    else:
        # Nobody chose a name, so don't quietly replace an earlier export.
        destination = unique_path(default_output_path(their_name))
    document = build_document(conversation, their_name, loaded.my_name, progress=progress)
    report("Saving {}...".format(destination.name))
    document.save(destination)

    text_path = None
    if options.also_text:
        report("Writing the plain-text copy...")
        text_path = write_text_transcript(
            conversation, destination.with_suffix(".txt"), their_name, loaded.my_name
        )

    return ExportResult(
        path=destination,
        conversation=conversation,
        their_name=their_name,
        my_name=loaded.my_name,
        message_count=len(conversation.messages),
        from_me=conversation.count_from_me(),
        from_them=conversation.count_from_them(),
        first_date=conversation.first_date,
        last_date=conversation.last_date,
        handles=conversation.handles,
        text_path=text_path,
        warnings=list(loaded.warnings),
        stats=conversation.stats,
    )


def export_to_word(
    options: ExportOptions,
    output_path: Optional[Path] = None,
    progress: ProgressCallback = None,
) -> ExportResult:
    """Read the conversation for ``options.number`` and write it to a .docx."""
    loaded = load_conversation(options, progress=progress)
    return export_loaded(loaded, options, output_path=output_path, progress=progress)
