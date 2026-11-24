// SPDX-License-Identifier: GPL-3.0-or-later
// VoidStation-Startseite (Qt):
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
        if (active) { corner.close(); music.close(); kbd.close("Startseite vorn"); app.forceActiveFocus(); app.poll() }
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
        property var mediaNow: null
        property var vpn: null                    // Mullvad VPN (/api/status "vpn"): installed, state, cc, city …
        property real tvFailedT: 0
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
        property bool shown: false                // Kacheln gezeichnet: Ladebild weg

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
            // Der Installer ist dichter als die anderen Seiten: Schrift hoechstens so gross wie Skalierung 1,15
            var sc = layerName === "inst" ? Math.min(Ui.scale, 1.15) : Ui.scale
            var r = H / 768, f = sc * r
            Ui.f = f
            Ui.padX = W * 0.06
            Ui.hintH = hint.height + 22 * f
            var stageH = H - homeHeader.height - Ui.hintH
            var titleH = 18 * f * 1.36 + 14 * f
            var avail = stageH - titleH
            var gap = 10 * f, want = 161 * r * (1 + (sc - 1) * 0.55), rows = 3, u = want
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
        readonly property var layerOrder: [osk, adlg, powerDlg, keymap, emuopts, roms, tv, vpnLayer, apps, radio, settings, inst]
        property string layerName: "home"
        property Item layerRoot: homeView
        function updateLayer() {
            var n = "home", r = homeView
            if (kbd.visible) { n = "kbd"; r = kbd.root }          // Tastatur ueber einem Programm (eigenes Fenster)
            else if (osk.open) { n = "osk"; r = osk }
            else if (adlg.open) { n = "adlg"; r = adlg }
            else if (powerDlg.open) { n = "dialog"; r = powerDlg }
            else if (chd.open) { n = "chd"; r = chd }               // Karte "in CHD umwandeln" ueber der Spieleliste
            else if (keymap.open) { n = "keymap"; r = keymap }
            else if (emuopts.open) { n = "emuopts"; r = emuopts }
            else if (roms.open) { n = "roms"; r = roms }
            else if (tv.open) { n = "tv"; r = tv }
            else if (vpnLayer.open) { n = "vpn"; r = vpnLayer }
            else if (apps.open) { n = "apps"; r = apps }
            else if (radio.open) { n = "radio"; r = radio }
            else if (settings.open) { n = "settings"; r = settings }
            else if (inst.open) { n = "inst"; r = inst }            // Installer liegt unter den anderen Ebenen
            var relayout = (n === "inst") !== (layerName === "inst")
            layerName = n; layerRoot = r
            if (relayout) layout()
        }
        function curTrack() {
            return ({ home: homeTrack, radio: radio.track, tv: tv.track, apps: null, settings: settings.track, roms: roms.track, keymap: keymap.track, emuopts: emuopts.track, vpn: vpnLayer.track, inst: inst.track })[layerName] || null
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
            var prev = Nav.current
            if (layerName === "adlg" && (dir === "up" || dir === "down")) return adlg.scrollText(dir === "down" ? 1 : -1)
            if (layerRoot.navMove && layerRoot.navMove(dir)) {
                if (Nav.current && Nav.current !== prev) vs.playSound("navigate")
                return
            }
            var items = navItems()
            if (!Nav.current || items.indexOf(Nav.current) < 0) { if (items.length) { setFocus(items[0]); vs.playSound("navigate") } return }
            var best = Nav.nearest(Nav.current, items, dir)
            if (best) { setFocus(best); if (best !== prev) vs.playSound("navigate") }
        }
        function activate(el) {
            el = el || Nav.current
            if (!el || splashTile) return
            if (!Nav.alive(el, layerRoot)) return
            var snd = el.sound !== undefined ? el.sound : "select"
            if (snd === "toggle") { if (el.on !== true || el.toggleFlip === true) vs.playSound("toggle") }
            else if (snd) vs.playSound(snd)
            if (el.pressFlash) { el.pressedNow = true; unpress.target = el; unpress.restart() }
            el.activate()
        }
        Timer { id: unpress; interval: 150; property Item target; onTriggered: if (target) target.pressedNow = false }
        function back() {
            if (splashTile) { vs.playSound("back"); return splashToBackground() }
            if (layerName === "osk") { vs.playSound("back"); return osk.close() }
            if (layerName === "adlg") { vs.playSound("back"); return adlg.close() }
            if (layerName === "dialog") { vs.playSound("back"); return powerDlg.close() }
            if (layerRoot.handleBack && layerRoot.handleBack()) { vs.playSound("back"); return }
            if (layerName !== "home") { vs.playSound("back"); closeLayer() }
        }
        function secondary() {
            if (layerName === "osk") return osk.backspace()
            if (layerName === "home" && Nav.current && (Nav.current.isVpnIcon || (Nav.current.t && Nav.current.t.type === "vpn"))) {
                if (vpn && vpn.state !== "nodaemon") vpnToggle()
                return
            }
            if (layerName === "home" && Nav.current && Nav.current.t) {
                var t = Nav.current.t
                if (running.indexOf(t.id) >= 0) closeApp(t)
                else if (t.cmd) toast(Ui.t("home.notOpen", { name: Ui.l(t.label) }))
                else toast(Ui.t("home.cantClose"))
                return
            }
            if (layerRoot.secondary) layerRoot.secondary()
        }
        // LT / RT, Bild auf / ab: Fokus in die naechste / vorige Gruppe. Blaetter-Pfeile oben rechts (byView):
        // vom sichtbaren Ausschnitt aus. Die Zielgruppe rutscht an den linken Rand – vorher wanderte nur der
        // Fokusrahmen, wenn ihre erste Kachel schon zu sehen war, und es sah aus, als taete sich nichts.
        function jumpGroup(dir, byView) {
            if (splashTile) return
            if (layerRoot.jump) { if (layerRoot.jump(dir)) vs.playSound("group"); return }
            var tr = curTrack()
            if (!tr) return
            var groups = tr.groupList().filter(function (g) { return Nav.collect(g).length > 0 })
            if (!groups.length) return
            var target = null
            if (byView) target = tr.pageTarget(dir, groups)
            else {
                var cur = Nav.current ? tr.groupOf(Nav.current) : null
                var i = groups.indexOf(cur)
                i = i < 0 ? (dir > 0 ? 0 : groups.length - 1) : Math.max(0, Math.min(groups.length - 1, i + dir))
                if (groups[i] !== cur) target = groups[i]
            }
            if (!target) return
            var first = Nav.collect(target)
            if (first.length) setFocus(first[0])
            tr.alignGroup(target)
            vs.playSound("group")
        }
        property real mouseGX: NaN
        property real mouseGY: NaN
        function mouseFocus(item, gx, gy) {
            var first = isNaN(mouseGX)
            var moved = !first && (Math.abs(gx - mouseGX) > 2 || Math.abs(gy - mouseGY) > 2)
            if (first || moved) { mouseGX = gx; mouseGY = gy }
            if (!moved) return                    // Zeiger steht still: Kachel ist nur darunter durchgewandert
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
            if (item.navigable === false) {         // nur mit der Maus bedienbar (z. B. Blaetter-Pfeile oben rechts)
                if (!item.off) item.activate()
                return
            }
            setFocus(item)
            activate(item)
        }
        function mousePress(item) {
            if (!Nav.alive(item, layerRoot)) return
            if (item.pressFlash) item.pressedNow = true
            if (item.pressStart) item.pressStart()
        }
        function mouseRelease(item) { item.pressedNow = false; if (item.pressEnd) item.pressEnd() }
        property bool keyHeld: false              // Enter / Leertaste gedrueckt (Installieren: halten)
        Keys.onReleased: function (e) {
            if ((e.key === Qt.Key_Return || e.key === Qt.Key_Enter || e.key === Qt.Key_Space) && !e.isAutoRepeat) keyHeld = false
        }

        Keys.onPressed: function (e) {
            var k = e.key
            if (updScreen.shown) {                // Updates im Vollbild: nur Esc / B (im Hintergrund weiter)
                if (k === Qt.Key_Escape || k === Qt.Key_Backspace || k === Qt.Key_Back) { vs.playSound("back"); updScreen.toBackground() }
                e.accepted = true
                return
            }
            if (layerName === "osk" && osk.key(e)) { e.accepted = true; return }
            if (layerRoot.keyFilter && layerRoot.keyFilter(e)) { e.accepted = true; return }
            if ((k === Qt.Key_Return || k === Qt.Key_Enter || k === Qt.Key_Space) && !e.isAutoRepeat) keyHeld = true
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
                if (music.visible) return music.navKey(k)
                if (corner.visible) return corner.navKey(k)
                if (kbd.visible) return kbd.pad(k)
                if (updScreen.shown) { if (k === "b") { vs.playSound("back"); updScreen.toBackground() } return }
                if (app.layerName === "osk") return osk.pad(k)
                if (app.layerRoot.padFilter && app.layerRoot.padFilter(k)) return
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
            function onPadMouse(on) { vs.playSound("toggle"); mouseHint.show(on) }
            function onPadKeyboard() {                            // L2 oder L3 in einem Programm
                if (kbd.visible) kbd.close("L2/L3")
                else if (!corner.visible && !music.visible) kbd.openFor("pad")
            }
            function onOskField(st) { app.oskField(st) }
        }

        // ------------------------------------------------------------ Tastatur ueber Programmen
        // Meldungen der Firefox-Erweiterung (FieldWatch in voidstation-home.py): focus oeffnet, blur derselben Seite
        // schliesst (nur, was sie selbst geoeffnet hat), typed = auf einer echten Tastatur getippt. Einstellung
        // "Tasten zeigen" wie auf der Startseite: Automatisch (nach Tippen auf der echten Tastatur nicht mehr),
        // Immer, Nicht mit Tastatur (sobald eine angeschlossen ist).
        function oskField(st) {
            if (st.ev === "shot") {                               // Bildschirmfoto (Launcher: F12, vsshot, Start + Select)
                vs.playSound(st.ok ? "notify" : "error")
                mouseHint.showText("camera", st.ok ? Ui.t("shot.saved") : Ui.t("shot.failed"))
                return
            }
            var mode = sett && sett.osk ? sett.osk.mode : "auto"
            if (st.ev === "typed") {
                if (vs.kbdIdle() < 0.6) return                    // das waren unsere eigenen Tastendruecke
                vs.kbdTyped()
                if (kbd.visible && kbd.auto && mode !== "always") kbd.close("echte Tastatur")
                return
            }
            if (st.ev === "blur") {
                if (kbd.visible && kbd.auto && st.sid === kbd.sid) kbd.close("Feld verlassen")
                return
            }
            if (st.ev !== "focus" || corner.visible || music.visible) return
            if (win.active && vs.homeInFront()) return
            if (kbd.visible && !kbd.auto) return                  // per L2/L3 offen: bleibt, wie sie ist
            if (mode === "keyboard" && vs.kbdPresent) return
            if (mode === "auto" && vs.kbdPresent && vs.kbdTyping) return
            kbd.openFor("field", st)
        }

        // ------------------------------------------------------------ Start
        function init() {
            Api.get("/api/settings", function (s) {
                sett = s
                Ui.scale = s.scale || 1.75
                live = !!s.live
                vs.setLang(s.lang || "de")
                vs.setTheme(s.theme || "default-dark")
                if (s.sounds) vs.setSounds(!!s.sounds.on, s.sounds.volume || 70, s.sounds.preset || "void")
                layout()
                loadFavs()
                load()
                poll()
                started = true
                if (live) liveStart()
            }, function () { retryInit.restart() })
        }
        Timer { id: retryInit; interval: 1000; onTriggered: app.init() }
        // Live-System: Installer gleich zeigen, wenn mit "voidstation.install" gestartet oder eine Installation laeuft/lief
        function liveStart() {
            Api.get("/api/install/status", function (st) {
                if (st.autostart || ["running", "error", "done"].indexOf(st.state) >= 0) inst.openInst()
            })
        }

        function load(keepFocus) {
            Api.get("/tiles.json", function (c) {
                var prevId = Nav.current && Nav.current.t ? Nav.current.t.id : (Nav.memory.home && Nav.memory.home.t ? Nav.memory.home.t.id : "")
                cfg = c
                if (!shown) showLater.start()
                Qt.callLater(function () {
                    var items = Nav.collect(homeTrack), again = null
                    for (var i = 0; i < items.length; i++) if (items[i].t && items[i].t.id === prevId) again = items[i]
                    again = again || items[0]
                    if (layerName === "home") setFocus(again, true); else Nav.memory.home = again
                })
            })
        }
        Timer { id: showLater; interval: 120; onTriggered: { app.shown = true; vs.playStartupSound() } }  // ein paar Bilder Zeit fuer die Kacheln
        function loadFavs() { Api.get("/api/radio/favs", function (j) { favs = j || [] }) }

        // Uhr
        function tick() {
            var d = new Date()
            if (Ui.t("fmt.clock") !== "12") { clockMain = Qt.formatTime(d, "HH:mm"); clockAp = "" }
            else {                                        // 12-Stunden-Uhr: "h" allein waere in Qt 0–23
                clockMain = ((d.getHours() % 12) || 12) + ":" + Qt.formatTime(d, "mm")
                clockAp = d.getHours() < 12 ? "AM" : "PM"
            }
            hdrTime = clockAp ? clockMain + " " + clockAp : clockMain
            clockDate = Ui.dateText(d)
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
                mediaNow = s.media || null
                vpn = s.vpn && s.vpn.installed ? s.vpn : null
                if (s.tvFailed && s.tvFailed.t !== tvFailedT) {        // Rueckfall ohne Player: Sender scheiterte
                    if (tvFailedT) toast(Ui.t("tv.failed", { name: s.tvFailed.name }), true)
                    tvFailedT = s.tvFailed.t
                } else if (!s.tvFailed && !tvFailedT) tvFailedT = -1
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
        readonly property var emuSystems: ["gba", "snes", "snes9x", "nes", "nestopia", "psx", "duckstation", "psp", "ppsspp", "nds", "melonds", "dreamcast", "flycast", "gamecube", "wii", "dolphin", "c64", "vice", "atari2600", "stella", "ps2", "pcsx2", "n64", "rmg", "xbox", "xemu", "3ds", "azahar", "wiiu", "cemu", "mame", "dos", "dosbox", "scummvm", "retroarch", "mednafen", "megadrive", "mastersystem", "gamegear", "saturn", "pcengine"]
        function tileActivate(t, el) {
            if (t.type === "radio") return openLayer(radio)
            if (t.type === "settings") return openLayer(settings)
            if (t.type === "tv") return openLayer(tv)
            if (t.type === "apps") return openLayer(apps)
            if (t.type === "vpn") return vpnLayer.openVpn()
            if (t.type === "roms") return roms.openFor(t)
            if (t.type === "install") return inst.openInst()
            // Emulator laeuft schon (auch mit Spiel aus der Liste): zurueck dorthin statt Spieleliste / neuer Instanz
            if (emuSystems.indexOf(t.id) >= 0 && running.indexOf(t.id) < 0) {
                return Api.get("/api/roms?system=" + encodeURIComponent(t.id), function (r) {
                    // Spieleliste mit Spielen – oder ohne, wenn es dort die Tastenbelegung gibt
                    if (r && (r.count > 0 || (r.roms && r.roms.length) || r.keymap)) roms.openFor(t); else launch(t)
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
        // Nach dem Schliessen einer Unterseite: abgebaute Kacheln und freigegebenen Speicher wirklich loswerden
        function trimSoon() { trimLater.restart() }
        Timer { id: trimLater; interval: 800; onTriggered: { gc(); vs.trimMemory() } }
        function closeApp(t) {
            Api.post("/api/close/" + encodeURIComponent(t.id), null, function (r) {
                running = r.running || []
                toast(Ui.t("home.closed", { name: Ui.l(t.label) || Ui.t("common.program") }))
            }, function () { toast(Ui.t("home.closeFailed"), true) })
        }
        function tileById(id) {
            var gs = cfg ? cfg.groups : []
            for (var i = 0; i < gs.length; i++)
                for (var j = 0; j < (gs[i].tiles || []).length; j++)
                    if (gs[i].tiles[j].id === id) return gs[i].tiles[j]
            return null
        }

        // ------------------------------------------------------------ Heisse Ecke (Maus unten rechts)
        // Was als Ecke zaehlt (Randstreifen + kleines Quadrat), entscheidet vs.cornerHit() in voidstation-home.py.
        // Zeiger alle 150 ms abfragen (eine kurze X-Anfrage), unabhaengig davon, ob der Launcher das Programm kennt
        // („Startseite“ geht immer). Das Feld kommt erst, wenn die Maus rund 0,3 s in der Ecke bleibt – dort liegen
        // oft Player-Knoepfe (Vollbild & Co.). Ob die Startseite selbst vorn ist, entscheidet nicht win.active
        // allein: Qt haelt sich auf manchen Geraeten fuer aktiv, obwohl ein Programm vorn ist (NiPoGi + FreeTube
        // als Flatpak). Haelt Qt sich fuer aktiv, fragt vs.homeInFront() den X-Server – nur bei Zeiger in der
        // Ecke, und steht dort wirklich die Startseite, erst nach 2 s wieder.
        // Entscheidungen stehen als „Ecke: …“ in logs/home.log.
        // Nach dem Schliessen (B, Esc, Auswahl) erst wieder oeffnen, wenn der Zeiger die Ecke einmal verlassen hat
        property bool cornerArmed: true
        property bool musicArmed: true
        property int musicHits: 0
        property real musicQuietUntil: 0
        readonly property bool cornerOpen: corner.visible || music.visible
        onCornerOpenChanged: vs.cornerInput(cornerOpen)
        property int cornerHits: 0
        property real cornerQuietUntil: 0
        Timer {
            id: cornerPoll
            interval: 150
            repeat: true
            running: app.started && !corner.visible
            onRunningChanged: app.cornerHits = 0
            onTriggered: {
                var p = vs.cornerHit()
                if (!p.length) { app.cornerHits = 0; app.cornerArmed = true; return }
                if (!app.cornerArmed || ++app.cornerHits < 2 || Date.now() < app.cornerQuietUntil) return
                app.cornerHits = 0
                if (win.active && vs.homeInFront()) {
                    app.cornerQuietUntil = Date.now() + 2000
                    return
                }
                if (win.active) vs.log("Ecke: Qt meldet die Startseite als aktiv, vorn ist aber ein anderes Fenster")
                corner.openAt(p[0], p[1])
            }
        }
        // Oben links dasselbe fuer die Musik: Karte nur, wenn Musik oder Radio laeuft (fragt MusicCorner den Launcher)
        Timer {
            interval: 150
            repeat: true
            running: app.started && !music.visible
            onRunningChanged: app.musicHits = 0
            onTriggered: {
                var p = vs.musicHit()
                if (!p.length) { app.musicHits = 0; app.musicArmed = true; return }
                if (!app.musicArmed || ++app.musicHits < 2 || Date.now() < app.musicQuietUntil) return
                app.musicHits = 0
                if (win.active && vs.homeInFront()) {
                    app.musicQuietUntil = Date.now() + 2000
                    return
                }
                app.musicQuietUntil = Date.now() + 1000        // laeuft nichts: nicht bei jedem Takt fragen
                music.openAt(p[0], p[1])
            }
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
        function volume(action) {
            Api.post("/api/volume/" + action, null, function (v) {
                showVol(v)
                if (v && v.level !== undefined && !v.muted) vs.playSound(action === "mute" ? "toggle" : "volume")
            })
        }
        function refreshVolume() { Api.get("/api/volume", showVol) }
        function power(action) {
            if (powerDlg.open) powerDlg.close()
            // Standby: keine Meldung – sie stuende nach dem Aufwachen noch da
            if (action !== "suspend") toast(action === "reboot" ? Ui.t("power.rebooting") : Ui.t("power.shuttingDown"))
            Api.post("/api/power/" + action, null, null, function () { toast(Ui.t("common.failed"), true) })
        }
        function toast(msg, err) { toastBox.show(String(msg), !!err) }
        // Mullvad VPN: Beschriftung, Symbol und Farbe je Zustand (Symbol oben rechts, Kachel, Seite)
        function vpnInfo(v) {
            var st = v ? v.state : "", c = Ui.c
            if (st === "connected") return { text: Ui.t("vpn.state.connected"), icon: "shieldok", color: c.statusOkText }
            if (st === "connecting" || st === "disconnecting")
                return { text: Ui.t("vpn.state." + st), icon: "shieldwait", color: c.statusWarnText }
            if ((st === "disconnected" || st === "error") && v.locked) return { text: Ui.t("vpn.state.locked"), icon: "shieldlock", color: c.statusDangerText }
            if (st === "error") return { text: Ui.t("vpn.state.error"), icon: "shieldlock", color: c.statusDangerText }
            if (st === "disconnected") return { text: Ui.t("vpn.state.disconnected"), icon: "shieldoff", color: c.textDim }
            return { text: Ui.t("vpn.state.nodaemon"), icon: "shieldoff", color: c.textFaint }
        }
        function vpnToggle() {
            vs.playSound("toggle")
            var on = vpn && (vpn.state === "connected" || vpn.state === "connecting")
            Api.post(on ? "/api/vpn/disconnect" : "/api/vpn/connect", on ? null : {},
                     function () { poll() }, function (e) { toast(Ui.t("common.failedMsg", { msg: e }), true) })
        }

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
        function watchJob() {
            if (jobState && jobState.action === "update" && jobState.state === "running") updScreen.open()   // Updates: Vollbild
            jobBand.watch()
        }

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
                    Focusable {                       // Mullvad VPN: Zustand, A oeffnet die Seite, X schaltet an/aus
                        id: vpnIcon
                        readonly property bool isVpnIcon: true
                        readonly property var info: app.vpnInfo(app.vpn)
                        visible: !!app.vpn
                        navOnlyUp: true
                        width: 44 * Ui.f; height: width
                        anchors.verticalCenter: parent.verticalCenter
                        onTriggered: vpnLayer.openVpn()
                        Rectangle {
                            anchors.fill: parent
                            radius: width / 2
                            color: Ui.alpha(vpnIcon.info.color, vpnIcon.info.icon === "shieldoff" ? 0 : 0.16)
                            border.width: vpnIcon.focused ? 2 : 1
                            border.color: vpnIcon.focused ? Ui.c.borderFocus : Ui.alpha(vpnIcon.info.color, vpnIcon.info.icon === "shieldoff" ? 0.45 : 0.6)
                        }
                        Glyph { anchors.centerIn: parent; width: parent.width * 0.52; height: width; name: vpnIcon.info.icon; color: vpnIcon.info.color }
                        SequentialAnimation on opacity {      // verbindet: sanft pulsieren
                            running: !!app.vpn && (app.vpn.state === "connecting" || app.vpn.state === "disconnecting")
                            loops: Animation.Infinite
                            onRunningChanged: if (!running) vpnIcon.opacity = 1
                            NumberAnimation { to: 0.45; duration: 700; easing.type: Easing.InOutQuad }
                            NumberAnimation { to: 1; duration: 700; easing.type: Easing.InOutQuad }
                        }
                    }
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
                                    playing: tile.type === "radio" ? !!app.radioState.station : tile.type === "tv" ? !!app.tvNow
                                           : tile.id === "media" ? !!app.mediaNow : false
                                    nowMain: tile.type === "radio" ? (app.radioState.station ? app.radioState.station.name : "")
                                           : tile.type === "tv" && app.tvNow ? app.tvNow.name
                                           : tile.id === "media" && app.mediaNow ? (app.mediaNow.title || "") : ""
                                    nowSub: tile.type === "radio" ? (app.radioState.station ? (app.radioState.title || Ui.t("common.live")) : "")
                                          : tile.type === "tv" && app.tvNow ? (app.tvNow.country ? Ui.regionName(app.tvNow.country) : Ui.t("common.live"))
                                          : tile.id === "media" && app.mediaNow ? (app.mediaNow.sub || "") : ""
                                    vpn: tile.type === "vpn" ? app.vpn : null
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
        InstallLayer { id: inst; anchors.fill: parent }
        SettingsLayer { id: settings; anchors.fill: parent }
        AppsLayer { id: apps; anchors.fill: parent }
        TvLayer { id: tv; anchors.fill: parent }
        VpnLayer { id: vpnLayer; anchors.fill: parent }
        RomsLayer { id: roms; anchors.fill: parent }
        ChdCard { id: chd; anchors.fill: parent; onFinished: roms.reload(); onOpenChanged: if (!open) roms.chdUpdate(chd.st) }
        KeymapLayer { id: keymap; anchors.fill: parent }
        EmuOptsLayer { id: emuopts; anchors.fill: parent }

        JobBand { id: jobBand }
        HintBar { id: hint }
        AppDialog { id: adlg; anchors.fill: parent }
        PowerDialog { id: powerDlg; anchors.fill: parent }
        Corner {
            id: corner
            onGoHome: Api.post("/api/home", null, function (r) { app.running = r.running || [] })
            onCloseFront: function (t) { app.closeApp(t) }
            onVisibleChanged: if (!visible) app.cornerArmed = false
        }
        MusicCorner {
            id: music
            onVisibleChanged: if (!visible) app.musicArmed = false
        }
        MouseHint { id: mouseHint }
        KbdOverlay {
            id: kbd
            onOpened: { vs.kbdInput(true); app.updateLayer() }
            onClosed: {
                vs.kbdInput(false)
                app.updateLayer()
                var f = Nav.alive(savedFocus, app.layerRoot) ? savedFocus : Nav.remembered(app.layerName, app.layerRoot)
                if (f) app.setFocus(f, true)
            }
        }
        Osk { id: osk; anchors.fill: parent }
        Splash { id: splash; anchors.fill: parent; tile: app.splashTile }
        UpdateScreen { id: updScreen; anchors.fill: parent }
        Toast { id: toastBox }
        LoadSplash { id: loadSplash; anchors.fill: parent; done: !!app.cfg && app.shown }
    }
}
