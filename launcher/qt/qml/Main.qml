// SPDX-License-Identifier: GPL-3.0-or-later
// VoidStation-Startseite (Qt). Aufbau und Verhalten wie web/index.html:
// Startseite mit Kachelgruppen, darueber Ebenen (Radio, Fernsehen, Spiele, AppCenter, Einstellungen),
// Dialoge, Bildschirmtastatur, Startbildschirm beim Programmstart, Hinweiszeile, Meldungen.
import QtQuick
import QtQuick.Window
import VS

Window {
    id: win
    title: vsTitle
    width: vsW > 0 ? vsW : Screen.width > 0 ? Screen.width : 1280
    height: vsH > 0 ? vsH : Screen.height > 0 ? Screen.height : 720
    visible: true
    visibility: vsDemo || vsW > 0 ? Window.Windowed : Window.FullScreen
    flags: Qt.Window | Qt.FramelessWindowHint
    color: Ui.c.bgMain
    onActiveChanged: {
        if (active) { app.forceActiveFocus(); app.poll() }
        else if (app.splashTile) hideSplashLater.restart()     // Programm hat ein Fenster: Startbildschirm weg
    }
    Timer { id: hideSplashLater; interval: 400; onTriggered: if (!win.active) app.hideSplash() }

    Item {
        id: app
        anchors.fill: parent
        focus: true

        // ------------------------------------------------------------ Zustand
        property var cfg: null
        property var running: []
        property var radioState: ({ station: null, title: null })
        property var tvNow: null
        property var updInfo: null
        property string updToasted: ""
        property var sett: null
        property bool live: false
        property real volLevel: 0
        property string volText: ""
        property bool volOk: true
        property var favs: []
        property var splashTile: null
        property real splashT0: 0
        property bool launching: false
        property var jobState: null
        property string clockMain: ""
        property string clockAp: ""
        property string clockDate: ""
        property string hdrTime: ""
        property bool started: false

        Component.onCompleted: {
            Ui.app = app
            layout()
            init()
        }

        // ------------------------------------------------------------ Masse
        function layout() {
            var H = win.height, W = win.width
            if (!H || !W) return
            Ui.screenW = W; Ui.screenH = H
            var r = H / 768, f = Ui.scale * r
            Ui.f = f
            Ui.padX = W * 0.06
            Ui.hintH = hint.height + 22 * f
            var stageH = H - homeHeader.height - Ui.hintH
            var titleH = 18 * f * 1.36 + 14 * f
            var avail = stageH - titleH
            var gap = 10 * f, want = 161 * r * (1 + (Ui.scale - 1) * 0.55), rows = 3, u = want
            for (rows = 3; rows >= 1; rows--) {
                var fit = (avail - gap * (rows - 1)) / rows
                if (rows === 1 || fit >= want * 0.82) { u = Math.min(want, fit); break }
            }
            Ui.u = Math.max(60, u)
            Ui.rows = Math.max(1, rows)
            if (Nav.current) Qt.callLater(function () { if (Nav.current) Nav.setFocus(Nav.current, true) })
        }
        Connections { target: win; function onWidthChanged() { Qt.callLater(app.layout) } function onHeightChanged() { Qt.callLater(app.layout) } }
        Connections { target: hint; function onHeightChanged() { Qt.callLater(app.layout) } }

        // ------------------------------------------------------------ Ebenen
        readonly property var layerOrder: [osk, adlg, powerDlg, roms, tv, apps, radio, settings]
        property string layerName: "home"
        property Item layerRoot: homeView
        function updateLayer() {
            var n = "home", r = homeView
            if (osk.open) { n = "osk"; r = osk }
            else if (adlg.open) { n = "adlg"; r = adlg }
            else if (powerDlg.open) { n = "dialog"; r = powerDlg }
            else if (roms.open) { n = "roms"; r = roms }
            else if (tv.open) { n = "tv"; r = tv }
            else if (apps.open) { n = "apps"; r = apps }
            else if (radio.open) { n = "radio"; r = radio }
            else if (settings.open) { n = "settings"; r = settings }
            layerName = n; layerRoot = r
        }
        function curTrack() {
            return ({ home: homeTrack, radio: radio.track, tv: tv.track, apps: null, settings: settings.track, roms: roms.track })[layerName] || null
        }
        function navItems() { return Nav.collect(layerRoot) }
        function setFocus(item, instant) { Nav.setFocus(item, instant, layerName) }
        function focusFirst(root, scope, instant) {
            var m = Nav.remembered(scope, root)
            if (m) return setFocus(m, instant)
            var it = Nav.collect(root)
            if (it.length) setFocus(it[0], instant)
        }
        function openLayer(ly) {
            ly.show()
            updateLayer()
            Qt.callLater(function () {
                var f = ly.firstFocus ? ly.firstFocus() : null
                var m = Nav.remembered(ly.scope, ly)
                setFocus(m || f || Nav.collect(ly)[0], true)
            })
        }
        function closeLayer(ly) {
            ly = ly || layerRoot
            if (!ly || ly === homeView) return
            ly.hide(function () {
                updateLayer()
                var m = Nav.remembered(layerName, layerRoot)
                setFocus(m || (layerRoot === homeView ? firstHomeTile() : Nav.collect(layerRoot)[0]), true)
            })
            updateLayer()
            var m2 = Nav.remembered(layerName, layerRoot)
            if (m2) setFocus(m2, true)
        }
        function firstHomeTile() { var it = Nav.collect(homeTrack); return it.length ? it[0] : null }

        // ------------------------------------------------------------ Navigation
        function move(dir) {
            if (splashTile) return
            if (layerName === "adlg" && (dir === "up" || dir === "down")) return adlg.scrollText(dir === "down" ? 1 : -1)
            if (layerRoot.navMove && layerRoot.navMove(dir)) return
            var items = navItems()
            if (!Nav.current || items.indexOf(Nav.current) < 0) { if (items.length) setFocus(items[0]); return }
            var best = Nav.nearest(Nav.current, items, dir)
            if (best) setFocus(best)
        }
        function activate(el) {
            el = el || Nav.current
            if (!el || splashTile) return
            if (!Nav.alive(el, layerRoot)) return
            if (el.pressFlash) { el.pressedNow = true; unpress.target = el; unpress.restart() }
            el.activate()
        }
        Timer { id: unpress; interval: 150; property Item target; onTriggered: if (target) target.pressedNow = false }
        function back() {
            if (splashTile) return splashToBackground()
            if (layerName === "osk") return osk.close()
            if (layerName === "adlg") return adlg.close()
            if (layerName === "dialog") return powerDlg.close()
            if (layerRoot.handleBack && layerRoot.handleBack()) return
            if (layerName !== "home") closeLayer()
        }
        function secondary() {
            if (layerName === "osk") return osk.backspace()
            if (layerName === "home" && Nav.current && Nav.current.t) {
                var t = Nav.current.t
                if (running.indexOf(t.id) >= 0) closeApp(t)
                else if (t.cmd) toast(Ui.t("home.notOpen", { name: Ui.l(t.label) }))
                else toast(Ui.t("home.cantClose"))
                return
            }
            if (layerRoot.secondary) layerRoot.secondary()
        }
        function jumpGroup(dir) {
            if (splashTile) return
            if (layerRoot.jump) return layerRoot.jump(dir)
            var tr = curTrack()
            if (!tr) return
            var groups = tr.groupList().filter(function (g) { return Nav.collect(g).length > 0 })
            if (!groups.length) return
            var cur = Nav.current ? tr.groupOf(Nav.current) : null
            var i = groups.indexOf(cur)
            i = i < 0 ? (dir > 0 ? 0 : groups.length - 1) : Math.max(0, Math.min(groups.length - 1, i + dir))
            if (groups[i] === cur) return
            var first = Nav.collect(groups[i])
            if (first.length) setFocus(first[0])
        }
        function mouseFocus(item) {
            if (splashTile || !Nav.alive(item, layerRoot) || Nav.current === item) return
            if (item.noHoverFocus) return
            setFocus(item)
        }
        function mouseClick(item, button) {
            if (splashTile) return splashToBackground()
            if (!Nav.alive(item, layerRoot) && !(item.navigable === false && item.visible)) return
            if (button === Qt.RightButton) {
                if (layerName === "home" && item.t && running.indexOf(item.t.id) >= 0) return closeApp(item.t)
                return back()
            }
            if (item.clickActivate) return item.clickActivate()
            if (item.navigable) setFocus(item)
            activate(item)
        }
        function mousePress(item) { if (Nav.alive(item, layerRoot) && item.pressFlash) item.pressedNow = true }
        function mouseRelease(item) { item.pressedNow = false }

        Keys.onPressed: function (e) {
            var k = e.key
            if (layerName === "osk" && osk.key(e)) { e.accepted = true; return }
            e.accepted = true
            if (k === Qt.Key_Left) move("left")
            else if (k === Qt.Key_Right) move("right")
            else if (k === Qt.Key_Up) move("up")
            else if (k === Qt.Key_Down) move("down")
            else if (k === Qt.Key_Return || k === Qt.Key_Enter || k === Qt.Key_Space) { if (!e.isAutoRepeat) activate() }
            else if (k === Qt.Key_Escape || k === Qt.Key_Backspace || k === Qt.Key_Back) back()
            else if (k === Qt.Key_Delete || k === Qt.Key_F || k === Qt.Key_Y) secondary()
            else if (k === Qt.Key_PageDown) jumpGroup(1)
            else if (k === Qt.Key_PageUp) jumpGroup(-1)
            else if (k === Qt.Key_U) openUpdate()
            else if (k === Qt.Key_Plus || k === Qt.Key_VolumeUp) volume("up")
            else if (k === Qt.Key_Minus || k === Qt.Key_VolumeDown) volume("down")
            else e.accepted = false
        }
        Connections {
            target: vs
            function onPadKey(k) {
                if (app.layerName === "osk") return osk.pad(k)
                if (k === "a") app.activate()
                else if (k === "b") app.back()
                else if (k === "x" || k === "y") app.secondary()
                else if (k === "lb") app.volume("down")
                else if (k === "rb") app.volume("up")
                else if (k === "lt") app.jumpGroup(-1)
                else if (k === "rt") app.jumpGroup(1)
                else if (k === "select") app.openUpdate()
                else if (k === "start") { if (app.layerName === "dialog") powerDlg.close(); else powerDlg.openDlg() }
                else app.move(k)
            }
            function onPadConnected(name) { app.toast(Ui.t("pad.connected", { name: name })) }
        }

        // ------------------------------------------------------------ Start
        function init() {
            Api.get("/api/settings", function (s) {
                sett = s
                Ui.scale = s.scale || 1.75
                live = !!s.live
                vs.setLang(s.lang || "de")
                vs.setTheme(s.theme || "default-dark")
                layout()
                loadFavs()
                load()
                poll()
                started = true
            }, function () { retryInit.restart() })
        }
        Timer { id: retryInit; interval: 1000; onTriggered: app.init() }

        function load(keepFocus) {
            Api.get("/tiles.json", function (c) {
                var prevId = Nav.current && Nav.current.t ? Nav.current.t.id : (Nav.memory.home && Nav.memory.home.t ? Nav.memory.home.t.id : "")
                cfg = c
                Qt.callLater(function () {
                    var items = Nav.collect(homeTrack), again = null
                    for (var i = 0; i < items.length; i++) if (items[i].t && items[i].t.id === prevId) again = items[i]
                    again = again || items[0]
                    if (layerName === "home") setFocus(again, true); else Nav.memory.home = again
                })
            })
        }
        function loadFavs() { Api.get("/api/radio/favs", function (j) { favs = j || [] }) }

        // Uhr
        function tick() {
            var d = new Date()
            if (Ui.lang === "de") { clockMain = Qt.formatTime(d, "HH:mm"); clockAp = "" }
            else { clockMain = Qt.formatTime(d, "h:mm"); clockAp = d.getHours() < 12 ? "AM" : "PM" }
            hdrTime = clockAp ? clockMain + " " + clockAp : clockMain
            clockDate = Ui.lang === "de" ? Ui.loc.toString(d, "dddd, d. MMMM") : Ui.loc.toString(d, "dddd, MMMM d")
        }
        Timer { interval: 5000; running: true; repeat: true; triggeredOnStart: true; onTriggered: app.tick() }
        Connections { target: vs; function onStringsChanged() { app.tick() } }

        // Zustand vom Launcher
        function poll() {
            if (!started) return
            Api.get("/api/status", function (s) {
                running = s.running || []
                setRadio(s.radio || {})
                setTvNow(s.tv)
                showUpdBadge(s.update)
                if (splashTile) splashCheck(s)
            })
        }
        Timer { interval: 1500; running: app.started; repeat: true; onTriggered: app.poll() }

        function setRadio(s) { radioState = { station: s.station || null, title: s.title || null } }
        function setTvNow(n) {
            var prev = tvNow ? tvNow.key : null
            tvNow = n || null
            if (prev !== (tvNow ? tvNow.key : null)) tv.tvSwitched()
        }

        // ------------------------------------------------------------ Programme
        readonly property var emuSystems: ["gba", "snes", "snes9x", "nes", "nestopia", "psx", "duckstation", "psp", "ppsspp", "nds", "melonds", "dreamcast", "flycast", "gamecube", "dolphin", "c64", "vice", "atari2600", "stella"]
        function tileActivate(t, el) {
            if (t.type === "radio") return openLayer(radio)
            if (t.type === "settings") return openLayer(settings)
            if (t.type === "tv") return openLayer(tv)
            if (t.type === "apps") return openLayer(apps)
            if (t.type === "roms") return roms.openFor(t)
            if (t.type === "install") return toast(Ui.t("qt.installerWeb"))
            if (emuSystems.indexOf(t.id) >= 0) {
                return Api.get("/api/roms?system=" + encodeURIComponent(t.id), function (r) {
                    if (r && (r.count > 0 || (r.roms && r.roms.length))) roms.openFor(t); else launch(t)
                }, function () { launch(t) })
            }
            launch(t)
        }
        function launch(t) {
            if (launching || !t.cmd) return
            var already = running.indexOf(t.id) >= 0
            if (!already) showSplash(t)
            launching = true
            Api.post("/api/launch/" + encodeURIComponent(t.id), null, function (r) {
                if (r && r.running) running = r.running
            }, function () {
                toast(Ui.t("home.launchFailed", { name: Ui.l(t.label) || Ui.t("common.program") }), true)
                hideSplash()
            })
            unlaunch.restart()
        }
        Timer { id: unlaunch; interval: 600; onTriggered: app.launching = false }
        function closeApp(t) {
            Api.post("/api/close/" + encodeURIComponent(t.id), null, function (r) {
                running = r.running || []
                toast(Ui.t("home.closed", { name: Ui.l(t.label) || Ui.t("common.program") }))
            }, function () { toast(Ui.t("home.closeFailed"), true) })
        }
        function showSplash(t) {
            splashTile = t
            splashT0 = Date.now()
            splash.hint = ""
            splash.keyShown = false
        }
        function splashCheck(s) {
            var t = splashTile, secs = (Date.now() - splashT0) / 1000
            if ((s.running || []).indexOf(t.id) < 0) {
                if (secs < 2) return
                hideSplash()
                return toast(Ui.t("home.exited", { name: Ui.l(t.label), id: t.id }), true)
            }
            if ((s.starting || []).indexOf(t.id) < 0) return hideSplash()
            if (secs > 5) {
                splash.hint = t.start_hint ? Ui.t("app." + t.id + ".hint", null, t.start_hint) : Ui.t("home.slow")
                splash.keyShown = true
            }
        }
        function hideSplash() { splashTile = null }
        function splashToBackground() {
            var t = splashTile
            hideSplash()
            if (t) toast(Ui.t("home.background", { name: Ui.l(t.label) }))
        }

        // ------------------------------------------------------------ Lautstaerke, Ausschalten, Meldungen
        function showVol(v) {
            if (!v || v.level === undefined) { volOk = false; volText = Ui.t("vol.none"); return }
            volOk = true
            volLevel = v.level
            volText = v.muted ? Ui.t("vol.muted") : Ui.pct(v.level)
        }
        function volume(action) { Api.post("/api/volume/" + action, null, showVol) }
        function refreshVolume() { Api.get("/api/volume", showVol) }
        function power(action) {
            if (powerDlg.open) powerDlg.close()
            toast(action === "reboot" ? Ui.t("power.rebooting") : Ui.t("power.shuttingDown"))
            Api.post("/api/power/" + action, null, null, function () { toast(Ui.t("common.failed"), true) })
        }
        function toast(msg, err) { toastBox.show(String(msg), !!err) }

        // Update verfuegbar: gelber Hinweis unten rechts (U / Select)
        function updNoteText(u) {
            return u.version ? Ui.t("upd.note", { version: u.version })
                 : u.system ? Ui.t("upd.noteSystem", { n: Ui.num(u.system) }) : u.reboot ? Ui.t("upd.noteReboot") : Ui.t("upd.badgeGeneric")
        }
        function showUpdBadge(u) {
            var on = !!(u && (u.available || u.reboot))
            updInfo = on ? u : null
            if (on && u.version && updToasted !== u.version && layerName === "home") { updToasted = u.version; toast(Ui.t("upd.toast")) }
        }
        function openUpdate() {
            if (!updInfo || splashTile || ["home", "radio", "tv", "apps", "settings"].indexOf(layerName) < 0) return
            if (layerName !== "settings") {
                for (var i = 0; i < layerOrder.length; i++) if (layerOrder[i].open && layerOrder[i] !== settings) layerOrder[i].hide()
                openLayer(settings)
            }
            settings.openCat("updates")
            runUpdatesLater.restart()
        }
        Timer { id: runUpdatesLater; interval: 400; onTriggered: settings.runUpdates() }

        // Auftraege (AppCenter, Updates)
        readonly property bool jobBusy: !!jobState && jobState.state === "running"
        function jobStart(action, a) {
            Api.post("/api/apps/" + action, a ? { id: a.id } : null, function (j) { jobState = j; watchJob() },
                     function (e) { toast(e, true) })
        }
        function watchJob() { jobBand.watch() }

        function openOsk(field) { osk.openFor(field) }
        function dialog(title, text, buttons) { adlg.openDlg(title, text, buttons) }
        function rebootPrompt(rb) {
            dialog(Ui.t("upd.doneTitle"), rb && rb.kernel ? Ui.t("upd.doneTextKernel") : Ui.t("upd.doneText"),
                   [[Ui.t("upd.rebootNow"), function () { app.power("reboot") }], [Ui.t("common.later")]])
        }

        // ------------------------------------------------------------ Startseite
        Background { anchors.fill: parent; wallpaper: app.cfg && app.cfg.background ? Ui.url(app.cfg.background) : "" }

        Item {
            id: homeView
            anchors.fill: parent
            property string scope: "home"
            Item {
                id: homeHeader
                x: Ui.padX
                width: parent.width - 2 * Ui.padX
                height: 34 * Ui.f + Math.max(h1.height, who.height) + 20 * Ui.f
                Txt {
                    id: h1
                    anchors.bottom: parent.bottom; anchors.bottomMargin: 20 * Ui.f
                    text: app.cfg ? (Ui.l(app.cfg.title) || Ui.t("home.title")) : ""
                    font.pixelSize: 52 * Ui.f
                    font.weight: Font.Light
                    elide: Text.ElideNone
                }
                Row {
                    id: who
                    anchors.right: parent.right
                    anchors.bottom: parent.bottom; anchors.bottomMargin: 20 * Ui.f
                    spacing: 16 * Ui.f
                    ScrollInd { track: homeTrack; anchors.verticalCenter: parent.verticalCenter }
                    Item { width: 2 * Ui.screenW * 0.01 - 16 * Ui.f; height: 1; visible: homeTrack.scrollable }
                    Column {
                        anchors.verticalCenter: parent.verticalCenter
                        Txt { anchors.right: parent.right; text: app.cfg ? Ui.l(app.cfg.user) : ""; font.pixelSize: 21 * Ui.f; font.weight: Font.Light }
                        Txt { anchors.right: parent.right; text: app.hdrTime; font.pixelSize: 15 * Ui.f; color: Ui.c.textDim }
                    }
                    RoundBtn {
                        id: powerBtn
                        iconName: "powerbtn"
                        navOnlyUp: true
                        anchors.verticalCenter: parent.verticalCenter
                        onTriggered: powerDlg.openDlg()
                    }
                }
            }
            Track {
                id: homeTrack
                anchors.top: homeHeader.bottom
                anchors.left: parent.left; anchors.right: parent.right
                anchors.bottom: parent.bottom; anchors.bottomMargin: Ui.hintH
                Repeater {
                    model: app.cfg ? app.cfg.groups : []
                    Group {
                        id: grp
                        title: Ui.l(modelData.name)
                        property int base: {
                            var n = 0
                            for (var i = 0; i < index; i++) n += (app.cfg.groups[i].tiles || []).length
                            return n
                        }
                        TileGrid {
                            items: modelData.tiles || []
                            rows: Ui.rows
                            delegate: Component {
                                HomeTile {
                                    property var tile: modelData
                                    t: tile
                                    enterDelay: (grp.base + index) * 45
                                    running: app.running.indexOf(tile.id) >= 0
                                    playing: tile.type === "radio" ? !!app.radioState.station : tile.type === "tv" ? !!app.tvNow : false
                                    nowMain: tile.type === "radio" ? (app.radioState.station ? app.radioState.station.name : "")
                                           : tile.type === "tv" && app.tvNow ? app.tvNow.name : ""
                                    nowSub: tile.type === "radio" ? (app.radioState.station ? (app.radioState.title || Ui.t("common.live")) : "")
                                          : tile.type === "tv" && app.tvNow ? (app.tvNow.country ? Ui.regionName(app.tvNow.country) : Ui.t("common.live")) : ""
                                    clockMain: app.clockMain
                                    clockAp: app.clockAp
                                    clockDate: app.clockDate
                                    onTriggered: app.tileActivate(tile, this)
                                }
                            }
                        }
                    }
                }
            }
        }

        // ------------------------------------------------------------ Ebenen
        RadioLayer { id: radio; anchors.fill: parent }
        SettingsLayer { id: settings; anchors.fill: parent }
        AppsLayer { id: apps; anchors.fill: parent }
        TvLayer { id: tv; anchors.fill: parent }
        RomsLayer { id: roms; anchors.fill: parent }

        JobBand { id: jobBand }
        HintBar { id: hint }
        AppDialog { id: adlg; anchors.fill: parent }
        PowerDialog { id: powerDlg; anchors.fill: parent }
        Osk { id: osk; anchors.fill: parent }
        Splash { id: splash; anchors.fill: parent; tile: app.splashTile }
        Toast { id: toastBox }
    }
}
