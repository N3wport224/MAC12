# Getting this running on your Mac

Written for someone who has never used Terminal. Every step says what to type,
what you should see, and what to do if you see something else.

Total time: about ten minutes, most of it waiting for one download.

---

## Step 1 — Download the app

Open Safari and go to this address:

```
https://github.com/N3wport224/MAC12/archive/refs/heads/claude/serene-ptolemy-ylui7u.zip
```

A `.zip` file lands in your **Downloads** folder, and Safari usually unzips it
for you. You end up with a folder called:

```
MAC12-claude-serene-ptolemy-ylui7u
```

If it did not unzip itself, double-click the `.zip` and it will.

Drag that folder somewhere you will find it again — your **Documents** folder is
a good home. The name is a mouthful; you can rename it to something like
`iMessage Export` if you like. Nothing breaks.

---

## Step 2 — Open Terminal

Terminal is a Mac app that lets you type commands instead of clicking.

1. Press **Command (⌘) + Space**. A search box appears in the middle of the screen.
2. Type `Terminal`.
3. Press **Return**.

A window opens with a line of text ending in `%` or `$`. That is the prompt —
it is waiting for you to type something. You can make the window bigger by
dragging its corner.

---

## Step 3 — Tell Terminal where the app is

Terminal is always "in" some folder. You need it to be in the app's folder.

1. Type `cd` followed by **one space**. Do not press Return yet:

   ```
   cd 
   ```

2. Now open a **Finder** window, find the app folder from Step 1, and **drag
   the folder onto the Terminal window**. Terminal fills in its location for you.

3. Press **Return**.

Nothing obvious happens, which is what success looks like. To check, type:

```
ls
```

and press Return. You should see `app.py`, `README.md`, `imessage_to_word` and
a few other names. If you see something else, you are in the wrong folder —
repeat this step.

> `cd` means "change directory". `ls` means "list". Those two get you a long way.

---

## Step 4 — Check you have Python

The app is written in Python, which your Mac already includes. Type:

```
python3 --version
```

**If a dialog appears** saying the `python3` command requires the "command line
developer tools", click **Install** and wait — it is a few hundred megabytes and
takes about five minutes. When it finishes, run the command again.

You should end up with something like `Python 3.9.6`. Any version starting with
3.8 or higher is fine.

---

## Step 5 — Run the setup check

```
python3 -m imessage_to_word --check
```

This checks the six things that decide whether an export will work. The first
time, expect it to fail on **Full Disk Access** — that is normal, and Step 6
fixes it.

If it says `No module named imessage_to_word`, you are in the wrong folder. Go
back to Step 3.

---

## Step 6 — Give Terminal permission to read your messages

macOS keeps your messages locked away until you explicitly allow an app to read
them. You are giving that permission to **Terminal**.

**On macOS Ventura (13) or newer — including Sonoma, Sequoia and macOS 26:**

1. Click the  **Apple menu** (top-left corner) → **System Settings**.
2. In the sidebar, click **Privacy & Security**.
3. Scroll down and click **Full Disk Access**.
4. Find **Terminal** in the list and turn its switch **on**. If it is not
   listed, click the **+** button, then go to **Applications → Utilities →
   Terminal** and click **Open**.
5. Enter your Mac password if asked.

**On macOS Monterey (12) or older:**

1. **Apple menu** → **System Preferences** → **Security & Privacy**.
2. Click the **Privacy** tab, then **Full Disk Access** in the left-hand list.
3. Click the **padlock** at the bottom-left and enter your password.
4. Click **+**, go to **Applications → Utilities → Terminal**, click **Open**.
5. Tick the box next to Terminal.

### Then do this, or nothing will work

**Quit Terminal completely** — click the Terminal window, then press
**Command (⌘) + Q**. Closing the window is not enough.

Now reopen Terminal (Step 2) and set the folder again (Step 3). The permission
only takes effect in a freshly opened Terminal. This is the step people miss.

---

## Step 7 — Check again

```
python3 -m imessage_to_word --check
```

It should now end with:

```
Ready. Try an export:
```

If it still complains about Full Disk Access, Terminal was not fully quit.
Press Command + Q and try once more.

---

## Step 8 — Find the right phone number

Messages stores a number in one particular form, which may not be the form you
have in your head. Ask it:

```
python3 -m imessage_to_word --list
```

You get a table of the numbers and email addresses in your Messages history,
how many messages each has, and when you last spoke. Find your person and note
exactly what is in the **Handle** column.

---

## Step 9 — Open the app

```
python3 app.py
```

A window opens. Type the phone number, add a name for them if you like, and
click **Preview** to see the conversation before anything is saved. If it is
the right one, click **Export this to Word**.

The document lands in **Documents → iMessage Exports**, along with a plain-text
copy of the same conversation.

**If no window appears** and you get an error mentioning `tkinter`, your Python
cannot draw windows. Use the question-and-answer version instead, which does
the same job:

```
python3 -m imessage_to_word --interactive
```

---

## Doing it again next time

Open Terminal, then:

```
cd ~/Documents/MAC12-claude-serene-ptolemy-ylui7u
python3 app.py
```

(Adjust the folder name if you renamed it or put it elsewhere. The `~` means
your home folder.)

Or, to skip the typing: in Finder, **right-click `run.command` → Open**, then
click **Open** in the warning dialog. macOS only asks the first time. If it says
"permission denied", run this once in Terminal and then try again:

```
chmod +x run.command
```

---

## When something goes wrong

**`command not found: python3`**
The developer tools did not install. Run `xcode-select --install` and follow the
prompts.

**`No module named imessage_to_word`**
Terminal is in the wrong folder. Type `pwd` to see where you are, then redo
Step 3.

**"macOS blocks access to your Messages database"**
Full Disk Access is not set for Terminal, or Terminal was not quit and reopened
after setting it. Redo Step 6, including the Command + Q.

**"No messages found for ..."**
Run `python3 -m imessage_to_word --list` and use a handle exactly as it appears
there. If you only ever talk in a group chat, tick **Include group chats**.

**The list is empty, or messages are missing**
Your history may not be on this Mac yet. Open Messages → Settings → iMessage and
check whether "Messages in iCloud" is still downloading.

**Emoji show as □ in the preview window**
Only in the preview. The Word document and the text file keep the real emoji.

---

## Two things worth knowing

- **Nothing leaves your Mac.** The app reads the Messages database that is
  already on this computer and writes files to your Documents folder. There is
  no account, no upload, no network use at all.
- **Your messages are never touched.** The database is copied before it is read,
  and the copy is deleted afterwards. Nothing is written back to Messages.
