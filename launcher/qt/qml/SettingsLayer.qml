// SPDX-License-Identifier: GPL-3.0-or-later
// Einstellungen: Uebersicht mit Bereichs-Kacheln → Bereich (Spalten mit Knoepfen) → Esc / B zurueck.
// Neuer Bereich: Eintrag in cats + SetGroup(s) mit visible: s.cat === "<id>" + Zustand in catSub().
import QtQuick
import VS
import "VS/OskLayouts.js" as OskLayouts

Layer {
    id: s
    scope: "settings"
    track: trk
    property string cat: ""
    property var sett: null
    property var bt: null
    property bool btScanning: false
    property var btRename: null                 // Geraet, das gerade umbenannt wird (Eingabefeld statt Liste)
    readonly property real btW: Ui.screenW * 0.7  // Bluetooth-Seite hat nur eine Spalte: Geraeteliste darf breiter sein
    property var vsState: null
    property var wifiList: null
    property var wifiPick: null
    property var acctList: []
    property var acctSession: null
    property var acctPolicy: null
    property string parentalChildId: ""
    property var parentalPolicies: ({})
    property var parentalStatuses: ({})
    property var parentalTiles: []
    property var parentalCats: []
    // Ton: Geraete (Fernseher, USB-/Bluetooth-Kopfhoerer …) statt PipeWire-Profilen; aktives Geraet zeigt Format + Mikro
    readonly property var audioDevs: sett && sett.audio && sett.audio.ok ? (sett.audio.devices || []) : []
    readonly property var audioDev: { for (var i = 0; i < audioDevs.length; i++) if (audioDevs[i].active) return audioDevs[i]; return null }
    readonly property var catDefs: [
        { id: "accounts", icon: "user", color: "#2d526b", title: "settings.accounts" },
        { id: "lang", icon: "speech", color: "#2d4a6b", title: "settings.language" },
        { id: "display", icon: "monitor", color: "#2b5b66", title: "settings.catDisplay" },
        { id: "design", icon: "palette", color: "#553a6e", title: "settings.catDesign" },
        { id: "audio", icon: "speaker", color: "#74461f", title: "settings.catAudio" },
        { id: "net", icon: "wifi", color: "#2b5a45", title: "settings.network" },
        { id: "bt", icon: "bluetooth", color: "#24477a", title: "bt.title" },
        { id: "share", icon: "folder", color: "#284843", title: "settings.share" },
        { id: "updates", icon: "update", color: "#6e2b3c", title: "settings.catUpdates" },
        { id: "system", icon: "power", color: "#3a3f46", title: "settings.system" }]
    readonly property bool isChildAccount: !(sett && sett.live) && !!(acctSession ? acctSession.role === "child" && !acctSession.is_guest : (app.session && app.session.role === "child" && !app.session.is_guest))
    readonly property bool isRestrictedAccount: !(sett && sett.live) && !!((acctSession || app.session) && ((acctSession || app.session).role === "child" || (acctSession || app.session).is_guest))
    readonly property var cats: catDefs.filter(function (c) {
        if (c.id === "share") return !!(sett && sett.share) && !isRestrictedAccount
        if (c.id === "accounts") return !(sett && sett.live)
        if (isRestrictedAccount && ["accounts", "lang", "display", "design", "audio"].indexOf(c.id) < 0) return false
        return true
    })
    readonly property var catNow: { for (var i = 0; i < cats.length; i++) if (cats[i].id === cat) return cats[i]; return null }
    title: catNow ? Ui.t(catNow.title) : Ui.t("settings.title")
    readonly property real colH: stage.height
    readonly property var fit: Ui.fitRows(stage.height - 12 * Ui.f - Ui.u * 0.03 - (12 * Ui.f + 0.03 * Ui.u), Ui.u * 0.74, Ui.gap, 3)
    readonly property string ip: sett && sett.net && sett.net.addresses.length ? sett.net.addresses[0].ip : ""

    onOpened: { cat = ""; wifiPick = null; btRename = null; load(); refreshVs(false); loadAccounts() }
    function firstFocus() { return Nav.collect(trk)[0] || null }
    function load() {
        Api.get("/api/settings", function (j) {
            update(function () {
                sett = j; app.sett = j; app.showVol(j.volume)
                if (j && j.sounds) vs.setSounds(!!j.sounds.on, j.sounds.volume || 70, j.sounds.preset || "void")
            })
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
        btRename = null
        if (id === "accounts") loadAccounts()
        trk.reset()
        wantFocus = id ? (id === "updates" ? "selfupd" : "") : "cat" + prev
        Qt.callLater(settle)
    }
    function handleBack() {
        if (wifiPick) { wifiPick = null; Qt.callLater(function () { refocus("scan") }); return true }
        if (btRename) { btRenameEnd(); return true }
        if (cat) { openCat(""); return true }
        return false
    }
    function fail(e) { app.toast(Ui.t("common.failedMsg", { msg: e }), true) }

    // ---- Kachel-Zustand
    function catSub(id) {
        if (!sett) return ""
        switch (id) {
        case "accounts":
            var sess = acctSession || app.session
            return sess ? (sess.display_name + " · " + Ui.t("account.role." + sess.role)) : Ui.t("account.title")
        case "lang":
            var l = (sett.langs || []).filter(function (x) { return x.id === Ui.lang })[0]
            return l ? l.label : (Ui.lang === "de" ? "Deutsch" : "English")
        case "display":
            var d = (sett.displays || [])[0]
            return (d && d.current ? d.current.replace("x", "\u00d7") + " · " : "") + Ui.num(Ui.scale) + "\u00d7"
        case "design": return Ui.t("theme." + vs.themeName, null, vs.themeName)
        case "audio": return (audioDev ? devLabel(audioDev) + " · " : "") + app.volText
        case "net":
            var nl = (sett.net.links || []).filter(function (x) { return x.internet })[0]
            if (nl) return (nl.type === "wifi" ? (nl.name || Ui.t("settings.wifi")) : Ui.t("settings.netWired")) + (nl.ip ? " · " + nl.ip : "")
            return sett.net.addresses.length ? sett.net.addresses[0].ip : Ui.t("settings.offline")
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
            return vsVersion() + (vsState ? " · " + (vsState.remote ? Ui.t("upd.allCurrent") : vsNoRemote(vsState)) : "")
        case "system": return sett.ssh === undefined ? sett.net.hostname : Ui.t("settings.ssh") + ": " + Ui.t(sett.ssh ? "common.on" : "common.off")
        }
        return ""
    }

    // ---- Updates: VoidStation + Void-Pakete (inkl. Kernel) + Flatpak/AppImages/Proton-GE, alles mit einem Knopf
    // Kein Stand vom Update-Server: offline, noch nicht geprueft oder Server wirklich nicht erreichbar
    function vsNoRemote(v) { return Ui.t(v && v.online === false ? "upd.offline" : v && !v.checked && !v.error ? "upd.searching" : "upd.unreachable") }
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
                                            : Ui.esc(vsState.remote ? Ui.t("upd.current") : vsNoRemote(vsState))
        // Kanal nur nennen, wenn er nicht Stable ist (Testing gibt es seit 2026.11 nur noch auf Wunsch)
        var ch = vsState && vsState.channel === "main" ? " · " + Ui.esc(Ui.t("upd.channel", { channel: chLabel(vsState) })) : ""
        return "VoidStation " + Ui.esc(vsVersion()) + ch + "<br>" + st
    }
    function sysInfo() {
        if (!vsState || !vsState.system) return ""
        var y = vsState.system, sum = sysSummary(vsState)
        var line = sum ? "<b>" + Ui.esc(sum) + "</b>" : Ui.esc(y.checked ? Ui.t("upd.sysCurrent") : Ui.t("upd.sysUnchecked"))
        if (sum && y.due_at && !y.due && !vsState.available)
            line += "<br>" + Ui.esc(Ui.t("upd.sysDueAt", { date: Ui.loc.toString(new Date(y.due_at * 1000), Ui.t("fmt.dateYear", null, "d. MMMM yyyy")) }))
        if (y.error && !(y.pkgs && y.pkgs.length)) line = Ui.esc(Ui.t("upd.sysError"))
        if (y.checking) line += "<br>" + Ui.esc(Ui.t("upd.sysChecking"))
        var rb = vsState.reboot || {}
        if (rb.kernel || rb.voidstation) line += "<br><b>" + Ui.esc(Ui.t(rb.kernel ? "upd.rebootKernel" : "upd.rebootVs")) + "</b>"
        if (rb.kernel_stuck) line += "<br>" + Ui.esc(Ui.t("upd.kernelStuck", { version: rb.kernel_stuck.version, running: rb.kernel_stuck.running }))
        return Ui.esc(Ui.t("upd.system")) + "<br>" + line
    }
    function refreshVs(force, then) {
        Api.get("/api/updates" + (force ? "?force=1" : ""), function (j) { update(function () { vsState = j }); if (then) then() },
                function () { vsState = { local: null, remote: null, available: false, any: false, error: "api" }; if (then) then() })
    }
    // Updates: Der VoidStation-Stand ist in Sekunden da, die Paketpruefung (Paketlisten laden, Flatpak …) laeuft im
    // Hintergrund. Gibt es schon etwas zu zeigen, oeffnet der Dialog sofort und ergaenzt den Systemteil, sobald die
    // Pruefung fertig ist. Sonst wird auf die Pruefung gewartet (hoechstens 3 Minuten).
    property int updSeq: 0
    function updDialogText(v) {
        var parts = []
        if (v.available) {
            var news = (v.changes || []).map(function (e) {
                var tr = Ui.lang === "de" ? null : ((e["changes_" + Ui.lang] || []).length ? e["changes_" + Ui.lang] : e.changes_en)   // Changelog gibt es de + en
                var ch = (tr && tr.length) ? tr : (e.changes || [])
                return e.version + ":\n" + ch.map(function (c) { return "\u2022 " + c }).join("\n")
            }).join("\n\n")
            parts.push(Ui.t("upd.confirmText", { remote: v.remote, local: v.local || "\u2013", channel: chLabel(v) }) + (news ? "\n\n" + Ui.t("upd.news") + "\n" + news : ""))
        }
        var y = v.system, rb = v.reboot || {}
        if (y && y.count) {
            var names = y.pkgs.slice(0, 12).join(", ") + (y.pkgs.length > 12 ? " " + Ui.t("upd.more", { n: Ui.num(y.pkgs.length - 12) }) : "")
            parts.push(Ui.t("upd.system") + ": " + sysSummary(v) + (names ? "\n" + names : "") + (y.checking ? "\n" + Ui.t("upd.sysChecking") : ""))
        } else if (y && y.checking) {
            parts.push(Ui.t("upd.system") + ": " + Ui.t("upd.sysChecking"))
        }
        var restart = v.available || (y && y.kernel) || rb.kernel || rb.voidstation
        parts.push(Ui.t(restart ? "upd.keep" : "upd.keepNoReboot"))
        return parts.join("\n\n")
    }
    function updShow(seq) {
        if (seq !== updSeq) return
        var v = vsState
        if (!v) return app.toast(Ui.t("upd.unreachable"), true)
        if (v.busy) return app.toast(Ui.t("upd.xbpsBusy"), true)
        var rb = v.reboot || {}, y = v.system || {}
        if (!v.any) {
            if (rb.kernel || rb.voidstation) return app.rebootPrompt(rb)
            if (y.checking || (y.error && !v.available)) return app.toast(Ui.t("upd.sysError"), true)   // Pruefung haengt/scheiterte
            if (!v.remote) return app.toast(vsNoRemote(v), true)
            return app.toast(Ui.t("upd.upToDate"))
        }
        app.dialog(Ui.t("upd.confirmTitle"), updDialogText(v), [[Ui.t("upd.now"), function () { app.jobStart("update") }], [Ui.t("common.cancel")]])
        updDlg.seq = seq
        if (y.checking) updWait(seq, function () {
            // Dialog noch offen? Dann den Systemteil mit dem frischen Stand neu schreiben
            if (updDlg.seq === seq && adlg.open && adlg.title === Ui.t("upd.confirmTitle") && vsState) adlg.text = updDialogText(vsState)
        })
    }
    QtObject { id: updDlg; property int seq: -1 }
    function updWait(seq, done) {
        sysPoll.seq = seq; sysPoll.done = done; sysPoll.until = Date.now() + 180000
        sysPoll.restart()
    }
    Timer {
        id: sysPoll
        interval: 1500; repeat: true
        property int seq: 0
        property var done: null
        property real until: 0
        onTriggered: {
            if (seq !== s.updSeq) { stop(); return }
            Api.get("/api/updates", function (j) {
                if (!sysPoll.running || sysPoll.seq !== s.updSeq) return
                if (j) update(function () { vsState = j })
                if (j && j.system && j.system.checking && Date.now() < sysPoll.until) return
                sysPoll.stop()
                var f = sysPoll.done; sysPoll.done = null
                if (f) f()
            }, function () {})
        }
    }
    function runUpdates() {
        if (app.jobBusy) return app.toast(Ui.t("common.busy"))
        var seq = ++updSeq
        toastBox.show(Ui.t("upd.checking"), false, 200000)
        refreshVs(true, function () {
            if (seq !== updSeq) return
            var v = vsState, y = (v && v.system) || {}
            if (v && !v.busy && y.checking && !(v.available || y.count)) {
                // noch nichts Bekanntes zum Zeigen: auf die Paketpruefung warten
                return updWait(seq, function () { toastBox.hide(); updShow(seq) })
            }
            toastBox.hide()
            updShow(seq)
        })
    }
    // Nur noch der Rueckweg zu Stable; Testing waehlt man im Terminal (vsctl channel testing)
    function toStable() {
        Api.post("/api/selfupdate/channel", { channel: "stable" }, function (j) {
            update(function () { vsState = j })
            app.toast(Ui.t("channel.toStableDone"))
        }, fail)
    }
    function setSysDays(d) {
        if (sett.sysupd_days === d) return
        Api.post("/api/settings/sysupd", { days: d }, function (j) { update(function () { vsState = j; var x = sett; x.sysupd_days = d; sett = null; sett = x }) }, fail)
    }

    // ---- Sprache, Anzeige, Design, Ton
    readonly property var oskConf: sett && sett.osk ? sett.osk : ({ choice: "auto", mode: "auto" })
    function setOsk(b) {
        Api.post("/api/settings/osk", b, function (j) { update(function () { sett = j; app.sett = j }) }, fail)
    }
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
    function setResolution(m, rate) {
        var body = { mode: m }
        if (rate) body.rate = rate
        Api.post("/api/settings/resolution", body, function (j) {
            update(function () { sett = j })
            app.toast(rate ? Ui.t("settings.rateToast", { hz: hz(rate) }) : Ui.t("settings.resToast", { mode: m.replace("x", "\u00d7") }))
        }, fail)
    }
    function setMatchRate(on) {
        if (!!sett.match_rate === on) return
        Api.post("/api/settings/matchrate", { on: on }, function (j) {
            update(function () { sett = j })
            app.toast(Ui.t(on ? "settings.matchRateOnToast" : "settings.matchRateOffToast"))
        }, fail)
    }
    function setGameFx(mode) {
        if (!sett.game_fx || sett.game_fx.mode === mode) return
        Api.post("/api/settings/gamefx", { mode: mode }, function (j) {
            update(function () { sett = j })
            if (mode !== "off" && j.game_fx && !j.game_fx.ready) app.toast(Ui.t("settings.gameFxInstall"))
        }, fail)
    }
    function hz(r) { return Ui.num(Math.round(r * 100) / 100, 2) }
    function devLabel(d) {
        switch (d.kind) {
        case "hdmi": return (d.name || Ui.t("audio.tv")) + (d.num ? " " + d.num : "")
        case "analog": return Ui.t("audio.analog")
        case "spdif": return Ui.t("audio.spdif")
        }
        return d.name
    }
    function devTag(d) { return { hdmi: "HDMI", usb: "USB", bt: "Bluetooth" }[d.kind] || "" }
    function devIcon(d) { return { hdmi: "tv", usb: "headphones", bt: "bluetooth" }[d.kind] || "speaker" }
    function fmtLabel(f) { return f.key ? Ui.t(f.key, { ch: f.label }) : f.label }
    function audioPost(path, body, toast) {
        Api.post(path, body, function (j) { update(function () { sett = j }); if (toast) app.toast(toast) }, fail)
    }
    function setDevice(d) { audioPost("/api/audio/device", { key: d.key }, Ui.t("settings.outToast", { name: devLabel(d) })) }
    function setFormat(d, f) {
        if (d.format === f.id) return
        audioPost("/api/audio/format", { key: d.key, format: f.id }, Ui.t("audio.fmtToast", { name: fmtLabel(f) }))
    }
    function setMic(d, on) {
        if (d.mic === on) return
        audioPost("/api/audio/mic", { key: d.key, on: on }, Ui.t(on ? "audio.micOn" : "audio.micOff"))
    }
    function setAudioAuto(on) { audioPost("/api/audio/auto", { on: on }, "") }
    readonly property var sndConf: sett && sett.sounds ? sett.sounds : ({ on: true, volume: 70, preset: "void", presets: ["void", "retro", "minimal"], custom: 0 })
    function setSounds(body, sampleEvent) {
        var nextOn = body.on !== undefined ? !!body.on : !!sndConf.on
        var nextVol = body.volume !== undefined ? body.volume : (sndConf.volume || 70)
        var nextPreset = body.preset !== undefined ? body.preset : (sndConf.preset || "void")
        vs.setSounds(nextOn, nextVol, nextPreset)
        if (nextOn && sampleEvent) vs.playSound(sampleEvent)
        Api.post("/api/settings/sounds", body, function (j) {
            update(function () {
                sett = j; app.sett = j
                if (j && j.sounds) vs.setSounds(!!j.sounds.on, j.sounds.volume || 70, j.sounds.preset || "void")
            })
        }, fail)
    }
    // Aufloesungen ab 1024x576, die mindestens ~50 Hz koennen (4K mit nur 30 Hz ruckelt) – dazu immer die aktuelle
    // und die bevorzugte; hoechstens acht, groesste zuerst (Reihenfolge von xrandr)
    function modes(d) {
        return d.modes.filter(function (m) {
            var p = m.split("x")
            if (parseInt(p[0]) < 1024 || parseInt(p[1]) < 576) return false
            return m === d.current || m === d.preferred || ((d.rates || {})[m] || []).some(function (r) { return r >= 49 })
        }).slice(0, 8)
    }
    // Bildraten der aktuellen Aufloesung ab 23 Hz, hoechste zuerst, ohne Doppelte (xrandr kennt 60.00 oft zweimal)
    function rates(d) {
        var out = []
        ;((d.rates || {})[d.current] || []).forEach(function (r) {
            if (r >= 23 && !out.some(function (x) { return Math.abs(x - r) < 0.005 })) out.push(r)
        })
        return out.sort(function (a, b) { return b - a })
    }

    // ---- Netzwerk, Bluetooth, System
    function wifiScan() {
        app.toast(Ui.t("wifi.scanning"))
        Api.get("/api/wifi/scan", function (j) { toastBox.hide(); update(function () { wifiList = j || [] }) },
                function (e) { app.toast(Ui.t("wifi.scanFailed", { msg: e }), true) })
    }
    // Internet nur ueber Kabel, nur ueber WLAN oder ueber beides
    function netModeLabel(m) { return Ui.t(m === "wifi" ? "settings.netWifiPick" : m === "wired" ? "settings.netWiredPick" : "settings.netBothPick") }
    function netPrefer(mode) {
        if (sett && sett.net && sett.net.mode === mode) return
        app.toast(Ui.t("settings.netSwitching"))
        Api.post("/api/net/prefer", { mode: mode }, function (j) {
            update(function () { sett = j })
            app.toast(Ui.t("settings.netPreferDone", { what: netModeLabel(mode) }))
        }, function (e) { app.toast(Ui.t("common.failedMsg", { msg: e }), true) })
    }
    function netLines() {
        var n = sett.net, out = [Ui.esc(Ui.t("settings.hostname")) + ": <b>" + Ui.esc(n.hostname) + "</b>"]
        var ls = (n.links || []).filter(function (x) { return x.connected })
        if (!ls.length && n.addresses.length) return out.concat(n.addresses.map(function (x) { return Ui.esc(x.iface) + ": <b>" + Ui.esc(x.ip) + "</b>" })).join("<br>")
        if (!ls.length) return out.concat([Ui.esc(Ui.t("settings.noConn"))]).join("<br>")
        ls.forEach(function (x) {
            var what = x.type === "wifi" ? Ui.t("settings.netWifiLine", { ssid: x.name || x.dev }) : Ui.t("settings.netWired")
            out.push((x.internet ? "\u2713 " : "") + "<b>" + Ui.esc(what) + "</b>" + (x.ip ? " · " + Ui.esc(x.ip) : "")
                     + (x.internet ? " <font color='" + Ui.c.textFaint + "'>· " + Ui.esc(Ui.t("settings.netViaThis")) + "</font>" : ""))
        })
        return out.join("<br>")
    }
    function netLink(kind) {
        var ls = sett && sett.net && sett.net.links ? sett.net.links : []
        for (var i = 0; i < ls.length; i++) if (ls[i].type === kind && (ls[i].connected || ls[i].ready)) return ls[i]
        return null
    }
    function wifiOn() { var l = netLink("wifi"); return l && l.connected ? l : null }
    function wifiDisconnect() {
        var l = wifiOn(), name = l ? (l.name || l.dev) : ""
        Api.post("/api/net/disconnect", { type: "wifi" }, function (j) {
            update(function () {
                sett = j
                if (wifiList) wifiList = wifiList.map(function (w) { return Object.assign({}, w, { active: false }) })
            })
            app.toast(Ui.t("settings.netDisconnected", { ssid: name }))
            Qt.callLater(function () { refocus("scan") })
        }, function (e) { app.toast(Ui.t("common.failedMsg", { msg: e }), true) })
    }
    function wiredToggle(on) {
        app.toast(Ui.t("settings.netSwitching"))
        Api.post(on ? "/api/net/connect" : "/api/net/disconnect", { type: "wired" }, function (j) {
            update(function () { sett = j })
            app.toast(Ui.t(on ? "settings.netWiredOnDone" : "settings.netWiredOffDone"))
            Qt.callLater(function () { refocus(on ? "wiredoff" : "wiredon") })
        }, function (e) { app.toast(Ui.t("common.failedMsg", { msg: e }), true) })
    }
    function wifiAsk(net) {
        wifiPw.value = ""
        wifiPw.password = true
        wifiPick = net
        Qt.callLater(function () { app.setFocus(wifiPw, true); app.openOsk(wifiPw) })
    }
    function wifiConnect(ssid, pw) {
        app.toast(Ui.t("wifi.connecting", { ssid: ssid }))
        Api.post("/api/wifi/connect", { ssid: ssid, password: pw }, function (j) {
            wifiPick = null
            update(function () {
                sett = j
                // Liste gleich mitziehen: das neue Netz ist jetzt das aktive
                if (wifiList) wifiList = wifiList.map(function (w) { return Object.assign({}, w, { active: w.ssid === ssid, known: w.known || w.ssid === ssid }) })
            })
            app.toast(Ui.t("wifi.connected", { ssid: ssid }))
            Qt.callLater(function () { refocus("scan") })
        }, function (e) {
            // Bekannte Fehler kommen als Schluessel "wifi.err.*", alles andere als Klartext
            app.toast(e.indexOf("wifi.err.") === 0 ? Ui.t(e, { ssid: ssid }) : Ui.t("wifi.failed", { msg: e }), true)
            // Auch wenn das gespeicherte Passwort nicht mehr passt: jetzt erst danach fragen
            if (e === "wifi.err.password") wifiAsk(wifiPick || { ssid: ssid })
        })
    }
    function btCall(path, body, busy, ok, okErr) {
        if (busy) app.toast(busy)
        Api.post(path, body, function (r) {
            btPairPoll.stop()
            update(function () { bt = r && r.status && r.status.available !== undefined ? r.status : (r && r.available !== undefined ? r : bt) })
            if (!ok) return
            var bad = !!(r && r.ok === false && okErr)
            app.toast(bad && r.error ? Ui.t(r.error) : bad ? okErr : ok, bad)   // Fehler mit Ursache (bt.err.*)
        }, function (e) { btPairPoll.stop(); fail(e) })
    }
    function btPair(mac) {
        btPairPoll.t0 = Date.now(); btPairPoll.shown = ""; btPairPoll.start()
        btCall("/api/bluetooth/pair", { mac: mac }, Ui.t("bt.pairing"), Ui.t("bt.pairedToast"), Ui.t("bt.pairFailed"))
    }
    function btExtra(d) {                       // " · Controller · 80 % · Verbunden"
        var p = []
        if (d.kind && d.kind !== "other") p.push(Ui.t("bt.kind." + d.kind))
        if (d.battery !== null && d.battery !== undefined) p.push(Ui.num(d.battery) + " %")
        if (d.connected) p.push(Ui.t("bt.connected"))
        else if (d.paired) p.push(Ui.t("bt.paired"))
        return p.length ? " · " + Ui.esc(p.join(" · ")) : ""
    }
    function btKey(mac) { return mac.replace(/[^A-Za-z0-9]/g, "") }
    function btRenameStart(d) {
        btName.value = d.name || ""
        btRename = d
        Qt.callLater(function () { app.setFocus(btName, true); app.openOsk(btName) })
    }
    function btRenameEnd() {
        var k = btRename ? "btmv" + btKey(btRename.mac) : "btscan"
        btRename = null
        Qt.callLater(function () { refocus(k) })
    }
    // Leerer Name oder der Name, den das Geraet selbst meldet = eigenen Namen wieder entfernen
    function btDoRename(name) {
        var d = btRename
        if (!d) return
        var n = (name || "").replace(/\s+/g, " ").trim()
        if (n === (d.orig || "")) n = ""
        if (n === "" && !d.custom) return btRenameEnd()                 // nichts zu tun
        btRenameEnd()
        btCall("/api/bluetooth/rename", { mac: d.mac, name: n }, "",
               Ui.t(n ? "bt.renamedToast" : "bt.nameResetToast", { name: n || d.orig || d.mac }), Ui.t("bt.renameFailed"))
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
            if (!b.scanning || Date.now() - btPoll.t0 > 35000) { btPoll.stop(); s.btScanning = false }
        }, function () { btPoll.stop(); s.btScanning = false })
    }
    // Waehrend des Koppelns: verlangt eine Tastatur einen Code, steht er unten rechts, bis die Kopplung durch ist
    Timer {
        id: btPairPoll; interval: 1000; repeat: true
        property real t0: 0
        property string shown: ""
        onTriggered: Api.get("/api/bluetooth/status", function (b) {
            if (b.prompt && b.prompt.code && b.prompt.code !== btPairPoll.shown) {
                btPairPoll.shown = b.prompt.code
                toastBox.show(Ui.t("bt.typeCode", { code: b.prompt.code }), false, 60000)
            }
            if (Date.now() - btPairPoll.t0 > 150000) btPairPoll.stop()   // sonst beendet btCall die Abfrage
        }, function () { btPairPoll.stop() })
    }
    function setPadMouse(on) {
        if (!!sett.padmouse === on) return
        Api.post("/api/settings/padmouse", { on: on }, function (j) {
            update(function () { sett = j })
            app.toast(Ui.t(on ? "settings.padMouseOnToast" : "settings.padMouseOffToast"))
        }, fail)
    }
    function setSsh(on) {
        if (!!sett.ssh === on) return
        app.toast(Ui.t(on ? "settings.sshTurningOn" : "settings.sshTurningOff"))
        Api.post("/api/settings/ssh", { on: on }, function (r) {
            update(function () { var x = sett; x.ssh = r.ssh; sett = null; sett = x })
            app.toast(r.ssh ? Ui.t("settings.sshOn", { host: s.ip || sett.net.hostname }) : Ui.t("settings.sshOff"))
        }, fail)
    }

    // Fehlerbericht: Version, Hardware, Protokolle nach share/vs-reports (vsreport.py), ohne Passwoerter und WLAN-Daten.
    // Danach Dialog mit Dateiname; "Inhalt ansehen" zeigt alles ausser den Protokollen und listet diese auf.
    property bool reportBusy: false
    function makeReport() {
        if (reportBusy) return
        reportBusy = true
        toastBox.show(Ui.t("report.busy"), false, 120000)
        Api.post("/api/report", {}, function (r) {
            reportBusy = false
            toastBox.hide()
            app.dialog(Ui.t("report.doneTitle"),
                       Ui.t("report.doneText", { path: "share/vs-reports/" + r.name, size: Ui.num(Math.max(1, Math.round(r.size / 1024))) + " KB" }),
                       [[Ui.t("report.show"), function () { Qt.callLater(function () { showReport(r) }) }], [Ui.t("common.close")]])
        }, function (e) {
            reportBusy = false
            toastBox.hide()
            if (e === "busy") app.toast(Ui.t("common.busy"))
            else fail(e)
        })
    }
    function showReport(r) {
        var logs = (r.logs || []).map(function (l) { return "\u2022 " + l.name + " \u2013 " + Ui.t("report.lines", { n: Ui.num(l.lines) }) }).join("\n")
        app.dialog(Ui.t("report.contentTitle"), r.overview + (logs ? "\n\n" + Ui.t("report.logs") + "\n" + logs : ""), [[Ui.t("common.close")]])
    }

    // ---- Konten & Profile
    readonly property bool isAdminAccount: !!(acctSession && acctSession.role === "admin" && !acctSession.is_guest)
    readonly property var childAccounts: (acctList || []).filter(function (a) { return a.role === "child" && a.active !== false })
    readonly property var curParentalPolicy: parentalChildId && parentalPolicies[parentalChildId] ? parentalPolicies[parentalChildId] : null
    readonly property var curParentalStatus: parentalChildId && parentalStatuses[parentalChildId] ? parentalStatuses[parentalChildId] : null
    readonly property var bedtimePresets: [
        { start: "", end: "", label: "" },
        { start: "19:00", end: "07:00", label: "19:00–07:00" },
        { start: "20:00", end: "07:00", label: "20:00–07:00" },
        { start: "21:00", end: "07:00", label: "21:00–07:00" },
        { start: "22:00", end: "08:00", label: "22:00–08:00" }
    ]
    readonly property var activeAccountObj: {
        if (!acctSession || acctSession.is_guest) return null
        for (var i = 0; i < (acctList || []).length; i++)
            if (acctList[i].id === acctSession.account_id) return acctList[i]
        return null
    }
    function loadAccounts() {
        if (sett && sett.live) return
        Api.get("/api/accounts", function (r) {
            update(function () {
                acctList = r.accounts || []
                acctSession = r.session || null
                acctPolicy = r.device_policy || null
                if (r.session) app.session = r.session
                if (r.device_policy) app.devicePolicy = r.device_policy
                app.accountsList = acctList
                app.accountsCount = acctList.length
            })
            if (r.session && r.session.role === "admin" && !r.session.is_guest) loadParental()
        }, function () {})
    }
    function loadParental() {
        Api.get("/api/accounts/parental", function (r) {
            update(function () {
                parentalPolicies = r.policies || ({})
                parentalStatuses = r.statuses || ({})
                parentalTiles = r.tiles || []
                parentalCats = r.categories || []
                var children = childAccounts
                var hasCur = children.some(function (c) { return c.id === parentalChildId })
                if (!hasCur) parentalChildId = children.length ? children[0].id : ""
            })
        }, function () {})
    }
    function saveParental(patch) {
        if (!curParentalPolicy || !parentalChildId) return
        var nextPol = Object.assign({}, curParentalPolicy, patch)
        Api.post("/api/accounts/parental", { account_id: parentalChildId, policy: nextPol }, function (r) {
            update(function () {
                var pm = Object.assign({}, parentalPolicies)
                if (r.policy) pm[parentalChildId] = r.policy
                parentalPolicies = pm
                var sm = Object.assign({}, parentalStatuses)
                if (r.status) sm[parentalChildId] = r.status
                parentalStatuses = sm
            })
            app.toast(Ui.t("parental.saved"))
        }, fail)
    }
    function toggleParentalList(field, item) {
        if (!curParentalPolicy) return
        var cur = (curParentalPolicy[field] || []).slice()
        var idx = cur.indexOf(item)
        if (idx >= 0) cur.splice(idx, 1)
        else cur.push(item)
        var patch = {}
        patch[field] = cur
        saveParental(patch)
    }
    function parentalHas(field, item) {
        if (!curParentalPolicy) return false
        var arr = curParentalPolicy[field] || []
        return arr.indexOf(item) >= 0
    }
    function parentalUsageText(st, pol) {
        if (!pol) return ""
        var u = st && st.usage ? st.usage : ({ used_seconds: 0, bonus_seconds: 0, remaining_seconds: null, in_bedtime: false })
        var usedMin = Math.floor((u.used_seconds || 0) / 60)
        var parts = []
        if (pol.daily_limit_min > 0) {
            var limMin = pol.daily_limit_min + Math.floor((u.bonus_seconds || 0) / 60)
            parts.push(Ui.t("parental.usageLine", { used: usedMin, limit: limMin }))
            if (u.remaining_seconds !== null && u.remaining_seconds !== undefined)
                parts.push(Ui.t("parental.usageRemaining", { remaining: Math.max(0, Math.ceil(u.remaining_seconds / 60)) }))
        } else {
            parts.push(Ui.t("parental.usageNoLimit", { used: usedMin }))
        }
        if (u.in_bedtime) parts.push("<b>" + Ui.esc(Ui.t("parental.usageBedtimeActive")) + "</b>")
        return parts.join(" · ")
    }
    function acctAuthText(a) {
        if (!a) return Ui.t("account.noAuth")
        var p = []
        if (a.has_pin) p.push(Ui.t("account.pin"))
        if (a.has_password) p.push(Ui.t("account.password"))
        return p.length ? p.join(" + ") : Ui.t("account.noAuth")
    }
    function setDevicePolicy(patch) {
        Api.post("/api/accounts/device-policy", patch, function (r) {
            update(function () {
                if (r.device_policy) { acctPolicy = r.device_policy; app.devicePolicy = r.device_policy }
                if (r.session) { acctSession = r.session; app.session = r.session }
            })
            app.toast(Ui.t("account.policySaved"))
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
                                text: { app.volText; app.updInfo; s.vsState; s.bt; Ui.lang; vs.themeName; s.acctSession; app.session; return s.catSub(modelData.id) }
                                font.pixelSize: uu * 0.085
                                font.weight: sub.warn ? Font.DemiBold : Font.Normal
                                color: sub.warn ? Ui.c.tileText : Ui.c.tileSub
                            }
                        }
                    }
                }
            }
        }
        // Konten & Profile
        SetGroup {
            visible: s.cat === "accounts"; availH: s.colH; title: Ui.t("account.currentProfile")
            Info {
                html: !s.acctSession ? ""
                    : "<b>" + Ui.esc(s.acctSession.display_name) + "</b> · " + Ui.esc(Ui.t("account.role." + s.acctSession.role))
                      + (s.acctSession.is_guest ? "" : "<br>" + Ui.esc(s.acctAuthText(s.activeAccountObj)))
            }
            SetRow {
                Pill { property string key: "accsw"; iconName: "user"; text: Ui.t("account.switch"); onTriggered: app.openAccountPicker() }
                Pill { property string key: "acclk"; iconName: "lock"; text: Ui.t("account.lock"); onTriggered: app.lockProfile() }
                Pill {
                    property string key: "acced"
                    visible: !!s.activeAccountObj && !!s.acctSession && !s.acctSession.is_guest && s.acctSession.role !== "child"
                    text: Ui.t("account.editOwn")
                    onTriggered: app.openAccountEdit(s.activeAccountObj, function () { s.loadAccounts() })
                }
            }
            Info { visible: !!s.acctSession && !s.isAdminAccount; html: Ui.esc(Ui.t("account.adminOnlyHint")) }
        }
        SetGroup {
            visible: s.cat === "accounts" && s.isAdminAccount; availH: s.colH; title: Ui.t("account.manageList")
            SetRow {
                Pill {
                    property string key: "accnew"
                    iconName: "plus"
                    text: Ui.t("account.add")
                    onTriggered: app.openAccountEdit(null, function () { s.loadAccounts() })
                }
            }
            SetRow {
                Repeater {
                    model: s.acctList || []
                    Pill {
                        property string key: "acc_" + modelData.id
                        iconName: modelData.avatar || "user"
                        rich: true
                        maxWidth: Ui.screenW * 0.4
                        on: !!s.acctSession && !s.acctSession.is_guest && s.acctSession.account_id === modelData.id
                        text: Ui.esc(modelData.display_name) + " <font color='" + Ui.c.textFaint + "'>· "
                            + Ui.esc(Ui.t("account.role." + modelData.role)) + " · "
                            + Ui.esc(s.acctAuthText(modelData)) + "</font>"
                        onTriggered: app.openAccountEdit(modelData, function () { s.loadAccounts() })
                    }
                }
            }
        }
        SetGroup {
            visible: s.cat === "accounts" && s.isAdminAccount && !!s.acctPolicy; availH: s.colH; title: Ui.t("account.deviceSettings")
            SetRow {
                label: Ui.t("account.askOnBoot")
                Repeater {
                    model: [true, false]
                    Pill {
                        property string key: "accboot" + modelData
                        text: Ui.t(modelData ? "common.on" : "common.off")
                        on: !!s.acctPolicy && !!s.acctPolicy.ask_on_boot === modelData
                        sound: "toggle"
                        onTriggered: s.setDevicePolicy({ ask_on_boot: modelData })
                    }
                }
            }
            Info { html: Ui.esc(Ui.t("account.askOnBootHint")) }
            SetRow {
                label: Ui.t("account.guestMode")
                Repeater {
                    model: [true, false]
                    Pill {
                        property string key: "accguest" + modelData
                        text: Ui.t(modelData ? "common.on" : "common.off")
                        on: !!s.acctPolicy && !!s.acctPolicy.guest_enabled === modelData
                        sound: "toggle"
                        onTriggered: s.setDevicePolicy({ guest_enabled: modelData })
                    }
                }
            }
            Info { html: Ui.esc(Ui.t("account.guestModeHint")) }
            SetRow {
                visible: (s.acctList || []).length > 1
                label: Ui.t("account.defaultAccount")
                Repeater {
                    model: s.acctList || []
                    Pill {
                        property string key: "accdef_" + modelData.id
                        text: modelData.display_name
                        on: !!s.acctPolicy && s.acctPolicy.default_account_id === modelData.id
                        sound: "toggle"
                        onTriggered: s.setDevicePolicy({ default_account_id: modelData.id })
                    }
                }
            }
        }
        SetGroup {
            visible: s.cat === "accounts" && s.isAdminAccount; availH: s.colH; title: Ui.t("parental.title")
            Info { visible: s.childAccounts.length === 0; html: Ui.esc(Ui.t("parental.noChildHint")) }
            SetRow {
                visible: s.childAccounts.length > 0
                label: Ui.t("parental.child")
                Repeater {
                    model: s.childAccounts
                    Pill {
                        property string key: "pchild_" + modelData.id
                        iconName: modelData.avatar || "user"
                        text: modelData.display_name
                        on: s.parentalChildId === modelData.id
                        sound: "toggle"
                        onTriggered: s.parentalChildId = modelData.id
                    }
                }
            }
            Info {
                visible: s.childAccounts.length > 0 && !!s.curParentalPolicy
                html: s.parentalUsageText(s.curParentalStatus, s.curParentalPolicy)
            }
            SetRow {
                visible: !!s.curParentalPolicy
                label: Ui.t("parental.mode")
                Repeater {
                    model: ["allowlist", "denylist"]
                    Pill {
                        property string key: "pmode_" + modelData
                        text: Ui.t("parental.mode." + modelData)
                        on: !!s.curParentalPolicy && s.curParentalPolicy.mode === modelData
                        sound: "toggle"
                        onTriggered: s.saveParental({ mode: modelData })
                    }
                }
            }
            SetRow {
                visible: !!s.curParentalPolicy
                label: Ui.t("parental.maxAge")
                Repeater {
                    model: [0, 6, 12, 16, 18]
                    Pill {
                        property string key: "page_" + modelData
                        text: Ui.t("parental.ageVal", { age: modelData })
                        on: !!s.curParentalPolicy && s.curParentalPolicy.max_age_rating === modelData
                        sound: "toggle"
                        onTriggered: s.saveParental({ max_age_rating: modelData })
                    }
                }
            }
            SetRow {
                visible: !!s.curParentalPolicy
                label: Ui.t("parental.dailyLimit")
                Repeater {
                    model: [0, 30, 60, 90, 120, 180]
                    Pill {
                        property string key: "plim_" + modelData
                        text: modelData === 0 ? Ui.t("parental.limitOff") : Ui.t("parental.minutesVal", { min: modelData })
                        on: !!s.curParentalPolicy && s.curParentalPolicy.daily_limit_min === modelData
                        sound: "toggle"
                        onTriggered: s.saveParental({ daily_limit_min: modelData })
                    }
                }
            }
            SetRow {
                visible: !!s.curParentalPolicy
                label: Ui.t("parental.bedtime")
                Repeater {
                    model: s.bedtimePresets
                    Pill {
                        property string key: "pbed_" + (modelData.start || "off")
                        text: modelData.start ? modelData.label : Ui.t("parental.bedtimeOff")
                        on: !!s.curParentalPolicy && (s.curParentalPolicy.bedtime_start || "") === modelData.start && (s.curParentalPolicy.bedtime_end || "") === modelData.end
                        sound: "toggle"
                        onTriggered: s.saveParental({ bedtime_start: modelData.start, bedtime_end: modelData.end })
                    }
                }
            }
            SetRow {
                visible: !!s.curParentalPolicy
                label: Ui.t("parental.options")
                Pill {
                    property string key: "pbrowser"
                    text: Ui.t("parental.allowBrowser")
                    on: !!s.curParentalPolicy && !!s.curParentalPolicy.allow_browser
                    sound: "toggle"
                    onTriggered: s.saveParental({ allow_browser: !s.curParentalPolicy.allow_browser })
                }
                Pill {
                    property string key: "pytsearch"
                    text: Ui.t("parental.allowYtSearch")
                    on: !!s.curParentalPolicy && !!s.curParentalPolicy.allow_yt_search
                    sound: "toggle"
                    onTriggered: s.saveParental({ allow_yt_search: !s.curParentalPolicy.allow_yt_search })
                }
                Pill {
                    property string key: "ppower"
                    text: Ui.t("parental.allowPowerMenu")
                    on: !!s.curParentalPolicy && !!s.curParentalPolicy.allow_power_menu
                    sound: "toggle"
                    onTriggered: s.saveParental({ allow_power_menu: !s.curParentalPolicy.allow_power_menu })
                }
            }
        }
        SetGroup {
            visible: s.cat === "accounts" && s.isAdminAccount && s.childAccounts.length > 0 && !!s.curParentalPolicy; availH: s.colH; title: Ui.t("parental.appsTitle")
            SetRow {
                label: Ui.t("parental.blockedCats")
                Repeater {
                    model: s.parentalCats || []
                    Pill {
                        property string key: "pcat_" + modelData
                        text: Ui.l(modelData)
                        on: s.parentalHas("blocked_cats", modelData)
                        sound: "toggle"
                        onTriggered: s.toggleParentalList("blocked_cats", modelData)
                    }
                }
            }
            SetRow {
                label: Ui.t(s.curParentalPolicy && s.curParentalPolicy.mode === "allowlist" ? "parental.allowedTiles" : "parental.blockedTiles")
                Repeater {
                    model: s.parentalTiles || []
                    Pill {
                        property string key: "ptile_" + modelData.id
                        property string listField: s.curParentalPolicy && s.curParentalPolicy.mode === "allowlist" ? "allowed_tiles" : "blocked_tiles"
                        text: Ui.l(modelData.label)
                        on: s.parentalHas(listField, modelData.id)
                        sound: "toggle"
                        onTriggered: s.toggleParentalList(listField, modelData.id)
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
                    Pill { property string key: "lang" + modelData.id; text: modelData.label; on: modelData.id === Ui.lang; sound: "toggle"; maxWidth: Ui.screenW * 0.4; onTriggered: s.setLang(modelData.id) }
                }
            }
        }
        SetGroup {
            visible: s.cat === "lang"; availH: s.colH; title: Ui.t("settings.osk")
            SetRow {
                label: Ui.t("settings.oskMode")
                Repeater {
                    model: ["auto", "always", "keyboard"]
                    Pill { property string key: "oskm" + modelData; text: Ui.t("settings.oskMode." + modelData); on: (s.oskConf.mode || "auto") === modelData; sound: "toggle"
                           maxWidth: Ui.screenW * 0.4; onTriggered: s.setOsk({ mode: modelData }) }
                }
            }
            SetRow {
                label: Ui.t("settings.oskLayout")
                Pill {
                    property string key: "oskauto"
                    text: Ui.t("settings.oskAuto", { name: Ui.t("inst.kb." + OskLayouts.forLang(Ui.lang), null, OskLayouts.forLang(Ui.lang)) })
                    on: s.oskConf.choice === "auto"; sound: "toggle"; maxWidth: Ui.screenW * 0.4
                    onTriggered: s.setOsk({ layout: "auto" })
                }
                Repeater {
                    model: OskLayouts.LIST
                    Pill { property string key: "osk" + modelData; text: Ui.t("inst.kb." + modelData, null, modelData); on: s.oskConf.choice === modelData; sound: "toggle"
                           maxWidth: Ui.screenW * 0.4; onTriggered: s.setOsk({ layout: modelData }) }
                }
            }
        }
        // Anzeige
        SetGroup {
            visible: s.cat === "display"; availH: s.colH; title: Ui.t("settings.scale")
            SetRow {
                Repeater {
                    model: s.sett ? s.sett.scales : []
                    Pill { property string key: "scale" + modelData; text: Ui.num(modelData) + "\u00d7"; on: Math.abs(modelData - Ui.scale) < 0.01; sound: "toggle"; onTriggered: s.setScale(modelData) }
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
                            sound: "toggle"
                            maxWidth: Ui.screenW * 0.4
                            onTriggered: s.setResolution(modelData)
                        }
                    }
                }
            }
        }
        // Bildrate je Ausgang: Automatisch (~60 Hz) oder fest, z. B. 50 Hz fuer Fernsehen aus Europa
        Repeater {
            model: s.cat === "display" && s.sett ? (s.sett.displays || []).filter(function (d) { return s.rates(d).length > 1 }) : []
            SetGroup {
                property var d: modelData
                availH: s.colH; title: Ui.t("settings.rate", { name: modelData.name })
                SetRow {
                    Pill {
                        property string key: "rateauto" + d.name
                        text: Ui.t("settings.rateAuto") + (!s.sett.rate && d.rate ? " · " + s.hz(d.rate) + " Hz" : "")
                        on: !s.sett.rate
                        sound: "toggle"
                        onTriggered: s.setResolution(d.current)
                    }
                    Repeater {
                        model: s.rates(d)
                        Pill {
                            property string key: "rate" + d.name + modelData
                            text: s.hz(modelData) + " Hz"
                            on: !!s.sett.rate && Math.abs(modelData - s.sett.rate) < 0.005
                            sound: "toggle"
                            onTriggered: s.setResolution(d.current, modelData)
                        }
                    }
                }
            }
        }
        SetGroup {
            visible: s.cat === "display" && !!s.sett && s.sett.match_rate !== undefined; availH: s.colH; title: Ui.t("settings.matchRate")
            SetRow {
                Repeater {
                    model: [true, false]
                    Pill { property string key: "mr" + modelData; text: Ui.t(modelData ? "common.on" : "common.off"); on: !!s.sett && !!s.sett.match_rate === modelData; sound: "toggle"; onTriggered: s.setMatchRate(modelData) }
                }
            }
            Info { html: Ui.esc(Ui.t("settings.matchRateHint")) }
        }
        SetGroup {
            visible: s.cat === "display" && !!s.sett && !!s.sett.game_fx; availH: s.colH; title: Ui.t("settings.gameFx")
            SetRow {
                Repeater {
                    model: ["off", "cas", "smaa"]
                    Pill {
                        property string key: "gfx" + modelData
                        text: Ui.t(modelData === "off" ? "common.off" : "settings.gameFx." + modelData)
                        on: !!s.sett && !!s.sett.game_fx && s.sett.game_fx.mode === modelData
                        sound: "toggle"
                        maxWidth: Ui.screenW * 0.4
                        onTriggered: s.setGameFx(modelData)
                    }
                }
            }
            Info {
                visible: !!s.sett && !!s.sett.game_fx && s.sett.game_fx.mode !== "off" && !s.sett.game_fx.ready
                html: Ui.esc(Ui.t(!!s.sett && !!s.sett.game_fx && s.sett.game_fx.failed ? "settings.gameFxFailed" : "settings.gameFxInstall"))
            }
        }
        // Design
        SetGroup {
            visible: s.cat === "design"; availH: s.colH; title: Ui.t("settings.colors")
            SetRow {
                Repeater {
                    model: s.sett ? (s.sett.themes || []) : []
                    Pill { property string key: "th" + modelData; text: Ui.t("theme." + modelData, null, modelData); on: modelData === vs.themeName; sound: "toggle"; maxWidth: Ui.screenW * 0.4; onTriggered: s.setTheme(modelData) }
                }
            }
        }
        SetGroup {
            visible: s.cat === "design" && !!s.sett && !!s.sett.cursor; availH: s.colH; title: Ui.t("settings.cursor")
            SetRow {
                label: Ui.t("settings.cursorStyle")
                Repeater {
                    model: s.sett && s.sett.cursor ? s.sett.cursor.themes : []
                    Pill { property string key: "ct" + modelData.id; text: Ui.l(modelData.label); on: modelData.id === s.sett.cursor.theme; sound: "toggle"; onTriggered: s.setCursor({ theme: modelData.id }) }
                }
            }
            SetRow {
                label: Ui.t("settings.cursorSize")
                Repeater {
                    model: s.sett && s.sett.cursor ? s.sett.cursor.sizes : []
                    Pill { property string key: "cs" + modelData; text: String(modelData); on: modelData === s.sett.cursor.size; sound: "toggle"; onTriggered: s.setCursor({ size: modelData }) }
                }
            }
        }
        // Ton: erst das Geraet, darunter Format und Mikrofon des aktiven Geraets
        SetGroup {
            visible: s.cat === "audio"; availH: s.colH; title: Ui.t("settings.audioOut")
            Info { visible: !!s.sett && !(s.sett.audio && s.sett.audio.ok); html: Ui.esc(Ui.t("settings.noAudio")) }
            Info { visible: !!s.sett && !!s.sett.audio && s.sett.audio.ok && !s.audioDevs.length; html: Ui.esc(Ui.t("audio.none")) }
            SetRow {
                Repeater {
                    model: s.audioDevs
                    Pill {
                        property string key: "dev" + modelData.key
                        iconName: s.devIcon(modelData)
                        rich: true
                        maxWidth: Ui.screenW * 0.4
                        text: Ui.esc(s.devLabel(modelData)) + (s.devTag(modelData) ? "<font color='" + Ui.c.textFaint + "'> · " + s.devTag(modelData) + "</font>" : "")
                        on: modelData.active
                        sound: "toggle"
                        onTriggered: s.setDevice(modelData)
                    }
                }
            }
            SetRow {
                visible: !!s.audioDev && s.audioDev.formats.length > 1
                label: Ui.t("audio.format")
                Repeater {
                    model: s.audioDev ? s.audioDev.formats : []
                    Pill { property string key: "fmt" + modelData.id; text: s.fmtLabel(modelData); on: s.audioDev.format === modelData.id; sound: "toggle"; onTriggered: s.setFormat(s.audioDev, modelData) }
                }
            }
            Info { visible: !!s.audioDev && s.audioDev.kind === "hdmi" && s.audioDev.formats.length > 1; html: Ui.esc(Ui.t("audio.fmtHintTv")) }
            SetRow {
                visible: !!s.audioDev && s.audioDev.micAvail
                label: Ui.t(s.audioDev && ["hdmi", "analog", "spdif", "other"].indexOf(s.audioDev.kind) >= 0 ? "audio.micJack" : "audio.mic")
                Repeater {
                    model: [true, false]
                    Pill { property string key: "mic" + modelData; text: Ui.t(modelData ? "common.on" : "common.off"); on: !!s.audioDev && s.audioDev.mic === modelData; sound: "toggle"; onTriggered: s.setMic(s.audioDev, modelData) }
                }
            }
            Info { visible: !!s.audioDev && s.audioDev.kind === "bt" && s.audioDev.micAvail; html: Ui.esc(Ui.t("audio.micBt")) }
        }
        SetGroup {
            visible: s.cat === "audio"; availH: s.colH; title: Ui.t("settings.volume")
            Flow { width: Ui.screenW * 0.4; spacing: 8 * Ui.f; VolBar { showMute: true } }
            SetRow {
                visible: !!s.sett && !!s.sett.audio && s.sett.audio.ok
                label: Ui.t("audio.auto")
                Repeater {
                    model: [true, false]
                    Pill { property string key: "aa" + modelData; text: Ui.t(modelData ? "common.on" : "common.off"); on: !!s.sett && !!s.sett.audio && !!s.sett.audio.auto === modelData; sound: "toggle"; onTriggered: s.setAudioAuto(modelData) }
                }
            }
            Info { visible: !!s.sett && !!s.sett.audio && s.sett.audio.ok; html: Ui.esc(Ui.t("audio.autoHint")) }
            SetRow {
                label: Ui.t("audio.sounds")
                Repeater {
                    model: [true, false]
                    Pill {
                        property string key: "snd" + modelData
                        text: Ui.t(modelData ? "common.on" : "common.off")
                        on: !!s.sndConf.on === modelData
                        sound: ""
                        onTriggered: if (!!s.sndConf.on !== modelData) s.setSounds({ on: modelData }, modelData ? "toggle" : "")
                    }
                }
            }
            SetRow {
                visible: !!s.sndConf.on
                label: Ui.t("audio.soundsPreset")
                Repeater {
                    model: s.sndConf.presets || ["void", "retro", "minimal"]
                    Pill {
                        property string key: "sndp" + modelData
                        text: Ui.t("audio.soundsPreset." + modelData, null, modelData)
                        on: s.sndConf.preset === modelData
                        sound: ""
                        onTriggered: s.setSounds({ preset: modelData }, "select")
                    }
                }
            }
            SetRow {
                visible: !!s.sndConf.on
                label: Ui.t("audio.soundsVol")
                SliderBar {
                    minusKey: "sndm"
                    plusKey: "sndpl"
                    value: s.sndConf.volume || 70
                    minVal: 1
                    maxVal: 100
                    step: 5
                    onPreview: function (v) { vs.setSounds(true, v, s.sndConf.preset || "void"); vs.playSound("volume") }
                    onCommitted: function (v) { s.setSounds({ volume: v }, "volume") }
                }
            }
            Info {
                visible: s.sndConf.custom > 0
                html: Ui.esc(Ui.t(s.sndConf.custom === 1 ? "audio.soundsCustomOne" : "audio.soundsCustomMany", { n: Ui.num(s.sndConf.custom) }))
            }
        }
        // Netzwerk
        SetGroup {
            visible: s.cat === "net"; availH: s.colH; title: Ui.t("settings.connection")
            Info { html: !s.sett ? "" : s.netLines() }
            // Nur mit Kabel- UND WLAN-Anschluss: nur Kabel, nur WLAN oder beides
            SetRow {
                visible: !!s.sett && !!s.sett.net.has_wired && !!s.sett.net.has_wifi
                label: Ui.t("settings.netPrefer")
                Repeater {
                    model: ["wired", "wifi", "both"]
                    Pill { property string key: "np" + modelData; text: s.netModeLabel(modelData)
                           on: !!s.sett && s.sett.net.mode === modelData; sound: "toggle"; onTriggered: s.netPrefer(modelData) }
                }
            }
            // Kabel per Klick trennen und wieder verbinden (ohne eingestecktes Kabel keine Anzeige)
            SetRow {
                visible: !!s.netLink("wired") && !!s.sett && s.sett.net.mode !== "wifi"
                Pill { property string key: "wiredoff"; visible: !!s.netLink("wired") && s.netLink("wired").connected
                       text: Ui.t("settings.netWiredOff"); onTriggered: s.wiredToggle(false) }
                Pill { property string key: "wiredon"; visible: !!s.netLink("wired") && !s.netLink("wired").connected
                       text: Ui.t("settings.netWiredOn"); onTriggered: s.wiredToggle(true) }
            }
        }
        SetGroup {
            visible: s.cat === "net" && !(s.sett && s.sett.net.mode === "wired"); availH: s.colH; title: Ui.t("settings.wifi")
            SetRow {
                visible: !!s.wifiPick
                Field {
                    id: wifiPw
                    property string key: "pw"
                    password: true
                    revealable: true
                    placeholder: s.wifiPick ? Ui.t("settings.wifiPw", { ssid: s.wifiPick.ssid }) : ""
                    onSubmitted: function (t) { if (s.wifiPick) s.wifiConnect(s.wifiPick.ssid, t) }
                }
                // Passwort im Klartext zeigen (Feld und Bildschirmtastatur), beim naechsten Netz wieder verdeckt
                Pill { property string key: "pwshow"; text: Ui.t(wifiPw.password ? "settings.pwShow" : "settings.pwHide"); on: !wifiPw.password
                       sound: "toggle"; toggleFlip: true; onTriggered: wifiPw.password = !wifiPw.password }
                Pill { property string key: "go"; text: Ui.t("settings.connect"); onTriggered: s.wifiConnect(s.wifiPick.ssid, wifiPw.value) }
                Pill { property string key: "cancel"; text: Ui.t("common.cancel"); onTriggered: { s.wifiPick = null; Qt.callLater(function () { s.refocus("scan") }) } }
            }
            SetRow {
                visible: !s.wifiPick
                Pill { property string key: "scan"; text: s.wifiList ? Ui.t("settings.rescan") : Ui.t("settings.scan"); onTriggered: s.wifiScan() }
                Pill { property string key: "wdis"; visible: !!s.wifiOn(); maxWidth: Ui.screenW * 0.3
                       text: s.wifiOn() ? Ui.t("settings.netDisconnect", { ssid: s.wifiOn().name || s.wifiOn().dev }) : ""
                       onTriggered: s.wifiDisconnect() }
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
                            if (modelData.active) s.wifiDisconnect()         // verbundenes Netz: trennen
                            else if (modelData.secure && !modelData.known) s.wifiAsk(modelData)
                            else s.wifiConnect(modelData.ssid, "")           // bekannt oder offen: gleich wechseln
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
            maxW: s.btW                                 // Platz fuer Geraet + Entkoppeln + Umbenennen in einer Zeile
            Info { visible: !s.bt || !s.bt.available; html: Ui.esc(Ui.t("bt.unsupported")) }
            Info { visible: !!s.bt && s.bt.available && !s.bt.service; html: Ui.esc(Ui.t("bt.serviceOff")) }
            SetRow {
                visible: !!s.bt && s.bt.available && !s.bt.service
                Pill { property string key: "btsrv"; text: Ui.t("bt.startService"); onTriggered: s.btCall("/api/bluetooth/service", { action: "start" }, Ui.t("bt.startingService")) }
            }
            SetRow {
                visible: !!s.bt && s.bt.available && s.bt.service
                Pill { property string key: "btpwr"; text: Ui.t(s.bt && s.bt.powered ? "bt.powerOff" : "bt.powerOn"); on: !!s.bt && s.bt.powered
                       sound: "toggle"; toggleFlip: true; onTriggered: s.btCall("/api/bluetooth/power", { powered: !s.bt.powered }, Ui.t(s.bt.powered ? "bt.poweringOff" : "bt.poweringOn")) }
                Pill { property string key: "btscan"; visible: !!s.bt && s.bt.powered; text: s.btScanning ? Ui.t("bt.scanning") : Ui.t("bt.scan"); onTriggered: s.btScan() }
            }
            Info { visible: !!s.bt && s.bt.available && s.bt.service && !!s.bt.blocked; html: Ui.esc(Ui.t("bt.blocked")) }
            // Umbenennen: Eingabefeld (Bildschirmtastatur) statt Geraeteliste, Esc / B bricht ab
            SetRow {
                visible: !!s.btRename && !!s.bt && s.bt.powered
                label: Ui.t("bt.rename")
                Field {
                    id: btName
                    property string key: "btname"
                    placeholder: s.btRename ? Ui.t("bt.renamePh", { name: s.btRename.orig || s.btRename.mac }) : ""
                    onSubmitted: function (t) { s.btDoRename(t) }
                }
                Pill { property string key: "btsave"; text: Ui.t("bt.save"); onTriggered: s.btDoRename(btName.value) }
                Pill { property string key: "btorig"; visible: !!s.btRename && !!s.btRename.custom
                       text: Ui.t("bt.resetName"); onTriggered: s.btDoRename("") }
                Pill { property string key: "btcancel"; text: Ui.t("common.cancel"); onTriggered: s.btRenameEnd() }
            }
            // Hinweis zum Kopplungsmodus, solange (noch) kein neues Geraet gefunden ist
            Info { visible: !s.btRename && !!s.bt && s.bt.available && s.bt.service && s.bt.powered &&
                            (s.btScanning || !(s.bt.devices || []).some(function (d) { return !d.paired }))
                   html: Ui.t("bt.hint") }
            Info { visible: !!s.bt && s.bt.available && s.bt.service && s.bt.powered && !(s.bt.devices || []).length
                   html: Ui.esc(s.btScanning ? Ui.t("bt.scanning") : Ui.t("bt.noDevices")) }
            SetRow {
                visible: !s.btRename && !!s.bt && s.bt.available && s.bt.service && s.bt.powered && (s.bt.devices || []).length > 0
                label: Ui.t("bt.available")
                width: s.btW
                Repeater {
                    model: s.bt && s.bt.devices ? s.bt.devices.slice(0, 10) : []
                    Row {
                        spacing: 8 * Ui.f
                        property var dev: modelData
                        width: s.btW
                        Pill {
                            property string key: "bt" + s.btKey(modelData.mac)
                            rich: true
                            maxWidth: s.btW - (rm.visible ? rm.width + mv.width + 16 * Ui.f : 0)
                            on: !!modelData.connected
                            text: Ui.esc(modelData.name || modelData.mac) + "<font color='" + Ui.c.textFaint + "'>" + s.btExtra(modelData) + "</font>"
                            onTriggered: {
                                var m = modelData.mac
                                if (modelData.connected) s.btCall("/api/bluetooth/disconnect", { mac: m }, Ui.t("bt.disconnecting"), Ui.t("bt.disconnectedToast"))
                                else if (modelData.paired) s.btCall("/api/bluetooth/connect", { mac: m }, Ui.t("bt.connecting"), Ui.t("bt.connectedToast"), Ui.t("bt.connectFailed"))
                                else s.btPair(m)
                            }
                        }
                        // Gekoppelte Geraete: Entkoppeln, daneben Umbenennen
                        Pill {
                            id: rm
                            property string key: "btrm" + s.btKey(modelData.mac)
                            visible: !!modelData.paired
                            text: Ui.t("bt.remove")
                            onTriggered: s.btCall("/api/bluetooth/remove", { mac: modelData.mac }, Ui.t("bt.disconnecting"), Ui.t("bt.disconnectedToast"))
                        }
                        Pill {
                            id: mv
                            property string key: "btmv" + s.btKey(modelData.mac)
                            visible: !!modelData.paired
                            text: Ui.t("bt.rename")
                            onTriggered: s.btRenameStart(modelData)
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
            // Kanal: keine Wahl mehr (seit 2026.11). Steht das Geraet auf Testing, steht das hier – mit Rueckweg.
            id: chGroup
            property bool testing: !!(s.vsState && s.vsState.channel === "main")
            visible: s.cat === "updates" && !!s.sett && !s.sett.live; availH: s.colH
            title: Ui.t(testing ? "settings.channel" : "settings.sysRemindTitle")
            Info { visible: chGroup.testing; html: Ui.esc(Ui.t("channel.testingInfo")) }
            SetRow {
                visible: chGroup.testing
                Pill { property string key: "chstable"; text: Ui.t("channel.toStable"); onTriggered: s.toStable() }
            }
            SetRow {
                label: Ui.t("settings.sysRemind")
                Repeater {
                    model: s.sett ? (s.sett.sysupd_choices || [30, 60, 90]) : []
                    Pill { property string key: "sd" + modelData; text: Ui.t("settings.days", { n: modelData }); on: (s.sett.sysupd_days || 90) === modelData; sound: "toggle"; onTriggered: s.setSysDays(modelData) }
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
                Pill { property string key: "standby"; visible: !!(app.sett && app.sett.standby); text: Ui.t("power.standby"); onTriggered: app.power("suspend") }
            }
        }
        // Controller als Maus in Programmen (Startseite: PadMouse in voidstation-home.py)
        SetGroup {
            visible: s.cat === "system" && !!s.sett && s.sett.padmouse !== undefined; availH: s.colH; title: Ui.t("settings.padMouse")
            SetRow {
                Repeater {
                    model: [true, false]
                    Pill { property string key: "pm" + modelData; text: Ui.t(modelData ? "common.on" : "common.off"); on: !!s.sett && !!s.sett.padmouse === modelData; sound: "toggle"; onTriggered: s.setPadMouse(modelData) }
                }
            }
            Info { html: Ui.keys(Ui.t("settings.padMouseHint"), Ui.c.textPrimary, 16 * Ui.f) }
        }
        SetGroup {
            visible: s.cat === "system" && !!s.sett && s.sett.ssh !== undefined; availH: s.colH; title: Ui.t("settings.ssh")
            SetRow {
                Repeater {
                    model: [true, false]
                    Pill { property string key: "ssh" + modelData; text: Ui.t(modelData ? "common.on" : "common.off"); on: !!s.sett && !!s.sett.ssh === modelData; sound: "toggle"; onTriggered: s.setSsh(modelData) }
                }
            }
        }
        SetGroup {
            visible: s.cat === "system" && !!s.sett; availH: s.colH; title: Ui.t("settings.report")
            SetRow {
                Pill { property string key: "report"; text: Ui.t("report.create"); onTriggered: s.makeReport() }
            }
        }
    }
}
