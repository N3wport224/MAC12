# iMessage → Word

A small Mac app for one person: you. Type a phone number, press **Export**, and
your whole conversation with that person is saved as a Word document with each
side clearly labelled.

Everything runs locally. The app reads the Messages database that already lives
on this Mac, never modifies it, and writes a `.docx` file. Nothing is uploaded
anywhere, and there are no dependencies to install — it uses the Python that
ships with macOS.

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
| **Save to** | Defaults to `~/Documents/iMessage Exports/` |

### The command line

Same engine, no window:

```bash
# Export a conversation
python3 -m imessage_to_word "+1 555 123 4567" --name "Alex" --me "Andrew" --open

# Not sure which number Messages has for them? List what's in the database
python3 -m imessage_to_word --list

# A date range, group chats included, to a specific file
python3 -m imessage_to_word 5551234567 --from 2025-01-01 --to 2025-12-31 \
    --groups -o ~/Desktop/alex-2025.docx
```

`python3 -m imessage_to_word --help` lists every option.

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

So the two speakers are distinguished three ways at once — name, colour, and
which side of the page the text sits on — which survives printing in black and
white.

---

## How it decides what to include

- **Matching the number.** Formatting is ignored: the last 10 digits have to
  agree (so a number with or without `+1` matches), and email handles match
  exactly. Short codes match on all their digits.
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
- **Your live database is never touched.** It's copied to a temporary folder
  (with its write-ahead log, so the newest messages are included), read there,
  and the copy is deleted afterwards.

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
attachment show as an attachment line; messages you deleted are gone from the
database and can't be recovered by this app.

**Nothing at all in the list** — the history isn't on this Mac yet. Check
"Messages in iCloud" has finished syncing.

---

## Layout

```
app.py                          the window (Tkinter, ships with macOS Python)
run.command                     double-clickable launcher
imessage_to_word/
    chatdb.py                   opens chat.db safely, finds handles/chats/messages
    phones.py                   phone-number and email matching
    attributed_body.py          decodes the archived message-body blobs
    contacts.py                 optional Contacts lookup (name + linked handles)
    models.py                   Message / Conversation types, Apple-epoch dates
    docx_writer.py              minimal Word (.docx) writer, no dependencies
    export.py                   builds the document, orchestrates the export
    cli.py                      command-line interface
tests/                          70 tests, run without a Mac or a real database
```

## Tests

```bash
python3 -m unittest discover -s tests -t .
```

The suite builds a miniature `chat.db` with the real Messages schema, so the
whole path — matching, decoding, filtering, document generation — is covered
without touching your own data. Installing `python-docx` (`pip3 install
python-docx`) enables a few extra checks that a Word library can read the
generated file; without it those are skipped.
