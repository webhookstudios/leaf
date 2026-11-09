# Scrawl

Simple sticky notes for your Linux desktop. Each note is its own window you can drag, resize, recolor and pin on top. Everything saves automatically.

![Scrawl notes](docs/screenshot.png)

## Features

- Unlimited notes, each in its own borderless window
- 7 pastel colors and adjustable text size
- "Keep on top" pin
- Auto-saves text, position, size, color and pin state
- Single instance: launching again brings your notes forward
- Optional start at login

## Install

Requires Python 3 and GTK 3 (preinstalled on Ubuntu desktop). If missing:

```bash
sudo apt install python3 python3-gi gir1.2-gtk-3.0
```

Then:

```bash
git clone https://github.com/webhookstudios/scrawl && cd scrawl
./install.sh              # app menu + `scrawl` command
./install.sh --autostart  # ...and start at login
```

Keep the folder in place: the `scrawl` command links to `scrawl.py`.

## Use

| Action | How |
| --- | --- |
| New note | `+` button, `Ctrl+N`, or `scrawl --new` |
| Move | Drag the colored header |
| Resize | Drag the ◢ corner |
| Color / text size | ☰ menu |
| Delete note | ✕ button or `Ctrl+W` (asks first if it has text) |

Tip: bind `scrawl --new` to a shortcut in Settings → Keyboard → Custom Shortcuts.

## Uninstall

```bash
./uninstall.sh          # keeps your notes
./uninstall.sh --purge  # also deletes them
```

Notes live in `~/.local/share/scrawl/notes.json`.

## Notes on Wayland

Wayland doesn't let apps position their own windows, so Scrawl runs through XWayland (`GDK_BACKEND=x11`). That's what lets notes remember where you put them.

## License

MIT
