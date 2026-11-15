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
            "tr", "gr", "ru", "ua", "ko"]
// Vorgabe je Sprache der Oberflaeche (sonst wie INSTALL_DEFAULTS in launcher.py). Koreanisch setzt die Tastatur
// selbst zusammen; Japanisch und Chinesisch brauchen eine Kandidatenauswahl (fcitx5) – dort tippt sie lateinisch.
var BY_LANG = { de: "de", en: "us", cs: "cz", es: "es", fr: "fr", it: "it", lv: "lv", hu: "hu", nl: "nl", pl: "pl",
                "pt-BR": "br", ro: "ro", sk: "sk", tr: "tr", el: "gr", ru: "ru", uk: "ua", ja: "us", ko: "ko",
                "zh-CN": "us", "zh-TW": "us", da: "dk", sv: "se", nb: "no", is: "is", fi: "fi", et: "ee" }

function layout(id) { return L[id] || L.us }
function forLang(lang) { return BY_LANG[lang] || "us" }
function known(id) { return L.hasOwnProperty(id) }

// Akzent-Seite in Reihen von hoechstens zehn Zeichen, gleichmaessig verteilt
function split(s) {
    if (!s) return []
    var n = Math.ceil(s.length / 10), per = Math.ceil(s.length / n), out = []
    for (var i = 0; i < s.length; i += per) out.push(s.slice(i, i + per))
    return out
}
