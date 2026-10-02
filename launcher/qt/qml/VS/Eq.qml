// SPDX-License-Identifier: GPL-3.0-or-later
// Kleine Pegel-Anzeige (Radio/TV laeuft)
import QtQuick

Row {
    id: eq
    property real h: 16
    property color color: Ui.c.textPrimary
    spacing: 3
    height: h
    Repeater {
        model: [200, 600, 400, 800]
        Rectangle {
            width: 3
            color: eq.color
            anchors.bottom: parent.bottom
            height: eq.h * 0.25
            SequentialAnimation on height {
                running: eq.visible
                loops: Animation.Infinite
                PauseAnimation { duration: 1000 - modelData }
                NumberAnimation { to: eq.h; duration: 400; easing.type: Easing.InOutSine }
                NumberAnimation { to: eq.h * 0.25; duration: 600 + 0 * modelData; easing.type: Easing.InOutSine }
            }
        }
    }
}
