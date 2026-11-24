// SPDX-License-Identifier: GPL-3.0-or-later
// Videos & Musik: Mediathek fuer ~/share/Videos, ~/share/Musik und USB-Laufwerke (Liste vom Launcher, /api/media/…)
// und die Wiedergabe – Videos vollflaechig mit Leiste unten, Musik mit Cover und Titelliste.
// Angefangene Videos merkt sich der Launcher (Weiterschauen).
// Tasten Video: A Pause, ◀▶ 10 s, LB/RB 1 min, ▲▼ Lautstaerke, Start Ton & Untertitel, Select Technik, B Stopp
// Tasten Musik: A Pause, ◀▶ Titel zurueck/vor, LB/RB 10 s, ▲▼ Lautstaerke, Y Wiederholen (wie beim MP3-Player:
// Titel wiederholen · Ordner, dann Stopp · Ordner wiederholen · weiter mit dem naechsten Ordner), X Zufaellig, Start Menue,
// B Stopp. Cover fuer Ordner ohne Bild laedt der Launcher im Hintergrund (MusicBrainz), die Kacheln aktualisieren sich.
// Guide/Win (oder Menue -> Zur Startseite): Startseite, Musik laeuft weiter, Videos halten an.
// DVD: Kachel auf der Startseite, sobald eine Disc liegt; Titelliste (Serien: ein Titel je Folge), ab dem gewaehlten
// Titel spielt alles der Reihe nach; X/Y naechster/voriger Titel, im Menue "Zeilensprung entfernen", Kachel Auswerfen.
import QtQuick
import VS

Item {
    id: mv
    readonly property Item navRoot: dlView.open ? dlView.navRoot : dlg.open ? dlg : browser
    readonly property bool wantVideo: phase === "video"
    readonly property var track: phase === "browse" ? trk : null
    readonly property var player: app.player
    readonly property var st: app.st || {}

    property string phase: "browse"               // browse | video | audio
    property var roots: []
    property var resumes: []
    property string path: ""                      // "" = Startseite der Mediathek
    property string parentPath: ""
    property string folderName: ""
    property var items: []
    property string msg: ""
    property string selectAfter: ""               // nach dem Laden diesen Eintrag fokussieren (zurueck aus einem Ordner)
    property var playing: null                    // laufender Eintrag (Video) bzw. Liste (Musik)
    property var playlist: []
    property string playFolder: ""                // Ordner, aus dem die Musik gerade spielt
    property string playFolderName: ""
    // Wiederholen (Musik), gemerkt in player.json: track | once | folder | next
    readonly property var repeatModes: ["next", "folder", "once", "track"]
    property string repeat: vs.prefGet("repeat", "next")
    property bool nextBusy: false
    property bool shuffle: vs.prefGet("shuffle", "0") === "1"
    property var origList: []                     // Titel des Ordners in Ordnerreihenfolge (fuer Zufall aus)
    property var thumbs: ({})                     // nachgeladene Cover: Pfad -> Bild
    property var coverState: null                 // /api/media/covers
    property bool osdOn: false
    property real seekAcc: 0
    readonly property var audioItems: items.filter(function (i) { return i.kind === "audio" })
    readonly property var fit: Ui.fitRows(browser.stage.height - 18 * Ui.f * 1.36 - 14 * Ui.f - 4, Ui.u * 0.86, Ui.gap, 3)
    readonly property real cell: Ui.u * 0.86 * fit.k
    property bool deint: false                    // DVD: Zeilensprung entfernen (Kammmuster bei Serien-DVDs)
    property string dvdSig: ""                    // eingelegte Discs (Startseite neu laden, wenn sich das aendert)
    readonly property bool dvdPlaying: phase === "video" && playlist.length > 0 && !!playing && String(playing.path).indexOf("dvd://") === 0
    readonly property var dvdItem: dvdPlaying && st.plpos >= 0 && playlist[st.plpos] ? playlist[st.plpos] : playing

    // ------------------------------------------------------------ Mediathek
    function start(arg) {
        browser.show()
        if (arg) openArg(arg); else openPath("")
    }
    // Eigener Regler fuer die Musik (heisse Ecke oben links): gilt nur fuer Musik, Videos bleiben bei 100
    property int musicVolume: 100
    function applyVolume() { player.setProp("volume", phase === "audio" ? musicVolume : 100) }
    onPhaseChanged: applyVolume()
    Component.onCompleted: Api.get("/api/settings", function (s) {
        if (s && s.music_volume !== undefined) { musicVolume = s.music_volume; applyVolume() }
    })
    function remote(m) {
        if (m.cmd === "open" && m.path) return openArg(m.path)
        if (m.cmd === "pause" && phase !== "browse") return player.setPause(true)          // Radio startet
        if (m.cmd === "control" && phase === "audio") {                                     // heisse Ecke oben links
            if (m.action === "prev") prevTrack()
            else if (m.action === "next") nextTrack()
            else if (m.action === "toggle") player.togglePause()
            else if (m.action === "volume") { musicVolume = m.value; applyVolume() }
            return
        }
        if (m.cmd === "background" && phase === "video" && !st.paused) {                    // Startseite / anderes Programm
            player.setPause(true)
            osdOn = true
        }
    }
    function openArg(p) {
        if (phase !== "browse") stopPlayback(true)
        openPath(p, true)
    }
    function decorate(list) {
        return (list || []).map(function (it) {
            var o = {}
            for (var k in it) o[k] = it[k]
            o.size = (it.kind === "video" || it.kind === "resume") && it.thumb ? "wide" : "medium"
            if (it.kind === "resume" && it.resume) o.sub = Ui.t("player.media.resumeAt", { time: vs.fmtTime(it.resume.pos, "") })
            if (it.kind === "videos") { o.title = Ui.t("player.media.videos") }
            if (it.kind === "music") { o.title = Ui.t("player.media.music") }
            if (it.kind === "drive" && !it.title) o.title = Ui.t("player.media.drive")
            if (it.kind === "dvd") {
                o.title = it.title || Ui.t("player.dvd")
                o.sub = it.game ? Ui.t("player.dvd.game", { system: it.game === "ps2" ? "PlayStation 2" : "PlayStation" })
                                : it.ready ? Ui.t("player.dvd.titles", { n: it.n }) : Ui.t("player.dvd.reading")
            }
            if (it.kind === "dvdtitle") {
                o.title = Ui.t("player.dvd.title", { n: it.ix })
                o.sub = [vs.fmtTime(it.dur, ""), it.chapters > 1 ? Ui.t("player.dvd.chapters", { n: it.chapters }) : "",
                         it.aspect || ""].filter(function (x) { return x }).join(" · ")
            }
            if (it.kind === "dvdall") { o.title = Ui.t("player.dvd.playAll"); o.sub = Ui.t("player.dvd.titles", { n: it.n }) }
            if (it.kind === "eject") { o.title = Ui.t("player.dvd.eject"); o.sub = Ui.t("player.dvd.ejectSub") }
            if (it.kind === "video" && it.resume && it.resume.pos > 0) o.sub = Ui.t("player.media.resumeAt", { time: vs.fmtTime(it.resume.pos, "") })
            return o
        })
    }
    function openPath(p, fromArg) {
        msg = ""
        if (!p) {
            Api.get("/api/media/roots", function (r) {
                r = r || {}
                path = ""; parentPath = ""; folderName = ""
                roots = decorate(r.roots)
                resumes = decorate(r.resume)
                items = []
                focusLater()
            }, function () { msg = Ui.t("player.media.unreachable") })
            return
        }
        Api.get("/api/media/list?path=" + encodeURIComponent(p), function (r) {
            r = r || {}
            path = r.path || p
            parentPath = r.parent || ""
            folderName = r.name || (r.dvd ? Ui.t("player.dvd") : "")
            items = decorate((r.audio && r.audio > 1 ? [{ kind: "playall", title: Ui.t("player.media.playAll"), sub: Ui.t("player.media.tracks", { n: r.audio }) }] : []).concat(r.items || []))
            if (!r.items || !r.items.length) msg = Ui.t("player.media.folderEmpty")
            thumbs = ({})
            if (r.coversPending) coverPoll.restart(); else coverPoll.stop()
            if (fromArg && r.select) {
                for (var i = 0; i < items.length; i++) if (items[i].path === r.select) { activate(items[i]); break }
            }
            focusLater()
        }, function (e) {
            msg = Ui.t("player.media.notFound")
            if (!path) openPath("")
        })
    }
    // Solange der Launcher Cover sucht: Liste neu holen und nur die Bilder der Kacheln austauschen (Fokus bleibt)
    Timer {
        id: coverPoll
        interval: 3000; repeat: true
        onTriggered: {
            if (!mv.path || mv.phase !== "browse") return stop()
            var p = mv.path
            Api.get("/api/media/list?path=" + encodeURIComponent(p), function (r) {
                if (!r || mv.path !== p) return
                var t = {}, changed = false
                for (var i = 0; i < (r.items || []).length; i++) {
                    var it = r.items[i]
                    if (it.thumb) { t[it.path] = it.thumb; changed = true }
                }
                if (changed) mv.thumbs = t
                if (!r.coversPending) coverPoll.stop()
            })
        }
    }
    function focusLater() {
        Qt.callLater(function () {
            var all = Nav.collect(browser)
            var pick = null
            for (var i = 0; i < all.length; i++) if (all[i].it && all[i].it.path && all[i].it.path === selectAfter) pick = all[i]
            if (!pick) for (i = 0; i < all.length; i++) if (all[i].it) { pick = all[i]; break }
            selectAfter = ""
            trk.reset()
            if (pick) app.setFocus(pick, true)
        })
    }
    function up() {
        if (!path) return app.leave()
        vs.playSound("back")
        selectAfter = path
        openPath(parentPath)
    }
    function activate(it) {
        if (!it) return
        if (it.kind === "dir" || it.kind === "videos" || it.kind === "music" || it.kind === "drive" || it.kind === "dvd") return openPath(it.path)
        if (it.kind === "dvdtitle" || it.kind === "dvdall") return playDvd(it)
        if (it.kind === "eject") {
            Api.post("/api/media/eject", { dev: String(it.path).slice(4) }, function () { mv.dvdSig = ""; openPath("") },
                     function () { app.toast(Ui.t("player.dvd.ejectFailed"), true) })
            return
        }
        if (it.kind === "dl") return dlView.show()
        if (it.kind === "playall") return playAudio(audioItems, 0, path, folderName)
        if (it.kind === "audio") {                    // nach Pfad suchen: die Kachel haelt eine Kopie des Eintrags
            var at = 0
            for (var i = 0; i < audioItems.length; i++) if (audioItems[i].path === it.path) { at = i; break }
            return playAudio(audioItems, at, path, folderName)
        }
        if (it.kind === "video" || it.kind === "resume") {
            if (it.resume && it.resume.pos > 30) return dlg.ask(it)
            return playVideo(it, 0)
        }
    }

    // ------------------------------------------------------------ Wiedergabe
    function playVideo(it, from) {
        playing = it
        playlist = []
        phase = "video"
        if (app.embedded) browser.hide()
        var o = {}
        if (from > 0) o.start = String(Math.floor(from))
        player.setProp("loop-file", "no")
        player.setProp("loop-playlist", "no")
        vs.setTitle(it.title || it.name || "")
        player.play(it.path, o)
        Api.post("/api/radio/stop", null)
        showOsd()
    }
    // DVD: alle Titel ab dem gewaehlten als Wiedergabeliste (Folge fuer Folge); "dvdall" = ab dem ersten
    function playDvd(it) {
        var titles = items.filter(function (x) { return x.kind === "dvdtitle" })
        var at = 0
        for (var i = 0; i < titles.length; i++) if (it.kind === "dvdtitle" && titles[i].path === it.path) at = i
        if (!titles.length) return
        playing = titles[at]
        playlist = titles
        phase = "video"
        if (app.embedded) browser.hide()
        player.setProp("loop-file", "no")
        player.setProp("loop-playlist", "no")
        player.setProp("deinterlace", deint ? "yes" : "no")
        vs.setTitle(folderName || Ui.t("player.dvd"))
        player.playList(titles.map(function (t) { return t.path }), at, {})
        Api.post("/api/radio/stop", null)
        showOsd()
    }
    function dvdStep(d) {
        var n = (st.plpos || 0) + d
        if (n < 0 || n >= (st.plcount || 0)) return
        player.playlistGo(n)
        player.osdText(Ui.t("player.dvd.title", { n: playlist[n].ix }), "2000")
        showOsd()
    }
    // DVD-Laufwerk auf der Startseite beobachten: Disc rein/raus -> Kacheln neu laden
    Timer {
        interval: 3000; repeat: true; triggeredOnStart: true
        running: mv.phase === "browse" && !mv.path && vsMode === "media"
        onTriggered: Api.get("/api/media/dvd", function (r) {
            var sig = ((r && r.discs) || []).map(function (d) { return d.dev + ":" + d.ready + ":" + d.n }).join(",")
            if (sig !== mv.dvdSig) { var first = mv.dvdSig === "" && sig === ""; mv.dvdSig = sig; if (!first) mv.openPath("") }
        })
    }

    // Cover des laufenden Titels neu suchen lassen; das Bild ein paar Mal neu laden, bis das neue da ist
    property int coverNonce: 0
    function refreshCover() {
        var it = mv.curTrackItem
        if (!it || !it.path) return
        Api.post("/api/media/covers/refresh", { path: it.path }, function () {
            app.toast(Ui.t("player.cover.refreshing"))
            coverReload.left = 10
            coverReload.restart()
        })
    }
    Timer {
        id: coverReload
        property int left: 0
        interval: 3000; repeat: true
        onTriggered: { mv.coverNonce++; if (--left <= 0) stop() }
    }
    function playAudio(list, index, folder, folderName) {
        if (!list.length) return
        origList = list
        if (shuffle) {                                // gewaehlter Titel zuerst, der Rest gemischt
            list = [list[index]].concat(shuffled(list.filter(function (x, i) { return i !== index })))
            index = 0
        }
        playlist = list
        playing = list[index]
        playFolder = folder || path
        playFolderName = folderName !== undefined ? folderName : mv.folderName
        phase = "audio"
        browser.hide()
        applyRepeat()
        player.playList(list.map(function (i) { return i.path }), index, {})
        vs.setTitle(Ui.t("player.media.music"))
        Api.post("/api/radio/stop", null)
    }
    // Wiederholen an mpv weitergeben: Titel = loop-file, Ordner = loop-playlist; "once" und "next" spielen die Liste
    // einmal, "next" holt danach den naechsten Ordner (audioEnded)
    function applyRepeat() {
        player.setProp("loop-file", phase === "audio" && repeat === "track" ? "inf" : "no")
        player.setProp("loop-playlist", phase === "audio" && repeat === "folder" ? "inf" : "no")
    }
    function setRepeat(m) {
        if (repeatModes.indexOf(m) < 0) return
        repeat = m
        vs.prefSet("repeat", m)
        applyRepeat()
        app.toast(Ui.t("player.repeat." + m))
        player.osdText(Ui.t("player.repeat." + m), "2000")
    }
    function cycleRepeat() { setRepeat(repeatModes[(repeatModes.indexOf(repeat) + 1) % repeatModes.length]) }
    function shuffled(a) {
        a = a.slice()
        for (var i = a.length - 1; i > 0; i--) { var j = Math.floor(Math.random() * (i + 1)); var t = a[i]; a[i] = a[j]; a[j] = t }
        return a
    }
    // Zufall an/aus waehrend der Wiedergabe: der laufende Titel spielt weiter, danach kommt der Rest neu sortiert
    // (aus: in Ordnerreihenfolge ab dem laufenden Titel, bei "Ordner wiederholen" danach wieder von vorn)
    function setShuffle(on) {
        shuffle = on
        vs.prefSet("shuffle", on ? "1" : "0")
        var msg = Ui.t(on ? "player.shuffle.on" : "player.shuffle.off")
        app.toast(msg)
        player.osdText(msg, "2000")
        if (phase !== "audio" || !origList.length) return
        var cur = curTrackItem, ci = -1
        for (var i = 0; i < origList.length; i++) if (cur && origList[i].path === cur.path) ci = i
        var rest
        if (on) rest = shuffled(origList.filter(function (x, i) { return i !== ci }))
        else rest = origList.slice(ci + 1).concat(repeat === "folder" ? origList.slice(0, Math.max(0, ci)) : [])
        player.command(["playlist-clear"])           // laesst den laufenden Titel stehen (Position 0)
        for (i = 0; i < rest.length; i++) player.command(["loadfile", rest[i].path, "append"])
        playlist = (cur ? [cur] : []).concat(rest)
    }
    // Ende der Liste: Stopp oder (Modus "next") naechster Ordner mit Musik – Reihenfolge wie in der Mediathek,
    // auch ueber Interpreten hinweg (Interpret A/Album 2 -> Interpret B/Album 1)
    function audioEnded() {
        if (phase !== "audio") return true
        if (!st.idle) return false                    // naechster Titel laeuft schon an (oder mpv meldet idle noch nicht)
        if (repeat !== "next" || !playFolder) backToBrowser()
        else nextFolder(false)
        return true
    }
    // byKey: mit ▶ am letzten Titel – gibt es keinen Ordner mehr, laeuft der aktuelle Titel einfach weiter
    function nextFolder(byKey) {
        if (nextBusy) return
        nextBusy = true
        Api.get("/api/media/nextfolder?path=" + encodeURIComponent(playFolder), function (r) {
            nextBusy = false
            if (phase !== "audio") return
            if (!r || !r.path || !r.items || !r.items.length) {
                app.toast(Ui.t("player.media.allPlayed"))
                if (!byKey) backToBrowser()
                return
            }
            playAudio(decorate(r.items), 0, r.path, r.name)
            app.toast(Ui.t("player.media.nextFolder", { name: r.name }))
            player.osdText(Ui.t("player.media.nextFolder", { name: r.name }), "3000")
        }, function () { nextBusy = false; backToBrowser() })
    }
    function saveResume(finished) {
        if (phase !== "video" || !playing || !playing.path || dvdPlaying) return
        var dur = st.duration || 0, pos = finished ? dur : (st.position || 0)
        if (dur <= 0) return
        Api.post("/api/media/resume", { path: playing.path, pos: pos, dur: dur })
    }
    Timer { interval: 10000; repeat: true; running: mv.phase === "video" && !mv.st.paused; onTriggered: mv.saveResume(false) }
    function stopPlayback(silent) {
        saveResume(false)
        player.stop()
        backToBrowser(silent)
    }
    function backToBrowser(silent) {
        var was = phase === "audio" ? curTrackItem : playing
        var wasAudio = phase === "audio"
        phase = "browse"
        osdOn = false
        menu.hide()
        tech.open = false
        playing = null
        vs.setTitle(Ui.t("player.media.title"))
        browser.show()
        if (was && was.path) selectAfter = was.path
        if (wasAudio && playFolder && playFolder !== path && !silent) path = playFolder    // nach "naechster Ordner"
        Api.post("/api/media/now", {})
        if (!silent) openPath(path)                 // Fortschritt (Weiterschauen) neu laden
    }
    Connections {
        target: mv.player
        enabled: vsMode === "media"
        function onEnded(reason, cause) {
            if (mv.phase === "browse") return
            if (reason === "error") {
                app.toast(Ui.t("player.media.cantPlay"), true)
                return mv.backToBrowser()
            }
            if (reason === "quit") return mv.backToBrowser()          // mpv-Fenster geschlossen (Stufe 2)
            if (reason === "eof") {
                if (mv.dvdPlaying) return dvdEnd.restart()           // naechster Titel laeuft an oder Liste zu Ende
                if (mv.phase === "video") { mv.saveResume(true); return mv.backToBrowser() }
                endCheck.restart()                                    // Musik: naechster Titel oder Ende der Liste?
            }
        }
    }
    Timer {
        id: dvdEnd
        property int left: 0
        interval: 300; repeat: true
        onRunningChanged: if (running) left = 8
        onTriggered: { if (mv.phase !== "video") return stop(); if (mv.st.idle) { stop(); return mv.backToBrowser() } if (--left <= 0) stop() }
    }
    // Nach jedem Titelende kurz nachsehen, ob die Liste zu Ende ist (mpv meldet "idle" etwas spaeter als das Ende)
    Timer {
        id: endCheck
        property int left: 0
        interval: 300; repeat: true
        onRunningChanged: if (running) left = 8
        onTriggered: if (mv.audioEnded() || --left <= 0) stop()
    }

    // Zur Startseite (Menue-Eintrag, fuer Controller ohne Guide-Taste): Musik laeuft weiter, Video haelt an
    function goHome() {
        menu.hide()
        if (phase === "video" && !st.paused) player.setPause(true)
        Api.post("/api/home", null)
    }
    // Was laeuft, fuer die Kachel auf der Startseite
    function reportNow() {
        if (phase === "browse") return
        var it = curTrackItem, meta = st.meta || {}
        var title = phase === "audio" ? (meta.title || (it ? (it.title || it.name) : "")) : (playing ? (playing.title || playing.name) : "")
        var sub = phase === "audio" ? (meta.artist || meta.album_artist || playFolderName || "") : (st.paused ? Ui.t("player.paused") : "")
        Api.post("/api/media/now", { title: title, sub: sub, kind: phase, paused: !!st.paused })
    }
    property string nowKey: phase + "|" + (curTrackItem ? curTrackItem.path : "") + "|" + ((st.meta || {}).title || "") + "|" + !!st.paused
    onNowKeyChanged: nowT.restart()
    Timer { id: nowT; interval: 300; onTriggered: mv.reportNow() }

    function showOsd() { osdOn = true; osdT.restart() }
    Timer { id: osdT; interval: 3500; onTriggered: if (!mv.st.paused) mv.osdOn = false }
    function seek(d) {
        seekAcc += d
        seekT.restart()
        player.seek(d)
        showOsd()
        player.osdText((d > 0 ? "+" : "−") + vs.fmtTime(Math.abs(d), ""), "1200")
    }
    Timer { id: seekT; interval: 1200; onTriggered: mv.seekAcc = 0 }

    function key(k) {
        if (dlView.open) return dlView.key(k)
        if (dlg.open) return dlg.key(k)
        if (menu.open) return menu.key(k)
        if (phase === "browse") {
            if (k === "b") return up()
            if (k === "a" || k === "play") { app.activate(); return }
            if (k === "up" || k === "down" || k === "left" || k === "right") return app.move(k)
            if (k === "chup" || k === "lt") { var movedL = false; for (var i = 0; i < 4; i++) if (app.move("left", true)) movedL = true; if (movedL) vs.playSound("group"); return }
            if (k === "chdown" || k === "rt") { var movedR = false; for (var j = 0; j < 4; j++) if (app.move("right", true)) movedR = true; if (movedR) vs.playSound("group"); return }
            return
        }
        if (k === "b" || k === "stop") return stopPlayback()
        if (k === "a" || k === "play") { player.togglePause(); showOsd(); return }
        if (k === "up" || k === "volup") return app.volume("up")
        if (k === "down" || k === "voldown") return app.volume("down")
        if (k === "select") { tech.open = !tech.open; return }
        if (k === "start") return menu.show()
        if (k === "home") return goHome()
        if (phase === "video") {
            if (dvdPlaying && (k === "x" || k === "next")) return dvdStep(1)
            if (dvdPlaying && (k === "y" || k === "prev")) return dvdStep(-1)
            if (k === "left") return seek(-10)
            if (k === "right") return seek(10)
            if (k === "lb" || k === "chdown") return seek(-60)
            if (k === "rb" || k === "chup") return seek(60)
            if (k === "x" || k === "y") return showOsd()
        } else {
            if (k === "left" || k === "prev") return prevTrack()
            if (k === "right" || k === "next") return nextTrack()
            if (k === "lb" || k === "chdown") return player.seek(-10)
            if (k === "rb" || k === "chup") return player.seek(10)
            if (k === "y") return cycleRepeat()
            if (k === "x") return setShuffle(!shuffle)
        }
    }
    function prevTrack() {
        if ((st.position || 0) > 4 || (st.plpos || 0) <= 0) return player.seekTo(0)
        player.playlistGo(st.plpos - 1)
    }
    function nextTrack() {
        if ((st.plpos || 0) < (st.plcount || 0) - 1) return player.playlistGo(st.plpos + 1)
        if (repeat === "folder") return player.playlistGo(0)
        if (repeat === "next") return nextFolder(true)                          // gleich zum naechsten Ordner
    }
    readonly property var curTrackItem: phase === "audio" && st.plpos >= 0 && playlist[st.plpos] ? playlist[st.plpos] : playing

    // ------------------------------------------------------------ Mediathek-Seite
    Layer {
        id: browser
        scope: "media"
        title: mv.path ? mv.folderName : Ui.t("player.media.title")
        track: trk
        anchors.fill: parent
        headRight: NowLine {
            main: !mv.path ? "" : mv.path.indexOf("dvd:") === 0
                  ? Ui.t("player.dvd.titles", { n: mv.items.filter(function (i) { return i.kind === "dvdtitle" }).length })
                  : Ui.t("player.media.items", { n: Ui.num(mv.items.filter(function (i) { return i.kind !== "playall" }).length, 0) })
            sub: !mv.path && mv.coverState && mv.coverState.running
                 ? Ui.t("player.covers.progress", { done: mv.coverState.done, total: mv.coverState.total, found: mv.coverState.found }) : ""
        }
        showBar: !mv.path
        bar: [
            Pill { iconName: "image"; text: Ui.t("player.covers.auto"); on: !!(mv.coverState && mv.coverState.auto)
                   onTriggered: Api.post("/api/media/covers/auto", { on: !(mv.coverState && mv.coverState.auto) }, function (s) { mv.coverState = s }) },
            Pill { iconName: "download"; text: Ui.t("player.covers.embed"); on: !!(mv.coverState && mv.coverState.embed)
                   onTriggered: Api.post("/api/media/covers/embed", { on: !(mv.coverState && mv.coverState.embed) }, function (s) {
                       mv.coverState = s
                       app.toast(Ui.t(s && s.embed ? "player.covers.embedOn" : "player.covers.embedOff"))
                   }) },
            Pill { iconName: "update"; text: Ui.t("player.covers.scan"); enabled: !(mv.coverState && mv.coverState.running)
                   onTriggered: Api.post("/api/media/covers/scan", {}, function (s) { mv.coverState = s; app.toast(Ui.t("player.covers.started")) }) }
        ]
        Track {
            id: trk
            anchors.fill: parent
            Group {
                visible: !mv.path && mv.resumes.length > 0
                title: Ui.t("player.media.resume")
                TileGrid { items: mv.path ? [] : mv.resumes; rows: mv.fit.n; cellW: mv.cell; cellH: mv.cell; delegate: tileDelegate }
            }
            Group {
                visible: !mv.path
                title: Ui.t("player.media.library")
                TileGrid { items: mv.path ? [] : mv.roots; rows: mv.fit.n; cellW: mv.cell; cellH: mv.cell; delegate: tileDelegate }
            }
            Group {
                visible: !mv.path
                title: Ui.t("dl.group")
                TileGrid { items: mv.path ? [] : [{ kind: "dl", title: Ui.t("dl.title"), sub: Ui.t("dl.tile.sub"), path: "" }]
                           rows: mv.fit.n; cellW: mv.cell; cellH: mv.cell; delegate: tileDelegate }
            }
            Group {
                visible: !!mv.path
                title: mv.folderName
                showTitle: false
                Column {
                    spacing: 12 * Ui.f
                    Txt {
                        visible: mv.msg !== ""
                        text: mv.msg
                        width: Math.min(implicitWidth, Ui.screenW * 0.5)
                        wrapMode: Text.Wrap; elide: Text.ElideNone
                        color: Ui.c.textFaint
                    }
                    TileGrid { items: mv.path ? mv.items : []; rows: mv.fit.n; cellW: mv.cell; cellH: mv.cell; delegate: tileDelegate }
                }
            }
        }
    }
    // Stand der Cover-Suche (Startseite der Mediathek)
    Timer {
        interval: 2000; repeat: true; triggeredOnStart: true
        running: mv.phase === "browse" && !mv.path && vsMode === "media"
        onTriggered: Api.get("/api/media/covers", function (s) {
            var was = mv.coverState && mv.coverState.running
            mv.coverState = s
            if (was && s && !s.running) app.toast(Ui.t("player.covers.done", { found: s.found, total: s.total }))
        })
    }
    Component {
        id: tileDelegate
        MediaTile {
            it: modelData
            coverOverride: mv.thumbs[modelData.path] || ""
            onTriggered: mv.activate(modelData)
        }
    }
    Hints {
        visible: mv.phase === "browse" && !dlView.open
        x: Ui.padX
        width: parent.width - 2 * Ui.padX
        anchors.bottom: parent.bottom; anchors.bottomMargin: 14 * Ui.f
        z: 31
        list: [Ui.t("hint.open"), Ui.t("hint.back")].concat(trk.scrollable ? [Ui.t("player.hint.pages")] : [])
    }

    // ------------------------------------------------------------ Video
    MouseArea {
        anchors.fill: parent
        visible: mv.phase === "video"
        hoverEnabled: true
        acceptedButtons: Qt.LeftButton | Qt.RightButton
        onPositionChanged: { mv.showOsd(); mouseBar.poke() }
        onClicked: function (m) { if (m.button === Qt.RightButton) mv.key("b"); else mv.key("a") }
        onWheel: function (w) { app.volume(w.angleDelta.y > 0 ? "up" : "down") }
    }
    Rectangle {                                    // Stufe 2: Bild im eigenen Fenster
        anchors.fill: parent
        visible: mv.phase === "video" && !app.embedded
        color: Ui.c.bgMain
        Txt { anchors.centerIn: parent; text: Ui.t("player.ownWindow"); color: Ui.c.textDim }
    }
    Column {
        anchors.centerIn: parent
        visible: app.embedded && mv.phase === "video" && (!!mv.st.buffering || (!mv.st.duration && mv.st.active))
        spacing: 14 * Ui.f
        Spinner { anchors.horizontalCenter: parent.horizontalCenter; size: 54 * Ui.f; line: 4 * Ui.f }
    }
    Rectangle {                                    // Pause
        anchors.centerIn: parent
        visible: mv.phase === "video" && !!mv.st.paused
        width: 110 * Ui.f; height: width; radius: width / 2
        color: Ui.alpha(Ui.c.surfaceDialog, 0.75)
        Glyph { anchors.centerIn: parent; name: "pause"; width: parent.width * 0.42; height: width }
    }
    Item {
        id: vosd
        anchors.left: parent.left; anchors.right: parent.right; anchors.bottom: parent.bottom
        height: vbox.height + 70 * Ui.f
        opacity: mv.phase === "video" && (mv.osdOn || !!mv.st.paused) ? 1 : 0
        visible: opacity > 0
        Behavior on opacity { NumberAnimation { duration: 220 } }
        Rectangle {
            anchors.fill: parent
            gradient: Gradient {
                GradientStop { position: 0.0; color: "transparent" }
                GradientStop { position: 0.4; color: Ui.alpha(Ui.c.bgMain, 0.75) }
                GradientStop { position: 1.0; color: Ui.alpha(Ui.c.bgMain, 0.95) }
            }
        }
        Column {
            id: vbox
            x: Ui.padX
            width: parent.width - 2 * Ui.padX
            anchors.bottom: parent.bottom; anchors.bottomMargin: 22 * Ui.f
            spacing: 12 * Ui.f
            Txt { width: parent.width; font.pixelSize: 26 * Ui.f; font.weight: Font.Light
                  text: mv.dvdPlaying ? [mv.folderName || Ui.t("player.dvd"), mv.dvdItem ? Ui.t("player.dvd.title", { n: mv.dvdItem.ix }) : "",
                                         mv.st.plcount > 1 ? ((mv.st.plpos || 0) + 1) + "/" + mv.st.plcount : ""]
                                        .filter(function (x) { return x }).join(" · ")
                      : mv.playing ? (mv.playing.title || mv.playing.name || "") : "" }
            Row {
                width: parent.width
                spacing: 18 * Ui.f
                Txt { id: tPos; text: vs.fmtTime(mv.st.position || 0, ""); font.pixelSize: 16 * Ui.f; anchors.verticalCenter: parent.verticalCenter }
                Bar {
                    width: parent.width - tPos.width - tDur.width - 36 * Ui.f
                    anchors.verticalCenter: parent.verticalCenter
                    value: mv.st.duration > 0 ? (mv.st.position || 0) / mv.st.duration : 0
                    buffered: mv.st.duration > 0 ? ((mv.st.position || 0) + (mv.st.cache || 0)) / mv.st.duration : 0
                    seekable: true
                    onSeek: function (f) { mv.player.seekTo(f * mv.st.duration); mv.showOsd() }
                }
                Txt { id: tDur; text: mv.st.duration > 0 ? vs.fmtTime(mv.st.duration, "") : "–"; color: Ui.c.textDim; font.pixelSize: 16 * Ui.f; anchors.verticalCenter: parent.verticalCenter }
            }
            Hints {
                width: parent.width
                list: [Ui.t("player.hint.pause"), Ui.t("player.hint.seek"), Ui.t("player.hint.seekBig")]
                      .concat(mv.dvdPlaying && mv.st.plcount > 1 ? [Ui.t("player.hint.dvdTitles")] : [])
                      .concat([Ui.t("player.hint.volumeUD"), Ui.t("player.hint.menu"), Ui.t("hint.homeShort"), Ui.t("player.hint.stop")])
            }
        }
    }

    // ------------------------------------------------------------ Musik
    Rectangle {
        id: music
        anchors.fill: parent
        visible: mv.phase === "audio"
        color: Ui.c.bgMain
        Background { anchors.fill: parent }
        MouseArea {
            anchors.fill: parent
            acceptedButtons: Qt.LeftButton | Qt.RightButton
            onClicked: function (m) { if (m.button === Qt.RightButton) mv.key("b"); else mv.key("a") }
            onWheel: function (w) { app.volume(w.angleDelta.y > 0 ? "up" : "down") }
        }
        Rectangle {
            id: cover
            x: Ui.padX
            anchors.verticalCenter: parent.verticalCenter
            anchors.verticalCenterOffset: -20 * Ui.f
            width: Math.min(parent.height * 0.5, parent.width * 0.32); height: width
            color: Ui.c.surfaceCard
            // Bild des Titels; fehlt es noch, sucht der Launcher im Netz – dann ein paar Mal nachfragen
            property string base: mv.curTrackItem && mv.curTrackItem.thumb ? Ui.url(mv.curTrackItem.thumb) : ""
            property int tries: 0
            onBaseChanged: tries = 0
            Timer {
                interval: 4000; repeat: true
                running: coverImg.status === Image.Error && cover.tries < 10 && mv.phase === "audio"
                onTriggered: cover.tries++
            }
            Image {
                id: coverImg
                anchors.fill: parent
                source: cover.base ? cover.base + (cover.tries ? "&try=" + cover.tries : "") + (mv.coverNonce ? "&n=" + mv.coverNonce : "") : ""
                fillMode: Image.PreserveAspectCrop
                asynchronous: true
                sourceSize: Qt.size(Math.ceil(width), Math.ceil(height))
                visible: status === Image.Ready
            }
            Glyph { anchors.centerIn: parent; visible: coverImg.status !== Image.Ready; name: "music"; width: parent.width * 0.36; height: width; opacity: 0.6 }
        }
        Column {
            id: musicInfo
            anchors.left: cover.right; anchors.leftMargin: 48 * Ui.f
            anchors.right: parent.right; anchors.rightMargin: Ui.padX
            anchors.top: cover.top
            spacing: 10 * Ui.f
            Txt {
                width: parent.width
                text: (mv.st.meta && mv.st.meta.title) || (mv.curTrackItem ? (mv.curTrackItem.title || mv.curTrackItem.name) : "")
                font.pixelSize: 36 * Ui.f; font.weight: Font.Light
                wrapMode: Text.WordWrap; maximumLineCount: 2
            }
            Txt {
                width: parent.width
                visible: text !== ""
                text: [(mv.st.meta && (mv.st.meta.artist || mv.st.meta.album_artist)) || "", (mv.st.meta && mv.st.meta.album) || ""].filter(function (s) { return s }).join(" · ")
                color: Ui.c.textSecondary
                font.pixelSize: 19 * Ui.f
            }
            Item { width: 1; height: 10 * Ui.f }
            Row {
                width: parent.width
                spacing: 18 * Ui.f
                Glyph { name: mv.st.paused ? "pause" : "playfill"; width: 22 * Ui.f; height: width; anchors.verticalCenter: parent.verticalCenter }
                Txt { id: mPos; text: vs.fmtTime(mv.st.position || 0, ""); font.pixelSize: 15 * Ui.f; anchors.verticalCenter: parent.verticalCenter }
                Bar {
                    width: parent.width - 22 * Ui.f - mPos.width - mDur.width - 54 * Ui.f
                    anchors.verticalCenter: parent.verticalCenter
                    value: mv.st.duration > 0 ? (mv.st.position || 0) / mv.st.duration : 0
                    seekable: true
                    onSeek: function (f) { mv.player.seekTo(f * mv.st.duration) }
                }
                Txt { id: mDur; text: mv.st.duration > 0 ? vs.fmtTime(mv.st.duration, "") : "–"; color: Ui.c.textDim; font.pixelSize: 15 * Ui.f; anchors.verticalCenter: parent.verticalCenter }
            }
            Txt {
                visible: mv.st.plcount > 1
                text: Ui.t("player.media.trackOf", { n: (mv.st.plpos || 0) + 1, total: mv.st.plcount || 0 })
                color: Ui.c.textDim
                font.pixelSize: 15 * Ui.f
            }
            Row {                                       // Ordner und Wiederholen
                spacing: 10 * Ui.f
                Glyph { name: "folder"; width: 17 * Ui.f; height: width; opacity: 0.7; anchors.verticalCenter: parent.verticalCenter }
                Txt { text: mv.playFolderName; color: Ui.c.textDim; font.pixelSize: 15 * Ui.f; anchors.verticalCenter: parent.verticalCenter
                      width: Math.min(implicitWidth, Ui.screenW * 0.25) }
                Rectangle {
                    color: Ui.alpha(Ui.c.surfaceCard, 0.9)
                    border.width: 1; border.color: Ui.c.borderSubtle
                    width: repRow.width + 20 * Ui.f; height: repRow.height + 8 * Ui.f
                    anchors.verticalCenter: parent.verticalCenter
                    Row {
                        id: repRow
                        anchors.centerIn: parent
                        spacing: 7 * Ui.f
                        Glyph { name: mv.repeat === "track" ? "repeat1" : mv.repeat === "once" ? "stop" : mv.repeat === "next" ? "next" : "repeat"
                                width: 15 * Ui.f; height: width; anchors.verticalCenter: parent.verticalCenter }
                        Txt { text: Ui.t("player.repeat." + mv.repeat); font.pixelSize: 14 * Ui.f; anchors.verticalCenter: parent.verticalCenter }
                    }
                    MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: mv.cycleRepeat() }
                }
                Rectangle {
                    color: mv.shuffle ? Ui.c.surfaceActive : Ui.alpha(Ui.c.surfaceCard, 0.9)
                    border.width: 1; border.color: Ui.c.borderSubtle
                    width: shRow.width + 20 * Ui.f; height: shRow.height + 8 * Ui.f
                    anchors.verticalCenter: parent.verticalCenter
                    opacity: mv.shuffle ? 1 : 0.55
                    Row {
                        id: shRow
                        anchors.centerIn: parent
                        spacing: 7 * Ui.f
                        Glyph { name: "shuffle"; width: 15 * Ui.f; height: width; anchors.verticalCenter: parent.verticalCenter }
                        Txt { text: Ui.t("player.shuffle"); font.pixelSize: 14 * Ui.f; anchors.verticalCenter: parent.verticalCenter }
                    }
                    MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: mv.setShuffle(!mv.shuffle) }
                }
            }
        }
        Column {                                        // die naechsten Titel – so viele, wie bis zur Hinweiszeile passen
            id: upNext
            readonly property real rowH: 27 * Ui.f
            readonly property int fit: Math.max(0, Math.floor((musicHints.y - 18 * Ui.f - y) / rowH))
            anchors.left: musicInfo.left; anchors.right: musicInfo.right
            y: musicInfo.y + musicInfo.height + 16 * Ui.f
            Repeater {
                model: mv.playlist.slice((mv.st.plpos || 0) + 1, (mv.st.plpos || 0) + 1 + Math.min(upNext.fit, 5))
                Txt {
                    width: upNext.width
                    height: upNext.rowH
                    verticalAlignment: Text.AlignVCenter
                    text: (index === 0 ? Ui.t("player.media.upNext") + "  " : "") + (modelData.title || modelData.name)
                    color: index === 0 ? Ui.c.textSecondary : Ui.c.textFaint
                    font.pixelSize: 16 * Ui.f
                    elide: Text.ElideRight
                }
            }
        }
        Hints {
            id: musicHints
            x: Ui.padX
            width: parent.width - 2 * Ui.padX
            anchors.bottom: parent.bottom; anchors.bottomMargin: 14 * Ui.f
            list: [Ui.t("player.hint.pause"), Ui.t("player.hint.tracks"), Ui.t("player.hint.seekSmall"), Ui.t("player.hint.volumeUD"),
                   Ui.t("player.hint.repeat"), Ui.t("player.hint.shuffle"), Ui.t("player.hint.playbackMenu"), Ui.t("hint.homeShort"), Ui.t("player.hint.stop")]
        }
    }

    // ------------------------------------------------------------ Fortsetzen?
    Rectangle {
        id: dlg
        property bool open: false
        property var it: null
        readonly property bool navBarrier: true
        anchors.fill: parent
        visible: open
        z: 48
        color: Ui.c.surfaceOverlay
        MouseArea { anchors.fill: parent; acceptedButtons: Qt.AllButtons; onClicked: function (m) { if (m.button === Qt.RightButton) dlg.close() } }
        function ask(item) {
            it = item
            open = true
            Qt.callLater(function () { app.setFocus(btnResume, true) })
        }
        function close() {
            open = false
            Qt.callLater(mv.focusLater)
        }
        function key(k) {
            if (k === "b") return close()
            if (k === "a" || k === "play") { app.activate(); return }
            if (k === "left" || k === "right" || k === "up" || k === "down") return app.move(k)
        }
        Rectangle {
            anchors.centerIn: parent
            width: Math.max(dcol.implicitWidth, 420 * Ui.f) + 64 * Ui.f
            height: dcol.implicitHeight + 56 * Ui.f
            color: Ui.c.surfaceDialog
            border.width: 1
            border.color: Ui.c.borderSubtle
            Column {
                id: dcol
                anchors.centerIn: parent
                spacing: 16 * Ui.f
                Txt { text: dlg.it ? (dlg.it.title || dlg.it.name || "") : ""; font.pixelSize: 24 * Ui.f; font.weight: Font.Light; width: Math.min(implicitWidth, Ui.screenW * 0.5) }
                Txt { text: dlg.it && dlg.it.resume ? Ui.t("player.media.resumeAsk", { time: vs.fmtTime(dlg.it.resume.pos, "") }) : ""; color: Ui.c.textDim }
                Row {
                    spacing: 12 * Ui.f
                    Btn { id: btnResume; text: Ui.t("player.media.resumeYes"); onTriggered: { var i = dlg.it; dlg.open = false; mv.playVideo(i, i.resume.pos - 3) } }
                    Btn { text: Ui.t("player.media.fromStart"); onTriggered: { var i = dlg.it; dlg.open = false; mv.playVideo(i, 0) } }
                }
            }
        }
    }

    MouseBar {
        id: mouseBar
        visible: mv.phase === "video" && !menu.open && !dlg.open && opacity > 0
        buttons: [
            { icon: "pause", tip: Ui.t("player.paused"), act: function () { mv.player.togglePause(); mv.showOsd() } },
            { icon: "subs", tip: Ui.t("player.menu.title"), act: function () { menu.show() } },
            { icon: "home", tip: Ui.t("player.menu.home"), act: function () { mv.goHome() } },
            { icon: "minus", tip: Ui.t("player.volume"), act: function () { app.volume("down") } },
            { icon: "plus", tip: Ui.t("player.volume"), act: function () { app.volume("up") } },
            { icon: "stop", tip: Ui.t("player.btn.stop"), act: function () { mv.stopPlayback() } }
        ]
    }
    DownloadView {
        id: dlView
        onClosed: {
            if (!mv.path) mv.openPath("")                  // neue Musik: Weiterschauen/Bibliothek neu laden
            Qt.callLater(function () { var it = Nav.collect(browser); for (var i = 0; i < it.length; i++) if (it[i].it && it[i].it.kind === "dl") return app.setFocus(it[i], true) })
        }
    }
    TechInfo { id: tech }
    TrackMenu {
        id: menu
        title: mv.phase === "audio" ? Ui.t("player.menu.playback") : Ui.t("player.menu.title")
        repeatMode: mv.phase === "audio" ? mv.repeat : ""
        shuffleState: mv.phase === "audio" ? (mv.shuffle ? 1 : 0) : -1
        onShuffleToggled: mv.setShuffle(!mv.shuffle)
        homeSub: mv.phase === "video" ? Ui.t("player.menu.homeVideo") : Ui.t("player.menu.homeMusic")
        onRepeatChosen: function (m) { mv.setRepeat(m) }
        extraRows: mv.dvdPlaying ? [{ id: "deint", label: Ui.t("player.dvd.deint") + (mv.deint ? " ✓" : ""), sub: Ui.t("player.dvd.deintSub") }]
                                    .concat(mv.st.plcount > 1 && (mv.st.plpos || 0) < mv.st.plcount - 1
                                            ? [{ id: "next", label: Ui.t("player.dvd.next"), sub: Ui.t("player.dvd.title", { n: mv.playlist[(mv.st.plpos || 0) + 1].ix }) }] : [])
                                  : []
        onExtraChosen: function (id) {
            if (id === "deint") { mv.deint = !mv.deint; mv.player.setProp("deinterlace", mv.deint ? "yes" : "no"); app.toast(Ui.t(mv.deint ? "player.dvd.deintOn" : "player.dvd.deintOff")) }
            if (id === "next") mv.dvdStep(1)
        }
        onHomeChosen: mv.goHome()
        onCoverRefresh: mv.refreshCover()
    }
}
