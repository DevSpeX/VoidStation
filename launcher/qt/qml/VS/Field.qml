// SPDX-License-Identifier: GPL-3.0-or-later
// Eingabefeld: Enter / A oeffnet die Bildschirmtastatur (auch fuer die echte Tastatur)
import QtQuick

Focusable {
    id: fld
    property string value: ""
    property string placeholder: ""
    property bool password: false
    signal submitted(string text)
    implicitWidth: Math.min(280 * Ui.f, Ui.screenW * 0.4)
    implicitHeight: 40 * Ui.f
    width: implicitWidth
    height: implicitHeight
    function activate() { Ui.app.openOsk(fld) }
    Rectangle {
        anchors.fill: parent
        color: Ui.c.surfaceRaised
        border.width: 2
        border.color: fld.focused ? Ui.c.borderFocus : Ui.c.borderSubtle
    }
    Txt {
        anchors.left: parent.left; anchors.right: parent.right
        anchors.leftMargin: 12 * Ui.f + 2; anchors.rightMargin: 12 * Ui.f + 2
        anchors.verticalCenter: parent.verticalCenter
        text: fld.value ? (fld.password ? "•".repeat(fld.value.length) : fld.value) : fld.placeholder
        color: fld.value ? Ui.c.textPrimary : Ui.c.textFaint
        font.pixelSize: 15 * Ui.f
    }
}
