// SPDX-License-Identifier: GPL-3.0-or-later
// Bildschirmtastatur ueber Programmen (Firefox, Terminal, Steam …). Geht auf mit L2 oder L3 am Controller (nur wo die
// Controller-Maus an ist) oder von selbst, wenn in Firefox ein Eingabefeld angewaehlt wird (Erweiterung
// VoidStation-Tastatur, s. firefox/keyboard/). Tastenfeld und Belegungen wie auf der Startseite (VS/KeyPad.qml).
// Getippt wird per XTest wie auf einer echten Tastatur (vs.kbdType, vsx11.py) – auch Zeichen, die auf der
// eingestellten X-Belegung fehlen. Eigenes Fenster ohne Fensterverwaltung wie die heissen Ecken (Corner.qml): liegt
// ueber Vollbild-Programmen und nimmt ihnen den Fokus nicht weg, sonst kaemen die Tasten nicht an.
// Controller, solange offen: Steuerkreuz waehlen, A tippen, X loeschen, Y Leerzeichen, LB/RB Cursor, RT Shift,
// Start Enter, B (oder L2/L3) zu. Maus: Tasten anklicken. Steht das Feld unten im Bild, liegt die Tastatur oben.
import QtQuick
import QtQuick.Window
import VS
import "VS/OskLayouts.js" as OskLayouts

Window {
    id: kw
    flags: Qt.ToolTip | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.BypassWindowManagerHint
           | Qt.WindowDoesNotAcceptFocus
    transientParent: null
    color: Ui.c.surfaceDialog
    visible: false
    width: scr[2]
    height: body.implicitHeight

    property var scr: [0, 0, 1280, 720]          // Bildschirm unter dem Mauszeiger: [x, y, Breite, Hoehe]
    property bool auto: false                    // fuer ein Eingabefeld in Firefox geoeffnet (zu, wenn es verlassen wird)
    property string kind: "text"
    property string sid: ""                      // meldende Seite (Erweiterung); Meldungen anderer Seiten zaehlen nicht
    property bool atTop: false
    property var savedFocus: null                // Fokus der Startseite, kommt beim Schliessen zurueck
    readonly property alias root: body           // Ebene fuer die Navigation (Main.qml updateLayer)
    readonly property var conf: Ui.app && Ui.app.sett && Ui.app.sett.osk ? Ui.app.sett.osk : ({})
    readonly property string layoutId: conf.choice && conf.choice !== "auto" && OskLayouts.known(conf.choice)
                                       ? conf.choice : OskLayouts.forLang(Ui.lang)

    signal opened()
    signal closed()

    // how: "pad" (L2/L3) oder "field" (Erweiterung: st = { kind, pos, sid })
    function openFor(how, st) {
        kp.endCompose()                        // Koreanisch: nicht mit dem vorigen Feld verbinden
        auto = how === "field"
        kind = st && st.kind ? st.kind : "text"
        sid = st && st.sid ? st.sid : ""
        atTop = auto && st.pos !== null && st.pos !== undefined && st.pos > 0.45     // unten belegt sie gut 45 %
        scr = vs.cursorScreen()
        if (!visible) {
            savedFocus = Nav.current
            kp.reset()
        }
        place()
        visible = true
        raise()
        opened()
        Qt.callLater(function () { if (!Nav.alive(Nav.current, body)) Ui.app.setFocus(firstFocus(), true) })
        vs.log("Tastatur: offen (" + (auto ? "Eingabefeld " + kind : "L2/L3") + (atTop ? ", oben" : ", unten") + ")")
    }
    function place() {
        kw.x = scr[0]
        kw.y = atTop ? scr[1] : scr[1] + scr[3] - kw.height
    }
    onHeightChanged: if (visible) place()
    function close(why) {
        if (!visible) return
        visible = false
        vs.log("Tastatur: zu (" + (why || "") + ")")
        closed()
    }
    function firstFocus() {
        var all = Nav.collect(kp)
        for (var i = 0; i < all.length; i++) if (all[i].key === "k1-0") return all[i]     // erster Buchstabe
        return all[0] || null
    }

    function type(ch) { vs.kbdType(ch) }
    function tap(name) { vs.kbdTap(name) }
    function enter() {
        vs.playSound("select")
        tap("Return")
        if (auto && kind !== "textarea") close("Enter")          // Suche & Co.: abgeschickt; mehrzeilig bleibt offen
    }
    function pad(k) {
        var dirs = ["left", "right", "up", "down"]
        if ((k === "a" || dirs.indexOf(k) >= 0) && !Nav.alive(Nav.current, body)) { Ui.app.setFocus(firstFocus(), true); return }
        if (k === "a") return Ui.app.activate()
        if (dirs.indexOf(k) >= 0) return Ui.app.move(k)
        if (k === "x") return kp.backspace()      // erase -> BackSpace (Koreanisch: nur den letzten Teil der Silbe)
        if (k === "y") { kp.endCompose(); return type(" ") }
        if (k === "lb") { kp.endCompose(); return tap("Left") }
        if (k === "rb") { kp.endCompose(); return tap("Right") }
        if (k === "rt") { kp.shift = !kp.shift; return }
        if (k === "start") return enter()
        if (k === "b") { vs.playSound("back"); return close("Taste B") }
    }

    Rectangle {                                  // Trennlinie zum Programm
        width: parent.width
        height: Math.max(1, Math.round(Ui.f))
        color: Ui.c.divider
        y: kw.atTop ? parent.height - height : 0
    }

    // Groessen haengen an der Tastenhoehe k: Die Tastatur nimmt hoechstens 45 % der Bildschirmhoehe ein (das Programm
    // darueber bleibt sichtbar), auch bei grosser Skalierung auf 720p. Gesamthoehe rund 7,2 k.
    readonly property real k: Math.max(22, Math.min(44 * Ui.f, scr[3] * 0.45 / 7.2))

    Item {
        id: body
        anchors.fill: parent
        implicitHeight: band.implicitHeight + 2 * kw.k * 0.3
        Column {
            id: band
            width: Math.min(kw.width * 0.9, kw.width - 2 * Ui.padX)
            x: (kw.width - width) / 2
            y: kw.k * 0.3
            spacing: kw.k * 0.3
            Item {
                id: top
                width: kp.width
                anchors.horizontalCenter: parent.horizontalCenter
                height: kw.k * 0.8
                Txt {
                    id: hintTxt
                    anchors.verticalCenter: parent.verticalCenter
                    width: parent.width - closeBtn.width - kw.k * 0.3
                    text: Ui.keys(Ui.t("kbd.hint"), Ui.c.textSecondary, Math.round(kw.k * 0.3))
                    textFormat: Text.StyledText
                    color: Ui.c.textFaint
                    font.pixelSize: Math.round(kw.k * 0.3)
                    fontSizeMode: Text.HorizontalFit             // lange Sprachen: kleiner statt umbrechen
                    minimumPixelSize: Math.round(kw.k * 0.2)
                    elide: Text.ElideRight
                }
                RoundBtn {
                    id: closeBtn
                    anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    iconName: "close"
                    size: kw.k * 0.8
                    onTriggered: kw.close("Knopf")
                }
            }
            KeyPad {
                id: kp
                anchors.horizontalCenter: parent.horizontalCenter
                layoutId: kw.layoutId
                doneText: "⏎"
                extra: [{ l: "⇥", a: "Tab" }, { l: "←", a: "Left" }, { l: "→", a: "Right" }]
                fitFont: true
                gap: kw.k * 0.12
                keyH: kw.k
                keyW: Math.min(keyH * 1.45, (band.width - (units - 1) * gap) / units)
                onTyped: function (ch) { kw.type(ch) }
                onErase: kw.tap("BackSpace")
                onDone: kw.enter()
                onSpecial: function (name) { kw.tap(name) }
            }
        }
    }
}
