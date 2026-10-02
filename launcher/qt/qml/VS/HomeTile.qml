// SPDX-License-Identifier: GPL-3.0-or-later
// Kachel der Startseite: Symbol oder Bild, Name, Zusatz, laeuft-Balken, ✕ zum Schliessen;
// Sonderformen Uhr und Radio/Fernsehen (zeigt, was laeuft)
import QtQuick

Tile {
    id: ht
    property var t: ({})
    property string kind: t.type === "clock" ? "clock" : (t.type === "radio" || t.type === "tv") ? "media" : "app"
    property bool running: false
    property bool playing: false
    property string nowMain: ""
    property string nowSub: ""
    property string clockMain: ""
    property string clockAp: ""
    property string clockDate: ""
    property bool closable: !!t.cmd || t.type === "tv"
    readonly property real s: Math.min(width, height) >= Ui.u * 0.99 ? Ui.u : Math.min(width, height)
    navigable: kind !== "clock"
    tileColor: t.color || Ui.c.tileDefaultC
    readonly property color fg: Ui.c.tileText
    readonly property bool wide: width > height * 1.5

    Image {
        anchors.fill: parent
        visible: !!ht.t.image
        source: Ui.url(ht.t.image)
        fillMode: Image.PreserveAspectCrop
        asynchronous: true
    }
    Glyph {
        visible: !ht.t.image && ht.kind !== "clock" && !(ht.kind === "media" && ht.playing)
        name: ht.t.icon || "globe"
        color: ht.fg
        opacity: 0.95
        width: ht.wide ? parent.width * 0.18 : parent.width * 0.34
        height: ht.wide ? parent.height * 0.36 : parent.height * 0.34
        x: (parent.width - width) / 2
        y: parent.height * 0.42 - height / 2
    }
    Txt {                                        // Zusatz oben rechts (nicht auf kleinen Kacheln)
        visible: !!ht.t.sub && ht.wide
        text: Ui.l(ht.t.sub)
        anchors.right: parent.right; anchors.rightMargin: parent.width * 0.06
        y: parent.height * 0.08
        font.pixelSize: ht.s * 0.08
        color: Ui.c.tileSub
    }
    Txt {
        visible: ht.kind !== "clock"
        text: Ui.l(ht.t.label)
        x: parent.width * 0.07
        width: parent.width * 0.86
        anchors.bottom: parent.bottom; anchors.bottomMargin: parent.height * 0.07
        font.pixelSize: ht.s * 0.105
        color: ht.fg
    }
    // Uhr
    Row {
        visible: ht.kind === "clock"
        x: parent.width * 0.07; y: parent.height * 0.12
        Txt { text: ht.clockMain; font.pixelSize: ht.s * 0.42; font.weight: Font.Light; color: ht.fg; elide: Text.ElideNone }
        Txt { text: ht.clockAp; visible: text !== ""; font.pixelSize: ht.s * 0.42 * 0.36; color: ht.fg; leftPadding: ht.s * 0.42 * 0.18
              anchors.baseline: parent.children[0].baseline; elide: Text.ElideNone }
    }
    Txt {
        visible: ht.kind === "clock"
        text: ht.clockDate
        x: parent.width * 0.075; width: parent.width * 0.85
        anchors.bottom: parent.bottom; anchors.bottomMargin: parent.height * 0.09
        font.pixelSize: ht.s * 0.1
        color: Ui.c.light ? "#ccffffff" : Ui.c.textDim
    }
    // Radio / Fernsehen: was laeuft
    Column {
        visible: ht.kind === "media" && ht.playing
        x: parent.width * 0.07; width: parent.width * 0.86; y: parent.height * 0.14
        spacing: 4
        Txt { width: parent.width; text: ht.nowMain; font.pixelSize: ht.s * 0.14; color: ht.fg }
        Txt { width: parent.width; text: ht.nowSub; font.pixelSize: ht.s * 0.095; color: Ui.c.light ? "#ccffffff" : Ui.c.textDim }
    }
    Eq {
        visible: ht.kind === "media" && ht.playing
        h: ht.s * 0.1
        color: ht.fg
        anchors.right: parent.right; anchors.rightMargin: parent.width * 0.07
        anchors.bottom: parent.bottom; anchors.bottomMargin: parent.height * 0.08
    }
    Rectangle {                                  // laeuft
        visible: ht.closable
        anchors.left: parent.left; anchors.right: parent.right; anchors.bottom: parent.bottom
        height: 4 * Ui.f
        color: Ui.c.light ? "#e6ffffff" : Ui.c.textSecondary
        transformOrigin: Item.Left
        scale: ht.running ? 1 : 0
        Behavior on scale { NumberAnimation { duration: 300; easing.type: Easing.OutQuint } }
    }
    Rectangle {                                  // ✕ schliessen (laeuft + Fokus)
        visible: ht.running && ht.focused && ht.closable
        x: parent.width * 0.05; y: parent.height * 0.07
        width: ht.s * 0.17; height: width; radius: width / 2
        color: Ui.c.surfaceOverlay
        z: 60
        Glyph { anchors.centerIn: parent; width: parent.width * 0.5; height: width; name: "close"; color: Ui.c.textPrimary }
        MouseArea { anchors.fill: parent; onClicked: Ui.app.closeApp(ht.t) }
    }
}
