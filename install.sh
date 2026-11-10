#!/usr/bin/env bash
# Installs Scrawl for the current user: command, icon, app-menu launcher, optional autostart.
#   ./install.sh               install
#   ./install.sh --autostart   install and start Scrawl at login
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"

if ! python3 -c "import gi; gi.require_version('Gtk','3.0'); from gi.repository import Gtk, Gdk" 2>/dev/null; then
  cat >&2 <<MSG
Scrawl needs Python 3 with GTK 3 bindings, which weren't found.
Install them, then run this script again:

  sudo apt install python3 python3-gi gir1.2-gtk-3.0

(Fedora: sudo dnf install python3-gobject gtk3   Arch: sudo pacman -S python-gobject gtk3)
MSG
  exit 1
fi

BIN="$HOME/.local/bin"
APPS="$HOME/.local/share/applications"
ICONS="$HOME/.local/share/icons/hicolor/scalable/apps"
mkdir -p "$BIN" "$APPS" "$ICONS"

chmod +x "$DIR/scrawl.py"
ln -sf "$DIR/scrawl.py" "$BIN/scrawl"
cp "$DIR/data/scrawl.svg" "$ICONS/scrawl.svg"

sed "s|@EXEC@|$BIN/scrawl|" "$DIR/data/scrawl.desktop.in" > "$APPS/scrawl.desktop"

if [[ "${1:-}" == "--autostart" ]]; then
  mkdir -p "$HOME/.config/autostart"
  cp "$APPS/scrawl.desktop" "$HOME/.config/autostart/scrawl.desktop"
  echo "Autostart enabled."
fi

command -v gtk-update-icon-cache >/dev/null && gtk-update-icon-cache -q -t "$HOME/.local/share/icons/hicolor" 2>/dev/null || true
command -v update-desktop-database >/dev/null && update-desktop-database -q "$APPS" 2>/dev/null || true

echo "Installed. Run 'scrawl' or find Scrawl in your app menu."
case ":$PATH:" in *":$BIN:"*) ;; *) echo "Note: $BIN isn't on your PATH yet; log out and back in." ;; esac
echo "Tip: bind 'scrawl --new' to a keyboard shortcut in Settings > Keyboard."
