// SPDX-License-Identifier: GPL-3.0-or-later
// Installer (nur im Live-System). Gleicher Ablauf wie zuvor in der Web-Oberflaeche:
//   welcome → disk (+ beside | free | manual) → account → device (→ host) → confirm → progress → done | error
// Die ganze Arbeit macht voidstation-installer (root, ueber den Launcher); hier nur Auswahl, Anzeige und Tastatur.
// Kacheln sind Beschreibungen ({ kind, size, act, … }), act() fuehrt sie aus.
import QtQuick
import VS

Layer {
    id: il
    scope: "inst"
    track: trk
    showBar: sub !== ""
    // ------------------------------------------------------------ Zustand
    property string step: "welcome"
    property var probe: null
    property string probeError: ""
    property var disk: null
    property string mode: ""
    property var opt: null
    property real newSize: 0
    property var region: null
    property var roles: ({})
    property var manual: null
    property string name: ""
    property string pw: ""
    property string pw2: ""
    property string host: "tv"
    property string hostEdit: ""
    property int field: 0
    property bool shift: false
    property bool sym: false
    property bool phys: false                 // zuletzt auf der echten Tastatur getippt
    property string keymap: "de"
    property string lang: "de"
    property string tz: "Europe/Berlin"
    property string channel: "stable"
    property bool wifi: false
    property bool share: true
    property bool favs: false
    property bool rtc: false
    property bool rtcSet: false
    property var status: null
    property real t0: 0
    property int tipN: 0
    property bool animate: true               // Kacheln fliegen nur beim Schrittwechsel ein
    readonly property real gib: 1073741824
    readonly property real minRoot: 16 * gib
    readonly property var tzs: ["Europe/Berlin", "Europe/Vienna", "Europe/Zurich", "Europe/Amsterdam", "Europe/Paris", "Europe/London", "Europe/Warsaw",
                                "America/New_York", "America/Chicago", "America/Denver", "America/Los_Angeles", "Australia/Sydney", "UTC"]
    readonly property var stepNo: ({ disk: 1, beside: 1, free: 1, manual: 1, account: 2, host: 3, device: 3, confirm: 4, progress: 5, error: 5 })
    // Der Installer ist dichter als die anderen Seiten: drei Reihen muessen zwischen Kopf und Hinweiszeile passen
    readonly property real iu: Math.max(70, Math.min(170 * Ui.screenH / 768, (stage.height - 46 * Ui.f - 20 * Ui.f) / 3))

    title: ({ welcome: Ui.t("inst.title"), probing: Ui.t("inst.title"), disk: Ui.t("inst.disk"),
              beside: opt ? Ui.t("inst.besideOs", { os: opt.os }) : "", free: disk && disk.systems.length === 1 ? Ui.t("inst.besideOs", { os: disk.systems[0] }) : Ui.t("inst.freeTitle"),
              manual: Ui.t("inst.manual"), account: Ui.t("inst.account"), host: Ui.t("inst.device"), device: Ui.t("inst.device"),
              confirm: Ui.t("inst.confirm"), progress: Ui.t("inst.installing"), error: Ui.t("inst.failed"), done: Ui.t("inst.done") })[step] || Ui.t("inst.title")
    readonly property string sub: {
        if (step === "welcome" && probe) { var bl = blockers(probe); return bl.length ? (bl.indexOf("fw") >= 0 ? Ui.t("inst.almost") : Ui.t("inst.cantHere")) : Ui.t("inst.offlineOk") }
        if (step === "beside" && disk) return Ui.t("inst.splitSub", { model: diskName(disk), size: gb(disk.size) })
        if (step === "free" && disk) return Ui.t("inst.freeSub", { model: diskName(disk), size: gb(disk.size) })
        if (step === "device") return Ui.t("inst.deviceSub")
        if (step === "done") return Ui.t("inst.doneSub")
        return ""
    }
    Component.onCompleted: backButton.visible = Qt.binding(function () { return il.step !== "progress" && il.step !== "done" })

    headRight: Column {
        visible: !!il.stepNo[il.step]
        spacing: 8 * Ui.f
        Txt { anchors.right: parent.right; text: Ui.t("inst.step", { n: il.stepNo[il.step] || 0, total: 5 }); font.pixelSize: 14 * Ui.f; color: Ui.c.textDim }
        Row {
            anchors.right: parent.right
            spacing: 6 * Ui.f
            Repeater { model: 5; Rectangle { width: 40 * Ui.f; height: 4 * Ui.f; color: index < (il.stepNo[il.step] || 0) ? Ui.c.textPrimary : Ui.c.borderMuted } }
        }
    }
    bar: [ Txt { width: Ui.screenW - 2 * Ui.padX; text: il.sub; font.pixelSize: 16 * Ui.f; color: Ui.c.textSecondary; topPadding: -10 * Ui.f; wrapMode: Text.WordWrap } ]

    // ------------------------------------------------------------ Helfer
    function gb(b) { var v = b / 1e9; return (v < 10 ? Ui.num(Math.round(v * 10) / 10, 1) : Ui.num(Math.round(v), 0)) + " GB" }
    function diskName(d) { return d.model || d.path.replace("/dev/", "") }
    readonly property var fsNames: ({ vfat: "FAT32", zfs_member: "ZFS", crypto_LUKS: "LUKS", LVM2_member: "LVM", BitLocker: "BitLocker", swap: "Swap" })
    function fsName(f) { return fsNames[f] || String(f || "\u2013").toUpperCase() }
    readonly property var busNames: ({ sata: "SATA", ata: "SATA", nvme: "NVMe", virtio: "VirtIO", scsi: "SCSI", mmc: "eMMC", sas: "SAS" })
    function loginOf(n) {
        var taken = (probe && probe.users) || []
        var m = { "ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss", "Ä": "ae", "Ö": "oe", "Ü": "ue" }
        var s = String(n).replace(/[äöüßÄÖÜ]/g, function (c) { return m[c] })
        try { s = s.normalize("NFD") } catch (e) {}
        s = s.replace(/[\u0300-\u036f]/g, "").toLowerCase().trim().replace(/\s+/g, "-").replace(/[^a-z0-9_-]/g, "")
        s = s.replace(/^[^a-z_]+/, "").slice(0, 31)
        if (!s) return s
        var out = s, k = 1
        while (["root", "tv", "nobody"].indexOf(out) >= 0 || taken.indexOf(out) >= 0) out = s.slice(0, 29) + (k++)
        return out
    }
    function tzLabel(z) { var t = vs.tzTime(z); return z.split("/").pop().replace(/_/g, " ") + (t ? " · " + t : "") }
    function chName() { return Ui.t("channel." + (channel === "main" ? "main" : "stable")) }
    function blockers(p) {
        var b = []
        if (p.arch !== "x86_64") b.push("arch")
        if (p.uefi && p.secureboot) b.push("fw")
        if (p.ram && p.ram < 3.5 * gib) b.push("ram")
        if (!p.disks.some(function (d) { return d.size >= minRoot + 1.5 * gib })) b.push("disk")
        return b
    }
    function partName(p) {
        if (p.role === "esp") return "EFI"
        if (p.role === "swap") return "Swap"
        if (p.role === "recovery") return Ui.t("inst.recovery")
        if (p.role === "reserved") return null
        if (p.os) return p.os + (p.fstype ? " (" + fsName(p.fstype) + ")" : "")
        return (p.label || fsName(p.fstype)) + " " + gb(p.size)
    }
    function diskSegs(d) {
        var segs = d.parts.map(function (p) { return { s: p.start, n: p.sectors, cls: p.role } })
        ;(d.free || []).forEach(function (r) { if (r.bytes > gib) segs.push({ s: r.start, n: r.sectors, cls: "free" }) })
        segs.sort(function (a, b) { return a.s - b.s })
        var tot = segs.reduce(function (a, x) { return a + x.n }, 0) || 1
        return segs.map(function (x) { return { flex: Math.max(0.015, x.n / tot), cls: x.cls } })
    }
    function diskLegend(d) {
        var names = d.parts.map(partName).filter(function (x) { return !!x })
        var fr = (d.free || []).filter(function (r) { return r.bytes >= 2 * gib }).reduce(function (a, r) { return a + r.bytes }, 0)
        if (fr && names.length) names.push(Ui.t("inst.freeGB", { size: gb(fr) }))
        return names.length ? names.join(" · ") : Ui.t("inst.empty")
    }

    // ------------------------------------------------------------ Oeffnen, Schritte
    function fresh(p) {
        var l = (p && p.lang) || Ui.lang
        probe = p; disk = null; mode = ""; opt = null; newSize = 0; region = null; roles = ({}); manual = null
        name = ""; pw = ""; pw2 = ""; host = "tv"; hostEdit = ""; field = 0; shift = false; sym = false
        keymap = l === "en" ? "us" : "de"; lang = l; tz = l === "en" ? "America/New_York" : "Europe/Berlin"; channel = "stable"
        wifi = !!(p && (p.wifi_saved || []).length); share = true; favs = !!(p && p.favs && (p.favs.radio + p.favs.tv)); rtc = false; rtcSet = false
        status = null; t0 = 0
    }
    function openInst() {
        app.openLayer(il)
        Api.get("/api/install/status", function (st) {
            if (st && ["running", "error", "done"].indexOf(st.state) >= 0) {
                status = st
                go(st.state === "running" ? "progress" : st.state)
                return
            }
            if (["done", "error", "progress"].indexOf(step) >= 0) fresh(null)
            if (!probe) runProbe(false, function () { go("welcome") }); else go(step)
        }, function () { if (!probe) runProbe(false, function () { go("welcome") }); else go(step) })
    }
    function close() { app.closeLayer(il) }
    function runProbe(force, then) {
        step = "probing"; probeError = ""
        Api.get("/api/install/probe" + (force ? "?force=1" : ""), function (p) {
            if (!probe) { var keep = { name: name, pw: pw, pw2: pw2 }; fresh(p); if (keep.name) { name = keep.name; pw = keep.pw; pw2 = keep.pw2 } }
            else probe = p
            if (then) then()
        }, function (e) { probeError = Ui.t("inst.probeFailed", { msg: e }) })
    }
    function go(s) {
        animate = true
        step = s
        trk.reset()
        Qt.callLater(focusDefault)
    }
    readonly property var defaultKey: ({ welcome: "start", disk: "", beside: "split", free: "next", manual: "", account: "fname", host: "fhostEdit",
                                         device: "host", confirm: "hold", error: "retry", done: "reboot" })
    function items() { return Nav.collect(trk) }
    function findKey(k) { var it = items(); for (var i = 0; i < it.length; i++) if (it[i].key === k) return it[i]; return null }
    function focusDefault() {
        if (!il.open || app.layerRoot !== il) return
        var k = defaultKey[step] || ""
        if (step === "disk" && disk) k = "disk" + disk.path
        if (step === "error" && status && status.error && status.error.alt) k = "alt"
        if (step === "account" || step === "host") k = "f" + fields()[field].id
        app.setFocus(findKey(k) || items()[0] || null, true)
    }
    function firstFocus() { return null }       // setzt focusDefault, sobald der Schritt aufgebaut ist
    // Inhalt aendern (Kacheln neu), Fokus auf demselben Element behalten
    function rerender(fn) {
        var k = Nav.current && Nav.current.key ? Nav.current.key : ""
        animate = false
        fn()
        Qt.callLater(function () { var it = k && findKey(k); if (it) app.setFocus(it, true); else focusDefault() })
    }
    function handleBack() {
        var s = step
        if (s === "progress") { app.toast(Ui.t("inst.busy")); return true }
        if (s === "done") { app.toast(Ui.t("inst.pleaseReboot")); return true }
        if (s === "welcome" || s === "error" || s === "probing") { close(); return true }
        if (s === "host") { go("device"); return true }
        go(({ disk: "welcome", beside: "disk", free: "disk", manual: "disk", account: mode === "whole" ? "disk" : mode, device: "account", confirm: "device" })[s] || "welcome")
        return true
    }
    function hints() {
        var T = Ui.t, b = T("hint.back")
        return ({ welcome: [T("hint.instSelect"), T("hint.instBackLive")], disk: [T("hint.instSelect"), b], beside: [T("hint.instSize"), T("hint.instContinue"), b],
                  free: [T("hint.instContinue"), b], manual: [T("hint.instRole"), b], account: [T("hint.instType"), T("hint.instDel"), T("hint.instFields"), b],
                  host: [T("hint.instType"), T("hint.instDel"), b], device: [T("hint.instChange"), T("hint.instNext"), b], confirm: [T("hint.instHold"), b],
                  progress: [T("hint.instWait"), T("hint.instVol")], error: [T("hint.instSelect"), T("hint.instBackLive")], done: [T("hint.instReboot")] })[step]
               || [T("hint.instSelect"), b]
    }
    // Gamepad: LB / RB naechstes Feld, Start = weiter (Geraet, Selbst einteilen), waehrend der Installation kein Ausschalten-Dialog
    function padFilter(k) {
        if ((step === "account" || step === "host") && (k === "lb" || k === "rb")) { nextField(k === "lb" ? -1 : 1); return true }
        if (k === "start" && step === "device") { go("confirm"); return true }
        if (k === "start" && step === "manual") { manualNext(); return true }
        if (k === "start" && step === "progress") { app.toast(Ui.t("inst.busy")); return true }
        return false
    }
    function secondary() { if (step === "account" || step === "host") del() }
    function navMove(dir) {
        if (Nav.current && Nav.current.adj && (dir === "left" || dir === "right")) { Nav.current.adj(dir === "left" ? -1 : 1); return true }
        return false
    }
    // Echte Tastatur in Konto / Rechnername: Buchstaben tippen direkt ins aktive Feld
    function keyFilter(e) {
        if (step !== "account" && step !== "host") return false
        if (e.modifiers & (Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier)) return false
        if (e.key === Qt.Key_Backspace) { del(); return true }
        if (e.key === Qt.Key_Tab || e.key === Qt.Key_Backtab) { nextField(e.key === Qt.Key_Backtab || (e.modifiers & Qt.ShiftModifier) ? -1 : 1); return true }
        if ((e.key === Qt.Key_Return || e.key === Qt.Key_Enter) && (phys || (Nav.current && Nav.current.isField))) { nextField(1); return true }
        if (e.text && e.text.length === 1 && e.text.charCodeAt(0) >= 32) {
            phys = true; type(e.text); return true
        }
        return false
    }

    // ------------------------------------------------------------ Aktionen der Kacheln
    function act(d) {
        switch (d.act) {
        case "reboot": return app.power("reboot")
        case "close": return close()
        case "start": return go("disk")
        case "wifi": app.openLayer(settings); return Qt.callLater(function () { settings.openCat("net") })   // gleich zu WLAN
        case "disk": disk = d.disk; mode = "whole"; opt = null; return go("account")
        case "bios": return app.dialog(Ui.t("inst.biosWays"), Ui.t("inst.biosWaysText"), [[Ui.t("common.ok")]])
        case "beside":
            if (d.opt.blocked) {
                var h = d.opt.blocked === "hibernated"
                return app.dialog(Ui.t(h ? "inst.blockedHib" : "inst.blockedDirty"), Ui.t(h ? "inst.blockedHibText" : "inst.blockedDirtyText"), [[Ui.t("common.ok")]])
            }
            newSize = opt && opt.part === d.opt.part ? newSize : d.opt["default"]
            disk = d.disk; mode = "beside"; opt = d.opt
            return go("beside")
        case "free": disk = d.disk; mode = "free"; region = d.region; return go("free")
        case "manual": mode = "manual"; return go("manual")
        case "gparted": return gparted()
        case "rescan": return runProbe(true, function () { go("manual") })
        case "next": return go(d.to)
        case "host": hostEdit = host; field = 0; return go("host")
        case "toggle": return rerender(function () { toggle(d.key) })
        case "hold": return holdStart()
        case "change": return handleBack()
        case "alt": return retry(true)
        case "retry": return retry(false)
        case "redo": return runProbe(true, function () { go("disk") })
        case "log": return showLog()
        case "save": return saveLog()
        }
    }

    // ------------------------------------------------------------ Kacheln je Schritt
    function welcomeInfo() {
        var p = probe, bl = blockers(p), ramTxt = gb(p.ram * 1e9 / gib)
        var maxDisk = Math.max.apply(null, [0].concat(p.disks.map(function (d) { return d.size })))
        var scr = p.screen ? p.screen.mode.replace("x", "\u00d7") + (p.screen.rate ? " · " + Math.round(p.screen.rate) + " Hz" : "") : "\u2013"
        function info(icon, k, v, state, big) { return { kind: "info", icon: icon, k: k, v: v, state: state || "", big: big || "" } }
        var T = Ui.t
        return [
            info("cpu", T("inst.cpu"), p.cpu),
            info("gpu", T("inst.gpu"), (p.gpu || [])[0]),
            bl.indexOf("ram") >= 0 ? info("ram", T("inst.ram"), ramTxt + " · " + T("inst.ramLow"), "bad")
                                   : info("ram", T("inst.ram"), p.ram < 7.8 * gib ? T("inst.ramSwap", { ram: ramTxt }) : ramTxt),
            !p.uefi ? info(null, T("inst.bootMode"), T("inst.biosMode"), "ok", "BIOS")
                    : p.secureboot ? info(null, T("inst.bootMode"), T("inst.sbOn"), "bad", "UEFI") : info(null, T("inst.bootMode"), T("inst.sbOff"), "ok", "UEFI"),
            bl.length ? info(null, T("inst.ssd"), T("inst.ssdMin"), bl.indexOf("disk") >= 0 ? "bad" : "ok", maxDisk ? gb(maxDisk) : "\u2013")
                      : info(p.net === "wifi" ? "wifi" : "lan", T("inst.network"), T(({ lan: "inst.netLan", wifi: "inst.netWifi" })[p.net] || "inst.netNone"), p.net !== "none" ? "ok" : ""),
            bl.length ? info(null, T("inst.arch"), "64 Bit", bl.indexOf("arch") >= 0 ? "bad" : "ok", p.arch)
                      : info(null, T("inst.screen"), scr, "", p.screen ? p.screen.mode.split("x")[1] + "p" : "\u2013")
        ]
    }
    function welcomeGo() {
        var bl = blockers(probe), T = Ui.t, out = []
        if (bl.length) {
            if (bl.indexOf("fw") >= 0) out.push({ kind: "tile", label: T("inst.reboot"), icon: "restart", color: "#2f6d4f", size: "wide", act: "reboot", key: "reboot" })
            out.push({ kind: "tile", label: T("inst.back"), icon: "back", color: "#3a3f46", act: "close", key: "back" })
        } else {
            out.push({ kind: "tile", label: T("inst.start"), sub: T("inst.minutes"), icon: "install", size: "large", color: "#2f6d4f", act: "start", key: "start" })
            out.push({ kind: "tile", label: T("inst.back"), icon: "back", color: "#3a3f46", act: "close", key: "back" })
            out.push({ kind: "tile", label: T("inst.wifi"), icon: "wifi", color: "#2f3238", act: "wifi", key: "wifi" })
        }
        return out
    }
    function welcomePanel() {
        var bl = blockers(probe), T = Ui.t
        if (!bl.length) return [{ k: T("inst.whatUi"), v: T("inst.whatUiText") }, { k: T("inst.whatShare"), v: T("inst.whatShareText") },
                                { k: T("inst.whatUpd"), v: T("inst.whatUpdText") }, { k: T("inst.whatLater"), v: T("inst.whatLaterText") }, { foot: T("inst.minSsd") }]
        var rows = []
        if (bl.indexOf("fw") >= 0) rows.push({ ol: [T("inst.fw1"), T("inst.fw2"), T("inst.fw3")], foot: T("inst.fwStick") })
        ;["ram", "disk", "arch"].forEach(function (k) { if (bl.indexOf(k) >= 0) rows.push({ v: T(({ ram: "inst.needRam", disk: "inst.needDisk", arch: "inst.needArch" })[k]) }) })
        return rows
    }
    function diskTiles() {
        return probe.disks.filter(function (d) { return d.options.whole }).map(function (d, i) {
            return { kind: "disk", size: "large", color: i ? "#2f3238" : "#39414d", act: "disk", disk: d, key: "disk" + d.path, tran: d.tran,
                     bus: busNames[d.tran] || String(d.tran || "").toUpperCase(), gb: gb(d.size), model: diskName(d), segs: diskSegs(d), legend: diskLegend(d) }
        })
    }
    function wayTiles() {
        var p = probe, multi = p.disks.length > 1, T = Ui.t, out = []
        if (!p.uefi)
            return [{ kind: "tile", size: "wide", color: "#2f3238", icon: "beside", off: true, key: "bios", act: "bios", label: T("inst.biosWays"), sub: T("inst.biosOnly") }]
        p.disks.forEach(function (d) {
            ;(d.options.beside || []).forEach(function (o) {
                var sub = o.blocked ? T(o.blocked === "hibernated" ? "inst.blockedHib" : "inst.blockedDirty")
                        : multi ? diskName(d) + " · " + fsName(o.fstype) : fsName(o.fstype) + " · " + T("inst.willShrink")
                out.push({ kind: "tile", size: "wide", color: /windows/i.test(o.os) ? "#2d3763" : "#34464f", icon: "beside", key: "b" + o.part, off: !!o.blocked,
                           label: T("inst.besideOs", { os: o.os }), sub: sub, act: "beside", disk: d, opt: o })
            })
            ;(d.options.free || []).forEach(function (r) {
                out.push({ kind: "tile", size: "wide", color: "#34464f", icon: "free", key: "f" + d.path + r.start, act: "free", disk: d, region: r,
                           label: T("inst.freeSpace", { size: gb(r.bytes) }), sub: multi || !d.systems.length ? diskName(d) : T("inst.nextTo", { os: d.systems[0] }) })
            })
        })
        out.push({ kind: "tile", size: "wide", color: "#2f3238", icon: "manual", label: T("inst.manual"), sub: T("inst.withGparted"), key: "manual", act: "manual" })
        return out
    }
    function deviceTiles() {
        var p = probe, T = Ui.t, ws = p.wifi_saved || [], favN = ((p.favs || {}).radio || 0) + ((p.favs || {}).tv || 0)
        function st(k, v, desc, key, nav) { return { kind: "set", size: "wide", color: "#23272c", k: k, v: v, desc: desc, key: key, act: nav === false ? "" : "toggle", nav: nav !== false } }
        var out = [
            { kind: "set", size: "wide", color: "#23272c", k: T("inst.hostname"), v: host, desc: T("inst.hostSub", { host: host }), key: "host", act: "host" },
            st(T("inst.channel"), chName(), T(channel === "main" ? "inst.chTestSub" : "inst.chStableSub"), "ch"),
            ws.length ? st(T("inst.wifiTake"), wifi ? ws[0] : T("common.off"), wifi ? T("inst.wifiSub") : T("inst.wifiOffSub"), "wifi") : null,
            st(T("inst.share"), T(share ? "common.on" : "common.off"), T("inst.shareSub"), "share"),
            st(T("inst.language"), lang === "en" ? "English" : "Deutsch", T("inst.langSub"), "lang"),
            st(T("inst.timezone"), tzLabel(tz), T("inst.tzSub"), "tz"),
            favN ? st(T("inst.favs"), favs ? T("inst.favCount", { n: favN }) : T("common.off"), T("inst.favSub"), "favs") : null,
            p.windows ? st(T("inst.rtc"), T(rtc ? "inst.rtcLocal" : "inst.rtcUtc"), T(rtc ? "inst.rtcSub" : "inst.rtcUtcSub"), "rtc") : null,
            p.screen ? st(T("inst.screen"), p.screen.mode.replace("x", "\u00d7"), T("inst.screenSub"), "screen", false) : null,
            { kind: "tile", size: "wide", color: "#2f6d4f", icon: "install", label: T("inst.continue"), key: "next", act: "next", to: "confirm" }
        ]
        return out.filter(function (x) { return !!x })
    }
    function toggle(k) {
        if (k === "ch") channel = channel === "main" ? "stable" : "main"
        else if (k === "wifi") wifi = !wifi
        else if (k === "share") share = !share
        else if (k === "lang") lang = lang === "en" ? "de" : "en"
        else if (k === "tz") tz = tzs[(tzs.indexOf(tz) + 1) % tzs.length]
        else if (k === "favs") favs = !favs
        else if (k === "rtc") rtc = !rtc
    }
    function summary() {
        var d = disk, T = Ui.t, what = d.systems.join(", "), eff
        if (mode === "whole") eff = what ? T("inst.sumWholeWith", { what: what }) : T("inst.sumWhole")
        else if (mode === "beside") eff = T("inst.sumBeside", { os: opt.os, old: gb(opt.size - newSize), size: gb(newSize) })
        else if (mode === "free") eff = T("inst.sumFree", { size: gb(region.bytes) })
        else eff = T("inst.sumManual", { root: manual.root, esp: manual.esp })
        var favN = probe.favs ? probe.favs.radio + probe.favs.tv : 0
        var extras = [(probe.wifi_saved || []).length && wifi ? T("inst.wifi") : null, share ? T("inst.whatShare") : null,
                      favs && favN ? T("inst.favCount", { n: favN }) : null].filter(function (x) { return !!x })
        return [
            { k: T("inst.sumDisk"), html: "<b>" + Ui.esc(diskName(d)) + " · " + Ui.esc(gb(d.size)) + "</b><br>" + Ui.esc(eff) },
            { k: T("inst.sumAccount"), html: "<b>" + Ui.esc(name) + "</b> · " + Ui.esc(T("inst.sumLogin", { login: loginOf(name) })) },
            { k: T("inst.sumDevice"), html: "<b>" + Ui.esc(host) + "</b> · " + (lang === "en" ? "English" : "Deutsch") + " · " + Ui.esc(tzLabel(tz).split(" · ")[0])
                                           + (probe.screen ? " · " + probe.screen.mode.replace("x", "\u00d7") : "") },
            { k: T("inst.sumUpdates"), v: T("inst.sumChannel", { channel: chName() }) },
            { k: T("inst.sumExtras"), v: extras.join(", ") || T("inst.sumNone") },
            probe.bitlocker && mode !== "whole" ? { k: "BitLocker", v: T("inst.bitlocker") } : null
        ]
    }

    // ------------------------------------------------------------ Selbst einteilen (GParted + Rollen)
    function rolesFor(p) {
        var r = [p.os ? "keep" : "none"]
        var foreign = (p.loaders || []).some(function (l) { return ["voidstation", "boot"].indexOf(l.vendor) < 0 })
        if (p.fstype === "vfat" || p.role === "esp") {
            if (p.fstype === "vfat") r.push("esp_keep")
            if (p.size >= 100 * 1048576 && !foreign) r.push("esp_format")
        }
        if (p.size >= minRoot - 512 * 1048576 && p.role !== "esp") r.push("root")
        return r
    }
    function cycleRole(p) {
        var rs = rolesFor(p), nx = rs[(rs.indexOf(roles[p.path] || rs[0]) + 1) % rs.length]
        var isEsp = function (x) { return x === "esp_keep" || x === "esp_format" }
        var r = {}
        for (var k in roles) if (!(k !== p.path && (roles[k] === nx || (isEsp(nx) && isEsp(roles[k]))))) r[k] = roles[k]
        r[p.path] = nx
        roles = r
    }
    function roleOf(want) { for (var k in roles) if (want(roles[k])) return k; return "" }
    function manualNext() {
        var root = roleOf(function (r) { return r === "root" }), esp = roleOf(function (r) { return /^esp/.test(r) })
        if (!(root && esp)) return app.toast(Ui.t("inst.manualMissing"), true)
        disk = probe.disks.filter(function (x) { return x.parts.some(function (p) { return p.path === root }) })[0]
        mode = "manual"
        manual = { root: root, esp: esp, format_esp: roles[esp] === "esp_format" }
        go("account")
    }
    property bool gpSeen: false
    function gparted() {
        Api.post("/api/install/gparted", null, function () {
            app.toast(Ui.t("inst.gpartedOpen"))
            gpSeen = false
            gpPoll.start()
        }, function (e) { app.toast(Ui.t("inst.gpartedFailed", { msg: e }), true) })
    }
    Timer {
        id: gpPoll; interval: 2000; repeat: true
        onTriggered: Api.get("/api/install/gparted", function (r) {
            if (r.running) { il.gpSeen = true; return }
            gpPoll.stop()
            il.runProbe(true, function () { il.roles = ({}); il.go("manual") })
        })
    }

    // ------------------------------------------------------------ Konto und Rechnername (Bildschirmtastatur)
    function fields() {
        return step === "host" ? [{ id: "hostEdit", label: Ui.t("inst.hostname"), max: 15, filter: /[A-Za-z0-9-]/ }]
             : [{ id: "name", label: Ui.t("inst.name"), max: 60, filter: /[^:,=\\]/ }, { id: "pw", label: Ui.t("inst.password"), max: 200, secret: true },
                { id: "pw2", label: Ui.t("inst.password2"), max: 200, secret: true }]
    }
    function type(ch) {
        var f = fields()[field]
        if (!f || (f.filter && !f.filter.test(ch)) || il[f.id].length >= f.max) return
        il[f.id] = il[f.id] + ch
        if (shift) shift = false
    }
    function del() { var f = fields()[field]; if (f) il[f.id] = il[f.id].slice(0, -1) }
    function nextField(dir) {
        var n = fields().length
        if (dir > 0 && field >= n - 1) return oskDone()
        field = (field + dir + n) % n
        var it = findKey("f" + fields()[field].id)
        if (it) app.setFocus(it, true)
    }
    function setKeymap(km) {
        rerender(function () { keymap = km })
        Api.post("/api/install/keymap", { keymap: km }, null, null)
    }
    function oskDone() {
        if (step === "host") {
            if (!/^[A-Za-z0-9](?:[A-Za-z0-9-]{0,13}[A-Za-z0-9])?$/.test(hostEdit)) return app.toast(Ui.t("inst.errHost"), true)
            host = hostEdit
            return go("device")
        }
        var login = loginOf(name)
        if (!name.trim() || !/^[a-z_][a-z0-9_-]{0,30}$/.test(login)) { field = 0; app.toast(Ui.t("inst.errName"), true); return focusField() }
        if (!pw) { field = 1; app.toast(Ui.t("inst.errPw"), true); return focusField() }
        if (pw !== pw2) { field = 2; pw2 = ""; app.toast(Ui.t("inst.errPw2"), true); return focusField() }
        name = name.trim()
        if (!rtcSet) { rtc = !!probe.windows && mode !== "whole"; rtcSet = true }
        go("device")
    }
    function focusField() { var it = findKey("f" + fields()[field].id); if (it) app.setFocus(it, true) }

    // ------------------------------------------------------------ Bestaetigen: A / Enter / Maus 2 s halten
    property Item holdItem: null
    property real holdT0: 0
    function holdStart() {
        if (holdTimer.running || !(Nav.current && Nav.current.isHold)) return
        holdItem = Nav.current
        holdT0 = Date.now()
        holdTimer.start()
    }
    Timer {
        id: holdTimer; interval: 16; repeat: true
        onTriggered: {
            var p = Math.min(1, (Date.now() - il.holdT0) / 2000), it = il.holdItem
            var held = app.keyHeld || vs.padDown("a") || (it && it.pressedNow && it.mouseDown)
            if (it) it.holdP = p
            if (!held || !it) {
                stop(); if (it) it.holdP = 0
                if (p < 1) app.toast(Ui.t("inst.holdHint"))
                return
            }
            if (p >= 1) { stop(); it.holdP = 0; app.keyHeld = false; il.startInstall() }
        }
    }
    function config() {
        var c = { mode: mode, disk: disk.path, user: { name: name, login: loginOf(name), password: pw }, hostname: host,
                  lang: lang, keymap: keymap, timezone: tz, channel: channel, wifi: wifi && !!(probe.wifi_saved || []).length,
                  share: share, favorites: favs, rtc_local: rtc && !!probe.windows }
        if (mode === "beside") { c.part = opt.part; c.new_size = newSize }
        if (mode === "free") c.region = { start: region.start, sectors: region.sectors }
        if (mode === "manual") c.manual = manual
        return c
    }
    function startInstall() {
        t0 = Date.now()
        status = { state: "running", pct: 0, phases: {}, mode: mode }
        go("progress")                                  // sofort umschalten: ab hier nichts mehr aenderbar
        Api.post("/api/install/start", { config: config() }, function (st) { status = st; poll.start() },
                 function (e) { go("confirm"); app.toast(Ui.t("inst.startFailed", { msg: e }), true) })
    }
    function retry(alt) {
        var prev = status
        status = Object.assign({}, prev, { state: "running", error: null })
        go("progress")
        Api.post("/api/install/retry", { alt: alt }, function (st) { status = st; poll.start() },
                 function (e) { status = prev; go("error"); app.toast(Ui.t("inst.startFailed", { msg: e }), true) })
    }
    // Fortschritt: einmal je Sekunde den Stand holen
    Timer {
        id: poll; interval: 1000; repeat: true
        running: il.step === "progress" && il.status && il.status.state === "running"
        onTriggered: Api.get("/api/install/status", function (st) {
            il.status = st
            il.tipN = (il.tipN + 1) % 32
            if (st.state === "done" || st.state === "error") { poll.stop(); il.go(st.state) }
        })
    }
    function phGroups(m) {
        var out = []
        if (m === "beside") out.push(["shrink", ["check", "shrink"]])
        out.push(["partition", m === "beside" ? ["partition", "format"] : ["check", "partition", "format"]])
        return out.concat([["copy", ["copy"]], ["configure", ["configure"]], ["boot", ["boot"]], ["cleanup", ["cleanup"]]])
    }
    function phases() {
        var st = status || {}, ph = st.phases || {}, m = st.mode || mode, cur = null
        var rows = phGroups(m).map(function (g) {
            var states = g[1].map(function (x) { return ph[x] })
            var s = states.indexOf("error") >= 0 ? "error" : states.every(function (x) { return x === "done" }) ? "done"
                  : states.some(function (x) { return x === "running" || x === "done" }) ? "run" : ""
            if (s === "run" && !cur) cur = g[0]
            var dt = ""
            if (g[0] === "copy" && s === "run" && st.copy && st.copy.total) dt = Ui.t("inst.copyOf", { done: gb(st.copy.done || 0), total: gb(st.copy.total) })
            if (g[0] === "boot") dt = m === "whole" ? Ui.t("inst.bootStub") : Ui.t("inst.bootMenuShort")
            return { id: g[0], state: s, dt: dt }
        })
        return { rows: rows, cur: cur }
    }
    function showLog() {
        Api.get("/api/install/log", function (j) {
            app.dialog(Ui.t("inst.logTitle"), String(j.log || "").trim().split("\n").slice(-18).join("\n"), [[Ui.t("common.close")], [Ui.t("inst.logSave"), il.saveLog]])
        }, function (e) { app.dialog(Ui.t("inst.logTitle"), e, [[Ui.t("common.close")]]) })
    }
    function saveLog() {
        Api.post("/api/install/savelog", null, function (r) { app.toast(r.ok ? Ui.t("inst.logSaved", { file: r.file }) : Ui.t("inst.noUsb"), !r.ok) },
                 function () { app.toast(Ui.t("inst.noUsb"), true) })
    }
    function errorState() {
        var st = status || {}, e = st.error || {}, T = Ui.t
        var done = e.done || Object.keys(st.phases || {}).filter(function (k) { return st.phases[k] === "done" })
        var systems = disk && disk.systems ? disk.systems.join(", ") : "", m = st.mode || mode, lines = []
        if (done.indexOf("shrink") >= 0 && opt) lines.push({ st: "ok", t: T("inst.stateShrunk", { os: opt.os }) })
        if (done.indexOf("partition") >= 0) lines.push({ st: "ok", t: m === "whole" ? T("inst.stateErased") : T("inst.statePart") })
        if (done.indexOf("copy") >= 0) lines.push({ st: "ok", t: T("inst.stateCopied") })
        if (done.indexOf("configure") >= 0) lines.push({ st: "ok", t: T("inst.stateConfigured") })
        if (e.phase === "boot") lines.push({ st: "bad", t: T("inst.stateNoBoot") })
        if (!lines.length) lines.push({ st: "keep", t: T("inst.stateNothing") })
        if (m !== "whole" && e.foreign_untouched !== false) lines.push({ st: "keep", t: systems ? T("inst.stateUntouched", { os: systems }) : T("inst.stateOthers") })
        var early = done.indexOf("copy") < 0
        var isFresh = !done.filter(function (x) { return x !== "check" }).length
        var acts = [
            e.alt ? { kind: "tile", size: "wide", color: "#2f6d4f", icon: "alt", label: T("inst.alt"), sub: T("inst.altSub"), key: "alt", act: "alt" } : null,
            { kind: "tile", size: "wide", color: e.alt ? "#2f3238" : "#2f6d4f", icon: "restart", label: T("inst.retry"), sub: early ? T("inst.retrySubEarly") : T("inst.retrySub"), key: "retry", act: "retry" },
            isFresh && probe ? { kind: "tile", size: "wide", color: "#2f3238", icon: "back", label: T("inst.redo"), sub: T("inst.redoSub"), key: "redo", act: "redo" } : null,
            { kind: "tile", color: "#2f3238", icon: "log", label: T("inst.log"), key: "log", act: "log" },
            { kind: "tile", color: "#2f3238", icon: "usb", label: T("inst.saveLog"), sub: T("inst.saveLogSub"), key: "save", act: "save" },
            e.alt || isFresh ? null : { kind: "tile", color: "#3a3f46", icon: "home", label: T("inst.home"), key: "home", act: "close" }
        ].filter(function (x) { return !!x })
        var phase = e.phase ? T("inst.ph." + e.phase, null, e.phase) : ""
        var what = [{ html: "<b>" + Ui.esc(phase) + "</b><br>" + Ui.esc(T("inst.err." + e.code, null, T("inst.err.generic"))) }]
        if (e.msg && e.msg !== e.code) what.push({ mono: String(e.msg).slice(-500) })
        what.push({ foot: T("inst.logAt", { path: "/run/voidstation-installer/install.log" }) })
        return { what: what, lines: lines, acts: acts }
    }

    // ------------------------------------------------------------ Darstellung
    Track {
        id: trk
        anchors.fill: parent
        Loader {
            id: stepLoader
            sourceComponent: ({ probing: cProbing, welcome: cWelcome, disk: cDisk, beside: cBeside, free: cFree, manual: cManual, account: cOsk, host: cOsk,
                                device: cDevice, confirm: cConfirm, progress: cProgress, error: cError, done: cDone })[il.probe || il.step === "probing" || il.status ? il.step : "probing"] || null
        }
    }
    Component {
        id: tileDelegate
        ITile {
            d: modelData
            u: il.iu
            navigable: modelData.kind !== "info" && modelData.nav !== false
            enterDelay: index * 35
            animateIn: il.animate
            onTriggered: il.act(modelData)
            onHoldBegin: il.holdStart()
        }
    }
    component Steps: Row { spacing: trk.spacing }

    Component {
        id: cProbing
        Steps {
            Row {
                spacing: 14 * Ui.f
                Spinner { size: 18 * Ui.f; line: 2; visible: !il.probeError; anchors.verticalCenter: parent.verticalCenter }
                Txt { text: il.probeError || Ui.t("inst.probing"); font.pixelSize: 18 * Ui.f; color: Ui.c.textDim; elide: Text.ElideNone }
            }
        }
    }
    Component {
        id: cWelcome
        Steps {
            Group { title: Ui.t("inst.thisDevice"); TileGrid { items: il.welcomeInfo(); rows: 3; cellW: il.iu; cellH: il.iu; delegate: tileDelegate } }
            Group { title: Ui.t("inst.letsGo"); TileGrid { items: il.welcomeGo(); rows: 3; cellW: il.iu; cellH: il.iu; delegate: tileDelegate } }
            Group { title: il.blockers(il.probe).length ? Ui.t("inst.howTo") : Ui.t("inst.onSsd"); IPanel { u: il.iu; rows: il.welcomePanel() } }
        }
    }
    Component {
        id: cDisk
        Steps {
            Group {
                title: Ui.t("inst.whole")
                Column {
                    spacing: Ui.gap
                    Txt { visible: !dg.items.length; text: Ui.t("inst.noDisks"); color: Ui.c.textFaint }
                    TileGrid { id: dg; items: il.diskTiles(); rows: 2; cellW: il.iu; cellH: il.iu; delegate: tileDelegate }
                    Rectangle {
                        visible: dg.items.length > 0
                        width: Math.max(dg.width, il.iu * 2); height: Math.max(il.iu * 0.43, warnTxt.implicitHeight + 16 * Ui.f)
                        color: Ui.c.statusDangerBg
                        Row {
                            x: 22 * Ui.f; anchors.verticalCenter: parent.verticalCenter
                            spacing: 16 * Ui.f
                            Glyph { name: "warn"; color: Ui.c.textPrimary; width: 26 * Ui.f; height: width; anchors.verticalCenter: parent.verticalCenter }
                            Txt { id: warnTxt; text: Ui.t("inst.wipeWarn"); font.pixelSize: 17 * Ui.f; width: Math.min(implicitWidth, parent.parent.width - 70 * Ui.f)
                                  wrapMode: Text.WordWrap; elide: Text.ElideNone; anchors.verticalCenter: parent.verticalCenter }
                        }
                    }
                }
            }
            Group { title: Ui.t("inst.otherWays"); TileGrid { items: il.wayTiles(); rows: 3; cellW: il.iu; cellH: il.iu; delegate: tileDelegate } }
        }
    }
    Component {
        id: cBeside
        Steps {
            Group {
                title: Ui.t("inst.split")
                Column {
                    spacing: 14 * Ui.f
                    Focusable {
                        id: split
                        property string key: "split"
                        readonly property real step_: il.opt.max_new - il.minRoot > 200 * il.gib ? 5 * il.gib : il.gib
                        readonly property real rest: il.opt.size - il.newSize - (il.disk.esp ? 0 : 512 * 1048576)
                        readonly property real fa: Math.max(0.22, Math.min(0.78, rest / il.opt.size))
                        width: il.iu * 4.2; height: il.iu * 1.25
                        // dir: Richtung des Griffs – nach links (−1) bekommt VoidStation mehr Platz
                        function adj(dir) { il.newSize = Math.max(il.minRoot, Math.min(il.opt.max_new, Math.round((il.newSize - dir * step_) / il.gib) * il.gib)) }
                        function setX(x) { il.newSize = Math.max(il.minRoot, Math.min(il.opt.max_new, Math.round(il.opt.size * (1 - Math.max(0, Math.min(1, x / width))) / il.gib) * il.gib)) }
                        function clickActivate() {}
                        onTriggered: il.go("account")
                        Rectangle {
                            anchors.fill: parent; anchors.margins: -6 * Ui.f; color: Ui.c.borderFocus; visible: split.focused
                            Rectangle { anchors.fill: parent; anchors.margins: 3 * Ui.f; color: Ui.c.bgMain }
                        }
                        Row {
                            anchors.fill: parent
                            spacing: 3
                            Rectangle {
                                width: split.fa * split.width - 2; height: parent.height; color: Ui.c.statusInfoBg; clip: true
                                Column {
                                    x: 14 * Ui.f; y: 14 * Ui.f; width: parent.width - 28 * Ui.f
                                    Txt { width: parent.width; text: il.opt.os + " · " + il.fsName(il.opt.fstype); font.pixelSize: 15 * Ui.f }
                                    Txt { text: il.gb(split.rest); font.pixelSize: il.iu * 0.26; font.weight: Font.Light; elide: Text.ElideNone }
                                    Txt { width: parent.width; text: il.opt.used ? Ui.t("inst.usedOf", { used: il.gb(il.opt.used) }) : ""; font.pixelSize: 13 * Ui.f; color: Ui.c.textSecondary }
                                }
                            }
                            Rectangle {
                                width: split.width - split.fa * split.width - 1; height: parent.height; color: Ui.c.statusOkBg; clip: true
                                Column {
                                    x: 14 * Ui.f; y: 14 * Ui.f; width: parent.width - 28 * Ui.f
                                    Txt { width: parent.width; text: "VoidStation"; font.pixelSize: 15 * Ui.f }
                                    Txt { text: il.gb(il.newSize); font.pixelSize: il.iu * 0.26; font.weight: Font.Light; elide: Text.ElideNone }
                                    Txt { width: parent.width; text: Ui.t("inst.newPart"); font.pixelSize: 13 * Ui.f; color: Ui.c.textSecondary }
                                }
                            }
                        }
                        Rectangle {                              // Griff
                            width: 34 * Ui.f; height: width; radius: width / 2; color: Ui.c.textPrimary
                            x: split.fa * split.width - width / 2; anchors.verticalCenter: parent.verticalCenter
                            Txt { anchors.centerIn: parent; text: "\u2039\u203a"; color: Ui.c.bgMain; font.pixelSize: 15 * Ui.f; elide: Text.ElideNone }
                        }
                        MouseArea {                              // ziehen oder klicken: Grenze setzen
                            anchors.fill: parent
                            onPressed: function (m) { app.setFocus(split); split.setX(m.x) }
                            onPositionChanged: function (m) { if (pressed) split.setX(m.x) }
                        }
                    }
                    Row {
                        spacing: Ui.gap
                        Pill { property string key: "minus"; text: "\u2212 VoidStation"; onTriggered: split.adj(1) }
                        Pill { property string key: "plus"; text: "+ VoidStation"; onTriggered: split.adj(-1) }
                        Pill { property string key: "next"; text: Ui.t("inst.continue"); onTriggered: il.go("account") }
                    }
                }
            }
            Group {
                title: Ui.t("inst.whatHappens")
                IPanel {
                    u: il.iu
                    rows: [{ k: Ui.t("inst.atBoot"), v: Ui.t("inst.bootMenu", { os: il.opt.os }) }, { k: Ui.t("inst.unchanged"), v: Ui.t("inst.keepsBeside", { os: il.opt.os }) },
                           { k: Ui.t("inst.beforeShrink"), v: Ui.t("inst.checkFirst", { os: il.opt.os }) }, il.opt.fstype === "ntfs" ? { v: Ui.t("inst.ntfsNote") } : null]
                }
            }
        }
    }
    Component {
        id: cFree
        Steps {
            readonly property string os: il.disk.systems.join(" / ")
            readonly property real used: il.disk.parts.reduce(function (a, p) { return a + p.size }, 0)
            readonly property real fa: Math.max(0.3, Math.min(0.7, used / (used + il.region.bytes)))
            Group {
                title: Ui.t("inst.split")
                Column {
                    spacing: 14 * Ui.f
                    Row {
                        width: il.iu * 4.2; height: il.iu * 1.25
                        spacing: 3
                        Rectangle {
                            width: fa * parent.width - 2; height: parent.height; color: "#34464f"; clip: true
                            Column {
                                x: 14 * Ui.f; y: 14 * Ui.f; width: parent.width - 28 * Ui.f
                                Txt { width: parent.width; text: os || Ui.t("inst.othersKeep"); font.pixelSize: 15 * Ui.f }
                                Txt { text: il.gb(used); font.pixelSize: il.iu * 0.26; font.weight: Font.Light; elide: Text.ElideNone }
                                Txt { width: parent.width; text: Ui.t("inst.stays"); font.pixelSize: 13 * Ui.f; color: Ui.c.textSecondary }
                            }
                        }
                        Rectangle {
                            width: parent.width - fa * parent.width - 1; height: parent.height; color: Ui.c.statusOkBg; clip: true
                            Column {
                                x: 14 * Ui.f; y: 14 * Ui.f; width: parent.width - 28 * Ui.f
                                Txt { width: parent.width; text: "VoidStation"; font.pixelSize: 15 * Ui.f }
                                Txt { text: il.gb(il.region.bytes); font.pixelSize: il.iu * 0.26; font.weight: Font.Light; elide: Text.ElideNone }
                                Txt { width: parent.width; text: Ui.t("inst.wholeFree"); font.pixelSize: 13 * Ui.f; color: Ui.c.textSecondary }
                            }
                        }
                    }
                    Pill { property string key: "next"; text: Ui.t("inst.continue"); onTriggered: il.go("account") }
                }
            }
            Group {
                title: Ui.t("inst.whatHappens")
                IPanel {
                    u: il.iu
                    rows: [os ? { k: Ui.t("inst.atBoot"), v: Ui.t("inst.bootMenu", { os: os }) } : null,
                           { k: Ui.t("inst.unchanged"), v: os ? Ui.t("inst.keepsFree", { os: os }) : Ui.t("inst.othersKeep") },
                           { k: Ui.t("inst.moreSpace"), v: Ui.t("inst.moreSpaceText") }]
                }
            }
        }
    }
    Component {
        id: cManual
        Steps {
            Group {
                title: Ui.t("inst.tool")
                TileGrid {
                    rows: 3; cellW: il.iu; cellH: il.iu; delegate: tileDelegate
                    items: [{ kind: "tile", size: "wide", color: "#2d3763", icon: "manual", label: Ui.t("inst.gparted"), sub: Ui.t("inst.gpartedSub"), key: "gparted", act: "gparted" },
                            { kind: "tile", color: "#2f3238", icon: "restart", label: Ui.t("inst.rescan"), key: "rescan", act: "rescan" }]
                }
            }
            Group {
                title: Ui.t("inst.whichPart")
                Column {
                    width: il.iu * 4.4
                    spacing: 8 * Ui.f
                    Repeater {
                        model: il.probe.disks
                        Column {
                            property var dk: modelData
                            width: parent.width
                            spacing: 8 * Ui.f
                            Txt { text: il.diskName(dk) + " · " + il.gb(dk.size); font.pixelSize: 13 * Ui.f; color: Ui.c.textFaint; topPadding: 6 * Ui.f }
                            Repeater {
                                model: dk.parts.filter(function (p) { return p.role !== "reserved" })
                                Focusable {
                                    id: prow
                                    property string key: "p" + modelData.path
                                    readonly property var rs: il.rolesFor(modelData)
                                    readonly property string cur: il.roles[modelData.path] || rs[0]
                                    enabled: rs.length > 1
                                    opacity: enabled ? 1 : 0.45
                                    width: parent.width; height: Math.max(46 * Ui.f, 30 * Ui.f)
                                    onTriggered: il.cycleRole(modelData)
                                    Rectangle {
                                        anchors.fill: parent
                                        color: Ui.c.surfaceCard
                                        border.width: 2; border.color: prow.focused ? Ui.c.borderFocus : "transparent"
                                    }
                                    Row {
                                        x: 16 * Ui.f; anchors.verticalCenter: parent.verticalCenter
                                        width: parent.width - 32 * Ui.f
                                        spacing: 14 * Ui.f
                                        Txt { width: parent.width * 0.18; text: modelData.path.replace("/dev/", ""); font.weight: Font.DemiBold; anchors.verticalCenter: parent.verticalCenter }
                                        Txt { width: parent.width - parent.width * 0.18 - roleBox.width - 28 * Ui.f; color: Ui.c.textDim; anchors.verticalCenter: parent.verticalCenter
                                              text: [il.fsName(modelData.fstype), il.gb(modelData.size), modelData.os || modelData.label].filter(function (x) { return !!x }).join(" · ") }
                                        Rectangle {
                                            id: roleBox
                                            width: roleTxt.implicitWidth + 20 * Ui.f; height: roleTxt.implicitHeight + 6 * Ui.f
                                            anchors.verticalCenter: parent.verticalCenter
                                            color: prow.cur === "root" ? Ui.c.statusOkBg : /^esp/.test(prow.cur) ? Ui.c.surfaceActive : Ui.c.surfaceCardHover
                                            Txt { id: roleTxt; anchors.centerIn: parent; text: Ui.t("inst.role." + prow.cur); elide: Text.ElideNone }
                                        }
                                    }
                                }
                            }
                        }
                    }
                    Txt { width: parent.width; text: Ui.t("inst.manualNeed"); color: Ui.c.textDim; font.pixelSize: 16 * Ui.f; wrapMode: Text.WordWrap; elide: Text.ElideNone; topPadding: 8 }
                    Pill {
                        property string key: "next"
                        readonly property bool ok: { il.roles; return !!(il.roleOf(function (r) { return r === "root" }) && il.roleOf(function (r) { return /^esp/.test(r) })) }
                        opacity: ok ? 1 : 0.45
                        text: Ui.t("inst.continue")
                        onTriggered: il.manualNext()
                    }
                }
            }
        }
    }
    Component {
        id: cOsk
        Steps {
            Group {
                title: il.step === "host" ? Ui.t("inst.editHost") : Ui.t("inst.account")
                Column {
                    width: il.iu * 2.3
                    spacing: 9 * Ui.f
                    Repeater {
                        model: il.fields()
                        Column {
                            width: parent.width
                            spacing: 9 * Ui.f
                            Focusable {
                                id: fb
                                property string key: "f" + modelData.id
                                property bool isField: true
                                readonly property bool cur: il.field === index
                                width: parent.width; height: fcol.implicitHeight + 14 * Ui.f + 4
                                onTriggered: il.field = index
                                Rectangle {
                                    anchors.fill: parent
                                    color: Ui.c.surfaceRaised
                                    border.width: 2
                                    border.color: fb.focused ? Ui.c.borderFocus : fb.cur ? Ui.c.borderMuted : Ui.c.borderSubtle
                                }
                                Column {
                                    id: fcol
                                    x: 12 * Ui.f + 2; y: 7 * Ui.f + 2; width: parent.width - 24 * Ui.f - 4
                                    Txt { width: parent.width; text: modelData.label; font.pixelSize: 12.5 * Ui.f; color: Ui.c.textDim }
                                    Row {
                                        height: 19 * Ui.f * 1.35
                                        Txt {
                                            id: fv
                                            text: { var v = il[modelData.id]; return modelData.secret ? "\u2022".repeat(v.length) : v }
                                            font.pixelSize: 19 * Ui.f
                                            width: Math.min(implicitWidth, fcol.width - 6)
                                            elide: Text.ElideLeft
                                            anchors.verticalCenter: parent.verticalCenter
                                        }
                                        Rectangle {
                                            visible: fb.cur
                                            width: 2; height: 19 * Ui.f * 1.05; color: Ui.c.textPrimary
                                            anchors.verticalCenter: parent.verticalCenter
                                            SequentialAnimation on opacity { running: fb.cur; loops: Animation.Infinite
                                                NumberAnimation { to: 1; duration: 0 } PauseAnimation { duration: 500 } NumberAnimation { to: 0; duration: 0 } PauseAnimation { duration: 500 } }
                                        }
                                    }
                                }
                            }
                            Rectangle {                              // Anmeldename (aus dem Namen gebildet)
                                visible: modelData.id === "name"
                                width: parent.width; height: lcol.implicitHeight + 14 * Ui.f
                                color: "transparent"
                                Column {
                                    id: lcol
                                    x: 12 * Ui.f + 2; y: 7 * Ui.f; width: parent.width - 24 * Ui.f
                                    Txt { width: parent.width; text: Ui.t("inst.login"); font.pixelSize: 12.5 * Ui.f; color: Ui.c.textDim }
                                    Txt { width: parent.width; text: il.loginOf(il.name); font.pixelSize: 19 * Ui.f; height: 19 * Ui.f * 1.35 }
                                }
                            }
                        }
                    }
                }
            }
            Group {
                title: Ui.t("inst.keyboard")
                Column {
                    spacing: 10 * Ui.f
                    Row {
                        spacing: 8 * Ui.f
                        Repeater {
                            model: ["de", "us", "gb"]
                            Pill { property string key: "km" + modelData; text: Ui.t("inst.kb." + modelData); on: il.keymap === modelData; onTriggered: il.setKeymap(modelData) }
                        }
                    }
                    Column {
                        id: kbd
                        spacing: 5 * Ui.f
                        readonly property real kc: il.iu * 0.3
                        readonly property real kg: 5 * Ui.f
                        readonly property var layouts: ({ de: ["1234567890ß", "qwertzuiopü", "asdfghjklöä", "yxcvbnm,.-"],
                                                          us: ["1234567890-", "qwertyuiop@", "asdfghjkl;'", "zxcvbnm,./"],
                                                          sym: ["!\"§$%&/()=?", "€@{}[]\\~*+#", ":;_<>|^°'`´", "²³µ«»¿¡¬¦"] })
                        readonly property var rows: il.sym ? layouts.sym : (layouts[il.keymap] || layouts.us)
                        // Tasten je Reihe: [Beschriftung, Aktion, Breite in Tasten, Schluessel, Zeichen]
                        readonly property var keyRows: {
                            var out = []
                            for (var r = 0; r < rows.length; r++) {
                                var row = []
                                if (r === 3) row.push(["\u21e7", "shift", 1, "kshift"])
                                for (var c = 0; c < rows[r].length; c++) row.push([rows[r][c], "char", 1, "k" + r + "-" + c, rows[r][c]])
                                if (r === 0) row.push(["\u232b", "del", 1, "kdel"])
                                else if (r === 3) row.push(["\u232b", "del", 1, "kdel2"])
                                else row.push([r === 1 ? "+" : "#", "char", 1, "kx" + r, r === 1 ? "+" : "#"])
                                out.push(row)
                            }
                            out.push([[il.sym ? "abc" : "&123", "sym", 2, "ksym"], [Ui.t("inst.space"), "char", 5, "kspace", " "], ["@", "char", 1, "kat", "@"],
                                      [Ui.t("inst.continue"), "go", 4, "kgo"]])
                            return out
                        }
                        Repeater {
                            model: kbd.keyRows
                            Row {
                                spacing: kbd.kg
                                Repeater {
                                    model: modelData
                                    Focusable {
                                        id: kk
                                        property string key: modelData[3]
                                        property bool pressFlash: true
                                        readonly property string label: modelData[1] === "char" && il.shift && modelData[4] !== " " ? modelData[0].toUpperCase() : modelData[0]
                                        width: modelData[2] * kbd.kc + (modelData[2] - 1) * kbd.kg
                                        height: kbd.kc
                                        onTriggered: {
                                            il.phys = false
                                            var a = modelData[1]
                                            if (a === "char") il.type(il.shift ? modelData[4].toUpperCase() : modelData[4])
                                            else if (a === "del") il.del()
                                            else if (a === "shift") il.shift = !il.shift
                                            else if (a === "sym") il.rerender(function () { il.sym = !il.sym })
                                            else if (a === "go") il.oskDone()
                                        }
                                        Rectangle {
                                            anchors.fill: parent
                                            color: modelData[1] === "go" ? Ui.c.statusOkBg : (modelData[1] === "shift" && il.shift) ? Ui.c.surfaceActive
                                                 : kk.focused ? Ui.c.surfaceCardHover : Ui.c.surfaceCard
                                            border.width: 2; border.color: kk.focused ? Ui.c.borderFocus : "transparent"
                                            Txt { anchors.centerIn: parent; text: kk.label; font.pixelSize: 17 * Ui.f; elide: Text.ElideNone }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
            Group {
                visible: il.step === "account"
                title: Ui.t("inst.greets")
                Column {
                    spacing: 12 * Ui.f
                    Rectangle {
                        width: il.iu * 1.9; height: pvRow.implicitHeight + 32 * Ui.f
                        color: Ui.c.surfaceRaised; border.width: 1; border.color: Ui.c.borderSubtle
                        Item {
                            id: pvRow
                            x: 16 * Ui.f; y: 16 * Ui.f; width: parent.width - 32 * Ui.f
                            implicitHeight: Math.max(pvT.implicitHeight, pvW.implicitHeight)
                            Txt { id: pvT; anchors.bottom: parent.bottom; text: app.cfg ? (Ui.l(app.cfg.title) || Ui.t("home.title")) : Ui.t("home.title"); font.pixelSize: 28 * Ui.f; font.weight: Font.Light }
                            Column {
                                id: pvW
                                anchors.right: parent.right; anchors.bottom: parent.bottom
                                Txt { anchors.right: parent.right; text: il.name; font.pixelSize: 16 * Ui.f; font.weight: Font.Light; width: Math.min(implicitWidth, pvRow.width * 0.5) }
                                Txt { anchors.right: parent.right; text: app.hdrTime; font.pixelSize: 12 * Ui.f; color: Ui.c.textDim }
                            }
                        }
                    }
                    Txt { width: il.iu * 1.9; text: Ui.t("inst.pwInfo"); font.pixelSize: 14 * Ui.f; color: Ui.c.textDim; wrapMode: Text.WordWrap; elide: Text.ElideNone; lineHeight: 1.4 }
                    Txt { width: il.iu * 1.9; text: Ui.t("inst.usbKb"); font.pixelSize: 14 * Ui.f; color: Ui.c.textDim; wrapMode: Text.WordWrap; elide: Text.ElideNone; lineHeight: 1.4 }
                }
            }
        }
    }
    Component {
        id: cDevice
        Steps {
            Group {
                title: Ui.t("inst.device")
                TileGrid {
                    items: { il.host; il.channel; il.wifi; il.share; il.lang; il.tz; il.favs; il.rtc; return il.deviceTiles() }
                    rows: 3; cellW: il.iu; cellH: il.iu; delegate: tileDelegate
                }
            }
        }
    }
    Component {
        id: cConfirm
        Steps {
            Group { title: Ui.t("inst.summary"); IPanel { u: il.iu; wide: true; rows: il.summary() } }
            Group {
                title: Ui.t("inst.install")
                TileGrid {
                    rows: 3; cellW: il.iu; cellH: il.iu; delegate: tileDelegate
                    items: [{ kind: "hold", size: "large", color: il.mode === "whole" ? "#6e2b2b" : "#2f6d4f", key: "hold", act: "hold", icon: "install",
                              label: il.mode === "whole" ? Ui.t("inst.eraseInstall") : Ui.t("inst.justInstall"), sub: il.mode === "whole" ? Ui.t("inst.eraseSub") : "" },
                            { kind: "tile", color: "#3a3f46", icon: "back", label: Ui.t("inst.change"), key: "change", act: "change" }]
                }
            }
        }
    }
    Component {
        id: cProgress
        Steps {
            id: prog
            readonly property var ph: { il.status; return il.phases() }
            readonly property var st: il.status || {}
            readonly property bool whole: (st.mode || il.mode) === "whole"
            Group {
                title: Ui.t("inst.installing")
                Rectangle {
                    width: il.iu * 2.9; height: il.iu * 2 + Ui.gap
                    color: prog.whole ? "#6e2b2b" : "#2f6d4f"
                    Rectangle {
                        anchors.fill: parent
                        gradient: Gradient { GradientStop { position: 0; color: "#14ffffff" } GradientStop { position: 0.45; color: "#00ffffff" } GradientStop { position: 1; color: "#33000000" } }
                    }
                    Column {
                        id: progTop
                        x: 22 * Ui.f; y: 20 * Ui.f; width: parent.width - 44 * Ui.f
                        height: progBottom.y - y - 10 * Ui.f       // Erklaerung endet ueber dem Balken
                        clip: true
                        spacing: 4 * Ui.f
                        Txt { width: parent.width; text: Ui.t(prog.whole ? "inst.progCapWhole" : "inst.progCap"); font.pixelSize: 15 * Ui.f; color: Ui.c.textSecondary }
                        Txt { text: Ui.pct(Math.round(prog.st.pct || 0)); font.pixelSize: il.iu * 0.55; font.weight: Font.Light; elide: Text.ElideNone }
                        Txt { width: parent.width; text: prog.ph.cur ? Ui.t("inst.ph." + prog.ph.cur) : Ui.t("inst.starting"); font.pixelSize: 18 * Ui.f }
                        Txt {
                            width: parent.width; font.pixelSize: 14 * Ui.f; color: Ui.c.textSecondary; height: Math.max(implicitHeight, 14 * Ui.f * 1.3)
                            text: prog.ph.cur === "copy" && prog.st.copy && prog.st.copy.total
                                  ? Ui.t("inst.copyOf", { done: il.gb(prog.st.copy.done || 0), total: il.gb(prog.st.copy.total) }) + " · " + Ui.pct(Math.round(prog.st.phase_pct || 0)) : ""
                        }
                        Txt { width: parent.width * 0.95; text: Ui.t("inst.phx." + (prog.ph.cur || "check")); font.pixelSize: 15 * Ui.f; wrapMode: Text.WordWrap
                              lineHeight: 1.3; topPadding: 8 * Ui.f
                              maximumLineCount: Math.max(1, Math.floor((progTop.height - y - 8 * Ui.f) / (15 * Ui.f * 1.3 * 1.17))) }
                    }
                    Column {
                        id: progBottom
                        x: 22 * Ui.f; width: parent.width - 44 * Ui.f
                        anchors.bottom: parent.bottom; anchors.bottomMargin: 20 * Ui.f
                        spacing: 6 * Ui.f
                        Rectangle {
                            width: parent.width; height: 8 * Ui.f; color: "#4d000000"
                            Rectangle { height: parent.height; color: "#ffffff"; width: parent.width * Math.min(100, prog.st.pct || 0) / 100
                                        Behavior on width { NumberAnimation { duration: 500 } } }
                        }
                        Txt {
                            width: parent.width; font.pixelSize: 14 * Ui.f; color: Ui.c.textSecondary
                            text: { var eta = prog.st.copy ? prog.st.copy.eta : 0
                                    return prog.st.phase === "copy" && eta ? (eta > 90 ? Ui.t("inst.etaShort", { min: Math.max(2, Math.round((eta + 60) / 60)) }) : Ui.t("inst.etaSoonShort")) : "" }
                        }
                        Txt { width: parent.width; text: Ui.t("inst.dontOffCaps"); font.pixelSize: 14 * Ui.f; font.weight: Font.DemiBold; wrapMode: Text.WordWrap; elide: Text.ElideNone }
                    }
                }
            }
            Group {
                title: Ui.t("inst.steps")
                Column {
                    spacing: 6 * Ui.f
                    Repeater {
                        model: prog.ph.rows
                        Rectangle {
                            width: il.iu * 2.6; height: il.iu * 0.36
                            color: modelData.state === "error" ? Ui.c.statusDangerBg : modelData.state === "run" ? Ui.c.surfaceCard : Ui.c.surfaceRaised
                            clip: true
                            Row {
                                x: 16 * Ui.f; anchors.verticalCenter: parent.verticalCenter
                                width: parent.width - 32 * Ui.f
                                spacing: 14 * Ui.f
                                Item {
                                    width: 20 * Ui.f; height: 20 * Ui.f; anchors.verticalCenter: parent.verticalCenter
                                    Txt { anchors.centerIn: parent; visible: modelData.state !== "run"; elide: Text.ElideNone; font.pixelSize: 16 * Ui.f
                                          text: modelData.state === "done" ? "\u2713" : modelData.state === "error" ? "\u2715" : "\u00b7"
                                          color: modelData.state === "done" ? Ui.c.statusOkText : modelData.state === "error" ? Ui.c.statusDangerText : Ui.c.textDim }
                                    Spinner { anchors.centerIn: parent; visible: modelData.state === "run"; size: 14 * Ui.f; line: 2 }
                                }
                                Txt { text: Ui.t("inst.ph." + modelData.id); font.pixelSize: 16 * Ui.f; anchors.verticalCenter: parent.verticalCenter; elide: Text.ElideNone
                                      color: modelData.state === "error" ? Ui.c.statusDangerText : modelData.state === "run" || modelData.state === "done" ? Ui.c.textPrimary : Ui.c.textDim }
                                Txt { text: modelData.dt; font.pixelSize: 13 * Ui.f; color: Ui.c.textFaint; anchors.verticalCenter: parent.verticalCenter }
                            }
                            Rectangle {
                                visible: modelData.state === "run"
                                anchors.bottom: parent.bottom; height: 3 * Ui.f; color: Ui.c.textPrimary
                                width: parent.width * Math.round(prog.st.phase_pct || 0) / 100
                                Behavior on width { NumberAnimation { duration: 500 } }
                            }
                        }
                    }
                    Txt {
                        width: il.iu * 2.6; topPadding: 10 * Ui.f; font.pixelSize: 14 * Ui.f; color: Ui.c.textDim; wrapMode: Text.WordWrap; elide: Text.ElideNone; lineHeight: 1.4
                        textFormat: Text.StyledText
                        text: "<font color='" + Ui.c.textFaint + "'>" + Ui.esc(Ui.t("inst.goodToKnow")) + "</font> "
                              + Ui.t(["inst.tip1", "inst.tip2", "inst.tip3", "inst.tip4"][Math.floor(il.tipN / 8)], { host: Ui.esc(il.host) })
                    }
                    Txt {
                        width: il.iu * 2.6; font.pixelSize: 14 * Ui.f; color: Ui.c.textDim; wrapMode: Text.WordWrap; elide: Text.ElideNone; lineHeight: 1.4
                        textFormat: Text.StyledText
                        text: "<font color='" + Ui.c.textFaint + "'>" + Ui.esc(Ui.t("radio.title")) + "</font> "
                              + Ui.esc(app.radioState.station ? app.radioState.station.name + " · " + Ui.t("inst.radioOn") : Ui.t("inst.radioNone"))
                    }
                }
            }
        }
    }
    Component {
        id: cError
        Steps {
            readonly property var es: { il.status; return il.errorState() }
            Group { title: Ui.t("inst.whatHappened"); IPanel { u: il.iu; rows: es.what } }
            Group { title: Ui.t("inst.diskState"); IPanel { u: il.iu; rows: es.lines } }
            Group { title: Ui.t("inst.whatNow"); TileGrid { items: es.acts; rows: 3; cellW: il.iu; cellH: il.iu; delegate: tileDelegate } }
        }
    }
    Component {
        id: cDone
        Steps {
            readonly property var r: (il.status || {}).result || {}
            readonly property int secs: r.seconds || Math.round((Date.now() - (il.t0 || Date.now())) / 1000)
            Group {
                title: Ui.t("inst.whatNow")
                TileGrid {
                    rows: 2; cellW: il.iu; cellH: il.iu; delegate: tileDelegate
                    items: [{ kind: "tile", size: "large", color: "#2f6d4f", icon: "restart", label: Ui.t("inst.rebootNow"), key: "reboot", act: "reboot" }]
                }
            }
            Group {
                title: Ui.t("inst.afterReboot")
                IPanel {
                    u: il.iu; wide: true
                    rows: [{ k: Ui.t("inst.loginAuto"), v: Ui.t("inst.loginAutoText", { name: r.user || il.name }) },
                           il.share ? { k: Ui.t("inst.whatShare"), v: Ui.t("inst.shareText", { host: r.hostname || il.host, login: r.login || il.loginOf(il.name) }) } : null,
                           { k: Ui.t("inst.sumUpdates"), v: Ui.t("inst.updText", { channel: il.chName() }) },
                           secs ? { k: Ui.t("inst.duration"), v: Ui.t("inst.durationText", { min: Math.floor(secs / 60), sec: secs % 60 }) } : null,
                           { k: Ui.t("inst.tip"), v: Ui.t("inst.tipText") }]
                }
            }
        }
    }
}
