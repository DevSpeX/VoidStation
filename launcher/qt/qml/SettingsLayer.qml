// SPDX-License-Identifier: GPL-3.0-or-later
// Einstellungen: Uebersicht mit Bereichs-Kacheln → Bereich (Spalten mit Knoepfen) → Esc / B zurueck.
// Neuer Bereich: Eintrag in cats + SetGroup(s) mit visible: s.cat === "<id>" + Zustand in catSub().
import QtQuick
import VS

Layer {
    id: s
    scope: "settings"
    track: trk
    property string cat: ""
    property var sett: null
    property var bt: null
    property bool btScanning: false
    property var vsState: null
    property var wifiList: null
    property var wifiPick: null
    readonly property var catDefs: [
        { id: "lang", icon: "globe", color: "#2d4a6b", title: "settings.language" },
        { id: "display", icon: "monitor", color: "#2b5b66", title: "settings.catDisplay" },
        { id: "design", icon: "palette", color: "#553a6e", title: "settings.catDesign" },
        { id: "audio", icon: "speaker", color: "#74461f", title: "settings.catAudio" },
        { id: "net", icon: "wifi", color: "#2b5a45", title: "settings.network" },
        { id: "bt", icon: "bluetooth", color: "#24477a", title: "bt.title" },
        { id: "share", icon: "folder", color: "#284843", title: "settings.share" },
        { id: "updates", icon: "update", color: "#6e2b3c", title: "settings.catUpdates" },
        { id: "system", icon: "power", color: "#3a3f46", title: "settings.system" }]
    readonly property var cats: catDefs.filter(function (c) { return c.id !== "share" || (sett && sett.share) })
    readonly property var catNow: { for (var i = 0; i < cats.length; i++) if (cats[i].id === cat) return cats[i]; return null }
    title: catNow ? Ui.t(catNow.title) : Ui.t("settings.title")
    readonly property real colH: stage.height
    readonly property var fit: Ui.fitRows(stage.height - 12 * Ui.f - Ui.u * 0.03 - (12 * Ui.f + 0.03 * Ui.u), Ui.u * 0.74, Ui.gap, 3)
    readonly property string ip: sett && sett.net && sett.net.addresses.length ? sett.net.addresses[0].ip : ""

    onOpened: { cat = ""; wifiPick = null; load(); refreshVs(false) }
    function firstFocus() { return Nav.collect(trk)[0] || null }
    function load() {
        Api.get("/api/settings", function (j) {
            update(function () { sett = j; app.sett = j; app.showVol(j.volume) })
            Api.get("/api/bluetooth/status", function (b) { update(function () { bt = b }) }, function () { bt = { available: false } })
        }, function () { app.toast(Ui.t("settings.loadFailed"), true) })
    }
    // Inhalt aendern, Fokus behalten (gleicher Schluessel wie vorher)
    property var wantFocus: null                // Bereich gerade geoeffnet: Fokus setzen, sobald die Knoepfe da sind
    function update(fn) {
        var k = Nav.current && Nav.current.key ? Nav.current.key : ""
        fn()
        Qt.callLater(function () { if (wantFocus !== null) settle(); else if (k) refocus(k) })
    }
    function refocus(k) {
        if (!s.open) return
        if (Nav.alive(Nav.current, s) && Nav.current.key === k) return
        var it = Nav.collect(trk)
        for (var i = 0; i < it.length; i++) if (it[i].key === k) return app.setFocus(it[i], true)
        if (!Nav.alive(Nav.current, s)) {
            for (i = 0; i < it.length; i++) if (it[i].on) return app.setFocus(it[i], true)
            if (it.length) app.setFocus(it[0], true)
        }
    }
    function settle() {                         // gewuenschter Knopf, sonst der aktive, sonst der erste
        if (!s.open || app.layerRoot !== s) return
        if (!sett) return                       // Daten kommen noch
        var it = Nav.collect(trk), want = wantFocus
        if (want === "selfupd") { if (!vsState) return; if (!vsState.any) want = "" }
        for (var i = 0; i < it.length; i++) if (want && it[i].key === want) { wantFocus = null; return app.setFocus(it[i], true) }
        for (i = 0; i < it.length; i++) if (it[i].on) { wantFocus = null; return app.setFocus(it[i], true) }
        if (it.length) { wantFocus = null; app.setFocus(it[0], true) }
    }
    function openCat(id) {
        var prev = cat
        cat = id
        wifiPick = null
        trk.reset()
        wantFocus = id ? (id === "updates" ? "selfupd" : "") : "cat" + prev
        Qt.callLater(settle)
    }
    function handleBack() {
        if (wifiPick) { wifiPick = null; Qt.callLater(function () { refocus("scan") }); return true }
        if (cat) { openCat(""); return true }
        return false
    }
    function fail(e) { app.toast(Ui.t("common.failedMsg", { msg: e }), true) }

    // ---- Kachel-Zustand
    function catSub(id) {
        if (!sett) return ""
        switch (id) {
        case "lang":
            var l = (sett.langs || []).filter(function (x) { return x.id === Ui.lang })[0]
            return l ? l.label : (Ui.lang === "de" ? "Deutsch" : "English")
        case "display":
            var d = (sett.displays || [])[0]
            return (d && d.current ? d.current.replace("x", "\u00d7") + " · " : "") + Ui.num(Ui.scale) + "\u00d7"
        case "design": return Ui.t("theme." + vs.themeName, null, vs.themeName)
        case "audio":
            var o = sett.audio && sett.audio.ok ? sett.audio.outputs.filter(function (x) { return x.active })[0] : null
            return (o ? o.label + " · " : "") + app.volText
        case "net": return sett.net.addresses.length ? sett.net.addresses[0].ip : Ui.t("settings.offline")
        case "bt":
            if (!bt || !bt.available) return Ui.t("settings.btNone")
            if (!bt.service || !bt.powered) return Ui.t("common.off")
            var c = (bt.devices || []).filter(function (x) { return x.connected }).map(function (x) { return x.name || x.mac })
            return c.length ? c.join(", ") : Ui.t("common.on")
        case "share": return sett.share.samba ? "\\\\" + sett.net.hostname + "\\share" : Ui.t("common.off")
        case "updates":
            if (sett.live) return Ui.t("settings.liveShort")
            if (app.updInfo) return app.updNoteText(app.updInfo)
            if (vsState && vsState.system && vsState.system.count) return vsVersion() + " · " + Ui.t("upd.noteSystem", { n: Ui.num(vsState.system.count) })
            return vsVersion() + (vsState ? " · " + (vsState.remote ? Ui.t("upd.allCurrent") : Ui.t("upd.unreachable")) : "")
        case "system": return sett.ssh === undefined ? sett.net.hostname : Ui.t("settings.ssh") + ": " + Ui.t(sett.ssh ? "common.on" : "common.off")
        }
        return ""
    }

    // ---- Updates: VoidStation + Void-Pakete (inkl. Kernel) + Flatpak/AppImages/Proton-GE, alles mit einem Knopf
    function vsVersion() { var sv = sett && sett.version; return (vsState && vsState.local) || (sv && (sv.version || sv.build)) || "\u2013" }
    function chLabel(v) { return Ui.t("channel." + v.channel, null, v.channel_label) }
    function sysSummary(st) {
        var y = st && st.system
        if (!y) return ""
        var p = []
        if (y.pkgs && y.pkgs.length) p.push(Ui.t("upd.sysPkgs", { n: Ui.num(y.pkgs.length) }) + (y.kernel ? " " + Ui.t("upd.sysKernel", { version: y.kernel.replace(/_\d+$/, "") }) : ""))
        if (y.flatpak) p.push(Ui.t("upd.sysFlatpak", { n: Ui.num(y.flatpak) }))
        for (var i = 0; i < (y.appimage || []).length; i++) p.push(Ui.l(y.appimage[i]))
        if (y.proton) p.push("Proton-GE " + y.proton)
        return p.join(" · ")
    }
    function vsInfo() {
        if (!sett) return ""
        if (sett.live) return "VoidStation " + Ui.esc(vsVersion()) + "<br>" + Ui.esc(Ui.t("settings.liveInfo"))
        var st = Ui.esc(Ui.t("upd.searching"))
        if (vsState) st = vsState.available ? "<b>" + Ui.esc(Ui.t("upd.available", { version: vsState.remote })) + "</b>"
                                            : Ui.esc(vsState.remote ? Ui.t("upd.current") : Ui.t("upd.unreachable"))
        var ch = vsState ? " · " + Ui.esc(Ui.t("upd.channel", { channel: chLabel(vsState) })) : ""
        return "VoidStation " + Ui.esc(vsVersion()) + ch + "<br>" + st
    }
    function sysInfo() {
        if (!vsState || !vsState.system) return ""
        var y = vsState.system, sum = sysSummary(vsState)
        var line = sum ? "<b>" + Ui.esc(sum) + "</b>" : Ui.esc(y.checked ? Ui.t("upd.sysCurrent") : Ui.t("upd.sysUnchecked"))
        if (sum && y.due_at && !y.due && !vsState.available)
            line += "<br>" + Ui.esc(Ui.t("upd.sysDueAt", { date: Ui.loc.toString(new Date(y.due_at * 1000), Ui.lang === "de" ? "d. MMMM yyyy" : "MMMM d, yyyy") }))
        if (y.error && !(y.pkgs && y.pkgs.length)) line = Ui.esc(Ui.t("upd.sysError"))
        var rb = vsState.reboot || {}
        if (rb.kernel || rb.voidstation) line += "<br><b>" + Ui.esc(Ui.t(rb.kernel ? "upd.rebootKernel" : "upd.rebootVs")) + "</b>"
        if (rb.kernel_stuck) line += "<br>" + Ui.esc(Ui.t("upd.kernelStuck", { version: rb.kernel_stuck.version, running: rb.kernel_stuck.running }))
        return Ui.esc(Ui.t("upd.system")) + "<br>" + line
    }
    function refreshVs(force, then) {
        Api.get("/api/updates" + (force ? "?force=1" : ""), function (j) { update(function () { vsState = j }); if (then) then() },
                function () { vsState = { local: null, remote: null, available: false, any: false }; if (then) then() })
    }
    function runUpdates() {
        if (app.jobBusy) return app.toast(Ui.t("common.busy"))
        app.toast(Ui.t("upd.checking"))
        refreshVs(true, function () {
            toastBox.hide()
            var v = vsState
            if (!v) return app.toast(Ui.t("upd.unreachable"), true)
            if (v.busy) return app.toast(Ui.t("upd.xbpsBusy"), true)
            var rb = v.reboot || {}
            if (!v.any) {
                if (rb.kernel || rb.voidstation) return app.rebootPrompt(rb)
                if (!v.remote) return app.toast(Ui.t("upd.unreachable"), true)
                return app.toast(Ui.t("upd.upToDate"))
            }
            var parts = []
            if (v.available) {
                var news = (v.changes || []).map(function (e) {
                    var ch = (Ui.lang !== "de" && e["changes_" + Ui.lang] && e["changes_" + Ui.lang].length) ? e["changes_" + Ui.lang] : e.changes
                    return e.version + ":\n" + ch.map(function (c) { return "\u2022 " + c }).join("\n")
                }).join("\n\n")
                parts.push(Ui.t("upd.confirmText", { remote: v.remote, local: v.local || "\u2013", channel: chLabel(v) }) + (news ? "\n\n" + Ui.t("upd.news") + "\n" + news : ""))
            }
            var y = v.system
            if (y && y.count) {
                var names = y.pkgs.slice(0, 12).join(", ") + (y.pkgs.length > 12 ? " " + Ui.t("upd.more", { n: Ui.num(y.pkgs.length - 12) }) : "")
                parts.push(Ui.t("upd.system") + ": " + sysSummary(v) + (names ? "\n" + names : ""))
            }
            var restart = v.available || (y && y.kernel) || rb.kernel || rb.voidstation
            parts.push(Ui.t(restart ? "upd.keep" : "upd.keepNoReboot"))
            app.dialog(Ui.t("upd.confirmTitle"), parts.join("\n\n"), [[Ui.t("upd.now"), function () { app.jobStart("update") }], [Ui.t("common.cancel")]])
        })
    }
    function setChannel(ch) {
        if (ch === "main" && !(vsState && vsState.channel === "main")) app.toast(Ui.t("channel.testWarn"))
        Api.post("/api/selfupdate/channel", { channel: ch }, function (j) { update(function () { vsState = j }) }, fail)
    }
    function setSysDays(d) {
        if (sett.sysupd_days === d) return
        Api.post("/api/settings/sysupd", { days: d }, function (j) { update(function () { vsState = j; var x = sett; x.sysupd_days = d; sett = null; sett = x }) }, fail)
    }

    // ---- Sprache, Anzeige, Design, Ton
    function setLang(l) {
        if (l === Ui.lang) return
        Api.post("/api/settings/lang", { lang: l }, function () {
            vs.setLang(l)
            app.load()
            update(function () { var x = sett; sett = null; sett = x })
        }, function () { app.toast(Ui.t("common.saveFailed"), true) })
    }
    function setScale(v) {
        Api.post("/api/settings/scale", { scale: v }, function (j) {
            update(function () { sett = j; Ui.scale = v; app.layout() })
            app.toast(Ui.t("settings.scaleToast", { scale: Ui.num(v) }))
        }, function () { app.toast(Ui.t("common.saveFailed"), true) })
    }
    function setTheme(th) {
        Api.post("/api/settings/theme", { theme: th }, function (j) {
            update(function () { sett = j; vs.setTheme(th) })
            app.toast(Ui.t("settings.themeToast", { name: Ui.t("theme." + th, null, th) }))
        }, fail)
    }
    function setCursor(c) {
        Api.post("/api/settings/cursor", c, function (j) { update(function () { sett = j }); app.toast(Ui.t("settings.cursorToast")) }, fail)
    }
    function setResolution(m) {
        Api.post("/api/settings/resolution", { mode: m }, function (j) {
            update(function () { sett = j })
            app.toast(Ui.t("settings.resToast", { mode: m.replace("x", "\u00d7") }))
        }, fail)
    }
    function setOutput(o) {
        Api.post("/api/audio/output", { card: o.card, profile: o.profile }, function (j) {
            update(function () { sett = j })
            app.toast(Ui.t("settings.outToast", { name: o.label }))
        }, fail)
    }
    function modes(d) {
        return d.modes.filter(function (m) { var p = m.split("x"); return parseInt(p[0]) >= 1024 && parseInt(p[1]) >= 576 }).slice(0, 6)
    }

    // ---- Netzwerk, Bluetooth, System
    function wifiScan() {
        app.toast(Ui.t("wifi.scanning"))
        Api.get("/api/wifi/scan", function (j) { toastBox.hide(); update(function () { wifiList = j || [] }) },
                function (e) { app.toast(Ui.t("wifi.scanFailed", { msg: e }), true) })
    }
    function wifiConnect(ssid, pw) {
        app.toast(Ui.t("wifi.connecting", { ssid: ssid }))
        Api.post("/api/wifi/connect", { ssid: ssid, password: pw }, function (j) {
            wifiPick = null
            update(function () { sett = j })
            app.toast(Ui.t("wifi.connected", { ssid: ssid }))
            Qt.callLater(function () { refocus("scan") })
        }, function (e) {
            // Bekannte Fehler kommen als Schluessel "wifi.err.*", alles andere als Klartext
            app.toast(e.indexOf("wifi.err.") === 0 ? Ui.t(e, { ssid: ssid }) : Ui.t("wifi.failed", { msg: e }), true)
            if (e === "wifi.err.password" && wifiPick) {
                wifiPw.value = ""
                Qt.callLater(function () { app.setFocus(wifiPw, true); app.openOsk(wifiPw) })
            }
        })
    }
    function btCall(path, body, busy, ok, okErr) {
        if (busy) app.toast(busy)
        Api.post(path, body, function (r) {
            update(function () { bt = r && r.status ? r.status : (r && r.available !== undefined ? r : bt) })
            if (ok) app.toast(r && r.ok === false && okErr ? okErr : ok, !!(r && r.ok === false && okErr))
        }, fail)
    }
    function btScan() {
        if (btScanning) return
        btScanning = true
        app.toast(Ui.t("bt.scanningToast"))
        Api.post("/api/bluetooth/scan", {}, function () { btPoll.t0 = Date.now(); btPoll.start() }, function (e) { btScanning = false; fail(e) })
    }
    Timer {
        id: btPoll; interval: 1500; repeat: true
        property real t0: 0
        onTriggered: Api.get("/api/bluetooth/status", function (b) {
            s.update(function () { s.bt = b })
            if (!b.scanning || Date.now() - btPoll.t0 > 14000) { btPoll.stop(); s.btScanning = false }
        }, function () { btPoll.stop(); s.btScanning = false })
    }
    function setFrontend(fe) {
        if (sett.frontend === fe) return
        Api.post("/api/settings/frontend", { frontend: fe }, function (j) { update(function () { sett = j }); app.toast(Ui.t("settings.frontendToast")) }, fail)
    }
    function setSsh(on) {
        if (!!sett.ssh === on) return
        app.toast(Ui.t(on ? "settings.sshTurningOn" : "settings.sshTurningOff"))
        Api.post("/api/settings/ssh", { on: on }, function (r) {
            update(function () { var x = sett; x.ssh = r.ssh; sett = null; sett = x })
            app.toast(r.ssh ? Ui.t("settings.sshOn", { host: s.ip || sett.net.hostname }) : Ui.t("settings.sshOff"))
        }, fail)
    }

    headRight: NowLine {
        main: s.sett ? (s.ip || Ui.t("settings.offline")) : ""
        sub: s.sett && s.ip ? s.sett.net.hostname : ""
    }

    Track {
        id: trk
        anchors.fill: parent
        // Uebersicht
        Group {
            visible: !s.cat
            showTitle: false
            topPadding: 12 * Ui.f + Ui.u * 0.03
            TileGrid {
                items: s.cats
                rows: s.fit.n
                cellW: Ui.u * 1.6 * s.fit.k
                cellH: Ui.u * 0.74 * s.fit.k
                delegate: Component {
                    Tile {
                        property string key: "cat" + modelData.id
                        tileColor: modelData.color
                        enterDelay: index * 35
                        onTriggered: s.openCat(modelData.id)
                        readonly property real uu: Ui.u * s.fit.k
                        Glyph { x: parent.width * 0.07; y: parent.height * 0.12; width: uu * 0.26; height: width; name: modelData.icon; color: Ui.c.tileText }
                        Txt { x: parent.width * 0.07; width: parent.width * 0.86; anchors.bottom: sub.top; anchors.bottomMargin: 2
                              text: Ui.t(modelData.title); font.pixelSize: uu * 0.115; color: Ui.c.tileText }
                        Row {
                            id: sub
                            x: parent.width * 0.07; width: parent.width * 0.86
                            anchors.bottom: parent.bottom; anchors.bottomMargin: parent.height * 0.08
                            spacing: uu * 0.03
                            readonly property bool warn: modelData.id === "updates" && !!app.updInfo && !(s.sett && s.sett.live)
                            Glyph { visible: sub.warn; name: "updwarn"; width: uu * 0.09; height: width; anchors.verticalCenter: parent.verticalCenter }
                            Txt {
                                width: parent.width - (sub.warn ? uu * 0.12 : 0)
                                text: { app.volText; app.updInfo; s.vsState; s.bt; Ui.lang; vs.themeName; return s.catSub(modelData.id) }
                                font.pixelSize: uu * 0.085
                                font.weight: sub.warn ? Font.DemiBold : Font.Normal
                                color: sub.warn ? Ui.c.tileText : Ui.c.tileSub
                            }
                        }
                    }
                }
            }
        }
        // Sprache
        SetGroup {
            visible: s.cat === "lang"; availH: s.colH; title: Ui.t("settings.langUi")
            SetRow {
                Repeater {
                    model: s.sett ? (s.sett.langs || [{ id: "de", label: "Deutsch" }, { id: "en", label: "English" }]) : []
                    Pill { property string key: "lang" + modelData.id; text: modelData.label; on: modelData.id === Ui.lang; maxWidth: Ui.screenW * 0.4; onTriggered: s.setLang(modelData.id) }
                }
            }
            Info { html: Ui.esc(Ui.t("settings.langApps")) }
        }
        // Anzeige
        SetGroup {
            visible: s.cat === "display"; availH: s.colH; title: Ui.t("settings.scale")
            SetRow {
                Repeater {
                    model: s.sett ? s.sett.scales : []
                    Pill { property string key: "scale" + modelData; text: Ui.num(modelData) + "\u00d7"; on: Math.abs(modelData - Ui.scale) < 0.01; onTriggered: s.setScale(modelData) }
                }
            }
        }
        Repeater {
            model: s.cat === "display" && s.sett ? (s.sett.displays || []) : []
            SetGroup {
                property var d: modelData
                availH: s.colH; title: Ui.t("settings.resolution", { name: modelData.name })
                SetRow {
                    Repeater {
                        model: s.modes(d)
                        Pill {
                            property string key: "res" + modelData
                            text: modelData.replace("x", "\u00d7").replace(/i$/, " " + Ui.t("settings.interlaced")) + (modelData === d.current && d.rate ? " · " + Math.round(d.rate) + " Hz" : "")
                            on: modelData === d.current
                            maxWidth: Ui.screenW * 0.4
                            onTriggered: s.setResolution(modelData)
                        }
                    }
                }
            }
        }
        // Design
        SetGroup {
            visible: s.cat === "design"; availH: s.colH; title: Ui.t("settings.colors")
            SetRow {
                Repeater {
                    model: s.sett ? (s.sett.themes || []) : []
                    Pill { property string key: "th" + modelData; text: Ui.t("theme." + modelData, null, modelData); on: modelData === vs.themeName; maxWidth: Ui.screenW * 0.4; onTriggered: s.setTheme(modelData) }
                }
            }
        }
        SetGroup {
            visible: s.cat === "design" && !!s.sett && !!s.sett.cursor; availH: s.colH; title: Ui.t("settings.cursor")
            SetRow {
                label: Ui.t("settings.cursorStyle")
                Repeater {
                    model: s.sett && s.sett.cursor ? s.sett.cursor.themes : []
                    Pill { property string key: "ct" + modelData.id; text: Ui.l(modelData.label); on: modelData.id === s.sett.cursor.theme; onTriggered: s.setCursor({ theme: modelData.id }) }
                }
            }
            SetRow {
                label: Ui.t("settings.cursorSize")
                Repeater {
                    model: s.sett && s.sett.cursor ? s.sett.cursor.sizes : []
                    Pill { property string key: "cs" + modelData; text: String(modelData); on: modelData === s.sett.cursor.size; onTriggered: s.setCursor({ size: modelData }) }
                }
            }
        }
        // Ton
        SetGroup {
            visible: s.cat === "audio"; availH: s.colH; title: Ui.t("settings.audioOut")
            Info { visible: !!s.sett && !(s.sett.audio && s.sett.audio.ok); html: Ui.esc(Ui.t("settings.noAudio")) }
            SetRow {
                Repeater {
                    model: s.sett && s.sett.audio && s.sett.audio.ok ? s.sett.audio.outputs : []
                    Pill { property string key: "out" + modelData.profile; text: modelData.label; on: modelData.active; maxWidth: Ui.screenW * 0.4; onTriggered: s.setOutput(modelData) }
                }
            }
        }
        SetGroup {
            visible: s.cat === "audio"; availH: s.colH; title: Ui.t("settings.volume")
            Flow { width: Ui.screenW * 0.4; spacing: 8 * Ui.f; VolBar { showMute: true } }
        }
        // Netzwerk
        SetGroup {
            visible: s.cat === "net"; availH: s.colH; title: Ui.t("settings.connection")
            Info {
                html: !s.sett ? "" : Ui.esc(Ui.t("settings.hostname")) + ": <b>" + Ui.esc(s.sett.net.hostname) + "</b><br>" +
                      (s.sett.net.addresses.length ? s.sett.net.addresses.map(function (x) { return Ui.esc(x.iface) + ": <b>" + Ui.esc(x.ip) + "</b>" }).join("<br>")
                                                   : Ui.esc(Ui.t("settings.noConn")))
            }
        }
        SetGroup {
            visible: s.cat === "net"; availH: s.colH; title: Ui.t("settings.wifi")
            SetRow {
                visible: !!s.wifiPick
                Field {
                    id: wifiPw
                    property string key: "pw"
                    password: true
                    placeholder: s.wifiPick ? Ui.t("settings.wifiPw", { ssid: s.wifiPick.ssid }) : ""
                    onSubmitted: function (t) { if (s.wifiPick) s.wifiConnect(s.wifiPick.ssid, t) }
                }
                Pill { property string key: "go"; text: Ui.t("settings.connect"); onTriggered: s.wifiConnect(s.wifiPick.ssid, wifiPw.value) }
                Pill { property string key: "cancel"; text: Ui.t("common.cancel"); onTriggered: { s.wifiPick = null; Qt.callLater(function () { s.refocus("scan") }) } }
            }
            SetRow {
                visible: !s.wifiPick
                Pill { property string key: "scan"; text: s.wifiList ? Ui.t("settings.rescan") : Ui.t("settings.scan"); onTriggered: s.wifiScan() }
            }
            SetRow {
                visible: !s.wifiPick && !!s.wifiList
                Repeater {
                    model: s.wifiList ? s.wifiList.slice(0, 8) : []
                    Pill {
                        property string key: "w" + modelData.ssid
                        rich: true
                        maxWidth: Ui.screenW * 0.4
                        text: (modelData.secure ? "\ud83d\udd12 " : "") + Ui.esc(modelData.ssid) + " <font color='" + Ui.c.textFaint + "'>" + modelData.signal + "%</font>"
                        on: modelData.active
                        onTriggered: {
                            if (modelData.secure && !modelData.active) {
                                wifiPw.value = ""
                                s.wifiPick = modelData
                                Qt.callLater(function () { app.setFocus(wifiPw, true); app.openOsk(wifiPw) })
                            } else s.wifiConnect(modelData.ssid, "")
                        }
                    }
                }
            }
        }
        // Freigabe
        SetGroup {
            visible: s.cat === "share"; availH: s.colH; title: Ui.t("settings.shareWin")
            Info {
                html: !s.sett || !s.sett.share ? "" : s.sett.share.samba
                    ? Ui.esc(Ui.t("settings.shareHow")) + "<br><b>\\\\" + Ui.esc(s.sett.net.hostname) + "\\share</b>" +
                      (s.ip ? "<br>" + Ui.esc(Ui.t("settings.shareOr")) + " <b>\\\\" + Ui.esc(s.ip) + "\\share</b>" : "") +
                      "<br>" + Ui.t("settings.shareLogin", { user: "<b>" + Ui.esc(s.sett.share.user || "") + "</b>" })
                    : Ui.esc(Ui.t("settings.shareOff"))
            }
        }
        // Bluetooth
        SetGroup {
            visible: s.cat === "bt"; availH: s.colH; title: Ui.t("bt.desc")
            Info { visible: !s.bt || !s.bt.available; html: Ui.esc(Ui.t("bt.unsupported")) }
            Info { visible: !!s.bt && s.bt.available && !s.bt.service; html: Ui.esc(Ui.t("bt.serviceOff")) }
            SetRow {
                visible: !!s.bt && s.bt.available && !s.bt.service
                Pill { property string key: "btsrv"; text: Ui.t("bt.startService"); onTriggered: s.btCall("/api/bluetooth/service", { action: "start" }, Ui.t("bt.startingService")) }
            }
            SetRow {
                visible: !!s.bt && s.bt.available && s.bt.service
                Pill { property string key: "btpwr"; text: Ui.t(s.bt && s.bt.powered ? "bt.powerOff" : "bt.powerOn"); on: !!s.bt && s.bt.powered
                       onTriggered: s.btCall("/api/bluetooth/power", { powered: !s.bt.powered }, Ui.t(s.bt.powered ? "bt.poweringOff" : "bt.poweringOn")) }
                Pill { property string key: "btscan"; visible: !!s.bt && s.bt.powered; text: s.btScanning ? Ui.t("bt.scanning") : Ui.t("bt.scan"); onTriggered: s.btScan() }
            }
            Info { visible: !!s.bt && s.bt.available && s.bt.service && s.bt.powered && !(s.bt.devices || []).length
                   html: Ui.esc(s.btScanning ? Ui.t("bt.scanning") : Ui.t("bt.noDevices")) }
            SetRow {
                visible: !!s.bt && s.bt.available && s.bt.service && s.bt.powered && (s.bt.devices || []).length > 0
                label: Ui.t("bt.available")
                Repeater {
                    model: s.bt && s.bt.devices ? s.bt.devices.slice(0, 10) : []
                    Row {
                        spacing: 8 * Ui.f
                        property var dev: modelData
                        width: Ui.screenW * 0.4
                        Pill {
                            property string key: "bt" + modelData.mac.replace(/[^A-Za-z0-9]/g, "")
                            rich: true
                            maxWidth: Ui.screenW * 0.4 - (rm.visible ? rm.width + 8 * Ui.f : 0)
                            on: !!modelData.connected
                            text: Ui.esc(modelData.name || modelData.mac) + "<font color='" + Ui.c.textFaint + "'>" +
                                  (modelData.connected ? " · " + Ui.t("bt.connected") : modelData.paired ? " · " + Ui.t("bt.paired") : "") + "</font>"
                            onTriggered: {
                                var m = modelData.mac
                                if (modelData.connected) s.btCall("/api/bluetooth/disconnect", { mac: m }, Ui.t("bt.disconnecting"), Ui.t("bt.disconnectedToast"))
                                else if (modelData.paired) s.btCall("/api/bluetooth/connect", { mac: m }, Ui.t("bt.connecting"), Ui.t("bt.connectedToast"), Ui.t("bt.connectFailed"))
                                else s.btCall("/api/bluetooth/pair", { mac: m }, Ui.t("bt.pairing"), Ui.t("bt.pairedToast"), Ui.t("bt.pairFailed"))
                            }
                        }
                        Pill {
                            id: rm
                            property string key: "btrm" + modelData.mac.replace(/[^A-Za-z0-9]/g, "")
                            visible: !!modelData.paired
                            text: Ui.t("bt.remove")
                            onTriggered: s.btCall("/api/bluetooth/remove", { mac: modelData.mac }, Ui.t("bt.disconnecting"), Ui.t("bt.disconnectedToast"))
                        }
                    }
                }
            }
        }
        // Updates
        SetGroup {
            visible: s.cat === "updates"; availH: s.colH; title: "VoidStation"
            Info { html: { s.vsState; s.sett; Ui.lang; return s.vsInfo() } }
            Info { visible: !!s.sett && !s.sett.live && text !== ""; html: { s.vsState; Ui.lang; return s.sysInfo() } }
            SetRow {
                visible: !!s.sett && !s.sett.live
                Pill { property string key: "selfupd"; text: Ui.t("settings.update"); onTriggered: s.runUpdates() }
                Pill { property string key: "updreboot"; visible: !!(s.vsState && s.vsState.reboot && (s.vsState.reboot.kernel || s.vsState.reboot.voidstation))
                       text: Ui.t("upd.rebootNow"); onTriggered: app.power("reboot") }
            }
        }
        SetGroup {
            visible: s.cat === "updates" && !!s.sett && !s.sett.live; availH: s.colH; title: Ui.t("settings.channel")
            SetRow {
                Repeater {
                    model: [["stable", "channel.stable"], ["main", "channel.main"]]
                    Pill { property string key: "ch" + modelData[0]; text: Ui.t(modelData[1]); on: ((s.vsState && s.vsState.channel) || "stable") === modelData[0]; onTriggered: s.setChannel(modelData[0]) }
                }
            }
            SetRow {
                label: Ui.t("settings.sysRemind")
                Repeater {
                    model: s.sett ? (s.sett.sysupd_choices || [30, 60, 90]) : []
                    Pill { property string key: "sd" + modelData; text: Ui.t("settings.days", { n: modelData }); on: (s.sett.sysupd_days || 90) === modelData; onTriggered: s.setSysDays(modelData) }
                }
            }
            Info { html: Ui.esc(Ui.t("settings.sysRemindHint")) }
        }
        // System
        SetGroup {
            visible: s.cat === "system"; availH: s.colH; title: Ui.t("settings.power")
            SetRow {
                Pill { property string key: "reload"; text: Ui.t("settings.reload"); onTriggered: vs.restart() }
                Pill { property string key: "reboot"; text: Ui.t("settings.reboot"); onTriggered: app.power("reboot") }
                Pill { property string key: "off"; text: Ui.t("settings.poweroff"); onTriggered: app.power("poweroff") }
            }
        }
        SetGroup {
            visible: s.cat === "system" && !!s.sett && (s.sett.frontends || []).length > 1; availH: s.colH; title: Ui.t("settings.frontend")
            SetRow {
                Repeater {
                    model: s.sett ? (s.sett.frontends || []) : []
                    Pill { property string key: "fe" + modelData; text: Ui.t("frontend." + modelData, null, modelData); on: s.sett.frontend === modelData; onTriggered: s.setFrontend(modelData) }
                }
            }
            Info { html: Ui.esc(Ui.t("settings.frontendHint")) }
        }
        SetGroup {
            visible: s.cat === "system" && !!s.sett && s.sett.ssh !== undefined; availH: s.colH; title: Ui.t("settings.ssh")
            SetRow {
                Repeater {
                    model: [true, false]
                    Pill { property string key: "ssh" + modelData; text: Ui.t(modelData ? "common.on" : "common.off"); on: !!s.sett && !!s.sett.ssh === modelData; onTriggered: s.setSsh(modelData) }
                }
            }
        }
    }
}
