// SPDX-License-Identifier: GPL-3.0-or-later
// Rechts oben in Unterseiten: gross was laeuft, darunter Zusatz
import QtQuick

Column {
    id: n
    property string main: ""
    property string sub: ""
    property Component extra
    property real maxW: Ui.screenW * 0.45
    spacing: 0
    width: Math.min(maxW, Math.max(m.implicitWidth, s.implicitWidth, ex.item ? ex.item.implicitWidth : 0))
    Txt { id: m; width: n.width; horizontalAlignment: Text.AlignRight; text: n.main; font.pixelSize: 21 * Ui.f }
    Txt { id: s; width: n.width; horizontalAlignment: Text.AlignRight; text: n.sub; visible: !n.extra && text !== ""; color: Ui.c.textDim }
    Loader { id: ex; width: n.width; sourceComponent: n.extra; visible: !!n.extra }
}
