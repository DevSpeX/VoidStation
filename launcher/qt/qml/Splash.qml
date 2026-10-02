// SPDX-License-Identifier: GPL-3.0-or-later
// Startbildschirm in der Kachelfarbe, bis das Programm ein Fenster hat
import QtQuick
import VS

Rectangle {
    id: sp
    property var tile: null
    property string hint: ""
    property bool keyShown: false
    property var shown: null
    z: 40
    color: shown && shown.color ? shown.color : Ui.c.tileDefaultC
    opacity: tile ? 1 : 0
    visible: opacity > 0
    onTileChanged: if (tile) shown = tile
    Behavior on opacity { NumberAnimation { duration: 250 } }
    MouseArea { anchors.fill: parent; hoverEnabled: true; onClicked: app.splashToBackground() }
    Column {
        anchors.centerIn: parent
        spacing: 0
        Glyph {
            anchors.horizontalCenter: parent.horizontalCenter
            width: sp.height * 0.16; height: width
            name: sp.shown ? (sp.shown.icon || "globe") : "globe"
            color: Ui.c.tileText
        }
        Item { width: 1; height: sp.height * 0.03 }
        Txt { anchors.horizontalCenter: parent.horizontalCenter; text: sp.shown ? Ui.l(sp.shown.label) : ""; font.pixelSize: 26 * Ui.f; font.weight: Font.Light; color: Ui.c.tileText }
        Item { width: 1; height: sp.height * 0.045 }
        Spinner { anchors.horizontalCenter: parent.horizontalCenter; visible: sp.visible }
        Item { width: 1; height: sp.height * 0.032 }
        Txt {
            anchors.horizontalCenter: parent.horizontalCenter
            width: Math.min(implicitWidth, sp.width * 0.6)
            horizontalAlignment: Text.AlignHCenter
            text: sp.hint
            wrapMode: Text.Wrap
            elide: Text.ElideNone
            color: Ui.c.textDim
            font.pixelSize: 15 * Ui.f
            lineHeight: 1.45
            height: Math.max(implicitHeight, 15 * Ui.f * 1.45)
        }
    }
    Txt {
        anchors.bottom: parent.bottom; anchors.bottomMargin: sp.height * 0.06
        anchors.horizontalCenter: parent.horizontalCenter
        text: String(Ui.t("splash.key")).replace(/<b>(.*?)<\/b>/g, "<b>$1</b>")
        textFormat: Text.StyledText
        color: Ui.c.textFaint
        font.pixelSize: 12 * Ui.f
        opacity: sp.keyShown ? 1 : 0
        Behavior on opacity { NumberAnimation { duration: 400 } }
    }
}
