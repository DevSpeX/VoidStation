// SPDX-License-Identifier: GPL-3.0-or-later
// Symbol aus icons.py in einer Farbe
import QtQuick

Image {
    property string name: "globe"
    property color color: Ui.c.textPrimary
    source: name ? Ui.icon(name, color) : ""
    sourceSize: Qt.size(Math.max(8, Math.ceil(width * 1.5)), Math.max(8, Math.ceil(height * 1.5)))
    fillMode: Image.PreserveAspectFit
    smooth: true
    asynchronous: false
    cache: true
}
