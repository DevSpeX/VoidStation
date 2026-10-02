// SPDX-License-Identifier: GPL-3.0-or-later
// Spiele eines Emulators (ROMs aus ~/share/ROMs/<system>) – Spiel starten oder Emulator ohne Spiel
import QtQuick
import VS

Layer {
    id: rl
    scope: "roms"
    track: trk
    property var tile: null
    property var romData: null
    readonly property var roms: romData ? (Array.isArray(romData) ? romData : (romData.roms || [])) : []
    readonly property string sysName: tile ? (Ui.l(tile.label) || tile.id) : ""
    readonly property var fit: Ui.fitRows(stage.height - 18 * Ui.f * 1.36 - 14 * Ui.f - 4, Ui.u, Ui.gap, 3)
    title: Ui.t("roms.title", { system: sysName })

    function openFor(t) {
        tile = t
        romData = null
        trk.reset()
        app.openLayer(rl)
        Api.get("/api/roms?system=" + encodeURIComponent(t.id), function (j) { romData = j; focusFirst() },
                function () { romData = { system: t.id, count: 0, roms: [] }; focusFirst() })
    }
    function focusFirst() { Qt.callLater(function () { var it = Nav.collect(trk); app.setFocus(it.length ? it[0] : startEmu, true) }) }
    function firstFocus() { var it = Nav.collect(trk); return it.length ? it[0] : startEmu }
    function launchRom(r) {
        app.toast(Ui.t("common.starting", null, "Starte …") + " " + (r.title || r.name))
        Api.post("/api/roms/launch", { system: tile.id, file: r.filename }, null,
                 function () { app.toast(Ui.t("home.launchFailed", { name: r.title || r.name }), true) })
    }

    headRight: NowLine { main: rl.sysName; sub: Ui.t("roms.count", { count: rl.roms.length }) }
    bar: [ Pill { id: startEmu; text: Ui.t("roms.startEmu"); onTriggered: { var t = rl.tile; app.closeLayer(rl); app.launch(t) } } ]

    Track {
        id: trk
        anchors.fill: parent
        Group {
            visible: rl.roms.length > 0
            title: Ui.t("roms.count", { count: rl.roms.length })
            TileGrid {
                items: rl.roms
                rows: rl.fit.n
                cellW: Ui.u * rl.fit.k * 1.5
                cellH: Ui.u * rl.fit.k
                delegate: Component {
                    Tile {
                        id: card
                        property var rom: modelData
                        tileColor: Ui.c.surfaceCard
                        enterDelay: Math.min(index * 25, 600)
                        onTriggered: rl.launchRom(modelData)
                        Glyph {
                            name: rl.tile ? (rl.tile.icon || "gamepad") : "gamepad"
                            color: Ui.c.textPrimary
                            opacity: 0.22
                            width: parent.width * 0.44; height: parent.height * 0.44
                            x: (parent.width - width) / 2; y: parent.height * 0.4 - height / 2
                        }
                        Column {
                            x: 14 * Ui.f; width: parent.width - 28 * Ui.f
                            anchors.bottom: parent.bottom; anchors.bottomMargin: 14 * Ui.f
                            spacing: 2 * Ui.f
                            Txt { width: parent.width; text: modelData.title || modelData.name || ""; font.pixelSize: 16 * Ui.f; font.weight: Font.Medium }
                            Txt { width: parent.width; text: modelData.size || ""; font.pixelSize: 12 * Ui.f; color: Ui.c.textDim; visible: text !== "" }
                        }
                    }
                }
            }
        }
        Group {
            visible: !!rl.romData && rl.roms.length === 0
            title: rl.sysName
            Column {
                spacing: 12
                Txt { text: Ui.t("roms.noGames"); color: Ui.c.textFaint; width: Math.min(implicitWidth, Ui.screenW * 0.34); wrapMode: Text.Wrap; elide: Text.ElideNone }
                Txt {
                    width: Math.min(implicitWidth, Ui.screenW * 0.4)
                    text: Ui.t("roms.hint", { host: app.sett && app.sett.net ? app.sett.net.hostname : "voidstation", system: rl.romData && rl.romData.system ? rl.romData.system : (rl.tile ? rl.tile.id : "") })
                    color: Ui.c.textDim; font.pixelSize: 16 * Ui.f; wrapMode: Text.Wrap; elide: Text.ElideNone; lineHeight: 1.5
                }
            }
        }
    }
}
