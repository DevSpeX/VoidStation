// SPDX-License-Identifier: GPL-3.0-or-later
// Fernsehen (iptv-org): Filter nach Land und Thema, Favoriten, A–Z-Leiste, Suche; oben rechts laeuft gerade + Programm (EPG)
// Die Senderliste kommt seitenweise (/api/tv/list, 200 je Seite) – am Ende geht es mit „Weiter“ bzw. dem naechsten Buchstaben weiter
import QtQuick
import VS

Layer {
    id: tvl
    scope: "tv"
    title: Ui.t("tv.title")
    track: trk
    property string query: ""
    property string country: ""               // "" bis der Launcher das Land meldet (status.region), "*" = alle
    property bool countryPicked: false         // selbst gewaehlt: bleibt, solange die Startseite laeuft
    property string cat: ""
    property bool more: false
    property var favs: []
    property var results: []
    property bool listed: false                // Antwort da: erst dann heisst eine leere Liste „keine Sender“
    property string letter: ""                 // "" = alle, sonst "#" oder "A"–"Z"
    property var letters: []                   // [{l, n}] fuer Land + Thema
    property int offset: 0
    property int total: 0
    property int pageLimit: 200
    readonly property bool morePages: offset + results.length < total
    readonly property string nextLetter: {
        if (!letter || query) return ""
        var i = 0
        while (i < letters.length && letters[i].l !== letter) i++
        for (i++; i < letters.length; i++) if (letters[i].n > 0) return letters[i].l
        return ""
    }
    property var status: null
    property var epg: null
    property string msg: ""
    readonly property var now: app.tvNow
    readonly property var cats: ["", "news", "general", "entertainment", "movies", "series", "documentary", "kids", "music", "sports", "culture"]
    readonly property var fit: Ui.fitRows(stage.height - 18 * Ui.f * 1.36 - 14 * Ui.f - 4, Ui.u * 0.8, Ui.gap, 3)
    readonly property real cell: Ui.u * 0.8 * fit.k
    // A–Z-Leiste: so viele Zeilen, wie unter der Ueberschrift Platz haben (mind. 3), Spalten nach Bedarf;
    // bei sehr wenig Hoehe (hohe Skalierung auf kleinem Bildschirm) werden die Tasten kleiner
    readonly property real azH: stage.height - 18 * Ui.f * 1.36 - 14 * Ui.f - 4
    readonly property real keyGap: 8 * Ui.f
    readonly property real keyH: Math.max(16, Math.min(40 * Ui.f, (azH - 3 * keyGap) / 4))
    readonly property int keyRows: Math.max(3, Math.floor((azH - keyH) / (keyH + keyGap)))
    readonly property int keyCols: Math.ceil(27 / keyRows)

    function isFav(key) { for (var i = 0; i < favs.length; i++) if (favs[i].key === key) return true; return false }
    function where() { return country === "*" ? Ui.t("tv.allCountriesLower") : Ui.regionName(country) }
    function countries() {
        // Schnellwahl: Land der Sprache, in der VoidStation installiert ist, und Nachbarn (status.quick vom Launcher)
        var top = (status && status.quick && status.quick.length) ? status.quick.slice() : ["DE", "AT", "CH"]
        if (country && country !== "*" && top.indexOf(country) < 0) top.push(country)
        var out = top.slice()
        if (more && status && status.countries) {
            var rest = status.countries.map(function (c) { return c.code }).filter(function (c) { return top.indexOf(c) < 0 }).slice(0, 16)
            out = out.concat(rest)
        }
        return out
    }
    onOpened: { app.refreshVolume(); load() }
    // Bis zu 200 Kacheln samt Logos kosten rund 60 MB: beim Schliessen abbauen, beim Oeffnen kommt die Liste ohnehin neu
    onClosed: { results = []; total = 0; listed = false }
    function firstFocus() { var it = Nav.collect(favGroup).concat(Nav.collect(chanGroup)); return it.length ? it[0] : null }
    function load() {
        Api.get("/api/tv/status", function (s) {
            status = s
            if (!countryPicked) country = s.region || "DE"
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
    // keepFocus: Fokus bleibt (Filter, Buchstabe); toList: Fokus auf den ersten Sender der Liste (Blaettern)
    function search(keepFocus, toList) {
        var c = country === "*" ? "" : country
        Api.get("/api/tv/list?q=" + encodeURIComponent(query) + "&country=" + encodeURIComponent(c) + "&cat=" + encodeURIComponent(cat)
                + "&letter=" + encodeURIComponent(query ? "" : letter) + "&offset=" + offset + "&limit=" + pageLimit, function (j) {
            j = j || {}
            if (letter && !query && !j.total) { letter = ""; offset = 0; return search(keepFocus, toList) }   // Buchstabe gibt es hier nicht
            results = j.items || []
            listed = true
            total = j.total || 0
            offset = j.offset || 0
            letters = j.letters || []
            if (!tvl.open) return
            if (toList) Qt.callLater(function () { var it = Nav.collect(chanTiles); app.setFocus(it.length ? it[0] : searchField, true) })
            else if (!keepFocus) Qt.callLater(function () { var it = Nav.collect(favGroup).concat(Nav.collect(chanGroup)); app.setFocus(it.length ? it[0] : searchField, true) })
        }, function () { results = []; total = 0 })
    }
    function setFilter(fn, key) {
        fn()
        offset = 0
        search(true)
        Qt.callLater(function () {
            var it = Nav.collect(filterGroup).concat(Nav.collect(azGroup))
            for (var i = 0; i < it.length; i++) if (it[i].fk === key) return app.setFocus(it[i], true)
        })
    }
    function countOf(l) { for (var i = 0; i < letters.length; i++) if (letters[i].l === l) return letters[i].n; return 0 }
    function page(dir) { offset = Math.max(0, offset + dir * pageLimit); search(false, true) }
    function goLetter(l) { letter = l; offset = 0; search(false, true) }
    function range() { return Ui.t("tv.range", { from: Ui.num(offset + 1, 0), to: Ui.num(offset + results.length, 0), n: Ui.num(total, 0) }) }
    function handleBack() {
        if (!query) return false
        query = ""
        offset = 0
        searchField.value = ""
        search()
        return true
    }
    function secondary() { if (Nav.current && Nav.current.ch) fav(Nav.current.ch) }
    // fromFavs: aus den Favoriten gestartet -> im Player schalten ▲▼ durch die Favoriten, sonst durch diese Liste
    function play(ch, fromFavs) {
        app.toast(Ui.t("tv.switching", { name: ch.name }))
        var ctx = fromFavs ? { favs: true } : { q: query, country: country === "*" ? "" : country, cat: cat }
        Api.post("/api/tv/play", { key: ch.key, ctx: ctx }, function (s) { app.setTvNow(s.now) }, function () { app.toast(Ui.t("tv.cantStart"), true) })
    }
    function stopTv() { Api.post("/api/tv/stop", null, function () { app.setTvNow(null) }) }
    function fav(ch) {
        vs.playSound("toggle")
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
        Field { id: searchField; placeholder: Ui.t("tv.search"); onSubmitted: function (t) { tvl.query = String(t).trim(); tvl.offset = 0; tvl.search() } },
        Pill { iconName: "stop"; text: Ui.t("common.stop"); enabled: !!tvl.now; onTriggered: tvl.stopTv() },
        VolBar {}
    ]

    Track {
        id: trk
        anchors.fill: parent
        Group {
            id: filterGroup
            title: Ui.t("tv.filter")
            Col {                                    // Laender + Themen: scrollt mit dem Fokus, Leiste links
                id: filterCol
                maxW: Ui.screenW * 0.42
                maxH: trk.height - filterGroup.headH
                Flow {
                    width: parent.width
                    spacing: 8 * Ui.f
                    Repeater {
                        model: tvl.countries()
                        Pill { property string fk: "c" + modelData; text: Ui.regionName(modelData); on: tvl.country === modelData
                               onTriggered: tvl.setFilter(function () { tvl.country = modelData; tvl.countryPicked = true }, fk) }
                    }
                    Pill { property string fk: "c*"; text: Ui.t("tv.allCountries"); on: tvl.country === "*"
                           onTriggered: tvl.setFilter(function () { tvl.country = "*"; tvl.countryPicked = true }, fk) }
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
            ScrollBar { flick: filterCol; x: -width - 12 * Ui.f; height: filterCol.height }
        }
        Group {
            id: favGroup
            visible: tvl.favs.length > 0 && !tvl.query
            title: Ui.t("common.favorites")
            TileGrid { items: tvl.favs; rows: tvl.fit.n; cellW: tvl.cell; cellH: tvl.cell; delegate: chanDelegate }
        }
        Group {
            id: azGroup
            visible: !tvl.msg && !tvl.query && tvl.letters.length > 0
            title: "A–Z"
            Column {
                spacing: tvl.keyGap
                Pill { property string fk: "l"; text: Ui.t("tv.allLetters"); on: tvl.letter === ""; height: tvl.keyH
                       onTriggered: tvl.setFilter(function () { tvl.letter = "" }, fk) }
                Grid {
                    flow: Grid.TopToBottom
                    rows: tvl.keyRows
                    spacing: tvl.keyGap
                    Repeater {
                        model: tvl.letters
                        Focusable {
                            id: key
                            property string fk: "l" + modelData.l
                            enabled: modelData.n > 0
                            opacity: enabled ? 1 : 0.3
                            width: tvl.keyH * 1.1; height: tvl.keyH
                            onTriggered: tvl.setFilter(function () { tvl.letter = modelData.l }, fk)
                            Rectangle {
                                anchors.fill: parent
                                color: tvl.letter === modelData.l ? Ui.c.surfaceActive : Ui.c.surfaceCard
                                border.width: 2
                                border.color: key.focused ? Ui.c.borderFocus : "transparent"
                            }
                            Txt {
                                anchors.centerIn: parent
                                text: modelData.l
                                font.pixelSize: Math.min(16 * Ui.f, tvl.keyH * 0.45)
                                font.weight: tvl.letter === modelData.l ? Font.DemiBold : Font.Normal
                                color: tvl.letter === modelData.l ? Ui.c.pillOnText : Ui.c.textPrimary
                            }
                        }
                    }
                }
            }
        }
        Group {
            id: chanGroup
            title: {
                if (tvl.msg) return Ui.t("tv.channels")
                var t = tvl.query ? Ui.t("tv.query", { q: tvl.query, where: tvl.where() })
                      : Ui.t("tv.list", { where: tvl.where() }) + (tvl.letter ? " · " + tvl.letter : "")
                return tvl.total > tvl.results.length ? t + " · " + tvl.range() : t
            }
            Txt {
                visible: tvl.msg !== "" || (tvl.listed && tvl.results.length === 0)
                text: tvl.msg || Ui.t("tv.none")
                width: Math.min(implicitWidth, Ui.screenW * 0.34)
                wrapMode: Text.Wrap; elide: Text.ElideNone
                color: Ui.c.textFaint
                lineHeight: 1.5
            }
            Row {
                id: chanGrid
                visible: !tvl.msg && tvl.results.length > 0
                spacing: Ui.gap
                PageTile {
                    width: tvl.cell; height: tvl.cell
                    visible: tvl.offset > 0
                    icon: "chevleft"
                    label: Ui.t("common.back")
                    sub: Ui.num(Math.max(1, tvl.offset - tvl.pageLimit + 1), 0) + "–" + Ui.num(tvl.offset, 0)
                    onTriggered: tvl.page(-1)
                }
                TileGrid { id: chanTiles; items: tvl.msg ? [] : tvl.results; rows: tvl.fit.n; cellW: tvl.cell; cellH: tvl.cell; delegate: chanDelegate }
                PageTile {
                    width: tvl.cell; height: tvl.cell
                    visible: tvl.morePages || tvl.nextLetter !== ""
                    icon: "chevright"
                    label: tvl.morePages ? Ui.t("tv.pageNext") : Ui.t("tv.nextLetter", { l: tvl.nextLetter })
                    sub: tvl.morePages ? Ui.num(tvl.offset + tvl.results.length + 1, 0) + "–" + Ui.num(Math.min(tvl.total, tvl.offset + tvl.results.length + tvl.pageLimit), 0)
                                       : Ui.t("tv.count", { n: Ui.num(tvl.countOf(tvl.nextLetter), 0) })
                    onTriggered: tvl.morePages ? tvl.page(1) : tvl.goLetter(tvl.nextLetter)
                }
            }
        }
    }
    // Blaettern am Anfang/Ende der Liste: Kachel in Sendergroesse mit Pfeil (eigene Komponente: keine ids von aussen)
    component PageTile: Tile {
        id: pt
        property string icon: "chevright"
        property string label: ""
        property string sub: ""
        tileColor: Ui.c.surfaceCard
        animateIn: false
        Glyph {
            name: pt.icon
            color: Ui.c.textPrimary
            opacity: 0.8
            width: pt.width * 0.3; height: width
            x: (pt.width - width) / 2
            y: pt.height * 0.36 - height / 2
        }
        Column {
            x: pt.width * 0.07
            width: pt.width * 0.86
            anchors.bottom: parent.bottom; anchors.bottomMargin: pt.height * 0.06
            Txt { width: parent.width; text: pt.label; font.pixelSize: pt.width * 0.106; font.weight: Font.Medium; wrapMode: Text.WordWrap; maximumLineCount: 2; elide: Text.ElideRight }
            Txt { visible: pt.sub !== ""; width: parent.width; text: pt.sub; font.pixelSize: pt.width * 0.088; color: Ui.c.textDim }
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
            broken: !!modelData.broken
            onTriggered: tvl.play(modelData, tvl.favs.indexOf(modelData) >= 0)
        }
    }
}
