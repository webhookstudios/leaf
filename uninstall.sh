#!/usr/bin/env bash
# Removes Scrawl's launcher, icon, command and autostart entry.
# Your notes are kept unless you pass --purge.
set -euo pipefail

rm -f "$HOME/.local/bin/scrawl" \
      "$HOME/.local/share/applications/scrawl.desktop" \
      "$HOME/.local/share/icons/hicolor/scalable/apps/scrawl.svg" \
      "$HOME/.config/autostart/scrawl.desktop"

command -v gtk-update-icon-cache >/dev/null && gtk-update-icon-cache -q -t "$HOME/.local/share/icons/hicolor" 2>/dev/null || true
command -v update-desktop-database >/dev/null && update-desktop-database -q "$HOME/.local/share/applications" 2>/dev/null || true

DATA="${XDG_DATA_HOME:-$HOME/.local/share}/scrawl"
if [[ "${1:-}" == "--purge" ]]; then
  rm -rf "$DATA"
  echo "Uninstalled and deleted your notes."
else
  echo "Uninstalled. Your notes are still in $DATA (run with --purge to delete them)."
fi
