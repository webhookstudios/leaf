#!/bin/sh
# Builds dist/leaf_<version>_all.deb. Needs only dpkg-deb.
#
# The package installs Leaf for every user of the machine:
#   /usr/bin/leaf                              the app
#   /usr/share/applications, /usr/share/icons   apps-menu entry and icon
set -e

ROOT="$(cd "$(dirname "$0")" && pwd)"
VERSION="$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$ROOT/leaf.py")"
[ -n "$VERSION" ] || { echo "Could not read __version__ from leaf.py" >&2; exit 1; }
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

install -d "$STAGE/DEBIAN" "$STAGE/usr/bin" \
    "$STAGE/usr/share/applications" \
    "$STAGE/usr/share/icons/hicolor/scalable/apps" \
    "$STAGE/usr/share/doc/leaf"

install -m 755 "$ROOT/leaf.py" "$STAGE/usr/bin/leaf"
install -d "$STAGE/usr/share/leaf"
cp -r "$ROOT/sedge" "$STAGE/usr/share/leaf/"
find "$STAGE/usr/share/leaf/sedge" -type f -exec chmod 644 {} +
install -m 644 "$ROOT/data/leaf.svg" "$STAGE/usr/share/icons/hicolor/scalable/apps/"
sed 's|@EXEC@|leaf|' "$ROOT/data/leaf.desktop.in" \
    > "$STAGE/usr/share/applications/leaf.desktop"
chmod 644 "$STAGE/usr/share/applications/leaf.desktop"

cat > "$STAGE/usr/share/doc/leaf/copyright" <<EOT
Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/
Upstream-Name: Leaf
Source: https://github.com/webhookstudios/leaf

Files: *
Copyright: 2026 Kaleb Schuster
License: Expat
 Permission is hereby granted, free of charge, to any person obtaining a copy
 of this software and associated documentation files (the "Software"), to deal
 in the Software without restriction, including without limitation the rights
 to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
 copies of the Software, and to permit persons to whom the Software is
 furnished to do so, subject to the following conditions:
 .
 The above copyright notice and this permission notice shall be included in
 all copies or substantial portions of the Software.
 .
 THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
 IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
 FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
 AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
 LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
 OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
 SOFTWARE.

Files: usr/share/leaf/sedge/fonts/*
Copyright: 2023 The Young Serif Project Authors; 2015 The Public Sans Project Authors
License: OFL-1.1
 The full license texts are in the same folder.
EOT
chmod 644 "$STAGE/usr/share/doc/leaf/copyright"

# Replaces/Breaks take over from this app's old package name, scrawl.
cat > "$STAGE/DEBIAN/control" <<EOT
Package: leaf
Version: $VERSION
Architecture: all
Maintainer: webhookstudios <354619278+webhookstudios@users.noreply.github.com>
Installed-Size: $(du -sk "$STAGE/usr" | cut -f1)
Depends: python3, python3-gi, gir1.2-gtk-3.0
Replaces: scrawl (<< 2~)
Breaks: scrawl (<< 2~)
Section: utils
Priority: optional
Homepage: https://github.com/webhookstudios/leaf
Description: Sticky notes for your Linux desktop
 Leaf puts simple sticky notes on your desktop. Each note is its own window
 that you can move, resize, recolor, name and roll up to its title bar. Notes
 snap to screen edges and corners, can be kept on top, and save automatically.
 .
 Open Leaf from the apps menu, or run "leaf --new" to add a note.
EOT

# Folders are created with the builder's umask; packages want 755.
find "$STAGE" -type d -exec chmod 755 {} +

mkdir -p "$ROOT/dist"
dpkg-deb --root-owner-group --build "$STAGE" "$ROOT/dist/leaf_${VERSION}_all.deb"
