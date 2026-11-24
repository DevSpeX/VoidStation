// SPDX-License-Identifier: GPL-3.0-or-later
// "Musik suchen" in Videos & Musik: Quellen waehlen (beim ersten Mal zuerst), suchen, herunterladen.
// Ganze Alben aus dem Internet Archive, einzelne Titel von YouTube/SoundCloud (yt-dlp) – mit Tags und Cover
// (Launcher: /api/dl/settings, /api/dl/search, /api/dl/get, /api/dl/status). Gespeichert wird nach share/Musik.
// Tasten: A suchen/laden, X Quellen, B zurueck; ▲▼ in der Trefferliste.
import QtQuick
import VS

Item {
    id: dv
    property bool open: false
    property string page: "search"                 // settings | search
    property var sett: null                        // /api/dl/settings
    property var draft: ({})                       // Quellen auf der Einstellungsseite (noch nicht gespeichert)
    property var items: []
    property var errors: ({})
    property string query: ""
    property bool busy: false
    property var jobs: ({})                        // key -> Download-Zustand
    property bool firstRun: false
    readonly property Item navRoot: page === "settings" ? setLayer : searchLayer
    readonly property var srcNames: ["archive", "youtube", "soundcloud"]
    signal closed()
    visible: open
    anchors.fill: parent

    function show() {
        open = true
        Api.get("/api/dl/settings", function (s) {
            sett = s
            if (!s.configured) { firstRun = true; openSettings() }
            else openSearch()
        }, function () { app.toast(Ui.t("player.media.unreachable"), true); hide() })
        pollJobs()
    }
    function hide() {
        setLayer.hide(); searchLayer.hide()
        open = false
        closed()
    }
    function openSettings() {
        var d = {}
        for (var i = 0; i < srcNames.length; i++) d[srcNames[i]] = !!(sett && sett.sources[srcNames[i]])
        draft = d
        page = "settings"
        searchLayer.hide()
        setLayer.show()
        Qt.callLater(function () { var it = Nav.collect(setCol); if (it.length) app.setFocus(it[0], true) })
    }
    function toggle(name) { var d = {}; for (var k in draft) d[k] = draft[k]; d[name] = !d[name]; draft = d }
    function saveSettings() {
        var any = false
        for (var k in draft) if (draft[k]) any = true
        if (!any) return app.toast(Ui.t("dl.sources.none"))       // keine Vorauswahl: der Nutzer entscheidet selbst
        Api.post("/api/dl/settings", { sources: draft }, function (s) {
            sett = s
            firstRun = false
            openSearch()
        }, function () { app.toast(Ui.t("common.saveFailed"), true) })
    }
    function openSearch() {
        page = "search"
        setLayer.hide()
        searchLayer.show()
        Qt.callLater(function () { app.setFocus(items.length ? firstResult() : field, true) })
    }
    function firstResult() { var it = Nav.collect(list.contentItem); return it.length ? it[0] : field }
    function anySource() { if (!sett) return false; for (var k in sett.sources) if (sett.sources[k]) return true; return false }
    function search(q) {
        query = String(q || "").trim()
        if (!query) return
        if (!anySource()) { app.toast(Ui.t("dl.noSources"), true); return openSettings() }
        busy = true
        items = []
        errors = ({})
        Api.post("/api/dl/search", { q: query }, function (r) {
            busy = false
            items = (r && r.items) || []
            errors = (r && r.errors) || ({})
            for (var k in errors) app.toast(Ui.t("dl.srcError", { src: Ui.t("dl.src." + k) }), true)
            Qt.callLater(function () { app.setFocus(firstResult(), true); list.contentY = 0 })
        }, function () { busy = false; app.toast(Ui.t("dl.searchFailed"), true) })
    }
    function get(it) {
        Api.post("/api/dl/get", { key: it.key }, function (s) {
            applyJobs(s)
            app.toast(Ui.t("dl.queued", { title: it.title }))
        }, function (e) { app.toast(Ui.t("dl.failed", { msg: e }), true) })
    }
    property bool wasActive: false
    function applyJobs(s) {
        var m = {}
        var list2 = (s && s.jobs) || []
        for (var i = 0; i < list2.length; i++) {
            var j = list2[i], old = jobs[j.key]
            if (old && old.state !== "done" && j.state === "done") app.toast(Ui.t("dl.saved", { path: j.msg }))
            if (old && old.state !== "error" && j.state === "error") app.toast(Ui.t("dl.failed", { msg: j.msg }), true)
            m[j.key] = j
        }
        jobs = m
        wasActive = !!(s && s.active)
    }
    function pollJobs() { Api.get("/api/dl/status", applyJobs) }
    Timer { interval: 1000; repeat: true; running: dv.open && dv.wasActive; onTriggered: dv.pollJobs() }

    function key(k) {
        if (page === "settings") {
            if (k === "b") { vs.playSound("back"); return firstRun ? hide() : openSearch() }
            if (k === "a" || k === "play") { app.activate(); return }
            if (["up", "down", "left", "right"].indexOf(k) >= 0) return app.move(k)
            if (k === "start") return saveSettings()
            return
        }
        if (k === "b") { vs.playSound("back"); return hide() }
        if (k === "x") return openSettings()
        if (k === "a" || k === "play") { app.activate(); return }
        if (k === "y") return app.setFocus(field, true)
        if (["up", "down", "left", "right"].indexOf(k) >= 0) return app.move(k)
        if (k === "chdown" || k === "rt") { var movedD = false; for (var i = 0; i < 6; i++) if (app.move("down", true)) movedD = true; if (movedD) vs.playSound("group"); return }
        if (k === "chup" || k === "lt") { var movedU = false; for (var j = 0; j < 6; j++) if (app.move("up", true)) movedU = true; if (movedU) vs.playSound("group"); return }
    }
    function fmtDur(s) { return s > 0 ? vs.fmtTime(s, "") : "" }

    // ------------------------------------------------------------ Einstellungen: Quellen
    Layer {
        id: setLayer
        scope: "dlset"
        anchors.fill: parent
        title: Ui.t("dl.sources.title")
        Flickable {
            id: setFlick
            anchors.fill: parent
            contentHeight: setCol.height + 20 * Ui.f
            clip: true
            interactive: contentHeight > height
            function ensureVisible(item) {
                var p = item.mapToItem(setCol, 0, 0)
                if (p.y < contentY) contentY = Math.max(0, p.y - 10 * Ui.f)
                else if (p.y + item.height > contentY + height) contentY = Math.min(contentHeight - height, p.y + item.height - height + 10 * Ui.f)
            }
            Column {
                id: setCol
                x: Ui.padX
                width: parent.width - 2 * Ui.padX
                spacing: 14 * Ui.f
                Txt {
                    width: Math.min(parent.width, 900 * Ui.f)
                    text: dv.firstRun ? Ui.t("dl.sources.first") : Ui.t("dl.sources.intro")
                    wrapMode: Text.Wrap; elide: Text.ElideNone
                    color: Ui.c.textSecondary
                    lineHeight: 1.3
                }
                Repeater {
                    model: dv.srcNames
                    Focusable {
                        id: row
                        width: Math.min(setCol.width, 900 * Ui.f)
                        height: rowCol.height + 26 * Ui.f
                        readonly property bool on: !!dv.draft[modelData]
                        onTriggered: dv.toggle(modelData)
                        Rectangle {
                            anchors.fill: parent
                            color: row.focused ? Ui.c.surfaceCardHover : Ui.c.surfaceCard
                            border.width: 2
                            border.color: row.focused ? Ui.c.borderFocus : "transparent"
                        }
                        Rectangle {                         // Haekchen-Feld
                            id: box
                            x: 18 * Ui.f
                            anchors.verticalCenter: parent.verticalCenter
                            width: 26 * Ui.f; height: width
                            color: row.on ? Ui.c.statusOkBg : "transparent"
                            border.width: 2
                            border.color: row.on ? Ui.c.statusOkText : Ui.c.borderMuted
                            Txt { anchors.centerIn: parent; text: row.on ? "✓" : ""; font.pixelSize: 18 * Ui.f; font.weight: Font.Bold; elide: Text.ElideNone }
                        }
                        Column {
                            id: rowCol
                            anchors.left: box.right; anchors.leftMargin: 18 * Ui.f
                            anchors.right: parent.right; anchors.rightMargin: 18 * Ui.f
                            anchors.verticalCenter: parent.verticalCenter
                            spacing: 4 * Ui.f
                            Txt { text: Ui.t("dl.src." + modelData); font.pixelSize: 19 * Ui.f; font.weight: Font.Medium }
                            Txt { width: parent.width; text: Ui.t("dl.src." + modelData + ".desc"); wrapMode: Text.Wrap; elide: Text.ElideNone
                                  color: Ui.c.textDim; font.pixelSize: 14 * Ui.f; lineHeight: 1.2 }
                            Txt {
                                visible: modelData !== "archive"
                                width: parent.width
                                text: Ui.t("dl.src.responsibility")
                                wrapMode: Text.Wrap; elide: Text.ElideNone
                                color: Ui.c.statusWarnText; font.pixelSize: 13 * Ui.f
                            }
                            Txt {
                                visible: modelData !== "archive" && dv.sett && dv.sett.tools && !dv.sett.tools.ytdlp
                                text: Ui.t("dl.needsYtdlp")
                                color: Ui.c.statusDangerText; font.pixelSize: 13 * Ui.f
                            }
                        }
                    }
                }
                Row {
                    spacing: 12 * Ui.f
                    Btn { text: Ui.t("dl.sources.save"); onTriggered: dv.saveSettings() }
                    Btn { visible: !dv.firstRun; text: Ui.t("common.cancel"); onTriggered: dv.openSearch() }
                }
                Txt {
                    visible: !!(dv.sett && dv.sett.tools && dv.sett.tools.ytdlp)
                    text: "yt-dlp " + (dv.sett && dv.sett.tools ? dv.sett.tools.ytdlp : "") + (dv.sett && dv.sett.tools && dv.sett.tools.node ? " · Node.js" : "")
                    color: Ui.c.textFaint; font.pixelSize: 12 * Ui.f
                }
            }
        }
    }

    // ------------------------------------------------------------ Suche und Treffer
    Layer {
        id: searchLayer
        scope: "dlsearch"
        anchors.fill: parent
        title: Ui.t("dl.title")
        headRight: NowLine {
            main: dv.busy ? Ui.t("dl.searching") : dv.query ? Ui.t("dl.hits", { n: dv.items.length }) : ""
            sub: {
                var on = []
                if (dv.sett) for (var i = 0; i < dv.srcNames.length; i++) if (dv.sett.sources[dv.srcNames[i]]) on.push(Ui.t("dl.src." + dv.srcNames[i]))
                return on.join(" · ")
            }
        }
        bar: [
            Field { id: field; placeholder: Ui.t("dl.placeholder"); implicitWidth: Math.min(480 * Ui.f, Ui.screenW * 0.45)
                    onSubmitted: function (t) { dv.search(t) } },
            Pill { iconName: "gear"; text: Ui.t("dl.sources.title"); onTriggered: dv.openSettings() }
        ]
        Item {
            anchors.fill: parent
            Spinner { anchors.centerIn: parent; visible: dv.busy; size: 54 * Ui.f; line: 4 * Ui.f }
            Txt {
                visible: !dv.busy && dv.items.length === 0
                x: Ui.padX
                width: Math.min(parent.width - 2 * Ui.padX, 820 * Ui.f)
                text: dv.query ? Ui.t("dl.none") : Ui.t("dl.hint")
                wrapMode: Text.Wrap; elide: Text.ElideNone
                color: Ui.c.textFaint
                lineHeight: 1.4
            }
            Flickable {
                id: list
                visible: !dv.busy && dv.items.length > 0
                x: Ui.padX
                width: parent.width - 2 * Ui.padX
                height: parent.height
                contentHeight: resCol.height
                clip: true
                interactive: contentHeight > height
                function ensureVisible(item) {
                    var p = item.mapToItem(resCol, 0, 0)
                    if (p.y < contentY) contentY = Math.max(0, p.y - 6 * Ui.f)
                    else if (p.y + item.height > contentY + height) contentY = Math.min(contentHeight - height, p.y + item.height - height + 6 * Ui.f)
                }
                Column {
                    id: resCol
                    width: list.width
                    spacing: 6 * Ui.f
                    Repeater {
                        model: dv.items
                        Focusable {
                            id: res
                            width: resCol.width
                            height: 74 * Ui.f
                            readonly property var job: dv.jobs[modelData.key] || null
                            onTriggered: { if (!job || job.state === "error" || job.state === "done") dv.get(modelData) }
                            Rectangle {
                                anchors.fill: parent
                                color: res.focused ? Ui.c.surfaceCardHover : Ui.c.surfaceCard
                                border.width: 2
                                border.color: res.focused ? Ui.c.borderFocus : "transparent"
                            }
                            Rectangle {                      // Fortschritt unten
                                visible: !!res.job && res.job.state === "running"
                                anchors.left: parent.left; anchors.bottom: parent.bottom
                                height: 3 * Ui.f
                                width: parent.width * (res.job ? res.job.pct : 0) / 100
                                color: Ui.c.statusOkText
                            }
                            Rectangle {
                                id: th
                                x: 10 * Ui.f
                                anchors.verticalCenter: parent.verticalCenter
                                width: (modelData.kind === "album" ? 56 : 96) * Ui.f; height: 56 * Ui.f
                                color: Ui.c.surfaceRaised
                                clip: true
                                Image {
                                    id: thImg
                                    anchors.fill: parent
                                    source: modelData.thumb || ""
                                    fillMode: Image.PreserveAspectCrop
                                    asynchronous: true
                                    sourceSize: Qt.size(Math.ceil(width * 1.5), Math.ceil(height * 1.5))
                                }
                                Glyph { anchors.centerIn: parent; visible: thImg.status !== Image.Ready; name: "music"; width: 24 * Ui.f; height: width; opacity: 0.5 }
                            }
                            Column {
                                anchors.left: th.right; anchors.leftMargin: 16 * Ui.f
                                anchors.right: stateBox.left; anchors.rightMargin: 14 * Ui.f
                                anchors.verticalCenter: parent.verticalCenter
                                spacing: 3 * Ui.f
                                Txt { width: parent.width; text: modelData.title; font.pixelSize: 17 * Ui.f; font.weight: Font.Medium }
                                Txt {
                                    width: parent.width
                                    color: Ui.c.textDim; font.pixelSize: 13 * Ui.f
                                    text: [modelData.artist, modelData.kind === "album" ? Ui.t("dl.album") : dv.fmtDur(modelData.duration),
                                           modelData.year, modelData.license === "CC" ? "Creative Commons" : modelData.license === "PD" ? Ui.t("dl.publicDomain") : ""]
                                          .filter(function (x) { return x }).join(" · ")
                                }
                            }
                            Row {
                                id: stateBox
                                anchors.right: parent.right; anchors.rightMargin: 16 * Ui.f
                                anchors.verticalCenter: parent.verticalCenter
                                spacing: 10 * Ui.f
                                Txt {
                                    anchors.verticalCenter: parent.verticalCenter
                                    font.pixelSize: 13 * Ui.f
                                    color: !res.job ? Ui.c.textFaint : res.job.state === "error" ? Ui.c.statusDangerText : res.job.state === "done" ? Ui.c.statusOkText : Ui.c.textSecondary
                                    text: !res.job ? "" : res.job.state === "queued" ? Ui.t("dl.state.queued")
                                          : res.job.state === "running" ? (res.job.pct + " %" + (res.job.msg ? " · " + res.job.msg : ""))
                                          : res.job.state === "done" ? "✓ " + Ui.t("dl.state.done") : Ui.t("dl.state.error")
                                }
                                Rectangle {                  // Quelle
                                    anchors.verticalCenter: parent.verticalCenter
                                    width: srcTxt.implicitWidth + 14 * Ui.f; height: srcTxt.implicitHeight + 6 * Ui.f
                                    color: modelData.src === "youtube" ? "#6e2b2b" : modelData.src === "soundcloud" ? "#7a4318" : "#2d4a3a"
                                    Txt { id: srcTxt; anchors.centerIn: parent; text: Ui.t("dl.src." + modelData.src + ".short"); font.pixelSize: 12 * Ui.f; color: "#ffffff"; elide: Text.ElideNone }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
    Hints {
        visible: dv.open
        x: Ui.padX
        width: parent.width - 2 * Ui.padX
        anchors.bottom: parent.bottom; anchors.bottomMargin: 14 * Ui.f
        z: 31
        list: dv.page === "settings" ? [Ui.t("dl.hint.toggle"), Ui.t("dl.hint.save"), Ui.t("hint.back")]
                                     : [Ui.t("dl.hint.get"), Ui.t("dl.hint.searchField"), Ui.t("dl.hint.sources"), Ui.t("hint.back")]
    }
}
