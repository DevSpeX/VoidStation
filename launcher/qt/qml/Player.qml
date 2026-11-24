// SPDX-License-Identifier: GPL-3.0-or-later
// VoidStation Player (voidstation-player.py): Fernsehen (vsMode "tv"), Videos & Musik ("media"), YouTube Light ("yt").
// Das Video zeichnet mpv unter diese Oberflaeche (Stufe 0/1) – alles hier liegt darueber und ist dort durchsichtig,
// wo das Bild zu sehen sein soll. Stufe 2: mpv hat ein eigenes Fenster, die Oberflaeche bleibt fuer Listen & Co.
import QtQuick
import QtQuick.Window
import VS
import "player"

Window {
    id: win
    title: "Player"
    width: vsW > 0 ? vsW : Screen.width > 0 ? Screen.width : 1280
    height: vsH > 0 ? vsH : Screen.height > 0 ? Screen.height : 720
    visible: true
    visibility: vsW > 0 ? Window.Windowed : Window.FullScreen
    flags: Qt.Window | Qt.FramelessWindowHint
    color: "#000000"
    property var videoItem: null                  // setzt voidstation-player.py (Video: show = Bild zeichnen)
    onActiveChanged: if (active) app.forceActiveFocus()

    Item {
        id: app
        anchors.fill: parent
        focus: true

        readonly property var player: vs.engine
        readonly property var st: player ? player.st : ({})
        readonly property bool embedded: player ? player.embedded : false
        property bool started: false
        property var sett: null
        readonly property Item view: vsMode === "tv" ? tvView : vsMode === "yt" ? ytView : mediaView
        // fuer VS-Bausteine (Focusable, Layer, Track): wie die Startseite
        property string layerName: "player"
        readonly property Item layerRoot: osk.open ? osk : (view.navRoot || view)
        property real mouseGX: NaN
        property real mouseGY: NaN

        Component.onCompleted: {
            Ui.app = app
            layout()
            init()
        }

        function layout() {
            var H = win.height, W = win.width
            if (!H || !W) return
            Ui.screenW = W; Ui.screenH = H
            var r = H / 768, f = Ui.scale * r
            Ui.f = f
            Ui.padX = W * 0.06
            Ui.hintH = 46 * f
            Ui.u = Math.max(60, 161 * r * (1 + (Ui.scale - 1) * 0.55))
        }
        Connections { target: win; function onWidthChanged() { Qt.callLater(app.layout) } function onHeightChanged() { Qt.callLater(app.layout) } }

        function init() {
            Api.get("/api/settings", function (s) {
                sett = s
                Ui.scale = s.scale || 1.75
                vs.setLang(s.lang || "de")
                vs.setTheme(s.theme || "default-dark")
                if (s.sounds) vs.setSounds(!!s.sounds.on, s.sounds.volume || 70, s.sounds.preset || "void")
                layout()
                started = true
                view.start(vsArg)
            }, function () { retryInit.restart() })
        }
        Timer { id: retryInit; interval: 1000; onTriggered: app.init() }

        // Bild zeichnen, solange etwas mit Bild laeuft (spart im Menue der Mediathek die Grafikkarte)
        Binding { target: win.videoItem; property: "show"; value: app.view.wantVideo; when: win.videoItem !== null }

        // ------------------------------------------------------------ Eingaben
        function key(k) {
            if (!started) return
            if (osk.open) return osk.pad(k)
            view.key(k)
        }
        function keyName(e) {
            var k = e.key
            if (k === Qt.Key_Return || k === Qt.Key_Enter) return "a"
            if (k === Qt.Key_Escape || k === Qt.Key_Backspace || k === Qt.Key_Back) return "b"
            if (k === Qt.Key_Up) return "up"
            if (k === Qt.Key_Down) return "down"
            if (k === Qt.Key_Left) return "left"
            if (k === Qt.Key_Right) return "right"
            if (k === Qt.Key_Space || k === Qt.Key_MediaTogglePlayPause || k === Qt.Key_MediaPlay || k === Qt.Key_MediaPause) return "play"
            if (k === Qt.Key_PageUp || k === Qt.Key_ChannelUp) return "chup"
            if (k === Qt.Key_PageDown || k === Qt.Key_ChannelDown) return "chdown"
            if (k === Qt.Key_MediaNext) return "next"
            if (k === Qt.Key_MediaPrevious) return "prev"
            if (k === Qt.Key_MediaStop) return "stop"
            if (k === Qt.Key_I || k === Qt.Key_Info) return "select"
            if (k === Qt.Key_L) return "x"
            if (k === Qt.Key_F) return "y"
            if (k === Qt.Key_M || k === Qt.Key_Menu) return "start"
            if (k === Qt.Key_Plus || k === Qt.Key_Equal) return "volup"
            if (k === Qt.Key_Minus) return "voldown"
            if (k === Qt.Key_Home) return "lb"
            return ""
        }
        Keys.onPressed: function (e) {
            if (osk.open && osk.key(e)) { e.accepted = true; return }
            var k = keyName(e)
            if (!k) return
            e.accepted = true
            key(k)
        }
        Connections {
            target: vs
            function onPadKey(k) { app.key(k) }
            function onRemote(m) { if (app.started) app.view.remote(m); else pendingRemote = m }
            function onPadConnected(name) { app.toast(Ui.t("pad.connected", { name: name })) }
        }
        property var pendingRemote: null
        onStartedChanged: if (started && pendingRemote) { view.remote(pendingRemote); pendingRemote = null }

        // Maus fuer VS-Bausteine (Kacheln, Knoepfe)
        function setFocus(item, instant) { Nav.setFocus(item, instant, "player") }
        function navItems() { return Nav.collect(layerRoot) }
        function move(dir, silent) {
            var prev = Nav.current
            var items = navItems()
            if (!Nav.current || items.indexOf(Nav.current) < 0) {
                if (items.length) { setFocus(items[0]); if (!silent) vs.playSound("navigate"); return true }
                return false
            }
            var best = Nav.nearest(Nav.current, items, dir)
            if (best) { setFocus(best); if (!silent && best !== prev) vs.playSound("navigate"); return best !== prev }
            return false
        }
        function mouseFocus(item, gx, gy) {
            var first = isNaN(mouseGX)
            var moved = !first && (Math.abs(gx - mouseGX) > 2 || Math.abs(gy - mouseGY) > 2)
            if (first || moved) { mouseGX = gx; mouseGY = gy }
            if (!moved || !Nav.alive(item, layerRoot) || Nav.current === item) return
            setFocus(item)
        }
        function playItemSound(item) {
            if (!item) return
            var snd = item.sound !== undefined ? item.sound : "select"
            if (snd === "toggle") { if (item.on !== true || item.toggleFlip === true) vs.playSound("toggle") }
            else if (snd) vs.playSound(snd)
        }
        function mouseClick(item, button) {
            if (button === Qt.RightButton) return key("b")
            if (!Nav.alive(item, layerRoot) && !(item.navigable === false && item.visible)) return
            if (item.clickActivate) { playItemSound(item); return item.clickActivate() }
            if (item.navigable !== false) setFocus(item)
            playItemSound(item)
            item.activate()
        }
        function mousePress(item) { if (item.pressFlash) item.pressedNow = true }
        function mouseRelease(item) { item.pressedNow = false }
        function back() { key("b") }
        // Bildschirmtastatur (Osk.qml der Startseite): braucht updateLayer/activate/openOsk wie dort
        function updateLayer() {}
        function openOsk(field) { osk.openFor(field) }
        function activate(el) {
            el = el || Nav.current
            if (!el || !Nav.alive(el, layerRoot)) return
            playItemSound(el)
            el.activate()
        }
        function curTrack() { return view.track || null }

        // ------------------------------------------------------------ Gemeinsames
        function toast(msg, err) { toastBox.show(msg, !!err) }
        function volume(dir) {
            Api.post("/api/volume/" + dir, null, function (v) {
                if (v) {
                    volOsd.show(v.level, v.muted)
                    if (!v.muted && (!app.st || app.st.paused || app.st.idle)) vs.playSound(dir === "mute" ? "toggle" : "volume")
                }
            })
        }
        // Zurueck zur Startseite und Player beenden
        function leave() {
            vs.playSound("back")
            if (player) player.stop()
            Api.post("/api/home", null, function () { vs.quit() }, function () { vs.quit() })
        }
        // Sprachname einer Spur (ISO 639): "deu" -> "Deutsch"
        function langName(code) {
            if (!code) return ""
            var n = Qt.locale(code).nativeLanguageName
            if (!n || Qt.locale(code).name === "C") return code.toUpperCase()
            return n.charAt(0).toUpperCase() + n.slice(1)
        }

        TvView { id: tvView; anchors.fill: parent; visible: vsMode === "tv"; enabled: visible }
        MediaView { id: mediaView; anchors.fill: parent; visible: vsMode === "media"; enabled: visible }
        Loader { id: ytLoader; anchors.fill: parent; active: vsMode === "yt"; source: "player/YtView.qml" }
        readonly property Item ytView: ytLoader.item

        VolumeOsd { id: volOsd }
        Osk { id: osk; anchors.fill: parent }
        Toast { id: toastBox }
    }
}
