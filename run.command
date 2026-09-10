#!/bin/bash
# Double-click this in Finder to open the app.
cd "$(dirname "$0")" || exit 1
exec /usr/bin/env python3 app.py
