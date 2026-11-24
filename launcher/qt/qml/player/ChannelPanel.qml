// SPDX-License-Identifier: GPL-3.0-or-later
// Senderliste links (X / L) – umschalten, ohne die Startseite zu oeffnen.
// Reiter: Liste (aus der heraus gestartet wurde), Favoriten, Zuletzt. ◀▶ Reiter, ▲▼ Sender, A einschalten, Y Favorit
import QtQuick
import VS

Rectangle {
    id: cp
    property bool open: false
    property var all: []
    property var favs: []
    property var recent: []
    property string curKey: ""
    property int tab: 0
    readonly property var tabs: [Ui.t("player.tv.tab.list"), Ui.t("common.favorites"), Ui.t("player.tv.tab.recent")]
    readonly property var items: tab === 0 ? all : tab === 1 ? favs : recent
    signal chosen(var ch)
    signal favToggle(var ch)
    z: 45
    width: Math.min(Ui.screenW * 0.36, 500 * Ui.f)
    height: parent.height
    x: open ? 0 : -width
    Behavior on x { NumberAnimation { duration: 250; easing.type: Easing.OutQuint } }
    visible: x > -width
    color: Ui.alpha(Ui.c.surfaceDialog, 0.95)
    MouseArea { anchors.fill: parent; acceptedButtons: Qt.AllButtons; onWheel: function (w) { w.accepted = true } }

    function isFav(key) { for (var i = 0; i < favs.length; i++) if (favs[i].key === key) return true; return false }
    function show() {
        tab = 0
        if (!all.length) tab = favs.length ? 1 : 2
        open = true
        Qt.callLater(focusCurrent)
    }
    function hide() { open = false }
    function focusCurrent() {
        var idx = 0
        for (var i = 0; i < items.length; i++) if (items[i].key === curKey) { idx = i; break }
        list.currentIndex = idx
        list.positionViewAtIndex(idx, ListView.Center)
    }
    function setTab(t) {
        tab = (t + tabs.length) % tabs.length
        Qt.callLater(focusCurrent)
    }
    function key(k) {
        if (k === "b" || k === "x") { vs.playSound("back"); return hide() }
        if (k === "left" || k === "lb") { vs.playSound("group"); return setTab(tab - 1) }
        if (k === "right" || k === "rb") { vs.playSound("group"); return setTab(tab + 1) }
        if (k === "up") { if (list.currentIndex > 0) { list.currentIndex--; vs.playSound("navigate") } return }
        if (k === "down") { if (list.currentIndex < items.length - 1) { list.currentIndex++; vs.playSound("navigate") } return }
        if (k === "chup") { var prevU = list.currentIndex; list.currentIndex = Math.max(0, list.currentIndex - 8); if (list.currentIndex !== prevU) vs.playSound("group"); return }
        if (k === "chdown") { var prevD = list.currentIndex; list.currentIndex = Math.min(items.length - 1, list.currentIndex + 8); if (list.currentIndex !== prevD) vs.playSound("group"); return }
        var ch = items[list.currentIndex]
        if (!ch) return
        if (k === "a" || k === "play") { vs.playSound("select"); chosen(ch); hide() }
        else if (k === "y") { vs.playSound("toggle"); favToggle(ch) }
    }

    Row {
        id: tabRow
        x: 24 * Ui.f; y: 30 * Ui.f
        spacing: 22 * Ui.f
        Repeater {
            model: cp.tabs
            Column {
                spacing: 6 * Ui.f
                Txt {
                    text: modelData
                    font.pixelSize: 21 * Ui.f
                    font.weight: index === cp.tab ? Font.DemiBold : Font.Light
                    color: index === cp.tab ? Ui.c.textPrimary : Ui.c.textDim
                    MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: cp.setTab(index) }
                }
                Rectangle { width: parent.width; height: 3 * Ui.f; color: index === cp.tab ? Ui.c.borderFocus : "transparent" }
            }
        }
    }
    Txt {
        visible: cp.items.length === 0
        anchors.top: tabRow.bottom; anchors.topMargin: 30 * Ui.f
        x: 24 * Ui.f
        width: cp.width - 48 * Ui.f
        wrapMode: Text.Wrap; elide: Text.ElideNone
        text: Ui.t("player.tv.listEmpty")
        color: Ui.c.textFaint
    }
    ListView {
        id: list
        anchors.top: tabRow.bottom; anchors.topMargin: 18 * Ui.f
        anchors.bottom: hintRow.top; anchors.bottomMargin: 12 * Ui.f
        x: 12 * Ui.f
        width: cp.width - 24 * Ui.f
        clip: true
        model: cp.items
        boundsBehavior: Flickable.StopAtBounds
        highlightMoveDuration: 120
        cacheBuffer: 400
        delegate: Item {
            width: list.width
            height: 58 * Ui.f
            readonly property bool sel: ListView.isCurrentItem
            readonly property bool playing: modelData.key === cp.curKey
            opacity: modelData.broken && !playing ? 0.55 : 1
            Rectangle {
                anchors.fill: parent
                anchors.topMargin: 2 * Ui.f; anchors.bottomMargin: 2 * Ui.f
                color: parent.sel ? Ui.c.surfaceCardHover : parent.playing ? Ui.alpha(Ui.c.accentTv, 0.6) : "transparent"
                border.width: 2
                border.color: parent.sel ? Ui.c.borderFocus : "transparent"
            }
            Item {
                id: logoBox
                x: 12 * Ui.f
                width: 64 * Ui.f; height: 40 * Ui.f
                anchors.verticalCenter: parent.verticalCenter
                Image {
                    id: lg
                    anchors.fill: parent
                    source: modelData.logo || ""
                    fillMode: Image.PreserveAspectFit
                    asynchronous: true
                    sourceSize: Qt.size(Math.ceil(width * 1.5), Math.ceil(height * 1.5))
                    visible: status === Image.Ready
                }
                Glyph { anchors.centerIn: parent; visible: lg.status !== Image.Ready; name: "tv"; width: 26 * Ui.f; height: width; opacity: 0.6 }
            }
            Column {
                anchors.left: logoBox.right; anchors.leftMargin: 14 * Ui.f
                anchors.right: marks.left; anchors.rightMargin: 8 * Ui.f
                anchors.verticalCenter: parent.verticalCenter
                Txt { width: parent.width; text: modelData.name || ""; font.pixelSize: 17 * Ui.f; font.weight: parent.parent.playing ? Font.DemiBold : Font.Normal }
                Txt {
                    width: parent.width
                    text: [modelData.country ? Ui.regionName(modelData.country) : "", modelData.quality || "",
                           modelData.broken ? Ui.t("tv.broken") : ""].filter(function (s) { return s }).join(" · ")
                    visible: text !== ""
                    font.pixelSize: 13 * Ui.f
                    color: Ui.c.textDim
                }
            }
            Row {
                id: marks
                anchors.right: parent.right; anchors.rightMargin: 14 * Ui.f
                anchors.verticalCenter: parent.verticalCenter
                spacing: 8 * Ui.f
                Glyph { visible: parent.parent.playing; name: "playfill"; width: 16 * Ui.f; height: width; anchors.verticalCenter: parent.verticalCenter }
                Txt { visible: cp.isFav(modelData.key); text: "★"; font.pixelSize: 16 * Ui.f; color: Ui.c.textSecondary; anchors.verticalCenter: parent.verticalCenter }
            }
            MouseArea {
                anchors.fill: parent
                hoverEnabled: true
                acceptedButtons: Qt.LeftButton | Qt.RightButton
                onEntered: list.currentIndex = index
                onClicked: function (m) { if (m.button === Qt.RightButton) cp.hide(); else { cp.chosen(modelData); cp.hide() } }
            }
        }
    }
    Hints {
        id: hintRow
        x: 24 * Ui.f
        width: cp.width - 48 * Ui.f
        anchors.bottom: parent.bottom; anchors.bottomMargin: 22 * Ui.f
        list: [Ui.t("player.hint.tune"), Ui.t("player.hint.tabs"), Ui.t("player.hint.fav"), Ui.t("player.hint.close")]
    }
}
