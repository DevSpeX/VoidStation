// SPDX-License-Identifier: GPL-3.0-or-later
import QtQuick

Item {
    id: s
    property real size: 34 * Ui.f
    property real line: 3 * Ui.f
    width: size; height: size
    Canvas {
        id: cv
        anchors.fill: parent
        property color a: Ui.c.borderMuted
        property color b: Ui.c.textPrimary
        onAChanged: requestPaint()
        onBChanged: requestPaint()
        onPaint: {
            var c = getContext("2d"), r = width / 2 - s.line / 2
            c.reset(); c.lineWidth = s.line
            c.strokeStyle = a; c.beginPath(); c.arc(width / 2, height / 2, r, 0, 2 * Math.PI); c.stroke()
            c.strokeStyle = b; c.beginPath(); c.arc(width / 2, height / 2, r, -Math.PI / 2, 0); c.stroke()
        }
        RotationAnimator on rotation { from: 0; to: 360; duration: 1000; loops: Animation.Infinite; running: s.visible }
    }
}
