// SPDX-License-Identifier: GPL-3.0-or-later
// Spiele eines Emulators (ROMs aus ~/share/ROMs/<system>, bei mGBA auch gbc) – Spiel starten oder Emulator ohne Spiel
import QtQuick
import VS

Layer {
    id: rl
    scope: "roms"
    track: trk
    property var tile: null
    property var romData: null
    readonly property var files: romData ? (Array.isArray(romData) ? romData : (romData.roms || [])) : []
    readonly property var disc: romData && romData.disc ? romData.disc : null    // PlayStation-Disc im Laufwerk (launcher.py DvdDrive)
    readonly property var roms: disc ? [{ disc: true, dev: disc.dev, filename: disc.name, title: disc.label || sysName,
                                          size: [Ui.t("roms.discSub"), disc.serial].filter(Boolean).join(" · "), noOpts: !disc.opts }].concat(files) : files
    readonly property string sysName: tile ? (Ui.l(tile.label) || tile.id) : ""
    readonly property bool gameOpts: !!romData && romData.gameOpts === true
    // bin/cue -> CHD (ChdCard): Anzahl umwandelbarer Spiele, laeuft gerade eine Umwandlung?
    readonly property var chdSt: romData && romData.chd ? romData.chd : null
    readonly property bool chdRunning: !!chdSt && !!chdSt.job && chdSt.job.state === "running"
    readonly property var fit: Ui.fitRows(stage.height - 18 * Ui.f * 1.36 - 14 * Ui.f - 4, Ui.u, Ui.gap, 3)
    title: Ui.t("roms.title", { system: sysName })

    function openFor(t) {
        tile = t
        romData = null
        trk.reset()
        app.openLayer(rl)
        Api.get("/api/roms?system=" + encodeURIComponent(t.id), function (j) {
            romData = j
            focusFirst()
            // Neue bin/cue-Spiele seit dem letzten "Nein": einmal fragen (Karte ueber der Liste)
            if (j.chd && j.chd.ask) Qt.callLater(function () { if (rl.open && rl.sameTile(t)) chd.openFor(t, j.chd) })
        }, function () { romData = { system: t.id, count: 0, roms: [] }; focusFirst() })
    }
    // Dieselbe Kachel? Nach der Kennung, nicht nach dem Objekt: tile kommt als neues Objekt zurueck, sobald es aus
    // den Kacheldaten stammt (dann ist rl.tile === t nie wahr)
    function sameTile(t) { return !!tile && !!t && tile.id === t.id }
    // Karte zu: ihren letzten Stand uebernehmen (Knopf zeigt "laeuft", der Zeitgeber unten verfolgt den Rest)
    function chdUpdate(st) { if (romData && st) { var d = Object.assign({}, romData); d.chd = st; romData = d } }
    // Liste neu holen (nach einer Umwandlung heissen die Spiele anders: .chd statt .cue)
    function reload() {
        var t = tile
        if (!t || !open) return
        Api.get("/api/roms?system=" + encodeURIComponent(t.id), function (j) {
            if (!rl.sameTile(t) || !rl.open) return
            romData = j
            Qt.callLater(function () { if (rl.open && app.layerName === "roms" && !Nav.alive(Nav.current, rl)) rl.focusFirst() })
        }, function () {})
    }
    // BIOS fehlt (DuckStation, PCSX2, xemu – launcher.py bios_status): was fehlt und wohin damit (share/ROMs/<folder>/bios)
    function biosText() {
        var b = romData && romData.bios
        if (!b || b.ok) return ""
        var what = (b.missing || []).map(function (m) { return Ui.t("roms.bios." + m) }).join(", ")
        var t = Ui.t("roms.bios", { name: sysName, what: what, folder: b.folder || "",
                                    host: app.sett && app.sett.net ? app.sett.net.hostname : "voidstation" })
        return t.replace(/\\/g, "\u2060\\\u2060")         // Pfad \\host\share\ROMs\psx\bios nicht umbrechen
    }
    // Y auf einem Spiel: Optionen nur fuer dieses Spiel (Bildformat, bei DOS Tempo und Soundkarte)
    function secondary() { if (gameOpts && Nav.current && Nav.current.rom && !Nav.current.rom.noOpts) emuopts.openFor(tile, Nav.current.rom) }
    // Mednafen hat kein eigenes Menue (romData.noMenu): dann gibt es "Emulator starten" nicht
    readonly property Item barFirst: startEmu.visible ? startEmu : keysPill
    function focusFirst() { Qt.callLater(function () { var it = Nav.collect(trk); app.setFocus(it.length ? it[0] : barFirst, true) }) }
    function firstFocus() { var it = Nav.collect(trk); return it.length ? it[0] : barFirst }
    // Spiel starten: Liste zu (zurueck auf der Startseite steht die Kachel als laufend da), Startbild wie bei
    // jeder Kachel – das Spiel laeuft unter der Kennung der Kachel
    function launchRom(r) {
        var t = tile
        app.closeLayer(rl)
        app.showSplash(t)
        Api.post("/api/roms/launch", r.disc ? { system: t.id, disc: r.dev } : { system: t.id, file: r.filename, folder: r.folder || r.system || "" },
                 function (res) { if (res && res.running) app.running = res.running },
                 function (err, data, status) {
                     app.hideSplash()
                     if (!app.handleBlockedError(err, data, status, t, function () { rl.launchRom(r) }))
                         app.toast(Ui.t("home.launchFailed", { name: r.title || r.name }), true)
                 })
    }

    // Laufwerk beobachten, solange die Liste offen ist (fragt nur den Zustand ab, die Disc laeuft dabei nicht an)
    Timer {
        interval: 3000; repeat: true
        running: rl.open && !!rl.romData && rl.romData.discDrive === true
        onTriggered: {
            var t = rl.tile
            Api.get("/api/roms/disc?system=" + encodeURIComponent(t.id), function (j) {
                if (!rl.sameTile(t) || !rl.romData || !rl.open) return
                if (JSON.stringify(j.disc || null) === JSON.stringify(rl.romData.disc || null)) return
                var d = Object.assign({}, rl.romData); d.disc = j.disc; rl.romData = d
                Qt.callLater(function () { if (rl.open && !keymap.open && !emuopts.open && !Nav.alive(Nav.current, rl)) rl.focusFirst() })
            }, function () {})
        }
    }
    // Umwandlung im Hintergrund (Karte zu): Stand fuer den Knopf, am Ende Liste neu laden und Bescheid geben
    Timer {
        interval: 2000; repeat: true
        running: rl.open && rl.chdRunning && !chd.open
        onTriggered: {
            var t = rl.tile
            Api.get("/api/roms/chd?system=" + encodeURIComponent(t.id), function (j) {
                if (!rl.sameTile(t) || !rl.romData || !rl.open) return
                var d = Object.assign({}, rl.romData); d.chd = j; rl.romData = d
                if (j.job && j.job.state !== "running") {
                    app.toast(j.job.state === "done" ? Ui.t("chd.toastDone", { games: chd.gamesText(j.job.ok || 0) }) : Ui.t("chd.toastStopped"), j.job.state !== "done")
                    rl.reload()
                }
            }, function () {})
        }
    }
    headRight: NowLine { main: rl.sysName; sub: Ui.t("roms.count", { count: rl.files.length }) }
    bar: [
        Pill { id: startEmu; visible: !(rl.romData && rl.romData.noMenu); text: Ui.t("roms.startEmu"); onTriggered: { var t = rl.tile; app.closeLayer(rl); app.launch(t) } },
        // Tastenbelegung des Emulators (KeymapLayer) – nur fuer Emulatoren, die VoidStation belegen kann
        Pill { id: keysPill; property string key: "romkeys"; visible: !!rl.romData && !!rl.romData.keymap; iconName: "gamepad"; text: Ui.t("keymap.title"); onTriggered: keymap.openFor(rl.tile) },
        // Wichtigste Einstellungen des Emulators (EmuOptsLayer) – nur fuer Emulatoren mit Optionen (launcher.py EMU_OPTS)
        Pill { property string key: "romopts"; visible: !!rl.romData && !!rl.romData.opts; iconName: "gear"; text: Ui.t("emuopt.title"); onTriggered: emuopts.openFor(rl.tile, null) },
        // bin/cue-Spiele in CHD umwandeln (ChdCard) – nur, wenn es welche gibt oder gerade umgewandelt wird
        Pill {
            property string key: "romchd"
            visible: !!rl.chdSt && (rl.chdSt.count > 0 || rl.chdRunning)
            iconName: "disc"
            text: rl.chdRunning ? Ui.t("chd.pillRun") : Ui.t("chd.pill")
            onTriggered: chd.openFor(rl.tile, rl.chdSt)
        }
    ]

    Track {
        id: trk
        anchors.fill: parent
        Group {
            visible: rl.biosText() !== ""
            title: Ui.t("roms.bios.title")
            Txt {
                width: Ui.screenW * 0.3
                text: rl.biosText()
                color: Ui.c.textDim; font.pixelSize: 16 * Ui.f; wrapMode: Text.Wrap; elide: Text.ElideNone; lineHeight: 1.5
            }
        }
        Group {
            visible: rl.roms.length > 0
            title: Ui.t("roms.count", { count: rl.files.length })
            TileGrid {
                items: rl.roms
                rows: rl.fit.n
                cellW: Ui.u * rl.fit.k * 1.5
                cellH: Ui.u * rl.fit.k
                delegate: Component {
                    // Mit Bild (Boxbild, s. RomCovers im Launcher): Bild links, Titel rechts, dahinter dasselbe Bild
                    // gedimmt als Flaeche. Ohne Bild (laedt noch, nicht gefunden): Symbol der Kachel wie bisher.
                    Tile {
                        id: card
                        property var rom: modelData
                        readonly property bool hasCover: cover.status === Image.Ready
                        tileColor: Ui.c.surfaceCard
                        enterDelay: Math.min(index * 25, 600)
                        onTriggered: rl.launchRom(modelData)
                        Image {
                            anchors.fill: parent
                            source: cover.status === Image.Ready ? cover.source : ""
                            fillMode: Image.PreserveAspectCrop
                            asynchronous: true
                            sourceSize: Qt.size(64, 64)
                            smooth: true
                            opacity: 0.28
                        }
                        Rectangle { anchors.fill: parent; color: "#000000"; opacity: card.hasCover ? 0.35 : 0 }
                        Image {
                            id: cover
                            x: 10 * Ui.f; y: 10 * Ui.f
                            width: parent.width * 0.5 - 15 * Ui.f; height: parent.height - 20 * Ui.f
                            source: modelData.cover ? Ui.url(modelData.cover) : ""
                            fillMode: Image.PreserveAspectFit
                            horizontalAlignment: Image.AlignHCenter
                            asynchronous: true
                            sourceSize: Qt.size(Math.ceil(width * 1.5), Math.ceil(height * 1.5))
                            visible: status === Image.Ready
                        }
                        Glyph {
                            visible: !card.hasCover
                            name: modelData.disc ? "disc" : (rl.tile ? (rl.tile.icon || "gamepad") : "gamepad")
                            color: Ui.c.textPrimary
                            opacity: 0.22
                            width: parent.width * 0.44; height: parent.height * 0.44
                            x: (parent.width - width) / 2; y: parent.height * 0.4 - height / 2
                        }
                        // Maus: Optionen des Spiels (Controller/Tastatur: Y bzw. F)
                        Focusable {
                            navigable: false
                            visible: rl.gameOpts && card.focused && !modelData.noOpts
                            width: Math.min(34 * Ui.f, card.height * 0.42); height: width
                            anchors.right: parent.right; anchors.top: parent.top; anchors.margins: 6 * Ui.f
                            onTriggered: emuopts.openFor(rl.tile, card.rom)
                            Rectangle { anchors.fill: parent; radius: width / 2; color: "#000000"; opacity: 0.55 }
                            Glyph { anchors.centerIn: parent; name: "gear"; color: Ui.c.textPrimary; width: parent.width * 0.6; height: width }
                        }
                        Column {
                            x: card.hasCover ? parent.width * 0.5 + 5 * Ui.f : 14 * Ui.f
                            width: card.hasCover ? parent.width * 0.5 - 19 * Ui.f : parent.width - 28 * Ui.f
                            anchors.bottom: parent.bottom; anchors.bottomMargin: 14 * Ui.f
                            spacing: 2 * Ui.f
                            Txt {
                                width: parent.width
                                text: modelData.title || modelData.name || ""
                                font.pixelSize: 16 * Ui.f; font.weight: Font.Medium
                                wrapMode: card.hasCover ? Text.Wrap : Text.NoWrap
                                maximumLineCount: card.hasCover ? 4 : 1
                            }
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
