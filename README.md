# iMessage → Word

A small Mac app for one person: you. Type a phone number, press **Export**, and
your whole conversation with that person is saved as a Word document with each
side clearly labelled.

Everything runs locally. The app reads the Messages database that already lives
on this Mac, never modifies it, and writes a `.docx` file. Nothing is uploaded
anywhere, and there are no dependencies to install — it uses the Python that
ships with macOS.

**New to the Mac?** [GETTING-STARTED.md](GETTING-STARTED.md) walks through the
whole thing from scratch — opening Terminal, installing what is needed, and
granting the one permission macOS requires.

---

## Do this first (about two minutes)

```bash
cd /path/to/this/folder
python3 -m imessage_to_word --check
```

That checks everything that decides whether an export will work: your Python
version, whether a window can open, whether macOS is letting you read the
Messages database, free disk space, and that your history is actually on this
Mac. It finishes by running a complete export against a two-message
conversation it makes up on the spot — reading SQLite, decoding an archived
message, writing the Word file and the text copy, and reading both back — so
the whole pipeline is proven on your machine before you point it at anything
real. Anything marked `[FAIL]` comes with the fix next to it. Run it again
until it says **Ready.**

Then find the exact number Messages has for the person:

```bash
python3 -m imessage_to_word --list
```

Look at the conversation before writing anything:

```bash
python3 -m imessage_to_word "+15551234567" --preview
```

And export:

The window:

```bash
python3 app.py
```

Or the command line:

```bash
python3 -m imessage_to_word "+15551234567" --text --open
```

---

## Setup (once)

### 1. Give Full Disk Access to whatever you launch it from

macOS protects `~/Library/Messages/chat.db`. Without this step the app will
tell you it can't read your messages.

1. Open **System Settings → Privacy & Security → Full Disk Access**
   (on macOS 12 Monterey: **System Preferences → Security & Privacy → Privacy →
   Full Disk Access**).
2. Click **+** and add **Terminal** (or iTerm, or whichever app you start the
   script from).
3. Quit and reopen Terminal — the permission only applies after a restart.

### 2. Check your history is actually on this Mac

Messages → Settings → iMessage. If "Messages in iCloud" is on, make sure the
conversations you want have finished downloading; the app can only export what
is stored locally.

---

## Using it

### The app

```bash
cd /path/to/this/folder
python3 app.py
```

Or double-click **`run.command`** in Finder.

Fill in:

| Field | What it does |
| --- | --- |
| **Phone number** | Any format: `5551234567`, `(555) 123-4567`, `+1 555 123 4567`, or an Apple ID email |
| **Their name** | Optional. Left blank, your Contacts are checked; failing that the number is used |
| **Your name** | What to call your own messages. Defaults to "Me" |
| **Date range** | Optional `YYYY-MM-DD` bounds |
| **Include group chats** | Off by default, so you get the one-to-one thread only |
| **Include tapbacks** | Off by default (the Loved / Liked / Laughed reactions) |
| **Also save a plain text copy** | On by default — a `.txt` next to the `.docx` |
| **Save to** | Defaults to `~/Documents/iMessage Exports/` |

**Preview** opens the conversation in a window before anything is written —
each side in its own colour and on its own side of the page, the same way the
document lays it out — with the message counts and date range at the top. If it
is the right conversation, **Export this to Word** writes exactly what you were
looking at, without reading the database again. **Check setup** runs the same
checks as `--check` and reports back in a dialog.

The preview has a **Find** box. Type and every match lights up; `<` and `>`
(or Return and Shift-Return) step through them, and the counter shows where you
are, plus how many matches are in the part of a long conversation that isn't on
screen. **Show only matches** narrows the view to just those messages —
useful for "did we ever talk about the deposit?" — and says plainly that the
export still contains everything. Cmd-F jumps to the box; Escape clears it.

Search looks at what people actually said, including attachment names. It
deliberately ignores the name labels, since searching a name in a two-person
thread would just match every message.

### The command line

Same engine, no window:

Check this Mac is ready, then see which handles Messages actually has:

```bash
python3 -m imessage_to_word --check
python3 -m imessage_to_word --list
```

Look at a conversation first — this writes nothing. The number is how many
messages to show (`0` shows all of them):

```bash
python3 -m imessage_to_word "+1 555 123 4567" --preview
python3 -m imessage_to_word "+1 555 123 4567" --preview 200
python3 -m imessage_to_word "+1 555 123 4567" --preview 0
```

Export it, with a plain-text copy, and open the result:

```bash
python3 -m imessage_to_word "+1 555 123 4567" --name "Alex" --me "Andrew" --text --open
```

A date range, group chats included, written to a file you choose:

```bash
python3 -m imessage_to_word 5551234567 --from 2025-01-01 --to 2025-12-31 --groups -o ~/Desktop/alex-2025.docx
```

No flags to remember — it asks for what it needs:

```bash
python3 -m imessage_to_word --interactive
```

> Every block above is meant to be pasted as-is. Terminal's zsh does not treat
> `#` as a comment, so a line with a note after it fails — which is why there
> are none here.

`python3 -m imessage_to_word --help` lists every option. The less obvious ones:
`--preview [N]` (show it instead of exporting; `0` shows everything),
`--text` (also write a `.txt`), `--no-copy` (read the database in place instead
of copying it — for when disk space is tight), `--no-placeholders` (drop
messages that carry no readable text), `--no-contacts` (skip the Contacts
lookup).

Interactive mode offers the preview too, then asks before saving anything.

---

## Previewing first

Nothing is written until you ask for it. `--preview`, and the **Preview**
button, run exactly the same search the export runs and show you the result —
so a preview can never disagree with the document you end up with. A long
history previews as its beginning and its end, with a line saying how many
messages are in between; the export always includes all of them. Narrowing the
preview with **Show only matches** changes what you are looking at and nothing
else — the export is always the whole conversation.

One visible compromise: emoji appear as `□` in the preview window. Tk (the
toolkit macOS ships for Python windows) refuses characters above U+FFFF on
older macOS, and current versions crash outright when asked to search a widget
holding one. The preview says so when it has substituted anything. The Word
document and the `.txt` keep the real characters.

---

## What the document looks like

- A header block: both participants, the handles found, the date range covered,
  and how many messages came from each person.
- A centred date heading each time the day changes.
- Every message as a labelled, shaded block:
  - **Them** — green label, against the left margin.
  - **You** — blue label, indented to the right.
  - Time of day next to each name, plus `(edited)` where Messages recorded an
    edit, and the group-chat name when group chats are included.
- Attachments listed by what they were (`Photo: IMG_0042.HEIC (2.3 MB)`), since
  the files themselves stay in the Messages attachment folder.
- Page numbers in the footer.
- A **Completeness** line: `4,812 of 4,813 messages exported; 1 tapback left
  out`. Every row the app looked at is either exported, or counted in that
  line — nothing disappears quietly.

So the two speakers are distinguished three ways at once — name, colour, and
which side of the page the text sits on — which survives printing in black and
white.

---

## Getting the *whole* history

The point of this app is a complete record, so the awkward cases are handled
rather than skipped:

- **Messages with no text.** Link previews, Apple Cash, audio messages,
  stickers, app messages and group events have no words in them. They stay in
  the transcript as a labelled note (`[Link]`, `[Apple Cash]`, `[Audio
  message]`) instead of vanishing. `--no-placeholders` drops them if you would
  rather have clean prose.
- **Messages the database stores oddly.** Bodies archived in `attributedBody`
  are decoded; the rare one that cannot be read becomes `[Message text could
  not be read]` and is counted, so you know it existed.
- **Messages attached to no conversation.** Rare, but they exist; they are
  pulled in too.
- **Old databases.** A chat.db from 2013 has none of the modern columns and
  stores its dates differently. Both work.
- **Long histories.** A 60,000-message thread exports in about five seconds and
  Word opens the result; progress is reported along the way.

---

## How it decides what to include

- **Matching the number.** Formatting is ignored. Two numbers are the same
  person when their digits match, or when one is the tail of the other — so
  `+1 (555) 123-4567`, `5551234567` and even a local `123-4567` all find the
  same thread. At least seven digits have to agree, so short codes and wrong
  numbers don't collide. Email handles match exactly, ignoring case.
- **One person, several handles.** If Contacts has the number, the app also
  pulls that person's other numbers and email addresses from their card, so a
  thread split between an iPhone number and an Apple ID still exports as one
  conversation.
- **One-to-one by default.** A chat counts as yours-and-theirs when every
  participant is one of their handles. Group chats are only included when you
  ask, and then each sender is named individually.
- **Text that isn't in the `text` column.** Recent macOS versions store message
  bodies in an archived `attributedBody` blob; those are decoded too, so newer
  messages don't come out blank.
- **Your live database is never touched, and the newest messages still come
  through.** Messages keeps its database in WAL mode, which means recent
  messages live in a `chat.db-wal` sidecar rather than in `chat.db` itself. The
  app snapshots the database with SQLite's own backup API, which takes a proper
  read lock and includes that sidecar. If Messages has the file locked, it
  falls back to copying the files (and gives up rather than hanging). Reading
  in place with `--no-copy` sees the sidecar too — and says so plainly if it
  ever has to fall back to a read that cannot.

---

## If something goes wrong

**"macOS blocks access to your Messages database…"** — Full Disk Access isn't
set for the app you launched from, or you didn't restart it after granting it.
See step 1 above.

**"No messages found for…"** — try `python3 -m imessage_to_word --list` to see
exactly which handles Messages has, then use one of those. Also worth trying:
the number with and without the country code, turning on group chats, and
widening the date range.

**Some messages look blank or missing** — messages whose only content was an
attachment show as an attachment line, and ones with no text at all show as
`[Link]`, `[Audio message]` and so on. Messages you deleted are gone from the
database and can't be recovered by this app. Anything the app couldn't read is
counted in the Completeness line rather than dropped quietly.

**A warning about missing messages** — if the app ever has to fall back to a
read that can't see Messages' write-ahead log, it says so instead of handing
you a quietly incomplete transcript. Quit Messages and run it again.

**Nothing at all in the list** — the history isn't on this Mac yet. Check
"Messages in iCloud" has finished syncing.

---

## Layout

```
app.py                          the window and the preview (Tkinter, ships with macOS Python)
run.command                     double-clickable launcher
imessage_to_word/
    chatdb.py                   opens chat.db safely, finds handles/chats/messages
    phones.py                   phone-number and email matching
    attributed_body.py          decodes the archived message-body blobs
    contacts.py                 optional Contacts lookup (name + linked handles)
    models.py                   Message / Conversation types, Apple-epoch dates
    docx_writer.py              minimal Word (.docx) writer, no dependencies
    export.py                   finds the conversation, builds the document
    preview.py                  what to show, and what a search matches
    cli.py                      command-line interface (incl. --check, --interactive)
    preflight.py                the setup checks behind --check
tests/                          223 tests, run without a Mac or a real database
```

## Tests

```bash
python3 -m unittest discover -s tests -t .
```

The suite builds miniature `chat.db` files with the real Messages schema —
a normal thread, a 2013-era one, one full of awkward untexted messages, and a
4,000-message one — so the whole path (matching, decoding, filtering, document
generation, the window's own logic) is covered without touching your own data.
It also covers the awkward realities: a database in WAL mode with messages not
yet written to `chat.db`, one locked by Messages, a corrupt one, a row of
invalid UTF-8, paths with spaces, and daylight-saving boundaries.

Installing any of `python-docx`, `mammoth` or `pandoc` enables extra checks
that three unrelated Word implementations can read the generated file; without
them those are skipped. Installing `python-docx` (`pip3 install
python-docx`) enables a few extra checks that a Word library can read the
generated file; without it those are skipped.
