// SPDX-License-Identifier: GPL-3.0-or-later
// Tafel mit Zeilen (Zusammenfassung, Erklaerungen). rows = Liste aus
//   { k: "Ueberschrift", v: "Text" }   { html: "<b>…</b>" }   { foot: "…" }   { ol: ["…", …] }
//   { mono: "Protokoll" }              { st: "ok" | "bad" | "keep", t: "…" }
import QtQuick
import VS

Rectangle {
    id: pn
    property var rows: []
    property real u: Ui.u
    property bool wide: false
    width: u * (wide ? 3.1 : 2.05)
    height: Math.max(u * 2, col.implicitHeight + 44 * Ui.f)
    color: Ui.c.surfaceRaised
    border.width: 1
    border.color: Ui.c.borderSubtle
    function rich(s) { return String(s || "").replace(/<b>/g, "<b><font color='" + Ui.c.textPrimary + "'>").replace(/<\/b>/g, "</font></b>") }
    Column {
        id: col
        x: 22 * Ui.f; y: 22 * Ui.f
        width: parent.width - 44 * Ui.f
        spacing: 15 * Ui.f
        Repeater {
            model: pn.rows.filter(function (r) { return !!r })
            Column {
                width: col.width
                spacing: 4
                Txt { visible: !!modelData.k; width: parent.width; text: modelData.k || ""; font.pixelSize: 12.5 * Ui.f; color: Ui.c.textDim }
                Txt {
                    visible: modelData.v !== undefined || modelData.html !== undefined
                    width: parent.width
                    text: modelData.html !== undefined ? pn.rich(modelData.html) : String(modelData.v || "")
                    textFormat: modelData.html !== undefined ? Text.StyledText : Text.PlainText
                    font.pixelSize: 15 * Ui.f
                    wrapMode: Text.WordWrap; elide: Text.ElideNone; lineHeight: 1.25
                }
                Column {                                   // nummerierte Schritte
                    visible: !!modelData.ol
                    width: parent.width
                    spacing: 14 * Ui.f
                    Repeater {
                        model: modelData.ol || []
                        Row {
                            width: col.width
                            spacing: 12 * Ui.f
                            Rectangle {
                                width: 24 * Ui.f; height: width; radius: width / 2; color: Ui.c.surfaceCard
                                Txt { anchors.centerIn: parent; text: index + 1; font.pixelSize: 13 * Ui.f; elide: Text.ElideNone }
                            }
                            Txt { width: parent.width - 36 * Ui.f; text: modelData; textFormat: Text.StyledText; font.pixelSize: 15 * Ui.f
                                  wrapMode: Text.WordWrap; elide: Text.ElideNone; lineHeight: 1.25 }
                        }
                    }
                }
                Row {                                      // Zustand: ✓ / ✕ / –
                    visible: !!modelData.st
                    width: parent.width
                    spacing: 10 * Ui.f
                    Txt { text: modelData.st === "ok" ? "✓" : modelData.st === "bad" ? "✕" : "–"; width: 15 * Ui.f * 1.1
                          horizontalAlignment: Text.AlignHCenter; font.pixelSize: 15 * Ui.f; elide: Text.ElideNone
                          color: modelData.st === "ok" ? Ui.c.statusOkText : modelData.st === "bad" ? Ui.c.statusDangerText : Ui.c.textDim }
                    Txt { width: parent.width - 30 * Ui.f; text: modelData.t || ""; font.pixelSize: 15 * Ui.f; wrapMode: Text.WordWrap; elide: Text.ElideNone }
                }
                Text {
                    visible: !!modelData.mono
                    width: parent.width
                    text: modelData.mono || ""
                    font.family: "DejaVu Sans Mono"; font.pixelSize: 12.5 * Ui.f
                    color: Ui.c.textDim
                    wrapMode: Text.WrapAnywhere
                    maximumLineCount: 8; elide: Text.ElideRight
                }
                Txt { visible: !!modelData.foot; width: parent.width; text: modelData.foot || ""; font.pixelSize: 13 * Ui.f; color: Ui.c.textDim
                      wrapMode: Text.WordWrap; elide: Text.ElideNone; topPadding: 6 * Ui.f }
            }
        }
    }
}
