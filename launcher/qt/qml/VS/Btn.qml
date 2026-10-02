// SPDX-License-Identifier: GPL-3.0-or-later
// Knopf in Dialogen
import QtQuick

Focusable {
    id: b
    property string text
    property bool danger: false
    property bool on: false
    property bool center: false
    implicitWidth: Math.max(180 * Ui.f, label.implicitWidth + 40 * Ui.f + 4)
    implicitHeight: label.implicitHeight + 24 * Ui.f + 4
    width: implicitWidth
    height: implicitHeight
    Rectangle {
        anchors.fill: parent
        color: b.danger ? Ui.c.statusDangerBg : b.on ? Ui.c.surfaceActive : Ui.c.surfaceCard
        border.width: 2
        border.color: b.focused ? Ui.c.borderFocus : "transparent"
    }
    Txt {
        id: label
        x: b.center ? (parent.width - width) / 2 : 20 * Ui.f + 2
        anchors.verticalCenter: parent.verticalCenter
        width: Math.min(implicitWidth, b.width - 40 * Ui.f - 4)
        text: b.text
        font.pixelSize: 17 * Ui.f
        fontSizeMode: Text.HorizontalFit
        minimumPixelSize: 12 * Ui.f
        color: b.on ? Ui.c.pillOnText : Ui.c.textPrimary
    }
}
