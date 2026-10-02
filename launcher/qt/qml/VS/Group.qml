// SPDX-License-Identifier: GPL-3.0-or-later
// Gruppe auf einer Buehne: Ueberschrift + Inhalt
import QtQuick

Column {
    id: g
    property bool isGroup: true
    property string title: ""
    property bool showTitle: true
    default property alias content: box.data
    spacing: 0
    Txt {
        visible: g.showTitle
        text: g.title
        font.pixelSize: 18 * Ui.f
        color: Ui.c.textDim
        font.letterSpacing: 18 * Ui.f * 0.02
        elide: Text.ElideNone
        height: implicitHeight + 14 * Ui.f
    }
    Item {
        id: box
        width: childrenRect.width
        height: childrenRect.height
    }
}
