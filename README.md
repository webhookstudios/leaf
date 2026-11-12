# Leaf

*Part of the Sedge family of webhookstudios apps.*

Simple sticky notes for your Linux desktop. Each note is its own window you can drag, resize, recolor and pin on top. Everything saves automatically.

![Leaf notes](docs/screenshot.png)

## Features

- Unlimited notes, each in its own borderless window
- Name your notes with a title, and double-click the header to roll a note up to just its title bar
- Format just the words you select: bold, underline, and bigger or smaller text, from a pop-up with cut, copy and paste
- A grab bar that appears when you hover the left edge and only moves the note, so you can't click the title by accident
- Snaps to screen edges and corners (no accidental full-screen tiling)
- 7 pastel colors, adjustable text size, and a font picker for each note
- "Keep on top" pin
- Auto-saves text, title, position, size, color, pin and rolled-up state, and saves instantly on logout or shutdown
- Single instance: launching again brings your notes forward
- Optional start at login

## Install

### With the deb package (recommended)

Download `leaf_1.3.2_all.deb` from the [latest release](https://github.com/webhookstudios/leaf/releases/latest), then install it:

```bash
sudo apt install ./leaf_1.3.2_all.deb
```

Open **Leaf** from the apps menu (or run `leaf`). Apt pulls in Python 3 and the GTK 3 bindings automatically.

To remove it:

```bash
sudo apt remove leaf
```

Your notes are kept in `~/.local/share/leaf/` and survive removal.

### From source, without root

Requires Python 3 and GTK 3 (preinstalled on Ubuntu desktop). If missing:

```bash
sudo apt install python3 python3-gi gir1.2-gtk-3.0
```

Then:

```bash
git clone https://github.com/webhookstudios/leaf && cd leaf
./install.sh              # app menu + `leaf` command
./install.sh --autostart  # ...and start at login
```

Keep the folder in place: the `leaf` command links to `leaf.py`.

## Use

| Action | How |
| --- | --- |
| New note | `+` button, `Ctrl+N`, or `leaf --new` |
| Move | Drag the grab bar on the left edge (or the header); notes snap to screen edges and corners |
| Format words | Select text; a pop-up offers cut, copy, paste, **B**, <u>U</u>, A− and A+. Also `Ctrl+B` and `Ctrl+U` |
| Name a note | Click "Title" in the header (or right-click the header), type, press Enter |
| Roll up / unroll | Double-click the header |
| Resize | Drag the ◢ corner |
| Color / font / text size | ☰ menu |
| Delete note | ✕ button or `Ctrl+W` (asks first if it has text) |

Tip: bind `leaf --new` to a shortcut in Settings → Keyboard → Custom Shortcuts.

## Troubleshooting

**Leaf shows up in search but not in the Show Applications grid (GNOME).** GNOME keeps a saved grid layout and doesn't always add new apps to it. Either reset the grid (this clears any custom ordering):

```bash
gsettings reset org.gnome.shell app-picker-layout
```

or pin Leaf to the dock from the search results (right-click, then Pin to Dock).

## Uninstall

If you installed the deb, use `sudo apt remove leaf`. If you installed from source:

```bash
./uninstall.sh          # keeps your notes
./uninstall.sh --purge  # also deletes them
```

Notes live in `~/.local/share/leaf/notes.json`.

## Notes on Wayland

Wayland doesn't let apps position their own windows, so Leaf runs through XWayland (`GDK_BACKEND=x11`). That's what lets notes remember where you put them.

## License

MIT

## Building the deb

```bash
./build-deb.sh
```

Writes `dist/leaf_<version>_all.deb` and needs only `dpkg-deb`. The version comes from `__version__` in `leaf.py`.
