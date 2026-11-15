// SPDX-License-Identifier: GPL-3.0-or-later
// Belegungen der Bildschirmtastatur (Startseite, Player, Installer). Kennungen wie die Tastaturen in launcher.py
// (INSTALL_DEFAULTS, setxkbmap): de, us, gb, fr … Je Belegung vier Reihen (Ziffern + drei Buchstabenreihen),
// dazu optional "acc" (Seite mit Akzenten, die auf der Hauptseite keinen Platz haben), "latin" (griechisch und
// kyrillisch: Umschalter auf lateinische Buchstaben, z. B. fuer WLAN-Passwoerter und Adressen) und "upper"
// (Grossbuchstaben, die toUpperCase() falsch bildet, z. B. tuerkisch i -> İ).
// Die Symbol-Seite ist fuer alle gleich und enthaelt jedes ASCII-Satzzeichen – Passwoerter gehen also immer.
.pragma library

var SYM = ["!\"#$%&'()*+", ",-./:;<=>?@", "[\\]^_`{|}~€", "£¥§°µ«»¿¡"]

var L = {
    us: { rows: ["1234567890", "qwertyuiop", "asdfghjkl'", "zxcvbnm,.-"] },
    gb: { rows: ["1234567890", "qwertyuiop", "asdfghjkl'", "zxcvbnm,.-"], acc: "£€" },
    de: { rows: ["1234567890ß", "qwertzuiopü", "asdfghjklöä", "yxcvbnm,.-"] },
    fr: { rows: ["1234567890", "azertyuiop", "qsdfghjklm", "wxcvbn,.'-"], acc: "éèêëàâîïôùûüÿçœæ", accLabel: "éè" },
    es: { rows: ["1234567890", "qwertyuiop", "asdfghjklñ", "zxcvbnm,.-"], acc: "áéíóúüñ¿¡", accLabel: "áé" },
    it: { rows: ["1234567890", "qwertyuiop", "asdfghjkl'", "zxcvbnm,.-"], acc: "àèéìíòóùú", accLabel: "àè" },
    br: { rows: ["1234567890", "qwertyuiop", "asdfghjklç", "zxcvbnm,.-"], acc: "áàâãéêíóôõúüç", accLabel: "ãé" },
    nl: { rows: ["1234567890", "qwertyuiop", "asdfghjkl'", "zxcvbnm,.-"], acc: "éèëïöüáóú", accLabel: "éë" },
    lv: { rows: ["1234567890", "qwertyuiop", "asdfghjkl'", "zxcvbnm,.-"], acc: "āčēģīķļņšūž", accLabel: "āč" },
    hu: { rows: ["1234567890ö", "qwertzuiopü", "asdfghjkléá", "yxcvbnm,.-"], acc: "áéíóöőúüű", accLabel: "őű" },
    pl: { rows: ["1234567890", "qwertyuiop", "asdfghjkl'", "zxcvbnm,.-"], acc: "ąćęłńóśźż", accLabel: "ąę" },
    cz: { rows: ["1234567890", "qwertzuiopú", "asdfghjklů", "yxcvbnm,.-"], acc: "áčďéěíňóřšťúůýž", accLabel: "čř" },
    sk: { rows: ["1234567890", "qwertzuiopú", "asdfghjklô", "yxcvbnm,.-"], acc: "áäčďéíĺľňóôŕšťúýž", accLabel: "čš" },
    ro: { rows: ["1234567890", "qwertyuiop", "asdfghjkl'", "zxcvbnm,.-"], acc: "ăâîșț", accLabel: "ăș" },
    // Türkçe Q: i/İ und ı/I sind verschiedene Buchstaben – Grossform von i ist İ (toUpperCase() kennt das nicht)
    tr: { rows: ["1234567890", "qwertyuıopğü", "asdfghjklşi", "zxcvbnmöç."], upper: { "i": "İ" } },
    // Nordisch: å æ ø / å ö ä rechts neben den Buchstabenreihen wie auf den Tastaturen dort; Finnisch tippt auf der
    // schwedischen Belegung. Íslenska: ð þ æ ö auf den Tasten, die Vokale mit Akut auf der Akzent-Seite.
    dk: { rows: ["1234567890", "qwertyuiopå", "asdfghjklæø", "zxcvbnm,.-"], acc: "éüöä", accLabel: "éü" },
    no: { rows: ["1234567890", "qwertyuiopå", "asdfghjkløæ", "zxcvbnm,.-"], acc: "éèêóòôäö", accLabel: "éò" },
    se: { rows: ["1234567890", "qwertyuiopå", "asdfghjklöä", "zxcvbnm,.-"], acc: "éüæø", accLabel: "éü" },
    fi: { rows: ["1234567890", "qwertyuiopå", "asdfghjklöä", "zxcvbnm,.-"], acc: "šžéü", accLabel: "šž" },
    is: { rows: ["1234567890ö", "qwertyuiopð", "asdfghjklæ", "zxcvbnm,.þ"], acc: "áéíóúý", accLabel: "áé" },
    ee: { rows: ["1234567890", "qwertyuiopüõ", "asdfghjklöä", "zxcvbnm,.-"], acc: "šž", accLabel: "šž" },
    // हिन्दी: InScript (wie die Tastaturen in Indien, xkb in(deva)); Umschalt gibt die zweite Ebene. ॉ/ऑ liegen auf der
    // z-Taste (statt der Zeichen fuer suedindische Umschrift). Zeichen, die erst im Wort ihre Form finden (Vokalzeichen,
    // Halant ्), tippt man nach dem Konsonanten; die Tasten zeigen sie mit Platzhalter-Kreis (label()).
    hi: { rows: ["1234567890ृ", "ौैाीूबहगदजड़", "ोे्िुपरकतचट", "ॉंमनवलस,.य"],
          upper: { "ृ": "ऋ", "ौ": "औ", "ै": "ऐ", "ा": "आ", "ी": "ई", "ू": "ऊ", "ब": "भ", "ह": "ङ", "ग": "घ", "द": "ध", "ज": "झ", "ड": "ढ", "़": "ञ", "ो": "ओ", "े": "ए", "्": "अ", "ि": "इ", "ु": "उ", "प": "फ", "र": "ऱ", "क": "ख", "त": "थ", "च": "छ", "ट": "ठ", "ॉ": "ऑ", "ं": "ँ", "म": "ण", "ल": "ळ", "स": "श", ",": "ष", ".": "।" },
          acc: "।ःॅऍॐ॥₹", accLabel: "ःॐ", latin: "us", nativeLabel: "कखग" },
    // தமிழ்: in der Reihenfolge des Alphabets – Vokalzeichen (mit Umschalt die Vokale selbst), darunter die Konsonanten
    // க … ன. InScript hat fuer Tamil Luecken, Tamil99 braucht eine Eingabelogik; Grantha-Buchstaben auf der Zusatzseite.
    ta: { rows: ["1234567890ஃ", "ாிீுூெேைொோௌ்", "கஙசஞடணதநபமய", "ரலவழளறனஜ,."],
          upper: { "ா": "ஆ", "ி": "இ", "ீ": "ஈ", "ு": "உ", "ூ": "ஊ", "ெ": "எ", "ே": "ஏ", "ை": "ஐ", "ொ": "ஒ", "ோ": "ஓ", "ௌ": "ஔ", "்": "அ" },
          acc: "ஷஸஹஶௐ₹", accLabel: "ஷஸ", latin: "us", nativeLabel: "அஆ" },
    // മലയാളം: InScript (xkb in(mal)); ൗ statt des veralteten ൌ, ഞ auf der Taste rechts oben. Chillus (ൺ ൻ ർ ൽ ൾ) und ൊ/ഒ
    // auf der Zusatzseite; ൊ geht auch als െ + ാ.
    ml: { rows: ["1234567890ൃ", "ൗൈാീൂബഹഗദജഡഞ", "ോേ്ിുപരകതചട", "െംമനവലസ,.യ"],
          upper: { "ൃ": "ഋ", "ൗ": "ഔ", "ൈ": "ഐ", "ാ": "ആ", "ീ": "ഈ", "ൂ": "ഊ", "ബ": "ഭ", "ഹ": "ങ", "ഗ": "ഘ", "ദ": "ധ", "ജ": "ഝ", "ഡ": "ഢ", "ോ": "ഓ", "േ": "ഏ", "്": "അ", "ി": "ഇ", "ു": "ഉ", "പ": "ഫ", "ര": "റ", "ക": "ഖ", "ത": "ഥ", "ച": "ഛ", "ട": "ഠ", "െ": "എ", "ം": "ഃ", "മ": "ണ", "വ": "ഴ", "ല": "ള", "സ": "ശ", ",": "ഷ" },
          acc: "ൺൻർൽൾൿൊഒൌ₹", accLabel: "ൻർ", latin: "us", nativeLabel: "അആ" },
    // ไทย: Kedmanee (xkb th(basic)) mit ihren vier Reihen, darueber die Ziffern – also fuenf Reihen. Umschalt gibt die
    // zweite Ebene (thailaendische Ziffern, seltenere Buchstaben).
    th: { rows: ["1234567890", "ๅ/-ภถุึคตจขช", "ๆไำพะัีรนยบล", "ฟหกดเ้่าสวง", "ผปแอิืทมใฝ"],
          upper: { "ๅ": "+", "/": "๑", "-": "๒", "ภ": "๓", "ถ": "๔", "ุ": "ู", "ึ": "฿", "ค": "๕", "ต": "๖", "จ": "๗", "ข": "๘", "ช": "๙", "ๆ": "๐", "ไ": "\"", "ำ": "ฎ", "พ": "ฑ", "ะ": "ธ", "ั": "ํ", "ี": "๊", "ร": "ณ", "น": "ฯ", "ย": "ญ", "บ": "ฐ", "ล": ",", "ฟ": "ฤ", "ห": "ฆ", "ก": "ฏ", "ด": "โ", "เ": "ฌ", "้": "็", "่": "๋", "า": "ษ", "ส": "ศ", "ว": "ซ", "ง": ".", "ผ": "(", "ป": ")", "แ": "ฉ", "อ": "ฮ", "ิ": "ฺ", "ื": "์", "ท": "?", "ม": "ฒ", "ใ": "ฬ", "ฝ": "ฦ" },
          latin: "us", nativeLabel: "กขค" },
    // Tiếng Việt: lateinisch, auf der Zusatzseite ă â ê ô ơ ư đ und die fuenf Tonzeichen. Ein Tonzeichen setzt sich auf
    // den Vokal davor (KeyPad: tones) – a, dann ◌́ gibt á; ein zweites Tonzeichen ersetzt das erste.
    vi: { rows: ["1234567890", "qwertyuiop", "asdfghjkl'", "zxcvbnm,.-"], acc: "ăâêôơưđ\u0300\u0301\u0309\u0303\u0323", accLabel: "ăơ", tones: true },
    // 한국어, 2-Beolsik wie auf koreanischen Tastaturen; Shift gibt die doppelten Konsonanten und ㅒ ㅖ. Die Jamo
    // setzen sich zu Silben zusammen (hangul, s. KeyPad.qml / Hangul.js)
    ko: { rows: ["1234567890", "ㅂㅈㄷㄱㅅㅛㅕㅑㅐㅔ", "ㅁㄴㅇㄹㅎㅗㅓㅏㅣ", "ㅋㅌㅊㅍㅠㅜㅡ,.-"],
          upper: { "ㅂ": "ㅃ", "ㅈ": "ㅉ", "ㄷ": "ㄸ", "ㄱ": "ㄲ", "ㅅ": "ㅆ", "ㅐ": "ㅒ", "ㅔ": "ㅖ" },
          hangul: true, latin: "us", nativeLabel: "한" },
    gr: { rows: ["1234567890", ";ςερτυθιοπ", "ασδφγηξκλ", "ζχψωβνμ,.-"], acc: "άέήίόύώϊϋΐΰ", accLabel: "άέ",
          latin: "us", nativeLabel: "ΑΒΓ" },
    ru: { rows: ["1234567890ё", "йцукенгшщзх", "фывапролджэ", "ячсмитьбюъ"], latin: "us", nativeLabel: "АБВ" },
    ua: { rows: ["1234567890ґ", "йцукенгшщзхї", "фівапролджє", "ячсмитьбю'"], latin: "us", nativeLabel: "АБВ" }
}
// Zur Auswahl in den Einstellungen (Reihenfolge der Anzeige); Namen: Texte "inst.kb.<id>"
var LIST = ["de", "us", "gb", "fr", "es", "it", "br", "nl", "lv", "hu", "pl", "cz", "dk", "ee", "is", "no", "ro", "sk", "fi", "se",
            "tr", "vi", "gr", "ru", "ua", "hi", "ta", "ml", "th", "ko"]
// Vorgabe je Sprache der Oberflaeche (sonst wie INSTALL_DEFAULTS in launcher.py). Koreanisch setzt die Tastatur
// selbst zusammen; Japanisch und Chinesisch brauchen eine Kandidatenauswahl (fcitx5) – dort tippt sie lateinisch.
var BY_LANG = { de: "de", en: "us", cs: "cz", es: "es", fr: "fr", it: "it", lv: "lv", hu: "hu", nl: "nl", pl: "pl",
                "pt-BR": "br", ro: "ro", sk: "sk", tr: "tr", el: "gr", ru: "ru", uk: "ua", ja: "us", ko: "ko",
                "zh-CN": "us", "zh-TW": "us", da: "dk", sv: "se", nb: "no", is: "is", fi: "fi", et: "ee",
                id: "us", ms: "us", vi: "vi", th: "th", hi: "hi", ta: "ta", ml: "ml" }

function layout(id) { return L[id] || L.us }
function forLang(lang) { return BY_LANG[lang] || "us" }
function known(id) { return L.hasOwnProperty(id) }
// Beschriftung einer Zeichentaste: Zeichen, die sich an das Zeichen davor haengen (Akzente, Vokalzeichen, Tonzeichen),
// stehen allein in der Luft – sie bekommen den Platzhalter-Kreis ◌ davor. Getippt wird nur das Zeichen selbst.
var MARKS = [[0x300, 0x36F], [0x900, 0x903], [0x93A, 0x93C], [0x93E, 0x94F], [0x951, 0x957], [0x962, 0x963], [0xB82, 0xB82],
             [0xBBE, 0xBCD], [0xBD7, 0xBD7], [0xD00, 0xD03], [0xD3B, 0xD3C], [0xD3E, 0xD4D], [0xD57, 0xD57], [0xD62, 0xD63],
             [0xE31, 0xE31], [0xE34, 0xE3A], [0xE47, 0xE4E]]
function isMark(ch) {
    if (ch.length !== 1) return false
    var c = ch.charCodeAt(0)
    if (c < 0x300) return false
    for (var i = 0; i < MARKS.length; i++) if (c >= MARKS[i][0] && c <= MARKS[i][1]) return true
    return false
}
function label(ch) { return isMark(ch) ? "\u25CC" + ch : ch }
// Vietnamesisch: Tonzeichen auf den Vokal davor setzen. Gibt das neue Zeichen zurueck oder "" (kein Vokal davor).
var TONES = /[\u0300\u0301\u0303\u0309\u0323]/g
function isTone(ch) { return ch.length === 1 && "\u0300\u0301\u0303\u0309\u0323".indexOf(ch) >= 0 }
function withTone(prev, tone) {
    if (!prev) return ""
    var base = prev.normalize("NFD").replace(TONES, "")
    var c = (base + tone).normalize("NFC")
    return c.length === 1 ? c : ""
}

// Akzent-Seite in Reihen von hoechstens zehn Zeichen, gleichmaessig verteilt
function split(s) {
    if (!s) return []
    var n = Math.ceil(s.length / 10), per = Math.ceil(s.length / n), out = []
    for (var i = 0; i < s.length; i += per) out.push(s.slice(i, i + per))
    return out
}
