// SPDX-License-Identifier: GPL-3.0-or-later
// Fokus und Pfeil-Navigation wie in der Web-Oberflaeche: das naechste Element in Pfeilrichtung
// nach Bildschirmposition (Hauptrichtung + 2,2 × Seitenabstand). Fokussierbar ist jedes sichtbare
// Element mit navigable: true; Container mit ensureVisible(item, instant) scrollen es ins Bild.
pragma Singleton
import QtQuick

QtObject {
    id: nav
    property Item current: null
    property var memory: ({})                   // zuletzt fokussiertes Element je Ebene
    property int serial: 0                      // zaehlt Fokuswechsel (fuer Bindungen)

    function collect(root) {
        var out = []
        if (root) walk(root, out)
        return out
    }
    function walk(it, out) {
        var ch = it.children
        for (var i = 0; i < ch.length; i++) {
            var c = ch[i]
            if (!c || !c.visible) continue
            if (c.navigable === true && c.enabled) out.push(c)
            if (c.navBarrier !== true) walk(c, out)
        }
    }
    function alive(item, root) {
        if (!item) return false
        try { if (!item.visible || !item.navigable) return false } catch (e) { return false }
        for (var p = item; p; p = p.parent) if (p === root) return true
        return false
    }
    function rectOf(it) {
        var p = it.mapToItem(null, 0, 0)
        var q = it.mapToItem(null, it.width, it.height)
        return { l: Math.min(p.x, q.x), t: Math.min(p.y, q.y), r: Math.max(p.x, q.x), b: Math.max(p.y, q.y) }
    }
    function nearest(from, items, dir) {
        var a = rectOf(from), ax = (a.l + a.r) / 2, ay = (a.t + a.b) / 2
        var best = null, bestScore = Infinity
        for (var i = 0; i < items.length; i++) {
            var el = items[i]
            if (el === from) continue
            if (el.navOnlyUp === true && dir !== "up") continue
            var b = rectOf(el), bx = (b.l + b.r) / 2, by = (b.t + b.b) / 2, dx = bx - ax, dy = by - ay, main, side
            if (dir === "left")  { if (b.r > a.l + 1) continue; main = -dx; side = Math.abs(dy) }
            if (dir === "right") { if (b.l < a.r - 1) continue; main = dx;  side = Math.abs(dy) }
            if (dir === "up")    { if (b.b > a.t + 1) continue; main = -dy; side = Math.abs(dx) }
            if (dir === "down")  { if (b.t < a.b - 1) continue; main = dy;  side = Math.abs(dx) }
            var score = main + side * 2.2
            if (score < bestScore) { bestScore = score; best = el }
        }
        return best
    }
    function setFocus(item, instant, scope) {
        if (!item) return
        current = item
        if (scope) memory[scope] = item
        serial++
        for (var p = item.parent; p; p = p.parent)
            if (typeof p.ensureVisible === "function") p.ensureVisible(item, !!instant)
    }
    function remembered(scope, root) {
        var m = memory[scope]
        return alive(m, root) ? m : null
    }
}
