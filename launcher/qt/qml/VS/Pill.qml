// SPDX-License-Identifier: GPL-3.0-or-later
// Knopf in Zeilen (Filter, Einstellungen): an = Haekchen + aktive Farbe
import QtQuick

Focusable {
    id: p
    property string text
    property string iconName: ""
    property bool on: false
    property bool rich: false
    property real maxWidth: 0                    // > 0: Text bricht um statt abgeschnitten zu werden
    property bool dim: false
    opacity: enabled ? 1 : 0.35
    implicitHeight: Math.max(40 * Ui.f, label.implicitHeight + 18 * Ui.f)
    implicitWidth: maxWidth > 0 ? Math.min(maxWidth, row.implicitWidth + 32 * Ui.f + 4) : row.implicitWidth + 32 * Ui.f + 4
    width: implicitWidth
    height: implicitHeight

    Rectangle {
        anchors.fill: parent
        color: p.on ? Ui.c.surfaceActive : Ui.c.surfaceCard
        border.width: 2
        border.color: p.focused ? Ui.c.borderFocus : "transparent"
    }
    Row {
        id: row
        anchors.left: parent.left
        anchors.leftMargin: 16 * Ui.f + 2
        anchors.verticalCenter: parent.verticalCenter
        spacing: 8 * Ui.f
        Glyph {
            visible: p.iconName !== ""
            name: p.iconName
            color: p.on ? Ui.c.pillOnText : Ui.c.textPrimary
            width: 16 * Ui.f; height: width
            anchors.verticalCenter: parent.verticalCenter
        }
        Txt {
            id: label
            text: (p.on ? "✓ " : "") + p.text
            textFormat: p.rich ? Text.StyledText : Text.PlainText
            color: p.on ? Ui.c.pillOnText : Ui.c.textPrimary
            font.pixelSize: 15 * Ui.f
            elide: Text.ElideNone
            wrapMode: p.maxWidth > 0 ? Text.Wrap : Text.NoWrap
            width: p.maxWidth > 0 ? Math.min(implicitWidth, p.maxWidth - 32 * Ui.f - 4) : implicitWidth
            lineHeight: 1.1
            anchors.verticalCenter: parent.verticalCenter
        }
    }
}
