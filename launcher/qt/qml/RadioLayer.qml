// SPDX-License-Identifier: GPL-3.0-or-later
// Radio: Favoriten, Vorschlaege, Sendersuche (radio-browser.info), laeuft im Hintergrund weiter
import QtQuick
import VS

Layer {
    id: r
    scope: "radio"
    title: Ui.t("radio.title")
    track: trk
    property var results: null
    property string lastQuery: ""
    readonly property var station: app.radioState.station
    readonly property bool isFav: !!station && favIndex(station.url) >= 0
    readonly property var fit: Ui.fitRows(stage.height - 18 * Ui.f * 1.36 - 14 * Ui.f - 4, Ui.u * 0.8, Ui.gap, 3)
    readonly property real cell: Ui.u * 0.8 * fit.k

    function favIndex(url) { for (var i = 0; i < app.favs.length; i++) if (app.favs[i].url === url) return i; return -1 }
    onOpened: app.refreshVolume()
    function firstFocus() {
        var it = Nav.collect(trk)
        for (var i = 0; i < it.length; i++) if (it[i].st && station && it[i].st.url === station.url) return it[i]
        return it.length ? it[0] : null
    }
    function handleBack() {
        if (!results) return false
        results = null
        search.value = ""
        trk.reset()
        Qt.callLater(function () { var f = firstFocus(); if (f) app.setFocus(f, true) })
        return true
    }
    function secondary() { if (Nav.current && Nav.current.st) toggleFav(Nav.current.st) }
    function doSearch(q) {
        q = String(q || "").trim()
        if (!q) return
        lastQuery = q
        app.toast(Ui.t("radio.searching", { q: q }))
        Api.get("/api/radio/search?q=" + encodeURIComponent(q), function (j) {
            toastBoxHide()
            results = j || []
            trk.reset()
            Qt.callLater(function () { var it = Nav.collect(trk); app.setFocus(it.length ? it[0] : search, true) })
        }, function () { app.toast(Ui.t("radio.dirUnreachable"), true) })
    }
    function toastBoxHide() { if (typeof toastBox !== "undefined") toastBox.hide() }
    function play(st) {
        Api.post("/api/radio/play", st, function (s) { app.setRadio(s); app.toast(Ui.t("radio.playing", { name: st.name })) },
                 function () { app.toast(Ui.t("radio.cantPlay"), true) })
    }
    function stop() { Api.post("/api/radio/stop", null, function (s) { app.setRadio(s) }) }
    function toggleFav(st) {
        st = st || station
        if (!st) return app.toast(Ui.t("radio.pickFirst"))
        var was = favIndex(st.url) >= 0
        Api.post(was ? "/api/radio/unfav" : "/api/radio/fav", st, function (j) {
            app.favs = j || []
            app.toast(was ? Ui.t("common.favRemoved") : Ui.t("common.favAdded"))
        }, function () { app.toast(Ui.t("common.saveFailed"), true) })
    }

    headRight: NowLine {
        main: r.station ? r.station.name : Ui.t("radio.none")
        sub: r.station ? (app.radioState.title || Ui.t("common.live")) : Ui.t("radio.noneHint")
    }
    bar: [
        Pill { iconName: "stop"; text: Ui.t("common.stop"); enabled: !!r.station; onTriggered: r.stop() },
        Pill { iconName: "star"; text: r.isFav ? Ui.t("radio.favRemove") : Ui.t("radio.fav"); onTriggered: r.toggleFav() },
        Field { id: search; placeholder: Ui.t("common.searchStations"); onSubmitted: function (t) { r.doSearch(t) } },
        VolBar {}
    ]

    Track {
        id: trk
        anchors.fill: parent
        Group {
            visible: !!r.results
            title: Ui.t("radio.results", { q: r.lastQuery })
            Loader {
                active: !!r.results
                sourceComponent: (r.results && r.results.length) ? resultGrid : nothing
            }
        }
        Group {
            visible: !r.results && app.favs.length > 0
            title: Ui.t("common.favorites")
            TileGrid {
                items: r.results ? [] : app.favs
                rows: r.fit.n
                cellW: r.cell; cellH: r.cell
                delegate: stationDelegate
            }
        }
        Group {
            visible: !r.results
            title: app.favs.length ? Ui.t("radio.search") : Ui.t("radio.suggestions")
            Column {
                spacing: 14 * Ui.f
                Txt {
                    visible: app.favs.length === 0
                    width: Math.min(implicitWidth, Ui.screenW * 0.34)
                    text: Ui.t("radio.noFavs")
                    color: Ui.c.textFaint
                    wrapMode: Text.Wrap
                    elide: Text.ElideNone
                    lineHeight: 1.5
                }
                Flow {
                    width: Ui.screenW * 0.44
                    spacing: Ui.gap
                    Repeater {
                        model: app.cfg ? (app.cfg.radio_suggestions || []) : []
                        Pill { text: modelData; onTriggered: { search.value = modelData; r.doSearch(modelData) } }
                    }
                }
            }
        }
    }
    Component { id: nothing; Txt { text: Ui.t("radio.nothing"); color: Ui.c.textFaint } }
    Component {
        id: resultGrid
        TileGrid { items: r.results; rows: r.fit.n; cellW: r.cell; cellH: r.cell; delegate: stationDelegate }
    }
    Component {
        id: stationDelegate
        StationTile {
            property var st: modelData
            enterDelay: index * 30
            logo: modelData.favicon || ""
            name: modelData.name || ""
            fav: { app.favs; return r.favIndex(modelData.url) >= 0 }
            playing: !!r.station && r.station.url === modelData.url
            onTriggered: r.play(modelData)
        }
    }
}
