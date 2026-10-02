// SPDX-License-Identifier: GPL-3.0-or-later
// Raster wie CSS "grid-auto-flow: column dense": feste Zeilenzahl, Spalten nach Bedarf.
// Kachelgroessen: medium 1×1, wide 2 Spalten, large 2×2.
import QtQuick

Item {
    id: g
    property var items: []
    property int rows: 3
    property real cellW: Ui.u
    property real cellH: Ui.u
    property real gap: Ui.gap
    property Component delegate
    property var places: pack(items, rows)
    property int cols: {
        var m = 0
        for (var i = 0; i < places.length; i++) m = Math.max(m, places[i].c + places[i].w)
        return m
    }
    width: cols > 0 ? cols * cellW + (cols - 1) * gap : 0
    height: rows * cellH + (rows - 1) * gap

    function span(t) {
        var s = (t && t.size) || "medium"
        return s === "wide" ? [1, 2] : s === "large" ? [2, 2] : [1, 1]
    }
    function pack(list, nrows) {
        var occ = {}, out = []
        nrows = Math.max(1, nrows)
        for (var i = 0; i < (list ? list.length : 0); i++) {
            var sp = span(list[i]), h = Math.min(sp[0], nrows), w = sp[1], placed = false
            for (var c = 0; !placed && c < 400; c++) {
                for (var r = 0; r + h <= nrows; r++) {
                    var free = true
                    for (var dr = 0; dr < h && free; dr++)
                        for (var dc = 0; dc < w && free; dc++)
                            if (occ[(r + dr) + ":" + (c + dc)]) free = false
                    if (!free) continue
                    for (dr = 0; dr < h; dr++) for (dc = 0; dc < w; dc++) occ[(r + dr) + ":" + (c + dc)] = true
                    out.push({ r: r, c: c, h: h, w: w })
                    placed = true
                    break
                }
            }
        }
        return out
    }
    Repeater {
        id: rep
        model: g.items
        delegate: g.delegate
        onItemAdded: function (index, item) {
            item.x = Qt.binding(function () { var p = g.places[index] || { c: 0 }; return p.c * (g.cellW + g.gap) })
            item.y = Qt.binding(function () { var p = g.places[index] || { r: 0 }; return p.r * (g.cellH + g.gap) })
            item.width = Qt.binding(function () { var p = g.places[index] || { w: 1 }; return p.w * g.cellW + (p.w - 1) * g.gap })
            item.height = Qt.binding(function () { var p = g.places[index] || { h: 1 }; return p.h * g.cellH + (p.h - 1) * g.gap })
        }
    }
}
