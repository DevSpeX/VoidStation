// SPDX-License-Identifier: GPL-3.0-or-later
// Gemeinsame Werte der Oberflaeche: Farben (aus web/themes), Texte (aus web/i18n), Masse.
// Alle Masse haengen an f (= Skalierung × Bildschirmhoehe/768) und u (Kachelgroesse) – wie in der Web-Oberflaeche.
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
    readonly property var loc: Qt.locale(lang === "en" ? "en_US" : "de_DE")
    readonly property int ease: Easing.OutQuint

    // Text der Oberflaeche; {name} wird durch vars.name ersetzt
    function t(key, vars, fallback) {
        var t = s[key]
        if (t === undefined || t === null) t = (fallback !== undefined && fallback !== null) ? fallback : key
        t = String(t)
        if (vars) t = t.replace(/\{(\w+)\}/g, function (m, k) { return vars[k] !== undefined ? vars[k] : m })
        return t
    }
    // Kachel-, Gruppen- und App-Namen: {"de": …, "en": …} oder deutscher Name (uebersetzt ueber "labels")
    function l(v) {
        if (v && typeof v === "object") return v[lang] || v.de || ""
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
    function pct(n) { return lang === "de" ? n + " %" : n + "%" }
    // Bild-Adresse wie im Web: "/bild.jpg" kommt vom Launcher, volle Adressen bleiben
    function url(p) {
        if (!p) return ""
        p = String(p)
        if (/^[a-z][a-z0-9+.-]*:/i.test(p)) return p
        return vsApi + (p.charAt(0) === "/" ? p : "/" + p)
    }
    function icon(name, color) { return vs.icon(name || "globe", String(color)) }
    function esc(t) { return String(t === undefined || t === null ? "" : t).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;") }
    function alpha(col, a) { var q = Qt.color(col); return Qt.rgba(q.r, q.g, q.b, a) }
    function regionName(code) {
        var names = s["region." + code]
        if (names) return names
        return regions[lang] && regions[lang][code] ? regions[lang][code] : code
    }
    readonly property var regions: ({
        de: { DE: "Deutschland", AT: "Österreich", CH: "Schweiz", FR: "Frankreich", IT: "Italien", GB: "Vereinigtes Königreich",
              US: "Vereinigte Staaten", ES: "Spanien", NL: "Niederlande", PL: "Polen", BE: "Belgien", LU: "Luxemburg", DK: "Dänemark",
              SE: "Schweden", NO: "Norwegen", FI: "Finnland", CZ: "Tschechien", PT: "Portugal", IE: "Irland", GR: "Griechenland",
              TR: "Türkei", HU: "Ungarn", RO: "Rumänien", HR: "Kroatien", SI: "Slowenien", SK: "Slowakei", CA: "Kanada",
              AU: "Australien", BR: "Brasilien", MX: "Mexiko", AR: "Argentinien", IN: "Indien", JP: "Japan", KR: "Südkorea",
              CN: "China", RU: "Russland", UA: "Ukraine", IL: "Israel", AE: "Vereinigte Arabische Emirate", ZA: "Südafrika" },
        en: { DE: "Germany", AT: "Austria", CH: "Switzerland", FR: "France", IT: "Italy", GB: "United Kingdom",
              US: "United States", ES: "Spain", NL: "Netherlands", PL: "Poland", BE: "Belgium", LU: "Luxembourg", DK: "Denmark",
              SE: "Sweden", NO: "Norway", FI: "Finland", CZ: "Czechia", PT: "Portugal", IE: "Ireland", GR: "Greece",
              TR: "Türkiye", HU: "Hungary", RO: "Romania", HR: "Croatia", SI: "Slovenia", SK: "Slovakia", CA: "Canada",
              AU: "Australia", BR: "Brazil", MX: "Mexico", AR: "Argentina", IN: "India", JP: "Japan", KR: "South Korea",
              CN: "China", RU: "Russia", UA: "Ukraine", IL: "Israel", AE: "United Arab Emirates", ZA: "South Africa" }
    })
}
