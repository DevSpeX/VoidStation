// SPDX-License-Identifier: GPL-3.0-or-later
// Einstellungs-Spalte: Zeilen untereinander, scrollt senkrecht mit dem Fokus, wenn sie nicht passt
import QtQuick

Flickable {
    id: col
    property real maxW: Ui.screenW * 0.4
    property real maxH: 400
    default property alias rows: box.data
    width: Math.min(maxW, box.implicitWidth)
    height: Math.min(maxH, box.implicitHeight + 4)
    contentWidth: width
    contentHeight: box.implicitHeight + 4
    clip: true
    interactive: false
    readonly property bool more: contentY + height < contentHeight - 2
    Column {
        id: box
        width: col.maxW
        spacing: 12 * Ui.f
        y: 2
    }
    NumberAnimation { id: a; target: col; property: "contentY"; duration: 250; easing.type: Easing.OutQuad }
    function ensureVisible(item, instant) {
        if (contentHeight <= height + 1) return
        var p = item.mapToItem(col.contentItem, 0, 0)
        var m = Math.max(0, Math.min(40 * Ui.f, (height - item.height) / 2))
        var y = a.running ? a.to : contentY
        if (p.y < y + m) y = p.y - m
        else if (p.y + item.height > y + height - m) y = p.y + item.height - height + m
        y = Math.max(0, Math.min(contentHeight - height, y))
        a.stop()
        if (instant) contentY = y; else { a.from = contentY; a.to = y; a.start() }
    }
    Rectangle {                                   // weich ausblenden, wo noch mehr kommt
        visible: col.more
        anchors.left: parent.left; anchors.right: parent.right; anchors.bottom: parent.bottom
        height: 36 * Ui.f
        gradient: Gradient {
            GradientStop { position: 0; color: Ui.alpha(Ui.c.bgMain, 0) }
            GradientStop { position: 1; color: Ui.c.bgMain }
        }
    }
    WheelHandler { onWheel: function (ev) { col.contentY = Math.max(0, Math.min(col.contentHeight - col.height, col.contentY - ev.angleDelta.y)) } }
}
