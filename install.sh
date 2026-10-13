#!/bin/sh
# silo installer:  curl -fsSL https://raw.githubusercontent.com/flinner/silo/main/install.sh | sh
# Installs to ${SILO_BIN:-~/.local/bin}. Re-running it upgrades in place.
set -eu
BIN=${SILO_BIN:-$HOME/.local/bin}
URL=https://raw.githubusercontent.com/flinner/silo/main/silo

say() { printf '\033[1;36m::\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m!!\033[0m %s\n' "$*" >&2; }

missing=
command -v bwrap >/dev/null || missing="$missing bubblewrap"
command -v python3 >/dev/null || { warn "python3 is required"; exit 1; }
for m in click rich prompt_toolkit; do
  python3 -c "import $m" 2>/dev/null || missing="$missing python-$m"
done
if [ -n "$missing" ]; then
  warn "missing:$missing"
  warn "  Arch:          sudo pacman -S bubblewrap python-click python-rich python-prompt_toolkit"
  warn "  Debian/Ubuntu: sudo apt install bubblewrap python3-click python3-rich python3-prompt-toolkit"
  warn "  Fedora:        sudo dnf install bubblewrap python3-click python3-rich python3-prompt-toolkit"
  warn "installing silo anyway; it will not run until these are present"
fi

mkdir -p "$BIN"
tmp=$(mktemp)                     # in /tmp; never deleted by this script
curl -fsSL "$URL" -o "$tmp"
head -1 "$tmp" | grep -q '^#!/usr/bin/env python3' || { warn "download does not look like silo ($tmp)"; exit 1; }
install -m 755 "$tmp" "$BIN/silo"
ln -sfn silo "$BIN/silo-codex"
say "installed $("$BIN/silo" --version 2>/dev/null || echo silo) to $BIN/silo (+ silo-codex)"
case ":$PATH:" in *":$BIN:"*) ;; *) warn "$BIN is not on your PATH" ;; esac
say "next: silo init"
