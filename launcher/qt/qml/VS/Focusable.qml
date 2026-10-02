// SPDX-License-Identifier: GPL-3.0-or-later
// Grundlage fuer alles, was den Fokus bekommen kann (Kacheln, Knoepfe, Felder).
// Maus: Ueberfahren setzt den Fokus, Klick loest aus, Rechtsklick wie "zurueck" bzw. Programm schliessen.
import QtQuick

Item {
    id: f
    property bool navigable: true
    property bool navOnlyUp: false
    readonly property bool focused: Nav.current === f
    property bool pressedNow: false
    signal triggered()
    function activate() { triggered() }

    MouseArea {
        anchors.fill: parent
        hoverEnabled: true
        acceptedButtons: Qt.LeftButton | Qt.RightButton
        cursorShape: Qt.PointingHandCursor
        onPositionChanged: if (!f.focused && f.navigable && Ui.app) Ui.app.mouseFocus(f)
        onEntered: if (!f.focused && f.navigable && Ui.app) Ui.app.mouseFocus(f)
        onClicked: function (m) { if (Ui.app) Ui.app.mouseClick(f, m.button) }
        onPressed: function (m) { if (m.button === Qt.LeftButton && Ui.app) Ui.app.mousePress(f) }
        onReleased: if (Ui.app) Ui.app.mouseRelease(f)
    }
}
