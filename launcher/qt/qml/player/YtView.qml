// SPDX-License-Identifier: GPL-3.0-or-later
// YouTube Light: YouTube ohne Browser und ohne Google-Konto. Startseite mit Weiterschauen, neuen Videos aus den Abos,
// "Spaeter ansehen" und den eigenen Kanaelen; Suche (Videos, Kanaele, Playlists), Kanal- und Playlist-Seiten, Verlauf.
// Alles kommt vom Launcher (/api/yt/…, yt-dlp + RSS-Feeds); abgespielt wird mit mpv wie bei Videos & Musik.
// Tasten Liste: A oeffnen/abspielen, Y Spaeter ansehen bzw. abonnieren, X Kanal des Videos, Start Suche, B zurueck.
// Tasten Video: A Pause, ◀▶ 10 s, LB/RB voriges/naechstes Kapitel (ohne Kapitel 1 min), ▲▼ Lautstaerke,
// X naechstes Video (Playlist), Y Spaeter ansehen, Start Menue (Qualitaet, Ton, Untertitel, Kapitel), Select Technik,
// B Stopp. Guide: Startseite (Video haelt an).
import QtQuick
import VS

Item {
    id: yv
    readonly property Item navRoot: intro.open ? intro : dlg.open ? dlg : browser
    readonly property bool wantVideo: phase === "video"
    readonly property var track: phase === "browse" ? trk : null
    readonly property var player: app.player
    readonly property var st: app.st || {}

    property string phase: "browse"               // browse | loading | video
    property var ystate: null                     // /api/yt/state
    readonly property bool searchAllowed: !(ystate && ystate.allow_search === false)
    property string page: "home"                  // home | feed | search | channel | playlist | later | history | subs
    property var args: ({})                       // Angaben der Seite (Kanal-ID, Suchbegriff …)
    property var stack: []                        // vorige Seiten fuer B
    property var groups: []                       // [{title, items}]
    property var cur: ({})                        // Antwort der Seite (Kanal, Playlist …)
    property string msg: ""
    property bool busy: false
    property bool refreshing: false
    property string selectAfter: ""               // nach dem Laden diesen Eintrag fokussieren ("video:ID")
    property int pageSeq: 0
    // Wiedergabe
    property var playing: null                    // Eintrag aus der Liste
    property var info: null                       // /api/yt/resolve
    property var queue: []                        // Playlist / Spaeter: Videos zum Weiterspielen
    property int qpos: -1
    property string quality: "auto"
    property bool osdOn: false
    property int loadSeq: 0
    property bool subsAdded: false
    // Kapitel [{t, title}] aus /api/yt/resolve (yt-dlp), leer ohne Kapitel und bei Livestreams
    readonly property var chaps: info && info.chapters && !info.live ? info.chapters : []
    readonly property int chapIdx: chapterAt(st.position || 0)
    readonly property var chapMarks: st.duration > 0 ? chaps.map(function (c) { return c.t / st.duration }) : []
    readonly property var fit: Ui.fitRows(browser.stage.height - 18 * Ui.f * 1.36 - 14 * Ui.f - 4, Ui.u * 0.86, Ui.gap, 3)
    readonly property real cell: Ui.u * 0.86 * fit.k

    // ------------------------------------------------------------ Start, Seiten
    function start(arg) {
        loadState(function () {
            if (!ystate.accepted) return intro.show(true)
            go("home", {}, false)
            if (arg) playArg(arg)
        })
    }
    function loadState(cb) {
        Api.get("/api/yt/state", function (s) {
            ystate = s
            quality = s.quality || "auto"
            if (cb) cb()
        }, function () { app.toast(Ui.t("player.media.unreachable"), true); if (cb) Qt.callLater(app.leave) })
    }
    function remote(m) {
        if (m.cmd === "open" && m.path) return playArg(m.path)
        if (m.cmd === "pause" && phase === "video") return player.setPause(true)
        if (m.cmd === "background" && phase === "video" && !st.paused) { player.setPause(true); osdOn = true }
    }
    function playArg(a) {
        var m = String(a).match(/(?:v=|youtu\.be\/|^)([A-Za-z0-9_-]{11})(?:[&?#]|$)/)
        if (m) playVideo({ kind: "video", id: m[1], title: "" }, -1, [])
    }
    function itemKey(it) { return it ? (it.kind || "") + ":" + (it.id || it.act || "") : "" }

    // Seite wechseln; push = die jetzige auf den Stapel legen (B kommt zurueck)
    function go(p, a, push) {
        if (push !== false && phase === "browse") {
            var s = stack.slice()
            s.push({ page: page, args: args, focus: Nav.current && Nav.current.it ? itemKey(Nav.current.it) : "" })
            stack = s
        }
        page = p
        args = a || {}
        groups = []
        cur = ({})
        msg = ""
        trk.reset()
        if (phase === "browse") browser.show()
        load(true)
    }
    function back() {
        if (!stack.length) return app.leave()
        vs.playSound("back")
        var s = stack.slice(), last = s.pop()
        stack = s
        page = last.page
        args = last.args
        selectAfter = last.focus
        groups = []
        trk.reset()
        load(true)
    }
    function load(showBusy) {
        var seq = ++pageSeq
        busy = !!showBusy
        var done = function (g, c) {
            if (seq !== pageSeq) return
            busy = false
            groups = g
            if (c) cur = c
            msg = g.some(function (x) { return x.items && x.items.length }) ? "" : Ui.t(page === "search" && !args.q ? "yt.search.hint" : "yt.empty")
            focusLater()
        }
        var fail = function (e) {
            if (seq !== pageSeq) return
            busy = false
            msg = Ui.t("yt.err." + e, null, Ui.t("yt.err.failed"))
            if (e === "outdated" || e === "bot") offerUpdate(e)
            focusLater()
        }
        if (page === "home") {
            Api.get("/api/yt/home", function (r) {
                refreshing = !!r.refreshing
                var g = []
                if (r.resume.length) g.push({ title: Ui.t("yt.resume"), items: r.resume })
                if (r.subs.length) {
                    var feed = r.feed.slice()
                    if (feed.length >= 60) feed.push(action("feed", "list", Ui.t("yt.more"), Ui.t("yt.feed.all")))
                    g.push({ title: Ui.t("yt.feed"), items: feed.length ? feed : [action("feed", "update", Ui.t("yt.feed.loading"), "")] })
                } else {
                    var startItems = yv.searchAllowed ? [action("search", "search", Ui.t("yt.search"), Ui.t("yt.search.sub"), "#6e2b2b")] : []
                    startItems.push(action("import", "download", Ui.t("yt.import"), Ui.t("yt.import.sub")))
                    g.push({ title: Ui.t("yt.start"), items: startItems })
                }
                if (r.laterCount) {
                    var later = r.later.slice()
                    if (r.laterCount > later.length) later.push(action("later", "clock", Ui.t("yt.more"), Ui.t("yt.n", { n: r.laterCount })))
                    g.push({ title: Ui.t("yt.later"), items: later })
                }
                if (r.subs.length) g.push({ title: Ui.t("yt.channels"), items: r.subs.concat([action("import", "download", Ui.t("yt.import"), Ui.t("yt.import.sub"))]) })
                g.push({ title: Ui.t("yt.more.group"), items: (r.subs.length && yv.searchAllowed ? [action("search", "search", Ui.t("yt.search"), Ui.t("yt.search.sub"), "#6e2b2b")] : []).concat([
                    action("history", "restart", Ui.t("yt.history"), r.historyCount ? Ui.t("yt.n", { n: r.historyCount }) : ""),
                    action("later", "clock", Ui.t("yt.later"), r.laterCount ? Ui.t("yt.n", { n: r.laterCount }) : ""),
                    action("settings", "gear", Ui.t("yt.settings"), "")]) })
                done(g, r)
                if (refreshing) homePoll.restart()
            }, fail)
        } else if (page === "feed") {
            Api.get("/api/yt/feed", function (r) { refreshing = !!r.refreshing; done([{ title: Ui.t("yt.feed"), items: r.items }], r); if (refreshing) homePoll.restart() }, fail)
        } else if (page === "search") {
            if (!args.q) return done([], {})
            Api.get("/api/yt/search?q=" + encodeURIComponent(args.q) + "&kind=" + (args.kind || "video"),
                    function (r) { done([{ title: Ui.t("yt.kind." + (args.kind || "video")), items: r.items }], r) }, fail)
        } else if (page === "channel") {
            Api.get("/api/yt/channel?id=" + encodeURIComponent(args.id) + "&tab=" + (args.tab || "videos"),
                    function (r) { done([{ title: Ui.t("yt.tab." + (args.tab || "videos")), items: r.items }], r) }, fail)
        } else if (page === "playlist") {
            Api.get("/api/yt/playlist?id=" + encodeURIComponent(args.id), function (r) {
                done([{ title: r.channel || Ui.t("yt.playlist"), items: (r.items.length > 1 ? [action("playall", "playfill", Ui.t("yt.playAll"), Ui.t("yt.videos", { n: r.items.length }), "#6e2b2b")] : []).concat(r.items) }], r)
            }, fail)
        } else if (page === "later" || page === "history") {
            Api.get("/api/yt/" + page, function (r) {
                var it = r.items
                if (page === "later" && it.length > 1) it = [action("playall", "playfill", Ui.t("yt.playAll"), Ui.t("yt.videos", { n: it.length }), "#6e2b2b")].concat(it)
                done([{ title: Ui.t("yt." + page), items: it }], r)
            }, fail)
        } else if (page === "subs") {
            Api.get("/api/yt/subs", function (r) { done([{ title: Ui.t("yt.channels"), items: r.items }], r) }, fail)
        }
    }
    // Feed laedt im Hintergrund: so lange nachfragen und die Kacheln austauschen (Fokus bleibt)
    Timer {
        id: homePoll
        interval: 3000
        onTriggered: {
            if (yv.phase !== "browse" || (yv.page !== "home" && yv.page !== "feed")) return
            if (Nav.current && Nav.current.it) yv.selectAfter = yv.itemKey(Nav.current.it)
            yv.load(false)
        }
    }
    function action(act, icon, title, sub, color) { return { kind: "action", act: act, icon: icon, title: title, sub: sub || "", color: color || "", size: "medium" } }
    function decorate(items) {
        return (items || []).map(function (it) {
            var o = {}
            for (var k in it) o[k] = it[k]
            if (!o.size) o.size = it.kind === "video" || it.kind === "playlist" ? "wide" : "medium"
            return o
        })
    }
    function focusLater() {
        Qt.callLater(function () {
            if (dlg.open || intro.open || phase !== "browse") return     // Dialog hat den Fokus
            var all = Nav.collect(browser), pick = null, i
            for (i = 0; i < all.length && selectAfter; i++) if (all[i].it && itemKey(all[i].it) === selectAfter) pick = all[i]
            if (!pick && page === "search" && !args.q) pick = field
            if (!pick) {                                  // nichts Gemerktes: erste Kachel, Buehne an den Anfang
                for (i = 0; i < all.length; i++) if (all[i].it) { pick = all[i]; break }
                trk.reset()
            }
            selectAfter = ""
            if (pick) app.setFocus(pick, true)
        })
    }
    function search(q) {
        q = String(q || "").trim()
        if (!q) return
        if (page === "search") { args = { q: q, kind: args.kind || "video" }; groups = []; trk.reset(); load(true) }
        else go("search", { q: q, kind: "video" })
    }
    function setKind(k) {
        if (page !== "search" || args.kind === k) return
        args = { q: args.q, kind: k }
        groups = []
        trk.reset()
        load(true)
    }
    function setTab(t) {
        if (page !== "channel" || args.tab === t) return
        args = { id: args.id, title: args.title, tab: t }
        groups = []
        trk.reset()
        load(true)
    }
    function openSearch() {
        if (!searchAllowed) {
            app.toast(Ui.t("parental.reason.yt_search_blocked"), true)
            return
        }
        if (page !== "search") go("search", { q: "", kind: "video" })
        Qt.callLater(function () { app.setFocus(field, true); field.activate() })
    }

    // ------------------------------------------------------------ Aktionen in der Liste
    function activate(it) {
        if (!it) return
        if (it.kind === "video") return playVideo(it, -1, queueFrom(it))
        if (it.kind === "channel") return go("channel", { id: it.id, title: it.title, tab: "videos" })
        if (it.kind === "playlist") return go("playlist", { id: it.id, title: it.title })
        if (it.kind !== "action") return
        if (it.act === "search") return openSearch()
        if (it.act === "import") return doImport()
        if (it.act === "settings") return intro.show(false)
        if (it.act === "playall") { var q = videosOfPage(); if (q.length) playVideo(q[0], 0, q.slice(1)); return }
        if (["feed", "later", "history", "subs"].indexOf(it.act) >= 0) return go(it.act, {})
    }
    function videosOfPage() {
        var out = []
        for (var g = 0; g < groups.length; g++) for (var i = 0; i < groups[g].items.length; i++) if (groups[g].items[i].kind === "video") out.push(groups[g].items[i])
        return out
    }
    // Playlist und "Spaeter ansehen": nach dem Video geht es mit dem naechsten weiter
    function queueFrom(it) {
        if (page !== "playlist" && page !== "later") return []
        var v = videosOfPage()
        for (var i = 0; i < v.length; i++) if (v[i].id === it.id) return v.slice(i + 1)
        return []
    }
    function toggleLater(it) {
        if (!it || it.kind !== "video") return
        var on = !it.later
        Api.post("/api/yt/later", { item: it, on: on }, function () {
            app.toast(Ui.t(on ? "yt.later.added" : "yt.later.removed"))
            markItem(it, "later", on)
            if (playing && playing.id === it.id) playing = withProp(playing, "later", on)
        })
    }
    function toggleSub(it) {
        if (!it) return
        var ch = it.kind === "channel" ? it : { id: it.channel_id, title: it.channel }
        if (!ch.id) return
        var on = it.kind === "channel" ? !it.sub : !(cur && cur.sub)
        Api.post("/api/yt/sub", { item: ch, on: on }, function () {
            app.toast(Ui.t(on ? "yt.sub.added" : "yt.sub.removed", { name: ch.title || "" }))
            if (it.kind === "channel") markItem(it, "sub", on)
            if (page === "channel" && cur.id === ch.id) cur = withProp(cur, "sub", on)
        })
    }
    function withProp(o, k, v) { var n = {}; for (var x in o) n[x] = o[x]; n[k] = v; return n }
    function markItem(it, k, v) {
        var g = groups.map(function (gr) {
            return { title: gr.title, items: gr.items.map(function (x) { return x.kind === it.kind && x.id === it.id ? withProp(x, k, v) : x }) }
        })
        selectAfter = itemKey(it)
        groups = g
        focusLater()
    }
    function openChannelOf(it) {
        if (it && it.channel_id) go("channel", { id: it.channel_id, title: it.channel, tab: "videos" })
    }
    function removeHistory(it) {
        if (!it || page !== "history" || it.kind !== "video") return
        Api.post("/api/yt/history/remove", { id: it.id }, function () { load(false) })
    }
    function doImport() {
        app.toast(Ui.t("yt.import.searching"))
        Api.post("/api/yt/import", {}, function (r) {
            if (!r.found) return dlg.ask(Ui.t("yt.import"), Ui.t("yt.import.howto"), [{ label: Ui.t("common.ok"), act: function () {} }])
            app.toast(Ui.t("yt.import.done", { n: r.added, total: r.total }))
            if (Nav.current && Nav.current.it) selectAfter = itemKey(Nav.current.it)
            load(false)
        }, function () { app.toast(Ui.t("yt.err.failed"), true) })
    }
    function offerUpdate(reason) {
        if (ystate && ystate.update && ystate.update.state === "running") return
        dlg.ask(Ui.t("yt.err." + reason, null, Ui.t("yt.err.failed")), Ui.t("yt.update.ask"),
                [{ label: Ui.t("yt.update"), act: function () { updateYtdlp() } }, { label: Ui.t("common.cancel"), act: function () {} }])
    }
    function updateYtdlp() {
        Api.post("/api/yt/update", {}, function () { app.toast(Ui.t("yt.update.running")); updPoll.restart() })
    }
    Timer {
        id: updPoll
        interval: 2000; repeat: true
        onTriggered: Api.get("/api/yt/state", function (s) {
            yv.ystate = s
            if (s.update.state === "running") return
            updPoll.stop()
            if (s.update.state === "done") app.toast(Ui.t("yt.update.done", { v: s.update.msg }))
            else app.toast(Ui.t("yt.update.failed", { msg: s.update.msg }), true)
        })
    }

    // ------------------------------------------------------------ Wiedergabe
    // from: -1 = fragen, ob weitergeschaut wird; sonst Startposition in Sekunden
    function playVideo(it, from, q) {
        if (from < 0 && !it.live && it.dur > 0 && it.pos > 30 && it.pos < it.dur * 0.95) {
            return dlg.ask(it.title, Ui.t("player.media.resumeAsk", { time: vs.fmtTime(it.pos, "") }), [
                { label: Ui.t("player.media.resumeYes"), act: function () { playVideo(it, Math.max(0, it.pos - 3), q) } },
                { label: Ui.t("player.media.fromStart"), act: function () { playVideo(it, 0, q) } }])
        }
        if (phase === "browse" && Nav.current && Nav.current.it) selectAfter = itemKey(Nav.current.it)
        playing = it
        queue = q || []
        info = null
        subsAdded = false
        phase = "loading"
        var seq = ++loadSeq
        Api.post("/api/radio/stop", null)
        Api.post("/api/yt/resolve", { id: it.id, quality: quality, lang: Ui.lang }, function (r) {
            if (seq !== loadSeq) return
            info = r
            if (!playing.title) playing = withProp(withProp(withProp(playing, "title", r.title), "channel", r.channel), "channel_id", r.channel_id)
            var o = { "force-media-title": r.title || "YouTube", "sid": "no" }
            if (r.audio) o["audio-files-append"] = r.audio
            if (r.ua) o["user-agent"] = r.ua
            if (r.referer) o.referrer = r.referer
            if (from > 0 && !r.live) o.start = String(Math.floor(from))
            phase = "video"
            if (app.embedded) browser.hide()
            player.setProp("loop-file", "no")
            player.play(r.url, o)
            vs.setTitle(r.title || "YouTube Light")
            showOsd()
        }, function (e) {
            if (seq !== loadSeq) return
            phase = "browse"
            browser.show()
            if (e === "outdated" || e === "bot" || e === "noytdlp") return offerUpdate(e)
            app.toast(Ui.t("yt.err." + e, null, Ui.t("yt.err.failed")), true)
            focusLater()
        })
    }
    function cancelLoad() { loadSeq++; phase = "browse"; browser.show(); focusLater() }
    Connections {
        target: yv.player
        enabled: vsMode === "yt"
        function onStarted() {
            if (yv.phase !== "video" || !yv.info || yv.subsAdded) return
            yv.subsAdded = true
            var s = yv.info.subs || []
            for (var i = 0; i < s.length; i++) yv.player.command(["sub-add", s[i].url, "auto", s[i].name, s[i].lang])
        }
        function onEnded(reason, cause) {
            if (yv.phase !== "video") return
            if (reason === "error") { app.toast(Ui.t("yt.err.play"), true); return yv.backToBrowser() }
            if (reason === "quit") return yv.backToBrowser()
            if (reason === "eof") {
                yv.saveProgress(true)
                if (yv.queue.length) return yv.nextVideo()
                return yv.backToBrowser()
            }
        }
    }
    function nextVideo() {
        if (!queue.length) return
        saveProgress(false)
        var n = queue[0]
        playVideo(n, 0, queue.slice(1))
        app.toast(Ui.t("yt.next", { title: n.title }))
    }
    function saveProgress(finished) {
        if (phase !== "video" || !playing || !info) return
        var dur = st.duration || info.duration || 0, pos = finished ? dur : (st.position || 0)
        if (!info.live && pos < 5 && !finished) return
        Api.post("/api/yt/progress", { id: playing.id, pos: pos, dur: dur, title: info.title || playing.title, channel: info.channel || playing.channel,
                                      channel_id: info.channel_id || playing.channel_id, duration: info.duration, live: !!info.live })
    }
    Timer { interval: 15000; repeat: true; running: yv.phase === "video" && !yv.st.paused; onTriggered: yv.saveProgress(false) }
    function stopPlayback() {
        saveProgress(false)
        player.stop()
        backToBrowser()
    }
    function backToBrowser() {
        phase = "browse"
        osdOn = false
        menu.hide()
        chapMenu.hide()
        tech.open = false
        playing = null
        info = null
        queue = []
        vs.setTitle("YouTube Light")
        browser.show()
        load(false)                                     // Fortschritt neu laden
    }
    function goHome() {
        menu.hide()
        if (phase === "video" && !st.paused) player.setPause(true)
        Api.post("/api/home", null)
    }
    function changeQuality(v) {
        quality = v
        Api.post("/api/yt/settings", { quality: v })
        if (phase === "video" && playing) playVideo(playing, info && info.live ? 0 : (st.position || 0), queue)
    }
    function qualityList() {
        var hs = info && info.heights ? info.heights : [], out = [], max = ystate && ystate.weak ? 720 : 1080
        var autoH = ystate && ystate.weak ? 480 : 1080
        out.push({ v: "auto", label: Ui.t("yt.quality.auto"), sub: Ui.t("yt.quality.autoSub", { h: autoH }) })
        var steps = [1080, 720, 480, 360]
        for (var i = 0; i < steps.length; i++) if (steps[i] <= max && (!hs.length || hs.some(function (h) { return h >= steps[i] * 0.9 })))
            out.push({ v: String(steps[i]), label: steps[i] + "p", sub: steps[i] >= 1080 ? Ui.t("yt.quality.hd") : "" })
        return out
    }
    function showOsd() { osdOn = true; osdT.restart() }
    Timer { id: osdT; interval: 3500; onTriggered: if (!yv.st.paused) yv.osdOn = false }
    function seek(d) {
        if (info && info.live) return
        player.seek(d)
        showOsd()
        player.osdText((d > 0 ? "+" : "−") + vs.fmtTime(Math.abs(d), ""), "1200")
    }

    // ------------------------------------------------------------ Kapitel
    function chapterAt(pos) {
        var i = -1
        for (var n = 0; n < chaps.length; n++) { if (chaps[n].t <= pos + 0.5) i = n; else break }
        return i
    }
    function chapterName(i) { return chaps[i] && chaps[i].title ? chaps[i].title : Ui.t("yt.chapter.n", { n: i + 1 }) }
    function gotoChapter(i) {
        if (i < 0 || i >= chaps.length) return
        player.seekTo(chaps[i].t)
        showOsd()
        player.osdText(chapterName(i), "1500")
    }
    function jumpChapter(d) {
        var pos = st.position || 0, i = chapterAt(pos)
        if (d < 0) return gotoChapter(i > 0 && pos - chaps[i].t < 3 ? i - 1 : Math.max(0, i))   // erst an den Anfang des Kapitels
        if (i + 1 < chaps.length) return gotoChapter(i + 1)
        showOsd()                                       // schon im letzten Kapitel
    }
    function chapterRows() {
        var out = []
        for (var i = 0; i < chaps.length; i++)
            out.push({ label: chapterName(i), sub: vs.fmtTime(chaps[i].t, ""), on: i === chapIdx, act: { kind: "extra", id: String(i) } })
        return out
    }

    // ------------------------------------------------------------ Tasten
    function key(k) {
        if (intro.open) return intro.key(k)
        if (dlg.open) return dlg.key(k)
        if (chapMenu.open) return chapMenu.key(k)
        if (menu.open) return menu.key(k)
        if (phase === "loading") { if (k === "b" || k === "stop") cancelLoad(); return }
        if (phase === "browse") {
            var it = Nav.current && Nav.current.it ? Nav.current.it : null
            if (k === "b") return back()
            if (k === "a" || k === "play") { app.activate(); return }
            if (k === "up" || k === "down" || k === "left" || k === "right") return app.move(k)
            if (k === "y") { if (it && it.kind === "video") return toggleLater(it); if (it && it.kind === "channel") return toggleSub(it); return }
            if (k === "x") { if (it && it.kind === "video" && page === "history") return removeHistory(it); if (it && it.kind === "video") return openChannelOf(it); return }
            if (k === "start") return openSearch()
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
        if (k === "left") return seek(-10)
        if (k === "right") return seek(10)
        if (k === "lb" || k === "chdown") return chaps.length ? jumpChapter(-1) : seek(-60)
        if (k === "rb" || k === "chup") return chaps.length ? jumpChapter(1) : seek(60)
        if (k === "x" || k === "next") { if (queue.length) return nextVideo(); return showOsd() }
        if (k === "y") return toggleLater(playing)
    }

    // ------------------------------------------------------------ Listen
    Layer {
        id: browser
        scope: "yt"
        title: yv.page === "home" ? "YouTube Light" : yv.page === "channel" ? (yv.cur.title || yv.args.title || "")
             : yv.page === "playlist" ? (yv.cur.title || yv.args.title || Ui.t("yt.playlist"))
             : yv.page === "search" ? (yv.args.q ? "„" + yv.args.q + "“" : Ui.t("yt.search")) : Ui.t("yt." + yv.page)
        track: trk
        anchors.fill: parent
        headRight: NowLine {
            main: yv.busy ? Ui.t("yt.loading") : yv.page === "channel" && yv.cur.followers ? Ui.t("yt.followers", { n: Ui.num(yv.cur.followers, 0) })
                : yv.page === "playlist" && yv.cur.count ? Ui.t("yt.videos", { n: yv.cur.count }) : ""
            sub: yv.refreshing ? Ui.t("yt.feed.refreshing") : yv.page === "home" && yv.cur.errors ? Ui.t("yt.feed.errors", { n: yv.cur.errors })
               : yv.page === "channel" && yv.cur.sub ? Ui.t("yt.subscribed") : ""
        }
        bar: [
            Field { id: field; visible: yv.searchAllowed && (yv.page === "home" || yv.page === "search"); placeholder: Ui.t("yt.search.placeholder")
                    implicitWidth: Math.min(420 * Ui.f, Ui.screenW * 0.4); onSubmitted: function (t) { yv.search(t) } },
            Pill { visible: yv.page === "search"; text: Ui.t("yt.kind.video"); on: yv.args.kind === "video"; onTriggered: yv.setKind("video") },
            Pill { visible: yv.page === "search"; text: Ui.t("yt.kind.channel"); on: yv.args.kind === "channel"; onTriggered: yv.setKind("channel") },
            Pill { visible: yv.page === "search"; text: Ui.t("yt.kind.playlist"); on: yv.args.kind === "playlist"; onTriggered: yv.setKind("playlist") },
            Pill { visible: yv.page === "channel"; iconName: yv.cur.sub ? "" : "plus"; text: Ui.t(yv.cur.sub ? "yt.subscribed" : "yt.subscribe"); on: !!yv.cur.sub
                   onTriggered: yv.toggleSub({ kind: "x", channel_id: yv.args.id, channel: yv.cur.title || yv.args.title }) },
            Pill { visible: yv.page === "channel"; text: Ui.t("yt.tab.videos"); on: yv.args.tab === "videos"; onTriggered: yv.setTab("videos") },
            Pill { visible: yv.page === "channel"; text: Ui.t("yt.tab.streams"); on: yv.args.tab === "streams"; onTriggered: yv.setTab("streams") },
            Pill { visible: yv.page === "channel"; text: Ui.t("yt.tab.playlists"); on: yv.args.tab === "playlists"; onTriggered: yv.setTab("playlists") },
            Pill { visible: yv.page === "home" || yv.page === "feed"; iconName: "update"; text: Ui.t("yt.feed.refresh"); enabled: !yv.refreshing
                   onTriggered: Api.get("/api/yt/feed?force=1", function () { yv.refreshing = true; homePoll.restart() }) },
            Pill { visible: yv.page === "history"; iconName: "close"; text: Ui.t("yt.history.clear")
                   onTriggered: dlg.ask(Ui.t("yt.history.clear"), Ui.t("yt.history.clearAsk"), [
                       { label: Ui.t("yt.history.clear"), act: function () { Api.post("/api/yt/history/clear", {}, function () { yv.load(false) }) } },
                       { label: Ui.t("common.cancel"), act: function () {} }]) },
            Pill { visible: yv.page === "home"; iconName: "gear"; text: Ui.t("yt.settings"); onTriggered: intro.show(false) }
        ]
        Track {
            id: trk
            anchors.fill: parent
            Repeater {
                model: yv.groups
                Group {
                    title: modelData.title
                    visible: modelData.items.length > 0
                    TileGrid { items: yv.decorate(modelData.items); rows: yv.fit.n; cellW: yv.cell; cellH: yv.cell; delegate: tileDelegate }
                }
            }
        }
        Column {
            x: Ui.padX
            y: parent.height * 0.12
            width: Math.min(parent.width - 2 * Ui.padX, 820 * Ui.f)
            spacing: 18 * Ui.f
            visible: yv.busy || yv.msg !== ""
            Spinner { visible: yv.busy; size: 54 * Ui.f; line: 4 * Ui.f }
            Txt { visible: !yv.busy; width: parent.width; text: yv.msg; wrapMode: Text.Wrap; elide: Text.ElideNone; color: Ui.c.textFaint; lineHeight: 1.4 }
        }
    }
    Component {
        id: tileDelegate
        YtTile { it: modelData; onTriggered: yv.activate(modelData) }
    }
    Hints {
        visible: yv.phase === "browse" && !intro.open
        x: Ui.padX
        width: parent.width - 2 * Ui.padX
        anchors.bottom: parent.bottom; anchors.bottomMargin: 14 * Ui.f
        z: 31
        readonly property var it: Nav.current && Nav.current.it ? Nav.current.it : null
        list: [Ui.t(it && it.kind === "video" ? "yt.hint.play" : "hint.open")]
              .concat(it && it.kind === "video" ? [Ui.t(it.later ? "yt.hint.unlater" : "yt.hint.later"), Ui.t(yv.page === "history" ? "yt.hint.forget" : "yt.hint.channel")] : [])
              .concat(it && it.kind === "channel" ? [Ui.t(it.sub ? "yt.hint.unsub" : "yt.hint.sub")] : [])
              .concat([Ui.t("yt.hint.search"), Ui.t("hint.back")])
    }

    // ------------------------------------------------------------ Laden und Video
    Rectangle {
        anchors.fill: parent
        visible: yv.phase === "loading"
        color: Ui.c.bgMain
        z: 20
        Image {
            anchors.fill: parent
            source: yv.playing ? Ui.url("/api/yt/img?v=" + yv.playing.id) : ""
            fillMode: Image.PreserveAspectCrop
            opacity: 0.25
            asynchronous: true
        }
        Column {
            anchors.centerIn: parent
            width: Math.min(parent.width * 0.7, 900 * Ui.f)
            spacing: 18 * Ui.f
            Spinner { anchors.horizontalCenter: parent.horizontalCenter; size: 60 * Ui.f; line: 4 * Ui.f }
            Txt { width: parent.width; horizontalAlignment: Text.AlignHCenter; text: yv.playing ? (yv.playing.title || "") : ""
                  font.pixelSize: 28 * Ui.f; font.weight: Font.Light; wrapMode: Text.WordWrap; maximumLineCount: 2 }
            Txt { width: parent.width; horizontalAlignment: Text.AlignHCenter; text: Ui.t(yv.ystate && yv.ystate.weak ? "yt.resolving.slow" : "yt.resolving")
                  color: Ui.c.textDim }
        }
        Hints { x: Ui.padX; anchors.bottom: parent.bottom; anchors.bottomMargin: 14 * Ui.f; list: [Ui.t("yt.hint.cancel")] }
    }
    MouseArea {
        anchors.fill: parent
        visible: yv.phase === "video"
        hoverEnabled: true
        acceptedButtons: Qt.LeftButton | Qt.RightButton
        onPositionChanged: { yv.showOsd(); mouseBar.poke() }
        onClicked: function (m) { if (m.button === Qt.RightButton) yv.key("b"); else yv.key("a") }
        onWheel: function (w) { app.volume(w.angleDelta.y > 0 ? "up" : "down") }
    }
    Rectangle {                                    // Stufe 2: Bild im eigenen Fenster
        anchors.fill: parent
        visible: yv.phase === "video" && !app.embedded
        color: Ui.c.bgMain
        Txt { anchors.centerIn: parent; text: Ui.t("player.ownWindow"); color: Ui.c.textDim }
    }
    Column {
        anchors.centerIn: parent
        visible: app.embedded && yv.phase === "video" && (!!yv.st.buffering || (!yv.st.duration && !yv.st.position && yv.st.active))
        Spinner { size: 54 * Ui.f; line: 4 * Ui.f }
    }
    Rectangle {
        anchors.centerIn: parent
        visible: yv.phase === "video" && !!yv.st.paused
        width: 110 * Ui.f; height: width; radius: width / 2
        color: Ui.alpha(Ui.c.surfaceDialog, 0.75)
        Glyph { anchors.centerIn: parent; name: "pause"; width: parent.width * 0.42; height: width }
    }
    Item {
        anchors.left: parent.left; anchors.right: parent.right; anchors.bottom: parent.bottom
        height: vbox.height + 70 * Ui.f
        opacity: yv.phase === "video" && (yv.osdOn || !!yv.st.paused) ? 1 : 0
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
            spacing: 10 * Ui.f
            Txt { width: parent.width; text: yv.info ? yv.info.title : ""; font.pixelSize: 26 * Ui.f; font.weight: Font.Light }
            Txt {
                width: parent.width
                color: Ui.c.textSecondary; font.pixelSize: 16 * Ui.f
                text: yv.info ? [yv.info.channel, yv.info.height ? yv.info.height + "p" : "", yv.queue.length ? Ui.t("yt.queue", { n: yv.queue.length }) : ""]
                                .filter(function (x) { return x }).join(" · ") : ""
            }
            Txt {                                       // aktuelles Kapitel
                width: parent.width
                visible: yv.chaps.length > 0 && yv.chapIdx >= 0
                font.pixelSize: 18 * Ui.f
                text: visible ? Ui.t("yt.chapter.pos", { i: yv.chapIdx + 1, n: yv.chaps.length })
                                + (yv.chaps[yv.chapIdx].title ? " · " + yv.chaps[yv.chapIdx].title : "") : ""
            }
            Row {
                width: parent.width
                spacing: 18 * Ui.f
                visible: !(yv.info && yv.info.live)
                Txt { id: tPos; text: vs.fmtTime(yv.st.position || 0, ""); font.pixelSize: 16 * Ui.f; anchors.verticalCenter: parent.verticalCenter }
                Bar {
                    width: parent.width - tPos.width - tDur.width - 36 * Ui.f
                    anchors.verticalCenter: parent.verticalCenter
                    value: yv.st.duration > 0 ? (yv.st.position || 0) / yv.st.duration : 0
                    buffered: yv.st.duration > 0 ? ((yv.st.position || 0) + (yv.st.cache || 0)) / yv.st.duration : 0
                    seekable: true
                    marks: yv.chapMarks
                    fill: "#e53935"
                    onSeek: function (f) { yv.player.seekTo(f * yv.st.duration); yv.showOsd() }
                }
                Txt { id: tDur; text: yv.st.duration > 0 ? vs.fmtTime(yv.st.duration, "") : "–"; color: Ui.c.textDim; font.pixelSize: 16 * Ui.f; anchors.verticalCenter: parent.verticalCenter }
            }
            Hints {
                width: parent.width
                list: [Ui.t("player.hint.pause")].concat(yv.info && yv.info.live ? []
                          : [Ui.t("player.hint.seek"), Ui.t(yv.chaps.length ? "yt.hint.chapters" : "player.hint.seekBig")])
                      .concat(yv.queue.length ? [Ui.t("yt.hint.next")] : []).concat([Ui.t("player.hint.volumeUD"), Ui.t("player.hint.menu"), Ui.t("hint.homeShort"), Ui.t("player.hint.stop")])
            }
        }
    }
    MouseBar {
        id: mouseBar
        visible: yv.phase === "video" && !menu.open && !chapMenu.open && !dlg.open && opacity > 0
        buttons: [
            { icon: "pause", tip: Ui.t("player.paused"), act: function () { yv.player.togglePause(); yv.showOsd() } },
            { icon: "subs", tip: Ui.t("player.menu.title"), act: function () { menu.show() } }
        ].concat(yv.chaps.length ? [{ icon: "list", tip: Ui.t("yt.chapters"), act: function () { chapMenu.show() } }] : []).concat([
            { icon: "next", tip: Ui.t("yt.nextVideo"), act: function () { yv.nextVideo() } },
            { icon: "home", tip: Ui.t("player.menu.home"), act: function () { yv.goHome() } },
            { icon: "minus", tip: Ui.t("player.volume"), act: function () { app.volume("down") } },
            { icon: "plus", tip: Ui.t("player.volume"), act: function () { app.volume("up") } },
            { icon: "stop", tip: Ui.t("player.btn.stop"), act: function () { yv.stopPlayback() } }
        ])
    }
    TechInfo { id: tech }
    TrackMenu {
        id: menu
        withQuality: true
        quality: yv.quality
        qualityList: yv.qualityList()
        homeSub: Ui.t("player.menu.homeVideo")
        // Kapitel ganz oben: Start, A oeffnet die Liste (unter "Weiteres" laege sie hinter Ton, Untertiteln, Bild, Qualitaet)
        leadRows: yv.playing && yv.chaps.length && yv.chapIdx >= 0
                  ? [{ head: Ui.t("yt.chapters") }, { id: "chapters", label: yv.chapterName(yv.chapIdx),
                       sub: Ui.t("yt.chapter.pos", { i: yv.chapIdx + 1, n: yv.chaps.length }) }] : []
        extraRows: yv.playing ? [{ id: "later", label: Ui.t(yv.playing.later ? "yt.later.remove" : "yt.later.add") }]
                   .concat(yv.queue.length ? [{ id: "next", label: Ui.t("yt.nextVideo"), sub: yv.queue[0].title }] : [])
                   .concat(yv.info && yv.info.channel_id ? [{ id: "channel", label: Ui.t("yt.openChannel"), sub: yv.info.channel }] : []) : []
        onQualityChosen: function (v) { yv.changeQuality(v) }
        onHomeChosen: yv.goHome()
        onExtraChosen: function (id) {
            if (id === "chapters") return chapMenu.show()
            if (id === "later") return yv.toggleLater(yv.playing)
            if (id === "next") return yv.nextVideo()
            if (id === "channel") { var it = { channel_id: yv.info.channel_id, channel: yv.info.channel }; yv.stopPlayback(); yv.openChannelOf(it) }
        }
    }

    TrackMenu {                                    // Kapitelliste (Start → Kapitel, Maus: Listen-Knopf)
        id: chapMenu
        title: Ui.t("yt.chapters")
        customRows: yv.chapterRows()
        startSel: yv.chapIdx
        onExtraChosen: function (id) { yv.gotoChapter(parseInt(id)) }
    }

    // ------------------------------------------------------------ Hinweis beim ersten Start / Einstellungen
    Rectangle {
        id: intro
        property bool open: false
        property bool first: false
        readonly property bool navBarrier: true
        anchors.fill: parent
        visible: open
        z: 46
        color: Ui.c.bgMain
        Background { anchors.fill: parent }
        MouseArea { anchors.fill: parent; acceptedButtons: Qt.AllButtons; onClicked: function (m) { if (m.button === Qt.RightButton) intro.key("b") } }
        function show(first) {
            intro.first = first
            open = true
            Qt.callLater(function () { var it = Nav.collect(intro); if (it.length) app.setFocus(it[0], true) })
        }
        function hide() {
            open = false
            if (first) return
            Qt.callLater(yv.focusLater)
        }
        function key(k) {
            if (k === "b") { if (first) return app.leave(); return hide() }
            if (k === "a" || k === "play") { if (Nav.current) Nav.current.activate(); return }
            if (["up", "down", "left", "right"].indexOf(k) >= 0) return app.move(k)
        }
        function accept() {
            Api.post("/api/yt/settings", { accepted: true }, function (s) {
                yv.ystate = s
                intro.first = false
                intro.open = false
                yv.go("home", {}, false)
                if (vsArg) yv.playArg(vsArg)
            }, function () { app.toast(Ui.t("common.saveFailed"), true) })
        }
        Flickable {
            anchors.fill: parent
            anchors.topMargin: 60 * Ui.f
            anchors.bottomMargin: 60 * Ui.f                   // Platz fuer die Hinweiszeile
            contentHeight: icol.height + 40 * Ui.f
            clip: true
            interactive: contentHeight > height
            function ensureVisible(item) {
                var p = item.mapToItem(icol, 0, 0)
                if (p.y < contentY) contentY = Math.max(0, p.y - 10 * Ui.f)
                else if (p.y + item.height > contentY + height) contentY = Math.min(contentHeight - height, p.y + item.height - height + 10 * Ui.f)
            }
            Column {
                id: icol
                x: Ui.padX
                width: Math.min(parent.width - 2 * Ui.padX, 980 * Ui.f)
                spacing: 18 * Ui.f
                Row {
                    spacing: 18 * Ui.f
                    Rectangle { width: 54 * Ui.f; height: width; color: "#6e2b2b"
                                Glyph { anchors.centerIn: parent; name: "playfill"; width: parent.width * 0.5; height: width; color: "#ffffff" } }
                    Txt { text: intro.first ? "YouTube Light" : Ui.t("yt.settings"); font.pixelSize: 40 * Ui.f; font.weight: Font.Light
                          anchors.verticalCenter: parent.verticalCenter }
                }
                Txt { visible: intro.first; width: parent.width; text: Ui.t("yt.intro"); wrapMode: Text.Wrap; elide: Text.ElideNone; color: Ui.c.textSecondary; lineHeight: 1.35; font.pixelSize: 17 * Ui.f }
                Txt { width: parent.width; text: Ui.t("yt.intro.warn"); wrapMode: Text.Wrap; elide: Text.ElideNone; color: Ui.c.statusWarnText; lineHeight: 1.3; font.pixelSize: 15 * Ui.f }
                Txt {
                    width: parent.width
                    color: yv.ystate && yv.ystate.tools.ytdlp ? Ui.c.textFaint : Ui.c.statusDangerText
                    font.pixelSize: 14 * Ui.f
                    text: !yv.ystate ? "" : yv.ystate.tools.ytdlp
                          ? "yt-dlp " + yv.ystate.tools.ytdlp + (yv.ystate.tools.local ? " · " + Ui.t("yt.ytdlp.local") : "") + (yv.ystate.tools.node ? " · Node.js" : " · " + Ui.t("yt.ytdlp.noNode"))
                          : Ui.t("yt.ytdlp.missing")
                }
                Row {
                    visible: intro.first
                    spacing: 12 * Ui.f
                    Btn { text: Ui.t("yt.intro.accept"); onTriggered: intro.accept() }
                    Btn { text: Ui.t("common.cancel"); onTriggered: app.leave() }
                }
                Column {
                    visible: !intro.first
                    spacing: 14 * Ui.f
                    width: parent.width
                    Txt { text: Ui.t("yt.quality.default"); color: Ui.c.textDim; font.pixelSize: 15 * Ui.f }
                    Flow {
                        width: parent.width
                        spacing: 10 * Ui.f
                        Repeater {
                            model: ["auto", "1080", "720", "480", "360"]
                            Pill { text: modelData === "auto" ? Ui.t("yt.quality.auto") : modelData + "p"; on: yv.quality === modelData
                                   onTriggered: { yv.quality = modelData; Api.post("/api/yt/settings", { quality: modelData }) } }
                        }
                    }
                    Txt { text: "yt-dlp"; color: Ui.c.textDim; font.pixelSize: 15 * Ui.f }
                    Txt { width: parent.width; text: Ui.t("yt.update.sub"); wrapMode: Text.Wrap; elide: Text.ElideNone; color: Ui.c.textFaint; font.pixelSize: 14 * Ui.f }
                    Flow {
                        width: parent.width
                        spacing: 10 * Ui.f
                        Pill { iconName: "update"; text: yv.ystate && yv.ystate.update.state === "running" ? Ui.t("yt.update.running") : Ui.t("yt.update")
                               enabled: !(yv.ystate && yv.ystate.update.state === "running"); onTriggered: yv.updateYtdlp() }
                        Pill { iconName: "download"; text: Ui.t("yt.import"); onTriggered: { intro.hide(); yv.doImport() } }
                        Pill { iconName: "clock"; text: Ui.t("yt.history.clear")
                               onTriggered: Api.post("/api/yt/history/clear", {}, function () { app.toast(Ui.t("yt.history.cleared")) }) }
                    }
                    Btn { text: Ui.t("common.close"); onTriggered: intro.hide() }
                }
            }
        }
        Hints { x: Ui.padX; anchors.bottom: parent.bottom; anchors.bottomMargin: 14 * Ui.f; list: [Ui.t("hint.open"), Ui.t("hint.back")] }
    }

    // ------------------------------------------------------------ Rueckfrage (Weiterschauen, Import, Fehler)
    Rectangle {
        id: dlg
        property bool open: false
        property string head: ""
        property string text: ""
        property var buttons: []
        readonly property bool navBarrier: true
        anchors.fill: parent
        visible: open
        z: 48
        color: Ui.c.surfaceOverlay
        MouseArea { anchors.fill: parent; acceptedButtons: Qt.AllButtons; onClicked: function (m) { if (m.button === Qt.RightButton) dlg.close() } }
        function ask(head, text, buttons) {
            dlg.head = head || ""
            dlg.text = text || ""
            dlg.buttons = buttons || []
            open = true
            Qt.callLater(function () { var it = Nav.collect(dlg); if (it.length) app.setFocus(it[0], true) })
        }
        function close() {
            open = false
            if (yv.phase === "browse") Qt.callLater(yv.focusLater)
        }
        function key(k) {
            if (k === "b") return close()
            if (k === "a" || k === "play") { if (Nav.current) Nav.current.activate(); return }
            if (k === "left" || k === "right" || k === "up" || k === "down") return app.move(k)
        }
        Rectangle {
            anchors.centerIn: parent
            width: Math.min(Math.max(dcol.implicitWidth, 460 * Ui.f) + 64 * Ui.f, parent.width * 0.8)
            height: dcol.implicitHeight + 56 * Ui.f
            color: Ui.c.surfaceDialog
            border.width: 1
            border.color: Ui.c.borderSubtle
            Column {
                id: dcol
                anchors.centerIn: parent
                width: parent.width - 64 * Ui.f
                spacing: 16 * Ui.f
                Txt { width: parent.width; text: dlg.head; font.pixelSize: 24 * Ui.f; font.weight: Font.Light; wrapMode: Text.WordWrap; maximumLineCount: 2 }
                Txt { width: parent.width; visible: text !== ""; text: dlg.text; color: Ui.c.textDim; wrapMode: Text.Wrap; elide: Text.ElideNone; lineHeight: 1.3 }
                Row {
                    spacing: 12 * Ui.f
                    Repeater {
                        model: dlg.buttons
                        Btn { text: modelData.label; onTriggered: { var a = modelData.act; dlg.close(); if (a) a() } }
                    }
                }
            }
        }
    }
}
