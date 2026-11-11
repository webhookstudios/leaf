#!/usr/bin/env bash
# Removes Leaf's launcher, icon, command and autostart entry.
# Your notes are kept unless you pass --purge.
set -euo pipefail

rm -f "$HOME/.local/bin/leaf" \
      "$HOME/.local/share/applications/leaf.desktop" \
      "$HOME/.local/share/icons/hicolor/scalable/apps/leaf.svg" \
      "$HOME/.config/autostart/leaf.desktop"

command -v gtk-update-icon-cache >/dev/null && gtk-update-icon-cache -q -t "$HOME/.local/share/icons/hicolor" 2>/dev/null || true
command -v update-desktop-database >/dev/null && update-desktop-database -q "$HOME/.local/share/applications" 2>/dev/null || true

DATA="${XDG_DATA_HOME:-$HOME/.local/share}/leaf"
if [[ "${1:-}" == "--purge" ]]; then
  rm -rf "$DATA"
  echo "Uninstalled and deleted your notes."
else
  echo "Uninstalled. Your notes are still in $DATA (run with --purge to delete them)."
fi
