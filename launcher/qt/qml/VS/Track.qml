// SPDX-License-Identifier: GPL-3.0-or-later
// Waagrechte Buehne mit Gruppen: folgt dem Fokus (6 % Rand), blaettert gruppenweise (LT/RT, Bild auf/ab)
import QtQuick

Flickable {
    id: tr
    property real spacing: Ui.u * 0.4
    property real pad: Ui.padX
    default property alias groups: row.data
    readonly property real maxX: Math.max(0, contentWidth - width)
    readonly property bool scrollable: maxX > 4
    interactive: false
    clip: false
    flickableDirection: Flickable.HorizontalFlick
    contentWidth: row.width + 2 * pad
    contentHeight: height
    boundsBehavior: Flickable.StopAtBounds

    Row {
        id: row
        x: tr.pad
        spacing: tr.spacing
        height: tr.height
    }
    NumberAnimation { id: anim; target: tr; property: "contentX"; duration: 450; easing.type: Easing.OutQuint }

    function scrollTo(x, instant) {
        x = Math.max(0, Math.min(maxX, x))
        anim.stop()
        if (instant) contentX = x
        else { anim.from = contentX; anim.to = x; anim.start() }
    }
    function reset() { anim.stop(); contentX = 0 }
    function ensureVisible(item, instant) {
        var p = item.mapToItem(tr.contentItem, 0, 0)
        var target = anim.running ? anim.to : contentX
        var margin = Ui.screenW * 0.06
        var x = target
        if (p.x + item.width > target + width - margin) x = p.x + item.width - (width - margin)
        if (p.x < x + margin) x = p.x - margin
        x = Math.max(0, Math.min(maxX, x))
        if (Math.abs(x - target) > 0.5 || instant) scrollTo(x, instant)
    }
    function groupList() {
        var out = []
        for (var i = 0; i < row.children.length; i++) {
            var g = row.children[i]
            if (g.isGroup && g.visible) out.push(g)
        }
        return out
    }
    function groupOf(item) {
        for (var p = item; p; p = p.parent) if (p.isGroup && p.parent === row) return p
        return null
    }
    WheelHandler {
        onWheel: function (ev) {
            var d = ev.angleDelta.y || ev.angleDelta.x
            if (Ui.app && d) Ui.app.move(d < 0 ? "right" : "left")
        }
    }
}
