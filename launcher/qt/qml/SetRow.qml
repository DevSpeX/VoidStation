// SPDX-License-Identifier: GPL-3.0-or-later
// Zeile mit Knoepfen, optional mit kleiner Beschriftung darueber
import QtQuick
import VS

Column {
    id: sr
    property string label: ""
    default property alias items: flow.data
    width: Ui.screenW * 0.4
    spacing: 8 * Ui.f
    Txt { visible: sr.label !== ""; text: sr.label; color: Ui.c.textFaint; font.pixelSize: 14 * Ui.f; topPadding: 6 * Ui.f; width: parent.width }
    Flow { id: flow; width: parent.width; spacing: 8 * Ui.f }
}
