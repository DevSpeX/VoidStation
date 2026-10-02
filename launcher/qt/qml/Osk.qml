// SPDX-License-Identifier: GPL-3.0-or-later
// Bildschirmtastatur fuer alle Eingabefelder (Gamepad: A tippen, X loeschen, Y Leerzeichen, Start fertig, B abbrechen).
// Die echte Tastatur tippt direkt hinein.
import QtQuick
import VS

Rectangle {
    id: o
    property string scope: "osk"
    property bool open: false
    property Item target: null
    property string value: ""
    property bool shift: false
    property bool sym: false
    property bool navMode: false               // mit Pfeilen bewegt: Enter tippt die Taste statt "Fertig"
    readonly property var layouts: ({
        de: ["1234567890ß", "qwertzuiopü", "asdfghjklöä", "yxcvbnm,.-"],
        us: ["1234567890-", "qwertyuiop@", "asdfghjkl;'", "zxcvbnm,./"],
        sym: ["!\"§$%&/()=?", "€@{}[]\\~*+#", ":;_<>|^°'`´", "²³µ«»¿¡¬¦"]
    })
    readonly property var rows: sym ? layouts.sym : (Ui.lang === "en" ? layouts.us : layouts.de)
    z: 45
    color: Ui.c.surfaceOverlay
    visible: open
    MouseArea { anchors.fill: parent; acceptedButtons: Qt.AllButtons }

    function openFor(field) {
        target = field
        value = field.value || ""
        shift = false; sym = false; navMode = false
        open = true
        app.updateLayer()
        Qt.callLater(function () { var k = Nav.collect(keys); if (k.length) app.setFocus(k[0], true) })
    }
    function close() {
        if (!open) return
        open = false
        navMode = false
        app.updateLayer()
        if (target && Nav.alive(target, app.layerRoot)) app.setFocus(target, true)
        else { var m = Nav.remembered(app.layerName, app.layerRoot); if (m) app.setFocus(m, true) }
    }
    function add(c) {
        value += c
        if (target) target.value = value
        if (shift) shift = false
    }
    function backspace() { value = value.slice(0, -1); if (target) target.value = value }
    function submit() {
        var t = target
        if (t) { t.value = value; }
        close()
        if (t) t.submitted(value)
    }
    function key(e) {                          // echte Tastatur
        if (e.key === Qt.Key_Escape) { close(); return true }
        if (e.key === Qt.Key_Return || e.key === Qt.Key_Enter) { if (navMode && Nav.current) app.activate(); else submit(); return true }
        if (e.key === Qt.Key_Backspace) { navMode = false; backspace(); return true }
        if (e.key === Qt.Key_Left || e.key === Qt.Key_Right || e.key === Qt.Key_Up || e.key === Qt.Key_Down) {
            navMode = true
            app.move(e.key === Qt.Key_Left ? "left" : e.key === Qt.Key_Right ? "right" : e.key === Qt.Key_Up ? "up" : "down")
            return true
        }
        if (e.text && e.text.length === 1 && e.text.charCodeAt(0) >= 32 && !(e.modifiers & (Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier))) {
            navMode = false
            add(e.text)
            return true
        }
        return true
    }
    function pad(k) {
        if (k === "x") return backspace()
        if (k === "y") return add(" ")
        if (k === "b") return close()
        if (k === "start") return submit()
        if (k === "a") return app.activate()
        if (["left", "right", "up", "down"].indexOf(k) >= 0) app.move(k)
    }

    Rectangle {
        width: parent.width
        anchors.verticalCenter: parent.verticalCenter
        height: band.implicitHeight + 72 * Ui.f
        color: Ui.c.surfaceDialog
        Rectangle { width: parent.width; height: 1; color: Ui.c.divider }
        Rectangle { width: parent.width; height: 1; color: Ui.c.divider; anchors.bottom: parent.bottom }
        Column {
            id: band
            width: Math.min(parent.width * 0.9, parent.width - 2 * Ui.padX)
            anchors.horizontalCenter: parent.horizontalCenter
            y: 36 * Ui.f
            spacing: 14 * Ui.f
            Row {
                width: parent.width
                spacing: 16 * Ui.f
                Rectangle {
                    width: parent.width - closeBtn.width - 16 * Ui.f
                    height: Math.max(valTxt.implicitHeight, lab.implicitHeight) + 16 * Ui.f + 4
                    color: Ui.c.surfaceCard
                    border.width: 2
                    border.color: o.navMode ? Ui.c.borderSubtle : Ui.c.borderFocus
                    Row {
                        x: 16 * Ui.f; anchors.verticalCenter: parent.verticalCenter
                        width: parent.width - 32 * Ui.f
                        spacing: 10 * Ui.f
                        Txt { id: lab; text: o.target ? o.target.placeholder : ""; color: Ui.c.textDim; font.pixelSize: 13 * Ui.f; anchors.verticalCenter: parent.verticalCenter; width: Math.min(implicitWidth, parent.width * 0.4) }
                        Txt {
                            id: valTxt
                            text: (o.target && o.target.password ? "•".repeat(o.value.length) : o.value)
                            font.pixelSize: 22 * Ui.f
                            elide: Text.ElideLeft
                            width: parent.width - lab.width - 10 * Ui.f - 4
                            anchors.verticalCenter: parent.verticalCenter
                            Rectangle {                        // Schreibmarke
                                x: Math.min(parent.contentWidth, parent.width) + 2; width: 2; height: parent.font.pixelSize * 1.05
                                anchors.verticalCenter: parent.verticalCenter
                                color: Ui.c.textPrimary
                                SequentialAnimation on opacity { running: o.open; loops: Animation.Infinite
                                    NumberAnimation { to: 0; duration: 0 } PauseAnimation { duration: 500 } NumberAnimation { to: 1; duration: 0 } PauseAnimation { duration: 500 } }
                            }
                        }
                    }
                }
                RoundBtn { id: closeBtn; iconName: "close"; anchors.verticalCenter: parent.verticalCenter; onTriggered: o.close() }
            }
            Grid {
                id: keys
                columns: 11
                spacing: 5 * Ui.f
                anchors.horizontalCenter: parent.horizontalCenter
                property real kw: (Math.min(band.width, 750 * Ui.f) - 10 * spacing) / 11
                Repeater {
                    model: {
                        var out = []
                        for (var r = 0; r < o.rows.length; r++) {
                            var row = o.rows[r]
                            for (var c = 0; c < 11; c++) out.push(c < row.length ? row[c] : "")
                        }
                        return out
                    }
                    Focusable {
                        id: kk
                        property string ch: o.shift ? modelData.toUpperCase() : modelData
                        navigable: modelData !== ""
                        width: keys.kw; height: 44 * Ui.f
                        property bool pressFlash: true
                        onTriggered: o.add(ch)
                        Rectangle {
                            anchors.fill: parent
                            visible: modelData !== ""
                            radius: 2
                            color: kk.focused ? Ui.c.surfaceCardHover : Ui.c.surfaceCard
                            border.width: 2
                            border.color: kk.focused ? Ui.c.borderFocus : "transparent"
                            Txt { anchors.centerIn: parent; text: kk.ch; font.pixelSize: 17 * Ui.f; elide: Text.ElideNone }
                        }
                    }
                }
            }
            Row {
                anchors.horizontalCenter: parent.horizontalCenter
                spacing: 10 * Ui.f
                property real bw: (Math.min(band.width, 750 * Ui.f) - 4 * spacing) / 5
                Btn { width: parent.bw; center: true; text: Ui.t("osk.space"); onTriggered: o.add(" ") }
                Btn { width: parent.bw; center: true; text: Ui.t("osk.backspace"); onTriggered: o.backspace() }
                Btn { width: parent.bw; center: true; text: o.shift ? "⇧ SHIFT" : "⇧ Shift"; on: o.shift; onTriggered: o.shift = !o.shift }
                Btn { width: parent.bw; center: true; text: o.sym ? Ui.t("osk.letters") : Ui.t("osk.symbols"); onTriggered: o.sym = !o.sym }
                Btn { width: parent.bw; center: true; text: Ui.t("osk.enter"); onTriggered: o.submit() }
            }
        }
    }
}
