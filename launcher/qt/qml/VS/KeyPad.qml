// SPDX-License-Identifier: GPL-3.0-or-later
// Tastenfeld der Bildschirmtastatur – dasselbe in Startseite, Player und Installer. Belegungen: OskLayouts.js.
// Seiten: Buchstaben, Akzente (wenn die Belegung welche hat), Symbole; griechisch und kyrillisch zusaetzlich
// lateinische Buchstaben. Shift gilt fuer ein Zeichen. Die Tasten tragen Schluessel (key: "k0-3", "kdel" …),
// damit der Fokus beim Umschalten der Seite auf derselben Stelle bleibt. extra: weitere Tasten in der unteren Reihe
// (Tastatur ueber Programmen: Tab, Cursor), sie melden sich ueber special(name).
// Koreanisch (Belegung mit hangul: true): Jamo setzen sich zu Silben zusammen (VS/Hangul.js). Dafuer ersetzt die
// Tastatur das zuletzt getippte Zeichen ueber erase() + typed(). Wer den Cursor anders bewegt oder echte Tasten
// tippt, ruft endCompose(); backspace() nimmt beim Zusammensetzen nur den letzten Teil der Silbe weg.
// Vietnamesisch (tones: true): ein Tonzeichen ersetzt den Vokal davor durch den Vokal mit Ton, auf demselben Weg.
// Belegungen mit upper fuer jede Taste (Hindi, Malayalam, Thai …): Umschalt ist die zweite Ebene der Tastatur.
import QtQuick
import "OskLayouts.js" as OL
import "Hangul.js" as HG

Column {
    id: kp
    property string layoutId: "us"
    property real keyW: 44
    property real keyH: 44
    property real gap: 5 * Ui.f
    property string doneText: Ui.t("osk.enter")
    property bool shift: false
    property string page: "abc"                 // abc, acc, sym
    property bool latin: false
    property var extra: []                      // [{ l: "⇥", a: "Tab" }, …] vor der Leertaste
    property bool fitFont: false                // Schrift nach der Tastenhoehe statt nach der Skalierung (Tastatur ueber Programmen)
    property string hprev: ""                   // Koreanisch: zuletzt getipptes Zeichen, solange es sich noch verbinden kann
    signal typed(string ch)
    signal erase()
    signal done()
    signal special(string name)
    spacing: gap

    readonly property var lay: OL.layout(layoutId)
    readonly property var rows: page === "sym" ? OL.SYM : page === "acc" ? OL.split(lay.acc)
                              : (latin && lay.latin ? OL.layout(lay.latin).rows : lay.rows)
    // Breite in Tasten: gleich fuer alle Seiten der Belegung, damit nichts springt
    readonly property int units: {
        var all = [lay.rows, OL.SYM, OL.split(lay.acc)]
        if (lay.latin) all.push(OL.layout(lay.latin).rows)
        // untere Reihe: Seitenwechsel, Zusatztasten, Leertaste (mindestens 2), @ und Enter (3)
        var m = Math.max(12, 2 + (lay.acc ? 2 : 0) + (lay.latin ? 2 : 0) + extra.length + 2 + 4)
        for (var p = 0; p < all.length; p++)
            for (var i = 0; i < all[p].length; i++) m = Math.max(m, rowExtra(i, all[p].length, all[p] === OL.SYM) + all[p][i].length)
        return m
    }
    readonly property int fullRows: Math.max(lay.rows.length, OL.SYM.length) + 1
    function rowExtra(i, n, sym) { return (i === 0 ? 1 : 0) + (i === n - 1 && i > 0 ? 1 : 0) + (i === n - 1 && !sym ? 1 : 0) }
    function lettersLabel() { return lay.latin && !latin ? lay.nativeLabel : Ui.t("osk.letters") }
    readonly property var keyRows: {
        var out = [], r = rows, sym = page === "sym"
        for (var i = 0; i < r.length; i++) {
            var row = [], last = i === r.length - 1
            if (last && !sym) row.push({ l: "⇧", a: "shift", w: 1, k: "kshift" })
            for (var c = 0; c < r[i].length; c++) row.push({ l: r[i][c], a: "char", w: 1, k: "k" + i + "-" + c, ch: r[i][c] })
            if (i === 0) row.push({ l: "⌫", a: "del", w: 1, k: "kdel" })
            else if (last) row.push({ l: "⌫", a: "del", w: 1, k: "kdel2" })
            out.push(row)
        }
        var b = [{ l: sym ? lettersLabel() : Ui.t("osk.symbols"), a: "sym", w: 2, k: "ksym" }]
        if (lay.acc) b.push({ l: page === "acc" ? lettersLabel() : (lay.accLabel || lay.acc.slice(0, 2)), a: "acc", w: 2, k: "kacc" })
        if (lay.latin) b.push({ l: latin ? lay.nativeLabel : "ABC", a: "latin", w: 2, k: "klatin" })
        for (var e = 0; e < extra.length; e++) b.push({ l: extra[e].l, a: "special", w: 1, k: "kx" + extra[e].a, name: extra[e].a })
        var used = 0
        for (var j = 0; j < b.length; j++) used += b[j].w
        b.push({ l: Ui.t("osk.space"), a: "char", w: Math.max(2, units - used - 4), k: "kspace", ch: " " })
        b.push({ l: "@", a: "char", w: 1, k: "kat", ch: "@" })
        b.push({ l: doneText, a: "go", w: 3, k: "kgo" })
        out.push(b)
        return out
    }

    function reset() { shift = false; page = "abc"; latin = false; hprev = "" }
    function endCompose() { hprev = "" }
    function typeChar(ch) {
        if (lay.hangul && page === "abc" && !latin && HG.isJamo(ch)) {
            var r = HG.compose(hprev, ch)
            if (r.replace) erase()
            for (var i = 0; i < r.out.length; i++) typed(r.out.charAt(i))
            hprev = r.out.charAt(r.out.length - 1)
            return
        }
        if (lay.tones && !latin && OL.isTone(ch)) {            // Tiếng Việt: Tonzeichen auf den Vokal davor
            var t = OL.withTone(hprev, ch)
            if (!t) return
            erase(); typed(t); hprev = t
            return
        }
        hprev = lay.tones && !latin && ch !== " " ? ch : ""
        typed(ch)
    }
    function backspace() {
        if (!hprev || !lay.hangul) { hprev = ""; erase(); return }
        var rest = HG.back(hprev)
        erase()
        if (rest) typed(rest)
        hprev = rest
    }
    onLayoutIdChanged: reset()
    function caseOf(ch) {
        if (!shift || ch === " ") return ch
        var lay0 = latin && lay.latin ? OL.layout(lay.latin) : lay
        var u = page === "abc" && lay0.upper && lay0.upper[ch] ? lay0.upper[ch] : ch.toUpperCase()
        return u.length === 1 ? u : ch          // ß, ΐ: keine einzelne Grossform
    }
    function press(m) {
        if (m.a === "char") { typeChar(caseOf(m.ch)); if (shift && m.ch !== " ") shift = false }
        else if (m.a === "del") backspace()
        else if (m.a === "shift") shift = !shift
        else if (m.a === "sym") keep(function () { page = page === "sym" ? "abc" : "sym" })
        else if (m.a === "acc") keep(function () { page = page === "acc" ? "abc" : "acc" })
        else if (m.a === "latin") keep(function () { latin = !latin; page = "abc" })
        else if (m.a === "go") { hprev = ""; done() }
        else if (m.a === "special") { hprev = ""; special(m.name) }
    }
    // Seite wechseln, Fokus auf derselben Taste (bzw. der ersten) lassen
    function keep(fn) {
        var inside = Nav.alive(Nav.current, kp), k = inside && Nav.current.key ? Nav.current.key : ""
        fn()
        if (inside) Qt.callLater(function () {
            var all = Nav.collect(kp)
            var it = all.filter(function (x) { return x.key === k })[0] || all[0]
            if (it) Ui.app.setFocus(it, true)
        })
    }
    function firstKey() { return Nav.collect(kp)[0] || null }

    // Kurze Seiten (Akzente) oben auffuellen: Die Hoehe bleibt gleich, nichts springt
    Item {
        width: 1
        height: Math.max(0, kp.fullRows - kp.keyRows.length) * (kp.keyH + kp.gap) - (kp.fullRows > kp.keyRows.length ? kp.gap : 0)
        visible: height > 0
    }
    Repeater {
        model: kp.keyRows
        Row {
            spacing: kp.gap
            anchors.horizontalCenter: parent.horizontalCenter
            Repeater {
                model: modelData
                Focusable {
                    id: kk
                    property string key: modelData.k
                    property bool pressFlash: true
                    sound: modelData.a === "go" ? "select"
                         : (modelData.a === "shift" || modelData.a === "sym" || modelData.a === "acc" || modelData.a === "latin") ? "toggle"
                         : "navigate"
                    toggleFlip: true
                    width: modelData.w * kp.keyW + (modelData.w - 1) * kp.gap
                    height: kp.keyH
                    onTriggered: kp.press(modelData)
                    Rectangle {
                        anchors.fill: parent
                        radius: 2
                        color: modelData.a === "go" ? Ui.c.statusOkBg
                             : (modelData.a === "shift" && kp.shift) || (modelData.a === "acc" && kp.page === "acc") ? Ui.c.surfaceActive
                             : kk.focused ? Ui.c.surfaceCardHover : Ui.c.surfaceCard
                        border.width: 2
                        border.color: kk.focused ? Ui.c.borderFocus : "transparent"
                        Txt {
                            anchors.centerIn: parent
                            width: Math.min(implicitWidth, parent.width - 8)
                            horizontalAlignment: Text.AlignHCenter
                            text: modelData.a === "char" && modelData.w === 1 ? OL.label(kp.caseOf(modelData.ch)) : modelData.l
                            font.pixelSize: kp.fitFont ? kp.keyH * (modelData.w === 1 ? 0.44 : 0.36)
                                                       : (modelData.w === 1 ? 18 : 15) * Ui.f
                            fontSizeMode: Text.HorizontalFit
                            minimumPixelSize: 9 * Ui.f
                            elide: Text.ElideNone
                        }
                    }
                }
            }
        }
    }
}
