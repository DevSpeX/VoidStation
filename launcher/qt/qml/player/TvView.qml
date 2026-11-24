// SPDX-License-Identifier: GPL-3.0-or-later
// Fernsehen im Player: Bild vollflaechig (mpv darunter), darueber Senderanzeige mit Programm (EPG), Senderliste,
// Menue fuer Ton & Bild, Technik-Anzeige und Fehlermeldungen.
// Senderliste, Favoriten, EPG und Stream-Adressen kommen vom Launcher (/api/tv/zap, /api/tv/tune, /api/tv/epg).
// Tasten (Fernbedienungs-Logik): ▲▼ Sender, ◀▶ Lautstaerke, A Info, X Senderliste, Y Favorit, Start Ton & Bild,
// Select Technik, LB/RB vorheriger Sender, B zweimal = Fernsehen beenden.
import QtQuick
import VS

Item {
    id: tv
    readonly property Item navRoot: tv
    readonly property bool wantVideo: true
    readonly property var track: null
    readonly property var player: app.player
    readonly property var st: app.st || {}

    property var list: []                      // Zapp-Liste (aus der heraus gestartet wurde)
    property var favs: []
    property var recent: []
    property var cur: null                     // laufender Sender (oeffentliche Angaben: key, name, logo, country …)
    property int pending: -1                   // beim schnellen Umschalten: Ziel in der Liste (noch nicht geladen)
    property string phase: "idle"              // idle | loading | playing | error
    property string why: ""                    // Fehlergrund (player.err.<why>)
    property bool retried: false
    property string prevKey: ""
    property var epg: null
    property bool infoOn: false
    property bool exitArmed: false
    // Qualitaet (hls-bitrate) wird gemerkt; schwache Hardware (32 Bit) startet mit "Sparsam"
    property string quality: vs.prefGet("tvQuality", (typeof vsWeak !== "undefined" && vsWeak) ? "min" : "max")
    property string clock: ""
    readonly property var shown: pending >= 0 && list[pending] ? list[pending] : cur
    readonly property int curIdx: indexOf(cur ? cur.key : "")

    function indexOf(key) { for (var i = 0; i < list.length; i++) if (list[i].key === key) return i; return -1 }
    function isFav(key) { for (var i = 0; i < favs.length; i++) if (favs[i].key === key) return true; return false }
    function find(key) {
        var i = indexOf(key)
        if (i >= 0) return list[i]
        for (i = 0; i < favs.length; i++) if (favs[i].key === key) return favs[i]
        for (i = 0; i < recent.length; i++) if (recent[i].key === key) return recent[i]
        return null
    }

    // ------------------------------------------------------------ Ablauf
    function start(arg) { loadZap(function () { if (arg) tune(arg) }) }
    function loadZap(cb) {
        Api.get("/api/tv/zap", function (z) {
            z = z || {}
            list = z.items || []
            favs = z.favs || []
            recent = z.recent || []
            if (cb) cb()
        }, function () { if (cb) cb() })
    }
    function remote(m) {
        if (m.cmd !== "tune" || !m.key) return
        if (cur && m.key === cur.key && phase !== "error") { loadZap(); showInfo(); return }
        loadZap(function () { tune(m.key) })
    }
    function tune(key) {
        zapT.stop()
        pending = -1
        if (cur && cur.key !== key) prevKey = cur.key
        var e = find(key)
        if (e) cur = e
        phase = "loading"
        why = ""
        retried = false
        epg = null
        showInfo()
        Api.post("/api/tv/tune", { key: key }, function (s) {
            if (!s || !s.url) { fail("failed"); return }
            cur = s.entry
            if (s.recent) recent = s.recent
            var o = { "hls-bitrate": quality }
            if (s.ref) o.referrer = s.ref
            if (s.ua) o["user-agent"] = s.ua
            vs.setTitle(Ui.t("tv.title") + " · " + cur.name)
            player.play(s.url, o)
            player.osdText(cur.name, "3000")
            watchdog.restart()
            refreshEpg()
        }, function () { fail("failed") })
    }
    function fail(reason) {
        watchdog.stop()
        phase = "error"
        why = reason || "failed"
        infoOn = false
        if (player) player.stop()
        if (cur) {
            Api.post("/api/tv/broken", { key: cur.key, reason: why })
            player.osdText(Ui.t("player.tv.unreachable") + " – " + Ui.t("player.err." + why), "6000")
        }
    }
    function retry() { if (cur) tune(cur.key) }
    Timer { id: watchdog; interval: 20000; onTriggered: if (tv.phase === "loading") tv.fail("timeout") }
    Connections {
        target: tv.player
        enabled: vsMode === "tv"
        function onStarted() { watchdog.stop(); tv.phase = "playing"; tv.retried = false }
        function onEnded(reason, cause) {
            if (tv.phase === "idle" || tv.phase === "error") return
            if (reason === "error") return tv.fail(cause)
            if (reason === "eof" || reason === "quit") {
                if (reason === "quit") { return app.leave() }        // mpv-Fenster geschlossen (Stufe 2)
                if (!tv.retried && tv.cur) {                         // Stream endet: einmal neu verbinden
                    tv.retried = true
                    tv.phase = "loading"
                    watchdog.restart()
                    tv.player.reload({})
                    return
                }
                tv.fail("ended")
            }
        }
    }

    // Schnelles Umschalten: Anzeige sofort, geladen wird erst nach einer kurzen Pause
    function zap(dir) {
        if (!list.length) { if (prevKey) tune(prevKey); return }
        var base = pending >= 0 ? pending : curIdx
        pending = base < 0 ? (dir > 0 ? 0 : list.length - 1) : (base + dir + list.length) % list.length
        showInfo()
        zapT.restart()
    }
    Timer { id: zapT; interval: 550; onTriggered: if (tv.pending >= 0 && tv.list[tv.pending]) tv.tune(tv.list[tv.pending].key) }

    function showInfo() {
        infoOn = true
        infoT.restart()
    }
    Timer { id: infoT; interval: 6000; onTriggered: if (!chan.open && !menu.open) tv.infoOn = false }

    function refreshEpg() {
        var c = cur
        if (!c) { epg = null; return }
        Api.get("/api/tv/epg?id=" + encodeURIComponent(c.cid || c.key || "") + "&name=" + encodeURIComponent(c.name || ""),
                function (j) { if (tv.cur && tv.cur.key === c.key) tv.epg = (j && j.current) ? j : null },
                function () { tv.epg = null })
    }
    Timer { interval: 30000; repeat: true; running: tv.phase === "playing"; onTriggered: tv.refreshEpg() }

    function fav(ch) {
        ch = ch || cur
        if (!ch) return
        var was = isFav(ch.key)
        Api.post(was ? "/api/tv/unfav" : "/api/tv/fav", { key: ch.key }, function (j) {
            favs = j || []
            app.toast(was ? Ui.t("common.favRemoved") : Ui.t("common.favAdded"))
            player.osdText(was ? Ui.t("common.favRemoved") : Ui.t("common.favAdded"), "2000")
        }, function () { app.toast(Ui.t("common.saveFailed"), true) })
    }

    // Zur Startseite (Menue-Eintrag, fuer Controller ohne Guide-Taste): Fernsehen laeuft weiter
    function goHome() {
        menu.hide()
        chan.hide()
        Api.post("/api/home", null)
    }
    function armExit() {
        if (exitArmed) { exitT.stop(); exitArmed = false; return app.leave() }
        exitArmed = true
        exitT.restart()
        player.osdText(Ui.t("player.tv.exitHint").replace(/<\/?b>/g, ""), "2500")
    }
    Timer { id: exitT; interval: 2500; onTriggered: tv.exitArmed = false }

    function key(k) {
        if (menu.open) return menu.key(k)
        if (chan.open) return chan.key(k)
        if (k !== "b") { exitArmed = false; exitT.stop() }
        if (k === "b") {
            if (tech.open) { vs.playSound("back"); tech.open = false; return }
            if (infoOn && phase !== "error") { vs.playSound("back"); infoOn = false; return }
            return armExit()
        }
        if (phase === "error" && (k === "a" || k === "play")) return retry()
        if (k === "up" || k === "chup") return zap(1)
        if (k === "down" || k === "chdown") return zap(-1)
        if (k === "left" || k === "voldown") return app.volume("down")
        if (k === "right" || k === "volup") return app.volume("up")
        if (k === "a" || k === "play") { if (infoOn) infoOn = false; else showInfo(); return }
        if (k === "x") { chan.curKey = cur ? cur.key : ""; infoOn = false; return chan.show() }
        if (k === "y") return fav()
        if (k === "start") { infoOn = false; return menu.show() }
        if (k === "home") return goHome()
        if (k === "select") { tech.open = !tech.open; return }
        if ((k === "lb" || k === "rb" || k === "prev") && prevKey) return tune(prevKey)
        if (k === "next") return zap(1)
    }

    function tickClock() {
        var d = new Date()
        clock = Ui.t("fmt.clock") === "12" ? ((d.getHours() % 12) || 12) + ":" + Qt.formatTime(d, "mm") + (d.getHours() < 12 ? " AM" : " PM")
                                         : Qt.formatTime(d, "HH:mm")
    }
    Timer { interval: 5000; repeat: true; running: true; triggeredOnStart: true; onTriggered: tv.tickClock() }

    // ------------------------------------------------------------ Anzeige
    // Stufe 2: das Bild laeuft in einem eigenen mpv-Fenster – hier nur ein ruhiger Hintergrund
    Rectangle {
        anchors.fill: parent
        visible: !app.embedded
        color: Ui.c.bgMain
        Column {
            anchors.centerIn: parent
            spacing: 14 * Ui.f
            Glyph { anchors.horizontalCenter: parent.horizontalCenter; name: "tv"; width: 80 * Ui.f; height: width; opacity: 0.5 }
            Txt { anchors.horizontalCenter: parent.horizontalCenter; text: tv.cur ? tv.cur.name : Ui.t("tv.title"); font.pixelSize: 28 * Ui.f; font.weight: Font.Light }
            Txt { anchors.horizontalCenter: parent.horizontalCenter; text: Ui.t("player.ownWindow"); color: Ui.c.textDim }
        }
    }

    // Maus: Bewegung zeigt die Knoepfe oben rechts, Rad = Lautstaerke, Klick = Info, Doppelklick = Senderliste
    MouseArea {
        anchors.fill: parent
        hoverEnabled: true
        acceptedButtons: Qt.LeftButton | Qt.RightButton
        onPositionChanged: mouseBar.poke()
        onClicked: function (m) { if (m.button === Qt.RightButton) tv.key("b"); else tv.key("a") }
        onDoubleClicked: tv.key("x")
        onWheel: function (w) { app.volume(w.angleDelta.y > 0 ? "up" : "down") }
    }

    // Laden / Puffern
    Column {
        anchors.centerIn: parent
        spacing: 16 * Ui.f
        visible: app.embedded && (tv.phase === "loading" || (tv.phase === "playing" && !!tv.st.buffering))
        Spinner { anchors.horizontalCenter: parent.horizontalCenter; size: 54 * Ui.f; line: 4 * Ui.f }
        Txt {
            anchors.horizontalCenter: parent.horizontalCenter
            text: tv.phase === "loading" && tv.retried ? Ui.t("player.tv.reconnecting") : tv.phase === "loading" ? Ui.t("player.loading") : Ui.t("player.buffering")
            style: Text.Outline; styleColor: "#80000000"
            font.pixelSize: 17 * Ui.f
        }
    }

    // Fehler
    Rectangle {
        anchors.centerIn: parent
        visible: tv.phase === "error"
        width: Math.min(parent.width * 0.6, errCol.implicitWidth + 64 * Ui.f)
        height: errCol.height + 52 * Ui.f
        color: Ui.alpha(Ui.c.surfaceDialog, 0.95)
        border.width: 1
        border.color: Ui.c.borderSubtle
        Column {
            id: errCol
            anchors.centerIn: parent
            width: parent.width - 64 * Ui.f
            spacing: 12 * Ui.f
            Row {
                spacing: 14 * Ui.f
                Glyph { name: "warn"; width: 30 * Ui.f; height: width; color: Ui.c.statusDangerText; anchors.verticalCenter: parent.verticalCenter }
                Txt { text: Ui.t("player.tv.unreachable"); font.pixelSize: 26 * Ui.f; font.weight: Font.Light; anchors.verticalCenter: parent.verticalCenter }
            }
            Txt { width: parent.width; text: tv.cur ? tv.cur.name : ""; color: Ui.c.textSecondary; font.pixelSize: 18 * Ui.f }
            Txt { width: parent.width; text: Ui.t("player.err." + (tv.why || "failed")); wrapMode: Text.Wrap; elide: Text.ElideNone; color: Ui.c.textDim }
            Item { width: 1; height: 4 * Ui.f }
            Hints { width: parent.width; list: [Ui.t("player.hint.nextChannel"), Ui.t("player.hint.retry"), Ui.t("player.hint.list"), Ui.t("player.hint.exit")] }
        }
    }

    // Senderanzeige unten: Logo, Name, Platz in der Liste, laufende und naechste Sendung, Hinweise
    Item {
        id: info
        anchors.left: parent.left; anchors.right: parent.right; anchors.bottom: parent.bottom
        height: infoBox.height + 60 * Ui.f
        opacity: tv.infoOn && tv.phase !== "error" && !!tv.shown ? 1 : 0
        visible: opacity > 0
        Behavior on opacity { NumberAnimation { duration: 220 } }
        Rectangle {
            anchors.fill: parent
            gradient: Gradient {
                GradientStop { position: 0.0; color: "transparent" }
                GradientStop { position: 0.35; color: Ui.alpha(Ui.c.bgMain, 0.78) }
                GradientStop { position: 1.0; color: Ui.alpha(Ui.c.bgMain, 0.95) }
            }
        }
        Item {
            id: infoBox
            x: Ui.padX
            width: parent.width - 2 * Ui.padX
            anchors.bottom: parent.bottom; anchors.bottomMargin: 22 * Ui.f
            height: Math.max(logoBox.height, infoCol.height) + 18 * Ui.f + tvHints.height
            Rectangle {
                id: logoBox
                width: 150 * Ui.f; height: 96 * Ui.f
                color: Ui.alpha(Ui.c.surfaceCard, 0.85)
                Image {
                    id: lg
                    anchors.fill: parent; anchors.margins: 12 * Ui.f
                    source: tv.shown && tv.shown.logo ? tv.shown.logo : ""
                    fillMode: Image.PreserveAspectFit
                    asynchronous: true
                    sourceSize: Qt.size(Math.ceil(width * 1.5), Math.ceil(height * 1.5))
                    visible: status === Image.Ready
                }
                Glyph { anchors.centerIn: parent; visible: lg.status !== Image.Ready; name: "tv"; width: 44 * Ui.f; height: width; opacity: 0.6 }
            }
            Column {
                id: infoCol
                anchors.left: logoBox.right; anchors.leftMargin: 26 * Ui.f
                anchors.right: clockTxt.left; anchors.rightMargin: 20 * Ui.f
                anchors.top: logoBox.top
                spacing: 6 * Ui.f
                Row {
                    spacing: 14 * Ui.f
                    width: parent.width
                    Txt {
                        id: nameTxt
                        text: tv.shown ? tv.shown.name : ""
                        font.pixelSize: 34 * Ui.f
                        font.weight: Font.Light
                        width: Math.min(implicitWidth, parent.width - starTxt.width - 20 * Ui.f)
                    }
                    Txt { id: starTxt; visible: !!tv.shown && tv.isFav(tv.shown.key); text: "★"; font.pixelSize: 24 * Ui.f; color: Ui.c.textSecondary; anchors.verticalCenter: nameTxt.verticalCenter }
                }
                Txt {
                    width: parent.width
                    color: Ui.c.textDim
                    font.pixelSize: 15 * Ui.f
                    text: {
                        var s = tv.shown, p = []
                        if (!s) return ""
                        var i = tv.pending >= 0 ? tv.pending : tv.curIdx
                        if (i >= 0 && tv.list.length) p.push(Ui.t("player.tv.pos", { n: Ui.num(i + 1, 0), total: Ui.num(tv.list.length, 0) }))
                        if (s.country) p.push(Ui.regionName(s.country))
                        if (s.quality) p.push(s.quality)
                        if (tv.pending >= 0) p.push(Ui.t("player.tv.switchHint"))
                        return p.join(" · ")
                    }
                }
                Item { width: 1; height: 4 * Ui.f; visible: epgCur.visible }
                Row {
                    id: epgCur
                    visible: tv.pending < 0 && !!tv.epg && !!tv.epg.current
                    spacing: 14 * Ui.f
                    width: parent.width
                    Txt { text: tv.epg && tv.epg.current ? (tv.epg.current.start || "") + "–" + (tv.epg.current.stop || "") : ""; color: Ui.c.textDim; font.pixelSize: 16 * Ui.f; anchors.verticalCenter: parent.verticalCenter }
                    Txt { text: tv.epg && tv.epg.current ? tv.epg.current.title : ""; font.pixelSize: 19 * Ui.f; font.weight: Font.Medium
                          width: Math.min(implicitWidth, parent.width * 0.6); anchors.verticalCenter: parent.verticalCenter }
                    Bar { width: 140 * Ui.f; value: tv.epg && tv.epg.current ? (tv.epg.current.progress || 0) / 100 : 0; fill: Ui.c.statusOkText; anchors.verticalCenter: parent.verticalCenter }
                }
                Txt {
                    visible: epgCur.visible && !!tv.epg.next
                    width: parent.width
                    text: tv.epg && tv.epg.next ? (tv.epg.next.start || "") + "  " + Ui.t("tv.epgNext", { title: tv.epg.next.title }) : ""
                    color: Ui.c.textDim
                    font.pixelSize: 15 * Ui.f
                }
            }
            Txt {
                id: clockTxt
                anchors.right: parent.right
                anchors.top: logoBox.top
                text: tv.clock
                font.pixelSize: 30 * Ui.f
                font.weight: Font.Light
                color: Ui.c.textSecondary
            }
            Hints {
                id: tvHints
                width: parent.width
                anchors.bottom: parent.bottom
                list: [Ui.t("player.hint.channels"), Ui.t("player.hint.volumeLR"), Ui.t("player.hint.list"), Ui.t("player.hint.fav"),
                       Ui.t("player.hint.menu"), Ui.t("hint.homeShort"), Ui.t("player.hint.exit")]
            }
        }
    }

    // „Nochmal B: Fernsehen beenden“
    Rectangle {
        anchors.horizontalCenter: parent.horizontalCenter
        y: parent.height * 0.12
        visible: tv.exitArmed
        width: exitTxt.implicitWidth + 44 * Ui.f
        height: exitTxt.implicitHeight + 22 * Ui.f
        color: Ui.alpha(Ui.c.surfaceDialog, 0.95)
        border.width: 1
        border.color: Ui.c.borderSubtle
        z: 50
        Txt {
            id: exitTxt
            anchors.centerIn: parent
            textFormat: Text.StyledText
            elide: Text.ElideNone
            font.pixelSize: 18 * Ui.f
            text: Ui.keys(Ui.t("player.tv.exitHint"), Ui.c.textPrimary, 18 * Ui.f)
        }
    }

    MouseBar {
        id: mouseBar
        visible: opacity > 0 && !menu.open && !chan.open
        buttons: [
            { icon: "chevleft", tip: Ui.t("player.btn.prevChannel"), act: function () { tv.zap(-1) } },
            { icon: "chevright", tip: Ui.t("player.btn.nextChannel"), act: function () { tv.zap(1) } },
            { icon: "list", tip: Ui.t("player.tv.tab.list"), act: function () { tv.key("x") } },
            { icon: "star", tip: Ui.t("common.favorites"), act: function () { tv.fav() } },
            { icon: "subs", tip: Ui.t("player.menu.title"), act: function () { tv.key("start") } },
            { icon: "home", tip: Ui.t("player.menu.home"), act: function () { tv.goHome() } },
            { icon: "minus", tip: Ui.t("player.volume"), act: function () { app.volume("down") } },
            { icon: "plus", tip: Ui.t("player.volume"), act: function () { app.volume("up") } },
            { icon: "close", tip: Ui.t("player.btn.exit"), act: function () { app.leave() } }
        ]
    }

    TechInfo { id: tech }
    ChannelPanel {
        id: chan
        all: tv.list
        favs: tv.favs
        recent: tv.recent
        onChosen: function (ch) { tv.tune(ch.key) }
        onFavToggle: function (ch) { tv.fav(ch) }
    }
    TrackMenu {
        id: menu
        withQuality: true
        quality: tv.quality
        onQualityChosen: function (v) { tv.quality = v; vs.prefSet("tvQuality", v); if (tv.cur) tv.player.reload({ "hls-bitrate": v }) }
        homeSub: Ui.t("player.menu.homeTv")
        onHomeChosen: tv.goHome()
    }
}
