// SPDX-License-Identifier: GPL-3.0-or-later
// Runder Knopf (Zurueck, Ausschalten, Blaetter-Pfeile)
import QtQuick

Focusable {
    id: r
    property string iconName: "chevleft"
    property real size: 44 * Ui.f
    property bool off: false
    width: size
    height: size
    opacity: off ? 0.22 : 1
    Rectangle {
        anchors.fill: parent
        radius: width / 2
        color: r.focused ? Ui.c.surfaceCardHover : "transparent"
        border.width: r.focused ? 2 : 1
        border.color: r.focused ? Ui.c.borderFocus : Ui.c.borderMuted
    }
    Glyph {
        anchors.centerIn: parent
        width: parent.width * 0.46; height: width
        name: r.iconName
        color: Ui.c.textPrimary
    }
}
