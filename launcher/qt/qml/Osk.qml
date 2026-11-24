// SPDX-License-Identifier: GPL-3.0-or-later
// Bildschirmtastatur fuer alle Eingabefelder der Startseite und des Players (Gamepad: A tippen, X loeschen,
// Y Leerzeichen, Start fertig, B abbrechen). Tastenfeld und Belegungen wie im Installer: VS/KeyPad.qml,
// VS/OskLayouts.js; Belegung nach der Sprache oder fest (Einstellungen -> Sprache -> Bildschirmtastatur).
// Die echte Tastatur tippt direkt hinein. Ist eine angeschlossen und wird darauf getippt, verschwinden die Tasten
// (vs.kbdPresent, vs.kbdTyping); der Controller oder "Tasten zeigen" holt sie zurueck.
import QtQuick
import VS
import "VS/OskLayouts.js" as OskLayouts

Rectangle {
    id: o
    property string scope: "osk"
    property bool open: false
    property Item target: null
    property string value: ""
    property bool navMode: false               // mit Pfeilen bewegt: Enter tippt die Taste statt "Fertig"
    property bool forceKeys: false             // fuer dieses Feld wieder Tasten (Controller benutzt, "Tasten zeigen")
    readonly property var conf: app.sett && app.sett.osk ? app.sett.osk : ({})
    readonly property string mode: conf.mode || "auto"
    readonly property string layoutId: conf.choice && conf.choice !== "auto" && OskLayouts.known(conf.choice)
                                       ? conf.choice : OskLayouts.forLang(Ui.lang)
    readonly property bool showKeys: forceKeys || mode === "always" || !vs.kbdPresent || (mode === "auto" && !vs.kbdTyping)
    z: 45
    color: Ui.c.surfaceOverlay
    visible: open
    MouseArea { anchors.fill: parent; acceptedButtons: Qt.AllButtons }
    onShowKeysChanged: if (open) Qt.callLater(fixFocus)

    function openFor(field) {
        kp.endCompose()                        // Koreanisch: nicht mit dem vorigen Feld verbinden
        target = field
        value = field.value || ""
        navMode = false
        forceKeys = false
        kp.reset()
        open = true
        app.updateLayer()
        Qt.callLater(fixFocus)
    }
    function fixFocus() {
        if (!open || Nav.alive(Nav.current, o)) return
        var it = Nav.collect(showKeys ? kp : hidden)
        if (it.length) app.setFocus(it[0], true)
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
    }
    function backspace() { value = value.slice(0, -1); if (target) target.value = value }
    function submit() {
        vs.playSound("select")
        var t = target
        if (t) { t.value = value; }
        close()
        if (t) t.submitted(value)
    }
    function key(e) {                          // echte Tastatur
        kp.endCompose()                        // Koreanisch: getippte Silbe ist abgeschlossen
        if (e.key === Qt.Key_Escape) { close(); return true }
        if (e.key === Qt.Key_Return || e.key === Qt.Key_Enter) { if (navMode && showKeys && Nav.current) app.activate(); else submit(); return true }
        if (e.key === Qt.Key_Backspace) { navMode = false; backspace(); return true }
        if (e.key === Qt.Key_Left || e.key === Qt.Key_Right || e.key === Qt.Key_Up || e.key === Qt.Key_Down) {
            if (!showKeys) return true
            navMode = true
            app.move(e.key === Qt.Key_Left ? "left" : e.key === Qt.Key_Right ? "right" : e.key === Qt.Key_Up ? "up" : "down")
            return true
        }
        if (e.text && e.text.length === 1 && e.text.charCodeAt(0) >= 32 && !(e.modifiers & (Qt.ControlModifier | Qt.MetaModifier))) {
            navMode = false
            add(e.text)
            return true
        }
        return true
    }
    function pad(k) {
        if (!showKeys) forceKeys = true           // Controller in der Hand: Tasten wieder zeigen
        var dirs = ["left", "right", "up", "down"]
        if ((k === "a" || dirs.indexOf(k) >= 0) && !Nav.alive(Nav.current, o)) { fixFocus(); return }
        if (k === "x") return kp.backspace()   // Koreanisch: nur den letzten Teil der Silbe
        if (k === "y") { kp.endCompose(); return add(" ") }
        if (k === "b") return close()
        if (k === "start") return submit()
        if (k === "a") return app.activate()
        if (dirs.indexOf(k) >= 0) app.move(k)
    }

    Rectangle {
        width: parent.width
        anchors.verticalCenter: parent.verticalCenter
        height: band.implicitHeight + 64 * Ui.f
        color: Ui.c.surfaceDialog
        Rectangle { width: parent.width; height: 1; color: Ui.c.divider }
        Rectangle { width: parent.width; height: 1; color: Ui.c.divider; anchors.bottom: parent.bottom }
        Column {
            id: band
            width: Math.min(parent.width * 0.9, parent.width - 2 * Ui.padX)
            anchors.horizontalCenter: parent.horizontalCenter
            y: 32 * Ui.f
            spacing: 14 * Ui.f
            Row {
                id: top
                width: parent.width
                spacing: 16 * Ui.f
                Rectangle {
                    width: parent.width - closeBtn.width - 16 * Ui.f - (showBtn.visible ? showBtn.width + 16 * Ui.f : 0)
                    height: Math.max(valTxt.implicitHeight, lab.implicitHeight) + 16 * Ui.f + 4
                    color: Ui.c.surfaceCard
                    border.width: 2
                    border.color: o.navMode && o.showKeys ? Ui.c.borderSubtle : Ui.c.borderFocus
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
                // Passwortfelder mit revealable: Klartext ein/aus direkt beim Tippen (Feld darunter folgt mit)
                Pill {
                    id: showBtn
                    visible: !!o.target && !!o.target.revealable
                    sound: "toggle"
                    toggleFlip: true
                    text: Ui.t(o.target && o.target.password ? "settings.pwShow" : "settings.pwHide")
                    on: !!o.target && !o.target.password
                    anchors.verticalCenter: parent.verticalCenter
                    onTriggered: if (o.target) o.target.password = !o.target.password
                }
                RoundBtn { id: closeBtn; iconName: "close"; sound: ""; anchors.verticalCenter: parent.verticalCenter; onTriggered: { vs.playSound("back"); o.close() } }
            }
            KeyPad {
                id: kp
                visible: o.showKeys
                anchors.horizontalCenter: parent.horizontalCenter
                layoutId: o.layoutId
                // Hoehe begrenzen: fuenf Reihen muessen auch bei grosser Skalierung auf 720p passen
                keyH: Math.max(22, Math.min(46 * Ui.f, (o.height * 0.86 - top.height - 64 * Ui.f - 14 * Ui.f - 4 * gap) / 5))
                keyW: Math.min(keyH * 1.45, (band.width - (units - 1) * gap) / units)
                onTyped: function (ch) { o.navMode = false; o.add(ch) }
                onErase: o.backspace()
                onDone: o.submit()
            }
            // Echte Tastatur in Gebrauch: nur das Eingabefeld, die Tasten auf Wunsch
            Row {
                id: hidden
                visible: !o.showKeys
                spacing: 20 * Ui.f
                anchors.horizontalCenter: parent.horizontalCenter
                Txt { text: Ui.t("osk.typeHint"); color: Ui.c.textDim; font.pixelSize: 15 * Ui.f; anchors.verticalCenter: parent.verticalCenter
                      width: Math.min(implicitWidth, band.width - keysBtn.width - 20 * Ui.f) }
                Btn { id: keysBtn; text: Ui.t("osk.showKeys"); anchors.verticalCenter: parent.verticalCenter; onTriggered: o.forceKeys = true }
            }
        }
    }
}
