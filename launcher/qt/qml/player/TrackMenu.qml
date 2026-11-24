// SPDX-License-Identifier: GPL-3.0-or-later
// Menue rechts (Start / M): Tonspur, Untertitel, Bildformat, beim Fernsehen auch Qualitaet.
// Bedienung: ▲▼ waehlen, A uebernehmen (Menue bleibt offen), B oder Start schliessen.
import QtQuick
import VS

Rectangle {
    id: m
    property bool open: false
    property var rows: []
    property int sel: 0
    property bool withQuality: false
    property string quality: "max"
    property string title: Ui.t("player.menu.title")
    property string repeatMode: ""               // Musik: Wiederholen-Abschnitt (leer = keiner)
    property int shuffleState: -1                // Musik: Zufall (-1 = kein Eintrag, 0 aus, 1 an)
    property string homeSub: ""
    property var qualityList: []                 // eigene Qualitaetsstufen [{v, label, sub}] statt Beste/Sparsam
    property var extraRows: []                   // weitere Eintraege unter "Weiteres" [{id, label, sub}]
    property var customRows: null                // statt Spuren usw. nur diese Zeilen [{label, sub, on, act}] (YouTube: Kapitel)
    property var leadRows: []                    // ganz oben, vor den Spuren [{head} | {id, label, sub}] (YouTube: Kapitel)
    property int startSel: -1                    // beim Oeffnen markierte Zeile (-1 = erste)
    signal qualityChosen(string v)
    signal extraChosen(string id)
    signal repeatChosen(string m)
    signal shuffleToggled()
    signal homeChosen()
    signal coverRefresh()
    z: 45
    width: Math.min(Ui.screenW * 0.34, 460 * Ui.f)
    height: parent.height
    x: open ? parent.width - width : parent.width
    Behavior on x { NumberAnimation { duration: 250; easing.type: Easing.OutQuint } }
    visible: x < parent.width
    color: Ui.alpha(Ui.c.surfaceDialog, 0.95)
    MouseArea { anchors.fill: parent; acceptedButtons: Qt.AllButtons; onWheel: function (w) { w.accepted = true } }

    function trackLabel(t) {
        var title = t.title || ""
        // externe Spur ohne echten Namen (YouTube: "videoplayback", Testdateien: "a.m4a") -> Sprache bzw. "Spur n"
        if (t.external && /^videoplayback|\.(m4a|mp4|webm|opus|aac|mka)$/i.test(title)) title = ""
        var name = title || app.langName(t.lang) || Ui.t("player.track", { n: t.id })
        return name
    }
    function trackSub(t) {
        var parts = []
        if (t.title && t.lang) parts.push(app.langName(t.lang))
        if (t.codec) parts.push(String(t.codec).toUpperCase())
        if (t.external) parts.push(Ui.t("player.external"))
        return parts.join(" · ")
    }
    function aspectNow(st) {
        if ((st.panscan || 0) > 0.01) return "zoom"
        var a = Number(st.aspect)
        if (Math.abs(a - 16 / 9) < 0.02) return "16:9"
        if (Math.abs(a - 4 / 3) < 0.02) return "4:3"
        return "-1"
    }
    function build() {
        if (customRows) return customRows
        var st = app.st || {}, out = [], tracks = st.tracks || [], i, t
        var audio = tracks.filter(function (t) { return t.type === "audio" })
        var subs = tracks.filter(function (t) { return t.type === "sub" })
        var hasVideo = tracks.some(function (t) { return t.type === "video" && !t.albumart })
        for (i = 0; i < leadRows.length; i++)
            out.push(leadRows[i].head ? { head: leadRows[i].head }
                     : { label: leadRows[i].label, sub: leadRows[i].sub || "", on: false, act: { kind: "extra", id: leadRows[i].id } })
        if (repeatMode) {
            out.push({ head: Ui.t("player.menu.repeat") })
            var modes = ["next", "folder", "once", "track"]
            for (i = 0; i < modes.length; i++)
                out.push({ label: Ui.t("player.repeat." + modes[i]), sub: Ui.t("player.repeat." + modes[i] + ".sub"), on: repeatMode === modes[i],
                           act: { kind: "repeat", v: modes[i] } })
        }
        if (shuffleState >= 0) {
            out.push({ head: Ui.t("player.menu.order") })
            out.push({ label: Ui.t("player.shuffle"), sub: Ui.t("player.shuffle.sub"), on: shuffleState === 1, act: { kind: "shuffle" } })
        }
        if (audio.length > 1 || (audio.length && hasVideo)) {
            out.push({ head: Ui.t("player.menu.audio") })
            for (i = 0; i < audio.length; i++) { t = audio[i]; out.push({ label: trackLabel(t), sub: trackSub(t), on: t.selected, act: { kind: "aid", id: t.id } }) }
        }
        if (hasVideo || subs.length) {
            out.push({ head: Ui.t("player.menu.subs") })
            out.push({ label: Ui.t("player.menu.subsOff"), sub: "", on: !subs.some(function (t) { return t.selected }), act: { kind: "sid", id: "no" } })
            for (i = 0; i < subs.length; i++) { t = subs[i]; out.push({ label: trackLabel(t), sub: trackSub(t), on: t.selected, act: { kind: "sid", id: t.id } }) }
        }
        if (hasVideo) {
            var asp = aspectNow(st)
            out.push({ head: Ui.t("player.menu.aspect") })
            out.push({ label: Ui.t("player.aspect.auto"), sub: "", on: asp === "-1", act: { kind: "aspect", v: "-1" } })
            out.push({ label: "16:9", sub: "", on: asp === "16:9", act: { kind: "aspect", v: "16:9" } })
            out.push({ label: "4:3", sub: "", on: asp === "4:3", act: { kind: "aspect", v: "4:3" } })
            out.push({ label: Ui.t("player.aspect.zoom"), sub: "", on: asp === "zoom", act: { kind: "aspect", v: "zoom" } })
        }
        if (withQuality && qualityList.length) {
            out.push({ head: Ui.t("player.menu.quality") })
            for (i = 0; i < qualityList.length; i++)
                out.push({ label: qualityList[i].label, sub: qualityList[i].sub || "", on: quality === qualityList[i].v,
                           act: { kind: "quality", v: qualityList[i].v } })
        } else if (withQuality) {
            out.push({ head: Ui.t("player.menu.quality") })
            out.push({ label: Ui.t("player.quality.best"), sub: "", on: quality === "max", act: { kind: "quality", v: "max" } })
            out.push({ label: Ui.t("player.quality.low"), sub: "", on: quality === "min", act: { kind: "quality", v: "min" } })
        }
        out.push({ head: Ui.t("player.menu.more") })
        for (i = 0; i < extraRows.length; i++)
            out.push({ label: extraRows[i].label, sub: extraRows[i].sub || "", on: false, act: { kind: "extra", id: extraRows[i].id } })
        if (repeatMode)                              // Musik: falsches oder fehlendes Cover
            out.push({ label: Ui.t("player.menu.recover"), sub: Ui.t("player.menu.recover.sub"), on: false, act: { kind: "recover" } })
        out.push({ label: Ui.t("player.menu.home"), sub: homeSub, on: false, act: { kind: "home" } })
        return out
    }
    function show() {
        rows = build()
        sel = -1
        if (startSel >= 0 && startSel < rows.length && !rows[startSel].head) sel = startSel
        else for (var i = 0; i < rows.length; i++) if (!rows[i].head) { sel = i; break }
        open = true
        Qt.callLater(function () { if (m.sel >= 0) list.positionViewAtIndex(m.sel, ListView.Center) })
    }
    function hide() { open = false }
    function refresh() {
        var keep = sel
        rows = build()
        sel = Math.min(keep, rows.length - 1)
        while (sel >= 0 && rows[sel] && rows[sel].head) sel++
    }
    Timer { interval: 600; repeat: true; running: m.open; onTriggered: m.refresh() }   // Spuren kommen manchmal spaeter
    function step(d) {
        var i = sel
        for (var n = 0; n < rows.length; n++) {
            i += d
            if (i < 0 || i >= rows.length) return
            if (!rows[i].head) { sel = i; list.positionViewAtIndex(i, ListView.Contain); return }
        }
    }
    function apply(act) {
        var p = app.player
        if (!p || !act) return
        if (act.kind === "aid" || act.kind === "sid") p.setProp(act.kind, act.id)
        else if (act.kind === "aspect") {
            p.setProp("video-aspect-override", act.v === "zoom" ? "-1" : act.v)
            p.setProp("panscan", act.v === "zoom" ? 1.0 : 0.0)
        } else if (act.kind === "quality") {
            quality = act.v
            qualityChosen(act.v)
        } else if (act.kind === "shuffle") {
            shuffleToggled()
        } else if (act.kind === "repeat") {
            repeatChosen(act.v)
        } else if (act.kind === "home") {
            return homeChosen()
        } else if (act.kind === "extra") {
            hide()
            return extraChosen(act.id)
        } else if (act.kind === "recover") {
            hide()
            return coverRefresh()
        }
        Qt.callLater(refresh)
    }
    function key(k) {
        if (k === "b" || k === "start") { vs.playSound("back"); return hide() }
        if (k === "up") { var prevU = sel; step(-1); if (sel !== prevU) vs.playSound("navigate"); return }
        if (k === "down") { var prevD = sel; step(1); if (sel !== prevD) vs.playSound("navigate"); return }
        if ((k === "a" || k === "play") && rows[sel] && !rows[sel].head) { vs.playSound("select"); return apply(rows[sel].act) }
    }

    Txt {
        id: title
        x: 28 * Ui.f; y: 34 * Ui.f
        text: m.title
        font.pixelSize: 26 * Ui.f
        font.weight: Font.Light
    }
    ListView {
        id: list
        anchors.top: title.bottom; anchors.topMargin: 18 * Ui.f
        anchors.bottom: hintRow.top; anchors.bottomMargin: 12 * Ui.f
        x: 16 * Ui.f
        width: m.width - 32 * Ui.f
        clip: true
        model: m.rows
        boundsBehavior: Flickable.StopAtBounds
        delegate: Item {
            width: list.width
            height: modelData.head ? 46 * Ui.f : 54 * Ui.f
            Txt {
                visible: !!modelData.head
                anchors.bottom: parent.bottom; anchors.bottomMargin: 8 * Ui.f
                x: 12 * Ui.f
                text: modelData.head || ""
                color: Ui.c.textDim
                font.pixelSize: 15 * Ui.f
                font.letterSpacing: 0.4
            }
            Rectangle {
                visible: !modelData.head
                anchors.fill: parent
                anchors.topMargin: 2 * Ui.f; anchors.bottomMargin: 2 * Ui.f
                color: index === m.sel ? Ui.c.surfaceCardHover : "transparent"
                border.width: 2
                border.color: index === m.sel ? Ui.c.borderFocus : "transparent"
                Txt {
                    id: check
                    x: 12 * Ui.f
                    anchors.verticalCenter: parent.verticalCenter
                    text: modelData.on ? "✓" : ""
                    width: 22 * Ui.f
                    font.pixelSize: 17 * Ui.f
                }
                Column {
                    anchors.left: check.right; anchors.leftMargin: 6 * Ui.f
                    anchors.right: parent.right; anchors.rightMargin: 12 * Ui.f
                    anchors.verticalCenter: parent.verticalCenter
                    Txt { width: parent.width; text: modelData.label || ""; font.pixelSize: 17 * Ui.f; font.weight: modelData.on ? Font.DemiBold : Font.Normal }
                    Txt { width: parent.width; visible: !!modelData.sub; text: modelData.sub || ""; font.pixelSize: 13 * Ui.f; color: Ui.c.textDim }
                }
                MouseArea {
                    anchors.fill: parent
                    hoverEnabled: true
                    onEntered: m.sel = index
                    onClicked: m.apply(modelData.act)
                }
            }
        }
    }
    Hints {
        id: hintRow
        x: 28 * Ui.f
        width: m.width - 56 * Ui.f
        anchors.bottom: parent.bottom; anchors.bottomMargin: 22 * Ui.f
        list: [Ui.t("player.hint.choose"), Ui.t("player.hint.close")]
    }
}
