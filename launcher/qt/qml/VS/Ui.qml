// SPDX-License-Identifier: GPL-3.0-or-later
// Gemeinsame Werte der Oberflaeche: Farben (aus web/themes), Texte (aus web/i18n), Masse.
// Alle Masse haengen an f (= Skalierung × Bildschirmhoehe/768) und u (Kachelgroesse).
pragma Singleton
import QtQuick

QtObject {
    id: ui
    property var c: vs.theme                  // Farben, z. B. Ui.c.surfaceCard
    property var s: vs.strings                // Texte
    property string lang: vs.lang
    property real scale: 1.75
    property real f: 1
    property real u: 161
    property int rows: 3
    property real gap: 10 * f
    property real padX: 80
    property real hintH: 60                   // Platz unten fuer die Hinweiszeile
    property real screenW: 1280
    property real screenH: 720
    property Item app                         // Hauptfenster (Main.qml): Aktionen wie toast(), openLayer()
    readonly property string font: Qt.application.font.family
    readonly property var loc: Qt.locale(s["fmt.locale"] || (lang === "en" ? "en_US" : "de_DE"))   // Zahlen, Datum
    readonly property int ease: Easing.OutQuint

    // Text der Oberflaeche; {name} wird durch vars.name ersetzt
    function t(key, vars, fallback) {
        var t = s[key]
        if (t === undefined || t === null) t = (fallback !== undefined && fallback !== null) ? fallback : key
        t = String(t)
        if (vars) t = t.replace(/\{(\w+)\}/g, function (m, k) { return vars[k] !== undefined ? vars[k] : m })
        return t
    }
    // Kachel-, Gruppen- und App-Namen: {"de": …, "en": …} oder deutscher Name (uebersetzt ueber "labels";
    // vs.strings bringt bei weiteren Sprachen die englischen labels als Rueckfall schon mit)
    function l(v) {
        if (v && typeof v === "object") return v[lang] || (lang !== "de" ? v.en : "") || v.de || ""
        if (!v || lang === "de") return v || ""
        var lab = s.labels || {}
        return lab[v] !== undefined ? lab[v] : v
    }
    function num(n, maxDec) {
        var d = maxDec === undefined ? 2 : maxDec
        var x = Number(n), dec = 0
        while (dec < d && Math.abs(x * Math.pow(10, dec) - Math.round(x * Math.pow(10, dec))) > 1e-9) dec++
        return x.toLocaleString(loc, "f", dec)
    }
    // Wie viele Reihen einer Kachelgroesse passen in avail? Eine Reihe mehr, wenn die Kacheln dafuer
    // hoechstens 15 % kleiner werden (wie fitGrid im Web). Ergebnis: { n: Reihen, k: Faktor fuer die Kachelgroesse }
    function fitRows(avail, cell, gap, max) {
        if (!(avail > 0) || !(cell > 0)) return { n: max, k: 1 }
        var n = Math.min(max, Math.floor((avail + gap) / (cell + gap))), k = 1
        if (n < max) {
            var k2 = (avail - n * gap) / ((n + 1) * cell)
            if (k2 >= 0.85) { n += 1; k = Math.min(1, k2) }
        }
        if (n < 1) { n = 1; k = avail / cell }
        return { n: n, k: k }
    }
    function pct(n) { return t("fmt.pct", { n: n }, n + "%") }
    // Datum nach fmt.date. Zusaetzlich zu Qts Formatzeichen gilt "cccc" (wie in CLDR): der Wochentag in der Grundform.
    // Qts "dddd" liefert die Form im Satz – auf Finnisch "sunnuntaina" (am Sonntag) statt "sunnuntai".
    function dateText(d) {
        var f = t("fmt.date", null, "dddd, d. MMMM")
        if (f.indexOf("cccc") >= 0)
            f = f.replace("cccc", "'" + loc.standaloneDayName(d.getDay(), Locale.LongFormat).replace(/'/g, "''") + "'")
        return loc.toString(d, f)
    }
    // Bild-Adresse wie im Web: "/bild.jpg" kommt vom Launcher, volle Adressen bleiben
    function url(p) {
        if (!p) return ""
        p = String(p)
        if (/^[a-z][a-z0-9+.-]*:/i.test(p)) return p
        return vsApi + (p.charAt(0) === "/" ? p : "/" + p)
    }
    function icon(name, color) { return vs.icon(name || "globe", String(color)) }

    // ---- Tasten-Hinweise: Controller-Symbole statt Buchstaben ----
    // padStyle: Bauart des zuletzt benutzten Controllers (xbox, ps, nintendo); "" = keiner angeschlossen oder
    // zuletzt die Tastatur benutzt – dann bleiben die Texte wie geschrieben ("<b>Enter / A</b> öffnen").
    property string padStyle: vs.padStyle
    // Controllertasten in den Texten (in allen Sprachen gleich geschrieben) -> Rolle (a = untere Taste usw.)
    readonly property var padWords: ({ "A": "a", "B": "b", "X": "x", "Y": "y", "LB": "lb", "RB": "rb", "LT": "lt", "RT": "rt",
                                       "Start": "start", "Select": "select", "Guide": "guide", "PS": "guide",
                                       "L3": "l3", "R3": "r3" })
    function keyImg(role, px, col) {
        var g = vs.keyGlyph(role, Math.round(px * 1.4))             // dunkle Taste, farbige Aufschrift
        if (!g || !g.src) return ""
        return "<img src=\"" + g.src + "\" width=\"" + g.w + "\" height=\"" + g.h + "\" align=\"middle\">"
    }
    // Wandelt jede Tastenangabe <b>…</b> um: mit Controller nur dessen Tasten als Symbole (Tastatur-Teile wie
    // "Enter", "Esc", "Bild ↑↓" fallen weg), ohne Controller halbfett in der Zweitfarbe wie bisher.
    // Angaben ohne Controllertaste ("<b>↑↓</b>", "<b>F2</b>") bleiben immer Text. px = Schriftgroesse.
    function keys(str, col, px) {
        col = col || c.textSecondary
        px = px || 14 * f
        var bold = function (t) { return "<b><font color='" + col + "'>" + t + "</font></b>" }
        var style = padStyle
        return String(str === undefined || str === null ? "" : str).replace(/<b>(.*?)<\/b>/g, function (m, inner) {
            if (!style) return bold(inner)
            var toks = inner.split(/ \/ | · /), out = [], seen = {}
            for (var i = 0; i < toks.length; i++) {
                var words = toks[i].split(" "), pad = false
                for (var j = 0; j < words.length; j++) if (padWords[words[j]]) pad = true
                if (!pad) continue                                   // Tastatur-Teil
                var part = []
                for (j = 0; j < words.length; j++) {
                    var r = padWords[words[j]]
                    if (r) { if (seen[r]) continue; seen[r] = true; part.push(keyImg(r, px, col) || bold(words[j])) }
                    else if (words[j]) part.push(bold(words[j]))     // "halten", "×2"
                }
                if (part.length) out.push(part.join(" "))
            }
            return out.length ? out.join("&nbsp;") : bold(inner)
        })
    }
    function esc(t) { return String(t === undefined || t === null ? "" : t).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;") }
    function alpha(col, a) { var q = Qt.color(col); return Qt.rgba(q.r, q.g, q.b, a) }
    function regionName(code) {
        var names = s["region." + code]
        if (names) return names
        var r = regions[lang] || regions.en           // weitere Sprachen: region.XX in ihrer i18n-Datei
        return r[code] ? r[code] : code
    }
    readonly property var regions: ({
        de: { DE: "Deutschland", AT: "Österreich", CH: "Schweiz", FR: "Frankreich", IT: "Italien", GB: "Vereinigtes Königreich",
              US: "Vereinigte Staaten", ES: "Spanien", NL: "Niederlande", PL: "Polen", BE: "Belgien", LU: "Luxemburg", DK: "Dänemark",
              SE: "Schweden", NO: "Norwegen", FI: "Finnland", CZ: "Tschechien", PT: "Portugal", IE: "Irland", GR: "Griechenland",
              TR: "Türkei", HU: "Ungarn", RO: "Rumänien", HR: "Kroatien", SI: "Slowenien", SK: "Slowakei", CA: "Kanada",
              AU: "Australien", BR: "Brasilien", MX: "Mexiko", AR: "Argentinien", IN: "Indien", JP: "Japan", KR: "Südkorea",
              CN: "China", RU: "Russland", UA: "Ukraine", IL: "Israel", AE: "Vereinigte Arabische Emirate", ZA: "Südafrika",
              BY: "Belarus", CL: "Chile", CO: "Kolumbien", CY: "Zypern", EE: "Estland", KZ: "Kasachstan", LI: "Liechtenstein", LT: "Litauen", LV: "Lettland", MC: "Monaco", MT: "Malta", NZ: "Neuseeland", PE: "Peru", SM: "San Marino", UY: "Uruguay", VE: "Venezuela", TW: "Taiwan", IS: "Island" },
        en: { DE: "Germany", AT: "Austria", CH: "Switzerland", FR: "France", IT: "Italy", GB: "United Kingdom",
              US: "United States", ES: "Spain", NL: "Netherlands", PL: "Poland", BE: "Belgium", LU: "Luxembourg", DK: "Denmark",
              SE: "Sweden", NO: "Norway", FI: "Finland", CZ: "Czechia", PT: "Portugal", IE: "Ireland", GR: "Greece",
              TR: "Türkiye", HU: "Hungary", RO: "Romania", HR: "Croatia", SI: "Slovenia", SK: "Slovakia", CA: "Canada",
              AU: "Australia", BR: "Brazil", MX: "Mexico", AR: "Argentina", IN: "India", JP: "Japan", KR: "South Korea",
              CN: "China", RU: "Russia", UA: "Ukraine", IL: "Israel", AE: "United Arab Emirates", ZA: "South Africa",
              BY: "Belarus", CL: "Chile", CO: "Colombia", CY: "Cyprus", EE: "Estonia", KZ: "Kazakhstan", LI: "Liechtenstein", LT: "Lithuania", LV: "Latvia", MC: "Monaco", MT: "Malta", NZ: "New Zealand", PE: "Peru", SM: "San Marino", UY: "Uruguay", VE: "Venezuela", TW: "Taiwan", IS: "Iceland" }
    })
}
