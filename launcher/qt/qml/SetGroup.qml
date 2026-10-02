// SPDX-License-Identifier: GPL-3.0-or-later
// Spalte einer Einstellungsseite: Ueberschrift + Zeilen (scrollt senkrecht, wenn sie nicht passt)
import QtQuick
import VS

Group {
    id: sg
    property real availH: 400
    default property alias rows: col.rows
    Col {
        id: col
        maxH: sg.availH - 18 * Ui.f * 1.36 - 14 * Ui.f
    }
}
