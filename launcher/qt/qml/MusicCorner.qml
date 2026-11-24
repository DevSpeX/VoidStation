// SPDX-License-Identifier: GPL-3.0-or-later
// Heisse Ecke oben links: Laeuft Musik oder Radio und ist ein Programm vorn, schwebt dort  ◀  Titel  ▶  zum Steuern,
// ohne das Spiel zu verlassen. Maus: Pfeile, Klick auf den Titel = Pause, Rad = Lautstaerke der Musik. Steuerkreuz
// oder Pfeiltasten, solange die Karte offen ist: ◀▶ Titel, ▲▼ Lautstaerke, A/Enter Pause, B/Esc zu.
// Die Lautstaerke ist nur die der Musik, Spielton und Systemlautstaerke bleiben.
// Eigenes Fenster wie die Ecke unten rechts (siehe Corner.qml): nimmt dem Programm den Fokus nicht weg.
import QtQuick
import QtQuick.Window
import VS

Window {
    id: mc
    flags: Qt.ToolTip | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.BypassWindowManagerHint
           | Qt.WindowDoesNotAcceptFocus
    transientParent: null
    color: Ui.c.surfaceDialog
    visible: false
    width: box.width + 2 * pad
    height: box.height + 2 * pad

    property real pad: 6 * Ui.f
    property real gap: 24 * Ui.f
    property var now: ({})
    property int awayMs: 0
    property real leftX: 0
    property real topY: 0

    function openAt(left, top) {
        Api.get("/api/nowplaying", function (r) {
            if (!r || !r.kind) return
            now = r
            leftX = left
            topY = top
            awayMs = 0
            mc.x = left + gap
            mc.y = top + gap
            visible = true
            raise()
            vs.log("Ecke oben links: offen, " + r.kind)
        })
    }
    function close(why) {
        if (visible) vs.log("Ecke oben links: zu (" + (why || "Startseite vorn") + ")")
        visible = false
        awayMs = 0
    }
    function control(a) {
        awayMs = 0
        if (a === "toggle") vs.playSound("toggle")
        else if (a === "prev" || a === "next") vs.playSound("select")
        Api.post("/api/nowplaying/control", { action: a }, function (r) {
            if (r && r.kind) now = r
            else close("nichts mehr da")
        })
    }
    function navKey(k) {
        awayMs = 0
        if (k === "left" && now.skip) control("prev")
        else if (k === "right" && now.skip) control("next")
        else if (k === "up") control("up")
        else if (k === "down") control("down")
        else if (k === "a") control("toggle")
        else if (k === "b") { vs.playSound("back"); close("Taste B") }
    }

    Rectangle {
        anchors.fill: parent
        color: "transparent"
        border.width: Math.max(1, Math.round(Ui.f))
        border.color: Qt.lighter(mc.color, 1.6)
    }
    HoverHandler { id: hov }
    WheelHandler {
        acceptedDevices: PointerDevice.Mouse | PointerDevice.TouchPad
        onWheel: function (e) { mc.control(e.angleDelta.y > 0 ? "up" : "down") }
    }

    component Arrow: Rectangle {
        property string glyph
        signal hit()
        width: 48 * Ui.f
        height: 56 * Ui.f
        color: am.containsMouse ? Qt.rgba(1, 1, 1, am.pressed ? 0.24 : 0.14) : "transparent"
        Glyph { anchors.centerIn: parent; width: 22 * Ui.f; height: width; name: parent.glyph; color: Ui.c.textPrimary }
        MouseArea { id: am; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: parent.hit() }
    }

    Row {
        id: box
        x: mc.pad
        y: mc.pad
        Arrow { glyph: "prev"; visible: !!mc.now.skip; onHit: mc.control("prev") }
        Rectangle {
            width: 280 * Ui.f
            height: 56 * Ui.f
            color: im.containsMouse ? Qt.rgba(1, 1, 1, im.pressed ? 0.24 : 0.14) : "transparent"
            Glyph {
                id: state
                x: 10 * Ui.f
                anchors.verticalCenter: parent.verticalCenter
                width: 20 * Ui.f
                height: width
                name: mc.now.paused ? "pause" : (mc.now.kind === "radio" ? "radio" : "music")
                color: Ui.c.textPrimary
            }
            Column {
                anchors.left: state.right
                anchors.leftMargin: 10 * Ui.f
                anchors.right: parent.right
                anchors.rightMargin: 10 * Ui.f
                anchors.verticalCenter: parent.verticalCenter
                spacing: 3 * Ui.f
                Txt {
                    width: parent.width
                    text: mc.now.title || ""
                    font.pixelSize: 15 * Ui.f
                    color: Ui.c.textPrimary
                    elide: Text.ElideRight
                }
                Txt {
                    width: parent.width
                    visible: text !== ""
                    text: mc.now.sub || ""
                    font.pixelSize: 12 * Ui.f
                    color: Ui.c.textSecondary
                    elide: Text.ElideRight
                }
                Rectangle {                                 // Lautstaerke der Musik
                    width: parent.width
                    height: Math.max(2, Math.round(3 * Ui.f))
                    color: Qt.rgba(1, 1, 1, 0.15)
                    Rectangle {
                        width: parent.width * (mc.now.volume === undefined ? 1 : mc.now.volume / 100)
                        height: parent.height
                        color: Ui.c.textPrimary
                    }
                }
            }
            MouseArea { id: im; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: mc.control("toggle") }
        }
        Arrow { glyph: "next"; visible: !!mc.now.skip; onHit: mc.control("next") }
    }

    // Titel aktuell halten
    Timer {
        interval: 1000
        repeat: true
        running: mc.visible
        onTriggered: Api.get("/api/nowplaying", function (r) { if (r && r.kind) mc.now = r; else mc.close("nichts mehr da") })
    }
    // Wieder zu, sobald die Maus eine Sekunde lang weder ueber der Karte noch in der Ecke ist
    Timer {
        interval: 200
        repeat: true
        running: mc.visible
        onTriggered: {
            if (hov.hovered || vs.musicHit().length) { mc.awayMs = 0; return }
            mc.awayMs += interval
            if (mc.awayMs >= 1000) mc.close("Maus weg")
        }
    }
}
