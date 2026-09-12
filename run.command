#!/bin/bash
# Double-click this in Finder to open the app.
cd "$(dirname "$0")" || exit 1

# Prefer a python3 that can actually open a window. Importing tkinter is not
# enough: a Tk built for a newer macOS than this one aborts when it starts.
PYTHON=""
FALLBACK=""
for candidate in /usr/local/bin/python3 /opt/homebrew/bin/python3 \
                 "$(command -v python3 2>/dev/null)" /usr/bin/python3; do
    [ -n "$candidate" ] && [ -x "$candidate" ] || continue
    [ -z "$FALLBACK" ] && FALLBACK="$candidate"
    if "$candidate" -c 'import tkinter; tkinter.Tk().destroy()' >/dev/null 2>&1; then
        PYTHON="$candidate"
        break
    fi
done

if [ -n "$PYTHON" ]; then
    "$PYTHON" app.py
    status=$?
elif [ -n "$FALLBACK" ]; then
    echo "No Python with window support (Tkinter) was found on this Mac,"
    echo "so here is the same thing as a set of questions instead."
    echo
    "$FALLBACK" -m imessage_to_word --interactive
    status=$?
else
    echo "Could not find python3. Install Xcode Command Line Tools with:"
    echo "    xcode-select --install"
    status=1
fi

# Keep the window open so any message stays readable after a double-click.
echo
read -r -p "Press Return to close this window. " _
exit $status
