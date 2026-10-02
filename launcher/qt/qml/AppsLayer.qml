// SPDX-License-Identifier: GPL-3.0-or-later
// AppCenter: links die Kategorien ("Installiert" + Katalog), rechts die Apps als Kacheln, senkrecht blaetternd.
// Installieren/Entfernen laufen als Auftrag (Band unten), danach entstehen/verschwinden die Kacheln.
import QtQuick
import VS

Layer {
    id: al
    scope: "apps"
    title: Ui.t("apps.title")
    property var data_: null
    property string cat: ""
    property var last: ({})                     // zuletzt gewaehlte App je Kategorie
    property bool fresh: false
    readonly property string inst: "#installed"
    readonly property var catIcon: ({ "#installed": "check", Gaming: "gamepad", Emulatoren: "emu", Spiele: "cube", Medien: "film",
                                      Streaming: "play", Browser: "globe", Werkzeuge: "gear" })
    readonly property var cats: data_ ? [inst].concat(data_.categories.filter(function (c) {
        return data_.apps.some(function (a) { return a.cat === c }) })) : []
    readonly property string localCat: data_ && data_.local_cat ? data_.local_cat : "Auf diesem Gerät"

    function catName(c) { return c === inst ? Ui.t("apps.cat.installed") : Ui.l(c) }
    function list(c) {
        if (!data_) return []
        return c === inst ? data_.apps.filter(function (a) { return a.installed }) : data_.apps.filter(function (a) { return a.cat === c })
    }
    function sections() {                       // [{title, apps}] fuer die rechte Seite
        var l = list(cat)
        if (!l.length) return []
        if (cat !== inst) return [{ title: "", apps: l }]
        var out = [], all = data_.categories.concat([localCat])
        for (var i = 0; i < all.length; i++) {
            var part = l.filter(function (a) { return a.cat === all[i] })
            if (part.length) out.push({ title: Ui.l(all[i]), apps: part })
        }
        return out
    }
    function desc(a) { return a.type === "local" ? (a.desc || Ui.t("apps.localDesc")) : Ui.t("app." + a.id + ".desc", null, a.desc) }

    onOpened: { fresh = true; load() }
    function load() {
        Api.get("/api/apps", function (j) {
            var keepId = Nav.current && Nav.current.appInfo ? Nav.current.appInfo.id : null
            var onCat = Nav.current && Nav.current.isCat
            data_ = j
            if (cats.indexOf(cat) < 0) cat = list(inst).length || cats.length < 2 ? inst : cats[1]
            if (j.job && j.job.state === "running") app.watchJob()
            Qt.callLater(function () {
                if (!al.open) return
                if (fresh || onCat || !keepId) { fresh = false; return app.setFocus(curCatItem(), true) }
                var c = findCard(keepId)
                app.setFocus(c || firstCard() || curCatItem(), true)
            })
        }, function () { app.toast(Ui.t("apps.loadFailed"), true) })
    }
    function firstFocus() { return curCatItem() }
    function curCatItem() { var it = Nav.collect(catList); for (var i = 0; i < it.length; i++) if (it[i].catId === cat) return it[i]; return it[0] || null }
    function cards() { return Nav.collect(pane) }
    function findCard(id) { var c = cards(); for (var i = 0; i < c.length; i++) if (c[i].appInfo.id === id) return c[i]; return null }
    function firstCard() { return findCard(last[cat]) || cards()[0] || null }
    function select(c) {
        if (!data_ || c === cat) return
        cat = c
        pane.contentY = 0
    }
    function jump(dir) {                         // LT / RT, Bild auf / ab: vorige / naechste Kategorie
        if (!data_) return
        var i = cats.indexOf(cat) + dir
        if (i < 0 || i >= cats.length) return
        var inGrid = Nav.current && Nav.current.appInfo
        if (inGrid) last[cat] = Nav.current.appInfo.id
        select(cats[i])
        Qt.callLater(function () { app.setFocus((inGrid && firstCard()) || curCatItem()) })
    }
    function navMove(dir) {
        var f = Nav.current
        if (!f) return false
        if (f.isCat) {
            if (dir === "up" || dir === "down") {
                var i = cats.indexOf(f.catId) + (dir === "down" ? 1 : -1)
                if (i < 0) { app.setFocus(backButton); return true }
                if (i >= cats.length) return true
                select(cats[i])
                Qt.callLater(function () { app.setFocus(curCatItem()) })
                return true
            }
            if (dir === "right") { var c = firstCard(); if (c) app.setFocus(c) }
            return true
        }
        if (f.appInfo) {
            var best = Nav.nearest(f, cards(), dir)
            if (best) { app.setFocus(best); return true }
            if (dir === "left") { last[cat] = f.appInfo.id; app.setFocus(curCatItem()) }
            else if (dir === "up") app.setFocus(backButton)
            return true
        }
        if (dir === "down" || dir === "right") { app.setFocus(curCatItem()); return true }
        return true
    }
    function localTile(a, on) {
        Api.post("/api/apps/localtile", { id: a.id, on: on }, function (j) {
            data_ = j
            app.toast(on ? Ui.t("apps.tileAdded", { name: a.name }) : Ui.t("apps.tileRemoved", { name: a.name }))
            app.load()
        }, function (e) { app.toast(Ui.t("common.failedMsg", { msg: e }), true) })
    }
    function tileOf(id) {
        if (!app.cfg) return null
        for (var g = 0; g < app.cfg.groups.length; g++) {
            var ts = app.cfg.groups[g].tiles || []
            for (var i = 0; i < ts.length; i++) if (ts[i].id === id) return ts[i]
        }
        return null
    }
    function openApp(t) { app.closeLayer(al); Qt.callLater(function () { app.tileActivate(t) }) }
    function appDialog(a) {
        var t = tileOf(a.id)
        if (a.type === "local") {
            var b = []
            if (a.tile && t) b.push([Ui.t("apps.open"), function () { al.openApp(t) }])
            b.push(a.tile ? [Ui.t("apps.removeTile"), function () { al.localTile(a, false) }, "danger"] : [Ui.t("apps.addTile"), function () { al.localTile(a, true) }])
            b.push([Ui.t("common.cancel")])
            return app.dialog(a.name, desc(a) + "\n\n" + Ui.t("apps.localHint"), b)
        }
        if (app.jobBusy) return app.toast(Ui.t("common.busy"))
        if (a.installed) {
            var bb = []
            if (t) bb.push([Ui.t("apps.open"), function () { al.openApp(t) }])
            bb.push([Ui.t("apps.remove"), function () { app.jobStart("remove", a) }, "danger"])
            bb.push([Ui.t("common.cancel")])
            app.dialog(Ui.l(a.name), desc(a), bb)
        } else
            app.dialog(Ui.t("apps.installQ", { name: Ui.l(a.name) }), desc(a) + (a.type === "flatpak" ? Ui.t("apps.flatpakNote") : ""),
                       [[Ui.t("apps.install"), function () { app.jobStart("install", a) }], [Ui.t("common.cancel")]])
    }

    headRight: NowLine { main: Ui.t("apps.optional"); sub: Ui.t("apps.autoTiles") }

    Flickable {
        id: catList
        x: Ui.padX - 10 * Ui.f
        width: Math.min(235 * Ui.f, Ui.screenW * 0.32)
        height: parent.height
        contentHeight: catCol.height + 20 * Ui.f
        clip: true
        interactive: false
        function ensureVisible(item, instant) {
            var p = item.mapToItem(contentItem, 0, 0), m = 10 * Ui.f
            if (p.y < contentY + m) contentY = Math.max(0, p.y - m)
            else if (p.y + item.height > contentY + height - m) contentY = Math.min(contentHeight - height, p.y + item.height - height + m)
        }
        Behavior on contentY { NumberAnimation { duration: 200 } }
        WheelHandler { onWheel: function (ev) { catList.contentY = Math.max(0, Math.min(catList.contentHeight - catList.height, catList.contentY - ev.angleDelta.y)) } }
        Column {
            id: catCol
            x: 10 * Ui.f; y: 10 * Ui.f
            width: parent.width - 20 * Ui.f
            spacing: 4 * Ui.f
            Repeater {
                model: al.cats
                Focusable {
                    id: ci
                    property bool isCat: true
                    property string catId: modelData
                    readonly property bool on: al.cat === modelData
                    width: catCol.width
                    height: Math.max(44 * Ui.f, nm.implicitHeight + 12 * Ui.f) + (index === 0 ? 10 * Ui.f : 0)
                    function clickActivate() { al.select(modelData); app.setFocus(ci) }
                    onTriggered: { al.select(modelData); Qt.callLater(function () { var c = al.firstCard(); if (c) app.setFocus(c) }) }
                    Rectangle {
                        width: parent.width
                        height: parent.height - (index === 0 ? 10 * Ui.f : 0)
                        color: ci.on ? Ui.c.surfaceActive : "transparent"
                        border.width: 2
                        border.color: ci.focused ? Ui.c.borderFocus : "transparent"
                        Row {
                            x: 12 * Ui.f + 2
                            anchors.verticalCenter: parent.verticalCenter
                            width: parent.width - 24 * Ui.f - 4
                            spacing: 10 * Ui.f
                            Glyph { name: al.catIcon[modelData] || "store"; color: ci.on || ci.focused ? Ui.c.textPrimary : Ui.c.textDim
                                    width: 22 * Ui.f; height: width; anchors.verticalCenter: parent.verticalCenter }
                            Txt { id: nm; text: al.catName(modelData); font.pixelSize: 16 * Ui.f; color: ci.on || ci.focused ? Ui.c.textPrimary : Ui.c.textDim
                                  width: parent.width - 22 * Ui.f - cnt.width - 20 * Ui.f; anchors.verticalCenter: parent.verticalCenter }
                            Txt { id: cnt; text: al.list(modelData).length; font.pixelSize: 13 * Ui.f; color: ci.on ? Ui.c.textDim : Ui.c.textFaint
                                  anchors.verticalCenter: parent.verticalCenter; elide: Text.ElideNone }
                        }
                    }
                }
            }
        }
    }
    Flickable {
        id: pane
        x: catList.x + catList.width + Ui.u * 0.22
        width: parent.width - x - Math.max(0, Ui.padX - 22 * Ui.f)
        height: parent.height
        contentHeight: paneCol.height + 18 * Ui.f
        clip: true
        interactive: false
        readonly property real innerW: width - 36 * Ui.f
        readonly property int cols: Math.max(1, Math.floor((innerW + Ui.gap) / (Ui.u * 1.75 + Ui.gap)))
        readonly property real cardW: (innerW - (cols - 1) * Ui.gap) / cols
        Behavior on contentY { id: smooth; NumberAnimation { duration: 260; easing.type: Easing.OutQuad } }
        function ensureVisible(item, instant) {
            var p = item.mapToItem(contentItem, 0, 0), m = Math.max(0, Math.min(26 * Ui.f, (height - item.height) / 2))
            var top = p.y
            if (item.firstRow) top = Math.min(top, item.firstRowTop + m)
            var y = contentY
            if (top - m < y) y = top - m
            else if (p.y + item.height + m > y + height) y = p.y + item.height + m - height
            y = Math.max(0, Math.min(Math.max(0, contentHeight - height), y))
            smooth.enabled = !instant
            contentY = y
            smooth.enabled = true
        }
        WheelHandler { onWheel: function (ev) { pane.contentY = Math.max(0, Math.min(pane.contentHeight - pane.height, pane.contentY - ev.angleDelta.y)) } }
        Column {
            id: paneCol
            x: 14 * Ui.f
            y: 10 * Ui.f + Ui.u * 0.03
            width: pane.innerW
            spacing: 22 * Ui.f
            Row {
                id: head
                spacing: 14 * Ui.f
                width: parent.width
                Txt { id: ah; text: al.catName(al.cat); font.pixelSize: 26 * Ui.f; font.weight: Font.Light; elide: Text.ElideNone }
                Txt { anchors.baseline: ah.baseline; text: Ui.t("apps.catDesc." + (al.cat === al.inst ? "installed" : al.cat), null, "")
                      color: Ui.c.textFaint; width: parent.width - ah.width - 14 * Ui.f }
            }
            Txt { visible: al.data_ !== null && al.list(al.cat).length === 0; text: Ui.t("apps.noneInstalled"); color: Ui.c.textFaint }
            Repeater {
                model: al.sections()
                Column {
                    id: sec
                    property int secIndex: index
                    spacing: 10 * Ui.f
                    width: paneCol.width
                    Txt { visible: modelData.title !== ""; text: modelData.title; font.pixelSize: 16 * Ui.f; color: Ui.c.textDim; font.letterSpacing: 16 * Ui.f * 0.02 }
                    Grid {
                        id: grid
                        columns: pane.cols
                        spacing: Ui.gap
                        Repeater {
                            model: modelData.apps
                            Tile {
                                id: card
                                property var appInfo: modelData
                                readonly property bool firstRow: index < pane.cols
                                readonly property real firstRowTop: sec.mapToItem(pane.contentItem, 0, 0).y - (sec.secIndex === 0 ? head.height + 22 * Ui.f : 0)
                                width: pane.cardW
                                height: Ui.u * 0.95
                                tileColor: Ui.c.surfaceCard
                                enterUp: true
                                enterDelay: Math.min(index * 25, 400)
                                onTriggered: al.appDialog(modelData)
                                Rectangle {
                                    x: parent.width * 0.06; y: parent.height * 0.1
                                    width: Ui.u * 0.26; height: width
                                    color: modelData.color || Ui.c.tileDefaultC
                                    Glyph { anchors.centerIn: parent; width: parent.width * 0.62; height: width; name: modelData.icon || "globe"; color: "#ecebe8" }
                                }
                                Txt {
                                    x: parent.width * 0.12 + Ui.u * 0.26; y: parent.height * 0.1
                                    width: parent.width * 0.82 - Ui.u * 0.26
                                    text: Ui.l(modelData.name)
                                    font.pixelSize: Ui.u * 0.105
                                }
                                Txt {
                                    x: parent.width * 0.12 + Ui.u * 0.26; y: parent.height * 0.1 + Ui.u * 0.13
                                    text: modelData.type === "local" ? (modelData.tile ? Ui.t("apps.hasTile") : Ui.t("apps.noTile"))
                                        : modelData.installed ? Ui.t("apps.installed") : Ui.t("apps.type." + modelData.type, null, Ui.t("apps.type.xbps"))
                                    font.pixelSize: Ui.u * 0.07
                                    color: modelData.installed && modelData.type !== "local" ? Ui.c.statusOkText : Ui.c.textFaint
                                }
                                Txt {
                                    x: parent.width * 0.06; width: parent.width * 0.88
                                    anchors.bottom: parent.bottom; anchors.bottomMargin: parent.height * 0.08
                                    text: al.desc(modelData)
                                    font.pixelSize: Ui.u * 0.072
                                    color: Ui.c.textDim
                                    wrapMode: Text.WordWrap
                                    maximumLineCount: 3
                                    lineHeight: 1.15
                                }
                            }
                        }
                    }
                }
            }
        }
        Rectangle {
            anchors.left: parent.left; anchors.right: parent.right; anchors.bottom: parent.bottom
            height: 40 * Ui.f
            visible: pane.contentY + pane.height < pane.contentHeight - 2
            gradient: Gradient { GradientStop { position: 0; color: Ui.alpha(Ui.c.bgMain, 0) } GradientStop { position: 1; color: Ui.c.bgMain } }
        }
    }
}
