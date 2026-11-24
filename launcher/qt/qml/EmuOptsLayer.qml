// SPDX-License-Identifier: GPL-3.0-or-later
// Optionen eines Emulators bzw. eines einzelnen Spiels (aus der Spieleliste): die wichtigsten Schalter, alles Weitere
// bleibt im Fenster des Emulators. Daten: /api/emuopts (launcher.py EMU_OPTS). Pro Option eine Zeile Knoepfe; "values"
// getrennt von der Liste, damit beim Umschalten nichts neu aufgebaut wird und der Fokus bleibt, wo er ist.
// Allgemein steht oben der Schalter "VoidStation-Einstellungen | Anpassen" (Option "mode"): Erst mit "Anpassen" schickt der
// Launcher die uebrigen Zeilen – nur dieser Schalter baut die Liste neu auf.
// Spalte "Bildstil": Hat die Moeglichkeit unter dem Fokus ein Vorschaubild (Feld "p", launcher.py look_preview), zeigt eine
// Karte unten auf der anderen Bildschirmseite es an – in ganzzahliger Vergroesserung, damit Zeilen- und Punktraster stimmen.
import QtQuick
import VS

Layer {
    id: eo
    scope: "emuopts"
    track: trk
    title: rom ? Ui.t("emuopt.gameTitle", { game: rom.title || rom.name || rom.filename }) : Ui.t("emuopt.title")
    property var tile: null
    property var rom: null                       // gesetzt: Optionen nur fuer dieses Spiel
    property var od: null                        // Antwort von /api/emuopts
    property var values: ({})
    readonly property real colW: Ui.screenW * 0.4

    function openFor(t, r) {
        tile = t
        rom = r || null
        od = null
        values = ({})
        app.openLayer(eo)
        var q = "/api/emuopts?emu=" + encodeURIComponent(t.id) + (rom ? "&game=" + encodeURIComponent(rom.filename) : "")
        Api.get(q, function (j) {
            od = j
            values = j.values
            Qt.callLater(focusFirst)
        }, function (e) { app.toast(Ui.t("common.failedMsg", { msg: e }), true); app.closeLayer(eo) })
    }
    // Die Spieleliste darunter ausblenden: die Ebenen sind leicht durchscheinend
    onOpened: if (roms.open) roms.opacity = 0
    onClosed: if (roms.open) roms.opacity = 1
    onOpenChanged: if (!open && roms.open) roms.opacity = 1
    function firstFocus() { return Nav.collect(trk)[0] || null }
    function focusFirst() { var it = Nav.collect(trk); if (eo.open && it.length) app.setFocus(it[0], true) }
    function choose(oid, v) {
        var body = { emu: tile.id, id: oid, value: v }
        if (rom) body.game = rom.filename
        Api.post("/api/emuopts/set", body, function (j) {
            if (oid !== "mode") { values = j.values; return }
            od = j
            values = j.values
            Qt.callLater(function () { focusKey("eomode" + (j.values.mode === "custom" ? 1 : 0)) })
        }, function (e) { app.toast(Ui.t("common.failedMsg", { msg: e }), true) })
    }
    function focusKey(key) {
        var it = Nav.collect(trk)
        for (var i = 0; i < it.length; i++) if (it[i].key === key) { app.setFocus(it[i], true); return }
        focusFirst()
    }
    // Fuer ein Spiel steht vorn "Wie ueberall" (keine eigene Wahl)
    function choicesOf(o) {
        return rom ? [{ v: null, k: "emuopt.v.inherit" }].concat(o.choices) : o.choices
    }
    function isOn(oid, v) {
        var cur = values[oid]
        return (cur === undefined ? null : cur) === v
    }

    headRight: NowLine { main: eo.od ? eo.od.name : ""; sub: "" }

    Track {
        id: trk
        anchors.fill: parent
        Repeater {
            model: eo.od ? eo.od.groups : []
            SetGroup {
                id: grp
                property var g: modelData
                property int gi: index
                availH: eo.stage.height
                maxW: eo.colW
                title: Ui.t("emuopt.g." + g.id)
                Repeater {
                    model: grp.g.opts
                    SetRow {
                        id: row
                        property var o: modelData
                        width: eo.colW
                        label: o.id === "mode" ? "" : Ui.t("emuopt." + (o.label || o.id))
                        Repeater {
                            model: eo.choicesOf(row.o)
                            Pill {
                                property string key: "eo" + row.o.id + index
                                property bool inLook: grp.g.id === "look"
                                property string preview: modelData.p || ""
                                sound: "toggle"
                                text: modelData.t || Ui.t(modelData.k)
                                on: eo.isOn(row.o.id, modelData.v)
                                maxWidth: eo.colW
                                onTriggered: eo.choose(row.o.id, modelData.v)
                            }
                        }
                    }
                }
                Info {
                    visible: grp.gi === 0
                    width: eo.colW
                    html: Ui.esc(eo.rom ? Ui.t("emuopt.gameInfo") : Ui.t("emuopt.info", { name: eo.od ? eo.od.name : "" }))
                    font.pixelSize: 14 * Ui.f
                    lineHeight: 1.35
                }
            }
        }
    }

    Rectangle {
        id: pv
        readonly property var cur: Nav.current
        readonly property bool want: eo.open && !!cur && cur.inLook === true && cur.preview !== ""
        // Steht "Bildstil" ganz links (Optionen eines Spiels), kommt das Bild nach rechts – sonst nach links
        readonly property bool atRight: !!eo.od && eo.od.groups.length > 0 && eo.od.groups[0].id === "look"
        readonly property int k: Math.max(1, Math.floor(Ui.screenW * 0.36 / 480))
        visible: opacity > 0
        opacity: want ? 1 : 0
        Behavior on opacity { NumberAnimation { duration: 120 } }
        x: atRight ? eo.stage.width - width - Ui.padX : Ui.padX
        y: eo.stage.height - height - 8 * Ui.f
        width: img.width + 2 * border.width
        height: img.height + cap.height + 2 * border.width
        color: Ui.c.bgMain
        border.width: 2
        border.color: Ui.c.borderFocus
        Image {
            id: img
            x: pv.border.width; y: pv.border.width
            source: pv.cur && pv.cur.inLook === true && pv.cur.preview ? "file://" + pv.cur.preview : ""
            width: implicitWidth * pv.k; height: implicitHeight * pv.k
            smooth: false
            cache: false
            asynchronous: false
        }
        Txt {
            id: cap
            anchors.top: img.bottom
            x: pv.border.width + 8 * Ui.f
            width: img.width - 16 * Ui.f
            height: implicitHeight + 10 * Ui.f
            verticalAlignment: Text.AlignVCenter
            text: Ui.t("emuopt.preview") + (pv.cur && pv.cur.text ? " · " + pv.cur.text : "")
            color: Ui.c.textFaint
            font.pixelSize: 13 * Ui.f
            elide: Text.ElideRight
        }
    }
}
