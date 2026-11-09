#!/usr/bin/env python3
# Copyright (c) 2026 Kaleb Schuster, MIT License
"""Scrawl - simple sticky notes for the Ubuntu desktop (GTK3)."""
import os

# Wayland doesn't let apps place their own windows; XWayland does.
os.environ.setdefault("GDK_BACKEND", "x11")

import json
import signal
import sys
import uuid
import tempfile

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: E402

DATA_DIR = os.path.join(
    os.environ.get("XDG_DATA_HOME", os.path.expanduser("~/.local/share")), "scrawl"
)
DATA_FILE = os.path.join(DATA_DIR, "notes.json")

# name: (paper, header, text)
COLORS = {
    "yellow": ("#fff7a8", "#f5e66b", "#3a3500"),
    "pink": ("#ffc9de", "#f7a3c4", "#4a1530"),
    "blue": ("#c7e6ff", "#9ccdf5", "#0e2f4a"),
    "green": ("#d0f5c0", "#a8e08e", "#1c3d0f"),
    "orange": ("#ffd9a8", "#f7bb72", "#4a2a05"),
    "purple": ("#e2d4ff", "#c6b0f5", "#2b1750"),
    "gray": ("#e8e8e8", "#cfcfcf", "#222222"),
}
DEFAULT_COLOR = "yellow"
DEFAULT_SIZE = (280, 300)
MIN_SIZE = (170, 160)
SNAP_DIST = 24  # px from a screen edge/corner at which a note snaps
FONT_SIZES = [10, 11, 12, 13, 14, 16, 18, 22]


def load_notes():
    try:
        with open(DATA_FILE) as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def save_notes(notes):
    os.makedirs(DATA_DIR, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=DATA_DIR)
    with os.fdopen(fd, "w") as f:
        json.dump(notes, f, indent=2)
        f.flush()
        os.fsync(f.fileno())  # force the data onto the disk, not just the OS cache
    os.replace(tmp, DATA_FILE)  # atomic: never leaves a half-written file
    try:  # make the rename itself durable too
        dfd = os.open(DATA_DIR, os.O_RDONLY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)
    except OSError:
        pass


class Note(Gtk.Window):
    def __init__(self, app, data):
        super().__init__(title="Sticky Note")
        self.app = app
        self.data = data
        self.provider = Gtk.CssProvider()
        self.save_timer = None

        self.set_decorated(False)
        self.set_icon_name("scrawl")
        self.set_default_size(*data["size"])
        self.set_skip_taskbar_hint(False)
        self.set_keep_above(data.get("pinned", False))
        self.set_resizable(True)
        self.set_size_request(*MIN_SIZE)
        self.cls = "n" + self.data["id"][:12]
        self.get_style_context().add_class("note")
        self.get_style_context().add_class(self.cls)
        self.add_events(Gdk.EventMask.STRUCTURE_MASK)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.add(root)

        # ---- header: drag handle + buttons ----
        self.header = Gtk.EventBox()
        self.header.get_style_context().add_class("note-header")
        self.header.add_events(Gdk.EventMask.POINTER_MOTION_MASK
                               | Gdk.EventMask.BUTTON_RELEASE_MASK)
        self.header.connect("button-press-event", self.on_header_press)
        self.header.connect("motion-notify-event", self.on_header_motion)
        self.header.connect("button-release-event", self.on_header_release)
        self.drag = None
        hbox = Gtk.Box(spacing=2)
        self.header.add(hbox)

        add_btn = self.icon_button("list-add-symbolic", "New note (Ctrl+N)")
        add_btn.connect("clicked", lambda *_: app.new_note())
        hbox.pack_start(add_btn, False, False, 0)

        hbox.pack_start(Gtk.Box(), True, True, 0)  # spacer = drag area

        self.pin_btn = self.icon_button("view-pin-symbolic", "Keep on top")
        self.pin_btn.connect("clicked", self.toggle_pin)
        hbox.pack_start(self.pin_btn, False, False, 0)

        menu_btn = self.icon_button("open-menu-symbolic", "Color & font size")
        menu_btn.connect("clicked", self.show_menu)
        self.menu_btn = menu_btn
        hbox.pack_start(menu_btn, False, False, 0)

        del_btn = self.icon_button("window-close-symbolic", "Delete note (Ctrl+W)")
        del_btn.connect("clicked", lambda *_: self.delete())
        hbox.pack_start(del_btn, False, False, 0)
        root.pack_start(self.header, False, False, 0)

        # ---- text body ----
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.view = Gtk.TextView()
        self.view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.view.set_left_margin(10)
        self.view.set_right_margin(10)
        self.view.set_top_margin(8)
        self.view.set_bottom_margin(8)
        self.buf = self.view.get_buffer()
        self.buf.set_text(data.get("text", ""))
        self.buf.connect("changed", self.on_changed)
        scroll.add(self.view)
        root.pack_start(scroll, True, True, 0)

        # ---- resize grip (bottom-right) ----
        grip_row = Gtk.Box()
        grip_row.pack_start(Gtk.Box(), True, True, 0)
        grip = Gtk.EventBox()
        grip.set_size_request(18, 18)
        grip.add(Gtk.Label(label="◢"))
        grip.get_style_context().add_class("grip")
        grip.connect("button-press-event", self.on_grip_press)
        grip.connect("realize", lambda w: w.get_window().set_cursor(
            Gdk.Cursor.new_from_name(w.get_display(), "se-resize")))
        grip_row.pack_end(grip, False, False, 0)
        root.pack_start(grip_row, False, False, 0)

        self.connect("configure-event", self.on_configure)
        self.connect("key-press-event", self.on_key)
        self.connect("delete-event", lambda *_: self.on_close())

        self.apply_style()
        self.show_all()
        if "pos" in data:
            self.move(*data["pos"])
        self.pin_btn.set_opacity(1.0 if data.get("pinned") else 0.5)

    # ---------- helpers ----------
    def icon_button(self, icon, tip):
        b = Gtk.Button()
        b.set_relief(Gtk.ReliefStyle.NONE)
        b.set_focus_on_click(False)
        b.set_tooltip_text(tip)
        b.add(Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.MENU))
        b.get_style_context().add_class("note-btn")
        return b

    def apply_style(self):
        paper, header, text = COLORS.get(self.data["color"], COLORS[DEFAULT_COLOR])
        size = self.data.get("font_size", 13)
        w = f"window.{self.cls}"
        css = f"""
        {w}, {w} textview, {w} textview text {{
            background-color: {paper}; color: {text};
            font-size: {size}px;
            caret-color: {text};
        }}
        {w} textview text selection {{
            background-color: {header}; color: {text};
        }}
        {w} {{ border: 1px solid rgba(0,0,0,0.25); }}
        {w} .note-header {{ background-color: {header}; padding: 2px 4px; }}
        {w} .note-btn {{ padding: 2px 4px; min-height: 0; min-width: 0; color: {text};
                     background: transparent; border: none; box-shadow: none; }}
        {w} .note-btn:hover {{ background-color: rgba(0,0,0,0.12); }}
        {w} .grip {{ color: rgba(0,0,0,0.35); font-size: 11px; }}
        {w} scrolledwindow {{ background-color: {paper}; }}
        """
        self.provider.load_from_data(css.encode())
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), self.provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1)

    # ---------- events ----------
    # Dragging is handled here instead of begin_move_drag() so the window
    # manager never sees a "move" and can't tile/maximize the note at screen
    # edges. We snap to edges and corners ourselves.
    def on_header_press(self, widget, ev):
        if ev.button == 1:
            x, y = self.get_position()
            self.drag = (ev.x_root - x, ev.y_root - y)
        return True

    def on_header_motion(self, widget, ev):
        if not self.drag:
            return False
        x = int(ev.x_root - self.drag[0])
        y = int(ev.y_root - self.drag[1])
        self.move(*self.snap(x, y, ev.x_root, ev.y_root))
        return True

    def on_header_release(self, widget, ev):
        self.drag = None
        return True

    def snap(self, x, y, px, py):
        """Snap the note's edges/corners to the usable screen area (panels excluded)."""
        display = Gdk.Display.get_default()
        mon = display.get_monitor_at_point(int(px), int(py))
        wa = mon.get_workarea()
        w, h = self.get_size()
        if abs(x - wa.x) <= SNAP_DIST:
            x = wa.x
        elif abs(x + w - (wa.x + wa.width)) <= SNAP_DIST:
            x = wa.x + wa.width - w
        if abs(y - wa.y) <= SNAP_DIST:
            y = wa.y
        elif abs(y + h - (wa.y + wa.height)) <= SNAP_DIST:
            y = wa.y + wa.height - h
        return x, y

    def on_grip_press(self, widget, ev):
        if ev.button == 1:
            self.begin_resize_drag(
                Gdk.WindowEdge.SOUTH_EAST, 1, int(ev.x_root), int(ev.y_root), ev.time)
        return True

    def on_configure(self, *_):
        w, h = self.get_size()
        x, y = self.get_position()
        self.data["size"] = [w, h]
        self.data["pos"] = [x, y]
        self.queue_save()
        return False

    def on_changed(self, *_):
        start, end = self.buf.get_bounds()
        self.data["text"] = self.buf.get_text(start, end, True)
        self.queue_save()

    def on_key(self, _w, ev):
        if ev.state & Gdk.ModifierType.CONTROL_MASK:
            k = Gdk.keyval_name(ev.keyval)
            if k in ("n", "N"):
                self.app.new_note()
                return True
            if k in ("w", "W"):
                self.delete()
                return True
        return False

    def queue_save(self):
        if self.save_timer:
            GLib.source_remove(self.save_timer)
        self.save_timer = GLib.timeout_add(400, self._flush)

    def _flush(self):
        self.save_timer = None
        self.app.persist()
        return False

    def on_close(self):
        # Closing the window == deleting only via the button; here just hide-quit
        self.app.persist()
        return False

    def toggle_pin(self, *_):
        pinned = not self.data.get("pinned", False)
        self.data["pinned"] = pinned
        self.set_keep_above(pinned)
        self.pin_btn.set_opacity(1.0 if pinned else 0.5)
        self.queue_save()

    def show_menu(self, *_):
        pop = Gtk.Popover.new(self.menu_btn)
        pop.set_position(Gtk.PositionType.BOTTOM)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_border_width(10)

        # Compact 4-column grid so the popover fits inside even the narrowest note.
        swatches = Gtk.Grid(column_spacing=6, row_spacing=6)
        for i, (name, (paper, header, _t)) in enumerate(COLORS.items()):
            b = Gtk.Button()
            b.set_size_request(24, 24)
            b.set_tooltip_text(name.capitalize())
            p = Gtk.CssProvider()
            p.load_from_data(
                f"button {{ background: {header}; border-radius: 12px; "
                f"min-width: 24px; min-height: 24px; padding: 0; }}".encode())
            b.get_style_context().add_provider(p, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
            b.connect("clicked", self.set_color, name, pop)
            swatches.attach(b, i % 4, i // 4, 1, 1)
        box.pack_start(swatches, False, False, 0)

        sizes = Gtk.Box(spacing=6, homogeneous=True)
        smaller = Gtk.Button.new_with_label("A−")
        bigger = Gtk.Button.new_with_label("A+")
        smaller.set_tooltip_text("Smaller text")
        bigger.set_tooltip_text("Bigger text")
        smaller.connect("clicked", self.step_font, -1)
        bigger.connect("clicked", self.step_font, +1)
        sizes.pack_start(smaller, True, True, 0)
        sizes.pack_start(bigger, True, True, 0)
        box.pack_start(sizes, False, False, 0)

        pop.add(box)
        box.show_all()
        pop.popup()

    def set_color(self, _b, name, pop):
        self.data["color"] = name
        self.apply_style()
        self.queue_save()
        pop.popdown()

    def step_font(self, _b, step):
        cur = self.data.get("font_size", 13)
        i = min(range(len(FONT_SIZES)), key=lambda j: abs(FONT_SIZES[j] - cur))
        i = max(0, min(len(FONT_SIZES) - 1, i + step))
        self.data["font_size"] = FONT_SIZES[i]
        self.apply_style()
        self.queue_save()

    def delete(self):
        text = self.data.get("text", "").strip()
        if text:
            dlg = Gtk.MessageDialog(
                transient_for=self, modal=True, message_type=Gtk.MessageType.QUESTION,
                buttons=Gtk.ButtonsType.NONE, text="Delete this note?")
            dlg.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Delete", Gtk.ResponseType.OK)
            resp = dlg.run()
            dlg.destroy()
            if resp != Gtk.ResponseType.OK:
                return
        self.app.remove_note(self)


class Scrawl(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="local.scrawl.Scrawl",
                         flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.notes = []
        self.started = False
        self.add_main_option("new", ord("n"), 0, 0, "Create a new note", None)
        # Logout/shutdown sends SIGTERM (or SIGHUP): save immediately, don't wait
        # for the 0.4s typing debounce.
        for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
            GLib.unix_signal_add(GLib.PRIORITY_HIGH, sig, self.on_signal)

    def on_signal(self):
        self.persist()
        self.quit()
        return GLib.SOURCE_REMOVE

    def do_shutdown(self):
        self.persist()
        Gtk.Application.do_shutdown(self)

    def do_command_line(self, cmdline):
        opts = cmdline.get_options_dict().end().unpack()
        if not self.started:
            self.started = True
            saved = load_notes()
            for d in saved:
                self.add_note(d)
            if not saved:
                self.new_note()
        if "new" in opts and len(self.notes) and self.started:
            self.new_note()
        elif self.started and self.notes:
            for n in self.notes:
                n.present()
        return 0

    def add_note(self, data):
        data.setdefault("id", uuid.uuid4().hex)
        data.setdefault("color", DEFAULT_COLOR)
        data.setdefault("size", list(DEFAULT_SIZE))
        data.setdefault("text", "")
        note = Note(self, data)
        self.add_window(note)
        self.notes.append(note)
        return note

    def new_note(self):
        import random
        color = random.choice(list(COLORS)[:6])
        d = {"color": color, "size": list(DEFAULT_SIZE)}
        if self.notes:
            x, y = self.notes[-1].get_position()
            d["pos"] = [x + 30, y + 30]
        note = self.add_note(d)
        note.view.grab_focus()
        self.persist()

    def remove_note(self, note):
        self.notes.remove(note)
        note.destroy()
        self.persist()
        if not self.notes:
            self.quit()

    def persist(self):
        save_notes([n.data for n in self.notes])


if __name__ == "__main__":
    sys.exit(Scrawl().run(sys.argv))
