#!/usr/bin/env python3
# Copyright (c) 2026 Kaleb Schuster, MIT License
"""Leaf - simple sticky notes for the Ubuntu desktop (GTK3)."""
import os

# Wayland doesn't let apps place their own windows; XWayland does.
os.environ.setdefault("GDK_BACKEND", "x11")

import json
import signal
import sys
import uuid
import tempfile

import gi

__version__ = "1.3.1"

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gio, GLib, Gtk, Pango  # noqa: E402

DATA_DIR = os.path.join(
    os.environ.get("XDG_DATA_HOME", os.path.expanduser("~/.local/share")), "leaf"
)
DATA_FILE = os.path.join(DATA_DIR, "notes.json")
# Leaf was called Scrawl. Its notes are copied over the first time Leaf starts;
# the old folder stays as it was, as a backup.
OLD_DATA_DIR = os.path.join(
    os.environ.get("XDG_DATA_HOME", os.path.expanduser("~/.local/share")), "scrawl"
)


def bring_over_old_notes():
    if not os.path.exists(DATA_DIR) and os.path.isdir(OLD_DATA_DIR):
        import shutil
        shutil.copytree(OLD_DATA_DIR, DATA_DIR)

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
MIN_SIZE = (170, 210)  # tall enough for the settings menu to fit inside
CLICK_SLOP = 8  # px the pointer may wander during a click before it counts as a drag
SNAP_DIST = 24  # px from a screen edge/corner at which a note snaps
FONT_SIZES = [10, 11, 12, 13, 14, 16, 18, 22]
# Relative sizes for individual words (multiplies the note's base text size)
SCALES = [0.7, 0.85, 1.0, 1.25, 1.5, 2.0, 2.6]
FORMAT_TAGS = (["bold", "underline"] + [f"scale-{x}" for x in SCALES if x != 1.0])


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
        self.set_icon_name("leaf")
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
        self.moved = False
        self.press_on_title = False
        hbox = Gtk.Box(spacing=2)
        self.header.add(hbox)

        add_btn = self.icon_button("list-add-symbolic", "New note (Ctrl+N)")
        add_btn.connect("clicked", lambda *_: app.new_note())
        hbox.pack_start(add_btn, False, False, 0)

        # Title: a label you can click to rename (swaps to an entry). The rest of
        # the header drags the note; double-click anywhere on it rolls the note up.
        self.title_stack = Gtk.Stack()
        self.title_label = Gtk.Label(xalign=0)
        self.title_label.set_ellipsize(Pango.EllipsizeMode.END)
        self.title_label.set_width_chars(1)
        self.title_label.get_style_context().add_class("note-title")
        self.title_entry = Gtk.Entry(has_frame=False, max_length=80, width_chars=1)
        self.title_entry.set_placeholder_text("Title")
        self.title_entry.connect("activate", lambda *_: self.stop_edit(True))
        self.title_entry.connect("focus-out-event", lambda *_: self.stop_edit(True) or False)
        self.title_entry.connect("key-press-event", self.on_title_key)
        self.title_entry.connect("button-press-event", self.on_title_click)
        self.title_stack.add_named(self.title_label, "label")
        self.title_stack.add_named(self.title_entry, "entry")
        hbox.pack_start(self.title_stack, True, True, 4)
        self.header.set_tooltip_text("Drag to move \u2022 click title to rename \u2022 double-click to roll up")
        self.last_click = None
        self.editing = False

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
        self.scroll = scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.view = Gtk.TextView()
        self.view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.view.set_left_margin(4)
        self.view.set_right_margin(10)
        self.view.set_top_margin(8)
        self.view.set_bottom_margin(20)  # keeps the last line clear of the grip
        self.buf = self.view.get_buffer()
        self.make_tags()
        self.buf.set_text(data.get("text", ""))
        self.load_formatting(data.get("tags", []))
        self.buf.connect("changed", self.on_changed)
        # connect_after: the tag must already be applied when we read it back
        self.buf.connect_after("apply-tag", lambda *_: self.sync_data())
        self.buf.connect_after("remove-tag", lambda *_: self.sync_data())
        self.buf.connect("notify::has-selection", self.on_selection_changed)
        self.view.add_events(Gdk.EventMask.BUTTON_RELEASE_MASK | Gdk.EventMask.KEY_RELEASE_MASK)
        self.view.connect("button-release-event", self.on_view_release)
        self.view.connect("key-release-event", self.on_view_key_release)
        self.build_selection_popover()
        scroll.set_shadow_type(Gtk.ShadowType.NONE)
        scroll.add(self.view)

        # Resize grip floats over the bottom-right corner of the text instead of
        # living in its own strip, so there's no seam along the bottom edge.
        grip = Gtk.EventBox()
        grip.set_size_request(18, 18)
        grip.set_halign(Gtk.Align.END)
        grip.set_valign(Gtk.Align.END)
        grip.add(Gtk.Label(label="\u25e2"))
        grip.get_style_context().add_class("grip")
        grip.connect("button-press-event", self.on_grip_press)
        grip.connect("realize", lambda w: w.get_window().set_cursor(
            Gdk.Cursor.new_from_name(w.get_display(), "se-resize")))
        overlay = Gtk.Overlay()
        overlay.add(scroll)
        overlay.add_overlay(grip)

        # Grab bar: a strip down the left of the text that only ever moves the
        # note, so you can reposition it without risking a click on the title.
        # It's invisible until the pointer is over it.
        self.grab_bar = Gtk.EventBox()
        self.grab_bar.set_size_request(14, -1)
        self.grab_bar.set_tooltip_text("Drag to move")
        self.grab_bar.get_style_context().add_class("grab-bar")
        self.grab_bar.add_events(Gdk.EventMask.POINTER_MOTION_MASK
                                 | Gdk.EventMask.BUTTON_RELEASE_MASK
                                 | Gdk.EventMask.ENTER_NOTIFY_MASK
                                 | Gdk.EventMask.LEAVE_NOTIFY_MASK)
        dots = Gtk.Label(label="\u22ee")
        dots.get_style_context().add_class("grab-dots")
        self.grab_bar.add(dots)
        self.grab_bar.connect("button-press-event", self.on_bar_press)
        self.grab_bar.connect("motion-notify-event", self.on_header_motion)
        self.grab_bar.connect("button-release-event", self.on_bar_release)
        self.grab_bar.connect("enter-notify-event", lambda *_: self.show_bar(True))
        self.grab_bar.connect("leave-notify-event", self.on_bar_leave)
        self.grab_bar.connect("realize", lambda w: w.get_window().set_cursor(
            Gdk.Cursor.new_from_name(w.get_display(), "grab")))

        self.body = Gtk.Box()
        self.body.pack_start(self.grab_bar, False, False, 0)
        self.body.pack_start(overlay, True, True, 0)
        root.pack_start(self.body, True, True, 0)

        self.connect("configure-event", self.on_configure)
        self.connect("key-press-event", self.on_key)
        self.connect("delete-event", lambda *_: self.on_close())

        self.apply_style()
        self.show_all()
        if "pos" in data:
            self.move(*data["pos"])
        self.pin_btn.set_opacity(1.0 if data.get("pinned") else 0.5)
        self.refresh_title()
        if data.get("rolled"):
            self.apply_roll()

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
        family = (self.data.get("font") or "").replace('"', "").replace("\\", "")
        family_css = f'\n            font-family: "{family}";' if family else ""
        css = f"""
        {w}, {w} textview, {w} textview text {{
            background-color: {paper}; color: {text};
            font-size: {size}px;{family_css}
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
        {w} .grab-bar {{ background-color: {paper}; }}
        {w} .grab-bar.show {{ background-color: {header}; }}
        {w} .grab-dots {{ color: {text}; opacity: 0; font-size: 14px; font-weight: 700; }}
        {w} .grab-bar.show .grab-dots {{ opacity: 0.6; }}
        {w} .note-title {{ color: {text}; font-weight: 600; font-size: 12px; }}
        {w} entry {{ background-color: rgba(255,255,255,0.5); color: {text};
                     caret-color: {text}; border: none; box-shadow: none;
                     min-height: 0; padding: 0 4px; border-radius: 3px;
                     font-size: 12px; font-weight: 600; }}
        {w} .grip {{ color: rgba(0,0,0,0.35); font-size: 11px; }}
        {w} scrolledwindow, {w} overlay {{ background-color: {paper}; border: none;
                                           box-shadow: none; }}
        {w} undershoot, {w} overshoot {{ background: none; background-image: none; }}
        {w} scrollbar {{ background: transparent; border: none; }}
        {w} scrollbar slider {{ background-color: rgba(0,0,0,0.28); border: none;
                                min-width: 6px; min-height: 6px; }}
        """
        self.provider.load_from_data(css.encode())
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), self.provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1)

    # ---------- events ----------
    # Dragging is handled here instead of begin_move_drag() so the window
    # manager never sees a "move" and can't tile/maximize the note at screen
    # edges. We snap to edges and corners ourselves.
    def is_double_click(self, ev):
        """Own double-click detection (GDK's is unreliable across child windows)."""
        gap = Gtk.Settings.get_default().get_property("gtk-double-click-time")
        last = self.last_click
        if last and ev.time - last[0] <= gap and abs(ev.x_root - last[1]) <= 6 \
                and abs(ev.y_root - last[2]) <= 6:
            self.last_click = None
            return True
        self.last_click = (ev.time, ev.x_root, ev.y_root)
        return False

    def on_header_press(self, widget, ev):
        if ev.button == 3:  # right-click anywhere on the header also renames
            self.start_edit()
            return True
        if ev.button != 1:
            return True
        if self.is_double_click(ev):
            self.drag = None
            self.toggle_roll()
            return True
        x, y = self.get_position()
        self.drag = (ev.x_root - x, ev.y_root - y)
        self.drag_start = (ev.x_root, ev.y_root)
        self.moved = False
        tx, ty = self.title_stack.translate_coordinates(self.header, 0, 0)
        a = self.title_stack.get_allocation()
        self.press_on_title = tx <= ev.x <= tx + a.width and ty <= ev.y <= ty + a.height
        return True

    def show_bar(self, visible):
        ctx = self.grab_bar.get_style_context()
        (ctx.add_class if visible else ctx.remove_class)("show")

    def on_bar_leave(self, *_):
        if not self.drag:  # keep it showing while it's being dragged
            self.show_bar(False)

    def on_bar_release(self, widget, ev):
        self.on_header_release(widget, ev)
        # Hide again if the pointer isn't over the bar any more
        pointer = Gdk.Display.get_default().get_default_seat().get_pointer()
        _w, x, y, _m = self.grab_bar.get_window().get_device_position(pointer)
        a = self.grab_bar.get_allocation()
        if not (0 <= x < a.width and 0 <= y < a.height):
            self.show_bar(False)
        return True

    def on_bar_press(self, widget, ev):
        if ev.button == 1:
            x, y = self.get_position()
            self.drag = (ev.x_root - x, ev.y_root - y)
            self.drag_start = (ev.x_root, ev.y_root)
            self.moved = False
            self.press_on_title = False
        return True

    def on_header_motion(self, widget, ev):
        if not self.drag:
            return False
        # Trackpad clicks jitter a few pixels; don't call that a drag.
        if not self.moved and (abs(ev.x_root - self.drag_start[0]) > CLICK_SLOP
                               or abs(ev.y_root - self.drag_start[1]) > CLICK_SLOP):
            self.moved = True
        if not self.moved:
            return True
        x = int(ev.x_root - self.drag[0])
        y = int(ev.y_root - self.drag[1])
        self.move(*self.snap(x, y, ev.x_root, ev.y_root))
        return True

    def on_header_release(self, widget, ev):
        was_click = self.drag and not self.moved and self.press_on_title
        self.drag = None
        if was_click and not self.editing:
            self.start_edit()
        return True

    # ---------- rich text ----------
    def make_tags(self):
        self.buf.create_tag("bold", weight=Pango.Weight.BOLD)
        self.buf.create_tag("underline", underline=Pango.Underline.SINGLE)
        for x in SCALES:
            if x != 1.0:
                self.buf.create_tag(f"scale-{x}", scale=x)

    def load_formatting(self, runs):
        table = self.buf.get_tag_table()
        n = self.buf.get_char_count()
        for start, end, name in runs:
            tag = table.lookup(name)
            if tag and 0 <= start < end <= n:
                self.buf.apply_tag(tag, self.buf.get_iter_at_offset(start),
                                   self.buf.get_iter_at_offset(end))

    def collect_formatting(self):
        runs = []
        table = self.buf.get_tag_table()
        for name in FORMAT_TAGS:
            tag = table.lookup(name)
            it = self.buf.get_start_iter()
            while True:
                if not it.has_tag(tag) and not it.forward_to_tag_toggle(tag):
                    break
                start = it.get_offset()
                more = it.forward_to_tag_toggle(tag)
                runs.append([start, it.get_offset(), name])
                if not more:
                    break
        return runs

    def sync_data(self):
        start, end = self.buf.get_bounds()
        self.data["text"] = self.buf.get_text(start, end, True)
        self.data["tags"] = self.collect_formatting()
        self.queue_save()

    def selection_bounds(self):
        b = self.buf.get_selection_bounds()
        return b if b else None

    def toggle_format(self, name):
        sel = self.selection_bounds()
        if not sel:
            return
        s, e = sel
        tag = self.buf.get_tag_table().lookup(name)
        it, all_tagged = s.copy(), True
        while it.compare(e) < 0:
            if not it.has_tag(tag):
                all_tagged = False
                break
            it.forward_char()
        (self.buf.remove_tag if all_tagged else self.buf.apply_tag)(tag, s, e)

    def step_scale(self, delta):
        sel = self.selection_bounds()
        if not sel:
            return
        s, e = sel
        cur = 1.0
        for t in s.get_tags():
            if t.props.name and t.props.name.startswith("scale-"):
                cur = float(t.props.name[6:])
        i = min(range(len(SCALES)), key=lambda j: abs(SCALES[j] - cur))
        new = SCALES[max(0, min(len(SCALES) - 1, i + delta))]
        table = self.buf.get_tag_table()
        for x in SCALES:
            if x != 1.0:
                self.buf.remove_tag(table.lookup(f"scale-{x}"), s, e)
        if new != 1.0:
            self.buf.apply_tag(table.lookup(f"scale-{new}"), s, e)

    # ---------- selection popup (cut/copy/paste + formatting) ----------
    def build_selection_popover(self):
        pop = Gtk.Popover.new(self.view)
        pop.set_modal(False)  # keep the selection and keyboard focus in the text
        pop.set_position(Gtk.PositionType.TOP)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.set_border_width(6)

        def btn(child, tip, fn):
            b = Gtk.Button()
            b.set_focus_on_click(False)
            b.set_tooltip_text(tip)
            b.add(child)
            b.connect("clicked", lambda *_: fn())
            return b

        def icon(name):
            return Gtk.Image.new_from_icon_name(name, Gtk.IconSize.MENU)

        def text(markup):
            l = Gtk.Label()
            l.set_markup(markup)
            return l

        row1 = Gtk.Box(spacing=4, homogeneous=True)
        row1.pack_start(btn(icon("edit-cut-symbolic"), "Cut", lambda: self.clip_action("cut")), True, True, 0)
        row1.pack_start(btn(icon("edit-copy-symbolic"), "Copy", lambda: self.clip_action("copy")), True, True, 0)
        row1.pack_start(btn(icon("edit-paste-symbolic"), "Paste", lambda: self.clip_action("paste")), True, True, 0)
        row2 = Gtk.Box(spacing=4, homogeneous=True)
        row2.pack_start(btn(text("<b>B</b>"), "Bold (Ctrl+B)", lambda: self.toggle_format("bold")), True, True, 0)
        row2.pack_start(btn(text("<u>U</u>"), "Underline (Ctrl+U)", lambda: self.toggle_format("underline")), True, True, 0)
        row2.pack_start(btn(text("A\u2212"), "Smaller", lambda: self.step_scale(-1)), True, True, 0)
        row2.pack_start(btn(text("A+"), "Bigger", lambda: self.step_scale(+1)), True, True, 0)
        box.pack_start(row1, False, False, 0)
        box.pack_start(row2, False, False, 0)
        pop.add(box)
        box.show_all()
        self.sel_pop = pop

    def clip_action(self, what):
        clip = self.view.get_clipboard(Gdk.SELECTION_CLIPBOARD)
        if what == "cut":
            self.buf.cut_clipboard(clip, True)
        elif what == "copy":
            self.buf.copy_clipboard(clip)
        else:
            self.buf.paste_clipboard(clip, None, True)
        self.sel_pop.popdown()
        self.view.grab_focus()

    def show_selection_popup(self):
        sel = self.selection_bounds()
        if not sel or self.data.get("rolled"):
            return False
        s, e = sel
        r = self.view.get_iter_location(s)
        x, y = self.view.buffer_to_window_coords(Gtk.TextWindowType.WIDGET, r.x, r.y)
        vis_h = self.view.get_allocated_height()
        y = max(0, min(y, vis_h - r.height))
        self.sel_pop.set_pointing_to(Gdk.Rectangle(max(0, x), y, max(1, r.width), r.height))
        self.sel_pop.popup()
        return False

    def on_view_release(self, *_):
        GLib.idle_add(self.show_selection_popup)  # after GTK has updated the selection
        return False

    def on_view_key_release(self, _w, ev):
        if ev.state & Gdk.ModifierType.SHIFT_MASK and self.buf.get_has_selection():
            self.show_selection_popup()
        return False

    def on_selection_changed(self, *_):
        if not self.buf.get_has_selection():
            self.sel_pop.popdown()

    # ---------- title ----------
    def refresh_title(self):
        title = self.data.get("title", "").strip()
        self.title_label.set_text(title or "Title")
        self.title_label.set_opacity(1.0 if title else 0.45)
        self.set_title(title or "Sticky Note")

    def start_edit(self):
        self.editing = True
        self.title_entry.set_text(self.data.get("title", ""))
        self.title_stack.set_visible_child_name("entry")
        self.title_entry.grab_focus()
        self.title_entry.select_region(0, -1)

    def stop_edit(self, commit):
        if not self.editing:
            return
        self.editing = False
        if commit:
            self.data["title"] = self.title_entry.get_text().strip()
            self.queue_save()
        self.refresh_title()
        self.title_stack.set_visible_child_name("label")
        if not self.data.get("rolled"):
            self.view.grab_focus()

    def on_title_key(self, _w, ev):
        if ev.keyval == Gdk.KEY_Escape:
            self.stop_edit(False)
            return True
        return False

    def on_title_click(self, _w, ev):
        if ev.button == 1 and self.is_double_click(ev):
            self.toggle_roll()
            return True
        return False

    # ---------- roll up ----------
    def toggle_roll(self):
        self.stop_edit(True)
        self.data["rolled"] = not self.data.get("rolled", False)
        self.apply_roll()
        self.queue_save()

    def apply_roll(self):
        rolled = self.data.get("rolled", False)
        w, h = self.get_size()
        if rolled:
            self.body.hide()
            self.set_size_request(MIN_SIZE[0], -1)
            self.resize(w, 1)
        else:
            self.body.show()
            self.set_size_request(*MIN_SIZE)
            self.resize(w, max(self.data["size"][1], MIN_SIZE[1]))
            self.view.grab_focus()

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
        if self.data.get("rolled"):
            self.data["size"][0] = w  # keep the full height for when it unrolls
        else:
            self.data["size"] = [w, h]
        self.data["pos"] = [x, y]
        self.queue_save()
        return False

    def on_changed(self, *_):
        self.sync_data()

    def on_key(self, _w, ev):
        if ev.state & Gdk.ModifierType.CONTROL_MASK:
            k = Gdk.keyval_name(ev.keyval)
            if k in ("n", "N"):
                self.app.new_note()
                return True
            if k in ("w", "W"):
                self.delete()
                return True
            if k in ("b", "B") and self.buf.get_has_selection():
                self.toggle_format("bold")
                return True
            if k in ("u", "U") and self.buf.get_has_selection():
                self.toggle_format("underline")
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

        # Font: opens the system font picker (families only). x resets to default.
        frow = Gtk.Box(spacing=4)
        fbtn = Gtk.Button(label=self.data.get("font") or "Default font")
        fbtn.set_focus_on_click(False)
        fbtn.set_tooltip_text("Choose a font for this note")
        fbtn.get_child().set_ellipsize(Pango.EllipsizeMode.END)
        fbtn.get_child().set_max_width_chars(11)
        fbtn.connect("clicked", lambda *_: (pop.popdown(), GLib.idle_add(self.choose_font)))
        frow.pack_start(fbtn, True, True, 0)
        if self.data.get("font"):
            rst = Gtk.Button(label="\u2715")
            rst.set_focus_on_click(False)
            rst.set_tooltip_text("Reset the font")
            rst.connect("clicked", lambda *_: (self.set_font(None), pop.popdown()))
            frow.pack_start(rst, False, False, 0)
        box.pack_start(frow, False, False, 0)

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

    def choose_font(self):
        dlg = Gtk.FontChooserDialog(title="Choose a font", transient_for=self, modal=True)
        dlg.set_level(Gtk.FontChooserLevel.FAMILY)  # just the family; size is set elsewhere
        dlg.set_preview_text("The quick brown fox jumps over the lazy dog")
        current = self.data.get("font")
        if current:
            dlg.set_font(f"{current} 12")
        if dlg.run() == Gtk.ResponseType.OK:
            desc = dlg.get_font_desc()
            if desc and desc.get_family():
                self.set_font(desc.get_family())
        dlg.destroy()
        return False

    def set_font(self, family):
        if family:
            self.data["font"] = family
        else:
            self.data.pop("font", None)
        self.apply_style()
        self.queue_save()

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


SEDGE_FONTS = ("YoungSerif-Regular.ttf", "PublicSans[wght].ttf", "PublicSans-Italic[wght].ttf")


def apply_sedge():
    """The Sedge accent color and fonts for Leaf's menus and dialogs.
    Each note keeps its own colors and the font chosen for it."""
    here = os.path.dirname(os.path.realpath(__file__))
    folder = next((d for d in (os.path.join(here, "sedge"), "/usr/share/leaf/sedge")
                   if os.path.isfile(os.path.join(d, "sedge-gtk3.css"))), None)
    if folder is None:
        return
    try:
        gi.require_version("PangoCairo", "1.0")
        from gi.repository import PangoCairo
        fontmap = PangoCairo.FontMap.get_default()
        for name in SEDGE_FONTS:
            fontmap.add_font_file(os.path.join(folder, "fonts", name))
    except Exception:  # the system font is fine
        pass
    provider = Gtk.CssProvider()
    provider.load_from_path(os.path.join(folder, "sedge-gtk3.css"))
    Gtk.StyleContext.add_provider_for_screen(
        Gdk.Screen.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)


class Leaf(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="io.github.webhookstudios.Leaf",
                         flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.notes = []
        self.started = False
        self.add_main_option("new", ord("n"), 0, 0, "Create a new note", None)
        # Logout/shutdown sends SIGTERM (or SIGHUP): save immediately, don't wait
        # for the 0.4s typing debounce.
        try:
            from gi.repository import GLibUnix
            add_signal = lambda sig: GLibUnix.signal_add(GLib.PRIORITY_HIGH, sig, self.on_signal)
        except ImportError:  # older PyGObject
            add_signal = lambda sig: GLib.unix_signal_add(GLib.PRIORITY_HIGH, sig, self.on_signal)
        for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
            add_signal(sig)

    def do_startup(self):
        Gtk.Application.do_startup(self)
        bring_over_old_notes()
        apply_sedge()

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
    GLib.set_prgname("leaf")  # window class matches leaf.desktop, so the dock groups it
    sys.exit(Leaf().run(sys.argv))
