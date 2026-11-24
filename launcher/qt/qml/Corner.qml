// SPDX-License-Identifier: GPL-3.0-or-later
// Heisse Ecke unten rechts: Ist ein Programm vorn und bleibt die Maus kurz ganz in der Ecke, schwebt dort eine
// kleine Karte in der Kachelfarbe des Programms – Startseite (Programm laeuft weiter, wie Win / Guide) oder
// App schliessen. Ausgeloest wird erst per Klick, eine Maus, die zufaellig in der Ecke parkt, stoert nicht.
// Eigenes Fenster ohne Fensterverwaltung (X11 override-redirect): liegt so auch ueber Vollbild-Programmen
// und nimmt ihnen den Tastaturfokus nicht weg. Eckig wie die Kacheln der Startseite (runde Ecken gingen ohne
// Compositor nur als Fenstermaske ohne Kantenglaettung).
import QtQuick
import QtQuick.Window
import VS

Window {
    id: cw
    flags: Qt.ToolTip | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.BypassWindowManagerHint
           | Qt.WindowDoesNotAcceptFocus
    transientParent: null
    color: cardColor
    visible: false
    width: box.width + 2 * pad
    height: box.height + 2 * pad

    property real pad: 6 * Ui.f
    property real gap: 24 * Ui.f              // Abstand zum Bildschirmrand: die Karte schwebt
    property var front: null                  // Kachel des Programms im Vordergrund (null: unbekannt -> nur Startseite)
    readonly property color cardColor: front && front.color ? front.color : Ui.c.surfaceDialog
    readonly property color fg: front && front.color ? Ui.c.tileText : Ui.c.textPrimary
    property real rightX: 0
    property real bottomY: 0
    property int awayMs: 0
    property bool asking: false
    property real askT0: 0

    signal goHome()
    signal closeFront(var t)

    property int sel: -1                      // mit Steuerkreuz/Pfeiltasten gewaehlter Knopf (-1: noch keiner)
    readonly property var buttons: front ? ["home", "close"] : ["home"]
    function act(name) {
        vs.playSound("select")
        // erst ausloesen, dann zu: Schliessen baut sonst diesen Knopf ab, solange der Klick noch laeuft
        if (name === "home") goHome()
        else closeFront(front)
        close(name === "home" ? "Startseite gewaehlt" : "App schliessen gewaehlt")
    }
    function navKey(k) {
        awayMs = 0
        var prev = sel
        if (k === "left") sel = 0
        else if (k === "right") sel = buttons.length - 1
        else if (k === "a") act(buttons[Math.max(0, sel)])
        else if (k === "b") { vs.playSound("back"); close("Taste B") }
        if ((k === "left" || k === "right") && sel !== prev) vs.playSound("navigate")
    }

    // right / bottom: rechte und untere Kante (letztes Pixel) des Bildschirms, auf dem der Zeiger steht
    function openAt(right, bottom) {
        if (asking && Date.now() - askT0 < 3000) return    // Antwort steht noch aus (nach 3 s neu fragen)
        asking = true
        askT0 = Date.now()
        awayMs = 0
        vs.log("Ecke: getroffen bei " + right + "," + bottom + " – frage, welches Programm vorn ist")
        Api.get("/api/front", function (r) { place(right, bottom, r && r.id ? Ui.app.tileById(r.id) : null) },
                function (e) { vs.log("Ecke: /api/front fehlgeschlagen: " + e); place(right, bottom, null) })
    }
    function place(right, bottom, t) {
        asking = false
        front = t
        sel = -1
        rightX = right
        bottomY = bottom
        cw.x = right - gap - cw.width + 1
        cw.y = bottom - gap - cw.height + 1
        visible = true
        raise()
        vs.log("Ecke: Karte offen bei " + cw.x + "," + cw.y + ", vorn: " + (t ? t.id : "unbekannt"))
    }
    function close(why) {                                   // front bleibt bis zum naechsten Oeffnen (place)
        if (visible) vs.log("Ecke: Karte zu (" + (why || "Startseite vorn") + ")")
        visible = false
        awayMs = 0
    }
    onWidthChanged: if (visible) cw.x = rightX - gap - cw.width + 1
    onHeightChanged: if (visible) cw.y = bottomY - gap - cw.height + 1

    // feine hellere Kante, damit sich die Karte auch von gleichfarbigem Hintergrund abhebt
    Rectangle {
        anchors.fill: parent
        color: "transparent"
        border.width: Math.max(1, Math.round(Ui.f))
        border.color: Qt.lighter(cw.cardColor, 1.6)
    }
    HoverHandler { id: hov }

    Row {
        id: box
        x: cw.pad
        y: cw.pad
        Repeater {
            model: cw.buttons                               // Startseite zuerst, daneben (an der Ecke) App schliessen
            Item {
                width: btn.width + (index > 0 ? sep.width : 0)
                height: btn.height
                Rectangle {                                 // Trennstrich zwischen den Knoepfen
                    id: sep
                    visible: index > 0
                    width: Math.max(1, Math.round(Ui.f))
                    height: parent.height * 0.5
                    anchors.verticalCenter: parent.verticalCenter
                    color: cw.fg
                    opacity: 0.25
                }
                Rectangle {
                    id: btn
                    x: index > 0 ? sep.width : 0
                    width: content.width + 2 * 16 * Ui.f
                    height: 48 * Ui.f
                    color: ma.containsMouse || cw.sel === index ? Qt.rgba(1, 1, 1, ma.pressed ? 0.24 : 0.14) : "transparent"
                    Row {
                        id: content
                        anchors.centerIn: parent
                        spacing: 10 * Ui.f
                        Glyph {
                            anchors.verticalCenter: parent.verticalCenter
                            width: 20 * Ui.f
                            height: width
                            name: modelData === "home" ? "home" : "bad"
                            color: cw.fg
                        }
                        Txt {
                            anchors.verticalCenter: parent.verticalCenter
                            text: Ui.t(modelData === "home" ? "corner.home" : "corner.close")
                            font.pixelSize: 16 * Ui.f
                            color: cw.fg
                            elide: Text.ElideNone
                        }
                    }
                    MouseArea {
                        id: ma
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: cw.act(modelData)
                    }
                }
            }
        }
    }

    // Wieder zu, sobald die Maus eine Sekunde lang weder ueber der Karte noch in der Ecke ist
    Timer {
        interval: 200
        repeat: true
        running: cw.visible
        onTriggered: {
            if (hov.hovered || vs.cornerHit().length) { cw.awayMs = 0; return }
            cw.awayMs += interval
            if (cw.awayMs >= 1000) cw.close("Maus weg")
        }
    }
}
