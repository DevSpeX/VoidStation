// SPDX-License-Identifier: GPL-3.0-or-later
// Fernsehen (iptv-org): Filter nach Land und Thema, Favoriten, Suche; oben rechts laeuft gerade + Programm (EPG)
import QtQuick
import VS

Layer {
    id: tvl
    scope: "tv"
    title: Ui.t("tv.title")
    track: trk
    property string query: ""
    property string country: "DE"
    property string cat: ""
    property bool more: false
    property var favs: []
    property var results: []
    property var status: null
    property var epg: null
    property string msg: ""
    readonly property var now: app.tvNow
    readonly property var cats: ["", "news", "general", "entertainment", "movies", "series", "documentary", "kids", "music", "sports", "culture"]
    readonly property var fit: Ui.fitRows(stage.height - 18 * Ui.f * 1.36 - 14 * Ui.f - 4, Ui.u * 0.8, Ui.gap, 3)
    readonly property real cell: Ui.u * 0.8 * fit.k

    function isFav(key) { for (var i = 0; i < favs.length; i++) if (favs[i].key === key) return true; return false }
    function where() { return country === "*" ? Ui.t("tv.allCountriesLower") : Ui.regionName(country) }
    function countries() {
        var top = ["DE", "AT", "CH"], out = top.slice()
        if (more && status && status.countries) {
            var rest = status.countries.map(function (c) { return c.code }).filter(function (c) { return top.indexOf(c) < 0 }).slice(0, 16)
            out = out.concat(rest)
        }
        return out
    }
    onOpened: { app.refreshVolume(); load() }
    function firstFocus() { var it = Nav.collect(favGroup).concat(Nav.collect(chanGroup)); return it.length ? it[0] : null }
    function load() {
        Api.get("/api/tv/status", function (s) {
            status = s
            Api.get("/api/tv/favs", function (f) { favs = f || [] })
            app.setTvNow(s.now)
            if (s.state === "loading" || s.state === "idle") { msg = Ui.t("tv.loading"); results = []; waitReady.start() }
            else if (s.state === "error") msg = Ui.t("tv.unreachable", { err: s.error || "" })
            else { msg = ""; search() }
        }, function () { status = { state: "error" }; msg = Ui.t("tv.unreachable", { err: "" }) })
    }
    Timer {
        id: waitReady; interval: 1500; repeat: true
        onTriggered: {
            if (!tvl.open) return stop()
            Api.get("/api/tv/status", function (s) {
                tvl.status = s
                if (s.state === "ready") { waitReady.stop(); tvl.msg = ""; tvl.search() }
                if (s.state === "error") { waitReady.stop(); tvl.msg = Ui.t("tv.unreachable", { err: s.error || "" }) }
            })
        }
    }
    function search(keepFocus) {
        var c = country === "*" ? "" : country
        Api.get("/api/tv/search?q=" + encodeURIComponent(query) + "&country=" + encodeURIComponent(c) + "&cat=" + encodeURIComponent(cat), function (j) {
            results = j || []
            if (!keepFocus && tvl.open) Qt.callLater(function () { var it = Nav.collect(favGroup).concat(Nav.collect(chanGroup)); app.setFocus(it.length ? it[0] : searchField, true) })
        }, function () { results = [] })
    }
    function setFilter(fn, key) {
        fn()
        search(true)
        Qt.callLater(function () {
            var it = Nav.collect(filterGroup)
            for (var i = 0; i < it.length; i++) if (it[i].fk === key) return app.setFocus(it[i], true)
        })
    }
    function handleBack() {
        if (!query) return false
        query = ""
        searchField.value = ""
        search()
        return true
    }
    function secondary() { if (Nav.current && Nav.current.ch) fav(Nav.current.ch) }
    function play(ch) {
        app.toast(Ui.t("tv.switching", { name: ch.name }))
        Api.post("/api/tv/play", { key: ch.key }, function (s) { app.setTvNow(s.now) }, function () { app.toast(Ui.t("tv.cantStart"), true) })
    }
    function stopTv() { Api.post("/api/tv/stop", null, function () { app.setTvNow(null) }) }
    function fav(ch) {
        var was = isFav(ch.key)
        Api.post(was ? "/api/tv/unfav" : "/api/tv/fav", { key: ch.key }, function (j) {
            favs = j || []
            app.toast(was ? Ui.t("common.favRemoved") : Ui.t("common.favAdded"))
        }, function () { app.toast(Ui.t("common.saveFailed"), true) })
    }
    // Programm (EPG) des laufenden Senders, alle 30 s
    function tvSwitched() { refreshEpg() }
    function refreshEpg() {
        if (!now) { epg = null; return }
        Api.get("/api/tv/epg?id=" + encodeURIComponent(now.cid || now.key || "") + "&name=" + encodeURIComponent(now.name || ""),
                function (j) { epg = j }, function () { epg = null })
    }
    Timer { interval: 30000; repeat: true; running: !!tvl.now; onTriggered: tvl.refreshEpg() }

    headRight: NowLine {
        main: tvl.now ? tvl.now.name : (tvl.status && tvl.status.count ? Ui.t("tv.count", { n: Ui.num(tvl.status.count, 0) }) : Ui.t("tv.title"))
        sub: tvl.now ? Ui.t("tv.running") : Ui.t("tv.free")
        extra: tvl.now && tvl.epg && tvl.epg.current ? epgView : null
    }
    Component {
        id: epgView
        Column {
            spacing: 3 * Ui.f
            property var cur: tvl.epg.current
            Row {
                anchors.right: parent.right
                spacing: 10 * Ui.f
                Txt { text: parent.parent.cur.title || ""; font.pixelSize: 14 * Ui.f; font.weight: Font.Medium; width: Math.min(implicitWidth, Ui.screenW * 0.25); anchors.verticalCenter: parent.verticalCenter }
                Rectangle {
                    visible: !!parent.parent.cur.progress
                    width: 80 * Ui.f; height: 4 * Ui.f; radius: 2; color: Ui.c.divider; anchors.verticalCenter: parent.verticalCenter
                    Rectangle { height: parent.height; radius: 2; color: Ui.c.statusOkText; width: parent.width * Math.min(100, Math.max(0, parent.parent.parent.cur.progress || 0)) / 100 }
                }
                Txt { text: (parent.parent.cur.start || "") + (parent.parent.cur.stop ? "–" + parent.parent.cur.stop : ""); color: Ui.c.textFaint; font.pixelSize: 12 * Ui.f; anchors.verticalCenter: parent.verticalCenter }
            }
            Txt {
                anchors.right: parent.right
                visible: !!tvl.epg.next
                text: tvl.epg.next ? Ui.t("tv.epgNext", { title: tvl.epg.next.title }) : ""
                color: Ui.c.textDim; font.pixelSize: 12.5 * Ui.f
            }
        }
    }
    bar: [
        Field { id: searchField; placeholder: Ui.t("tv.search"); onSubmitted: function (t) { tvl.query = String(t).trim(); tvl.search() } },
        Pill { iconName: "stop"; text: Ui.t("common.stop"); enabled: !!tvl.now; onTriggered: tvl.stopTv() },
        VolBar {}
    ]

    Track {
        id: trk
        anchors.fill: parent
        Group {
            id: filterGroup
            title: Ui.t("tv.filter")
            Column {
                spacing: 10 * Ui.f
                width: Ui.screenW * 0.42
                Flow {
                    width: parent.width
                    spacing: 8 * Ui.f
                    Repeater {
                        model: tvl.countries()
                        Pill { property string fk: "c" + modelData; text: Ui.regionName(modelData); on: tvl.country === modelData
                               onTriggered: tvl.setFilter(function () { tvl.country = modelData }, fk) }
                    }
                    Pill { property string fk: "c*"; text: Ui.t("tv.allCountries"); on: tvl.country === "*"
                           onTriggered: tvl.setFilter(function () { tvl.country = "*" }, fk) }
                    Pill { property string fk: "more"; text: tvl.more ? Ui.t("tv.less") : Ui.t("tv.more")
                           onTriggered: { tvl.more = !tvl.more; Qt.callLater(function () { var it = Nav.collect(filterGroup); for (var i = 0; i < it.length; i++) if (it[i].fk === "more") app.setFocus(it[i], true) }) } }
                }
                Flow {
                    width: parent.width
                    spacing: 8 * Ui.f
                    Repeater {
                        model: tvl.cats
                        Pill { property string fk: "t" + modelData; text: Ui.t("tv.cat." + (modelData || "all")); on: tvl.cat === modelData
                               onTriggered: tvl.setFilter(function () { tvl.cat = modelData }, fk) }
                    }
                }
            }
        }
        Group {
            id: favGroup
            visible: tvl.favs.length > 0 && !tvl.query
            title: Ui.t("common.favorites")
            TileGrid { items: tvl.favs; rows: tvl.fit.n; cellW: tvl.cell; cellH: tvl.cell; delegate: chanDelegate }
        }
        Group {
            id: chanGroup
            title: tvl.msg ? Ui.t("tv.channels") : tvl.query ? Ui.t("tv.query", { q: tvl.query, where: tvl.where() }) : Ui.t("tv.list", { where: tvl.where() })
            Txt {
                visible: tvl.msg !== "" || tvl.results.length === 0
                text: tvl.msg || Ui.t("tv.none")
                width: Math.min(implicitWidth, Ui.screenW * 0.34)
                wrapMode: Text.Wrap; elide: Text.ElideNone
                color: Ui.c.textFaint
                lineHeight: 1.5
            }
            TileGrid { visible: !tvl.msg; items: tvl.msg ? [] : tvl.results; rows: tvl.fit.n; cellW: tvl.cell; cellH: tvl.cell; delegate: chanDelegate }
        }
    }
    Component {
        id: chanDelegate
        StationTile {
            property var ch: modelData
            enterDelay: Math.min(index * 20, 600)
            logo: modelData.logo || ""
            name: modelData.name || ""
            fallbackIcon: "tv"
            quality: modelData.quality || ""
            accent: Ui.c.accentTv
            fav: tvl.isFav(modelData.key)
            playing: !!tvl.now && tvl.now.key === modelData.key
            onTriggered: tvl.play(modelData)
        }
    }
}
