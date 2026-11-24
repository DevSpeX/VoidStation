// SPDX-License-Identifier: GPL-3.0-or-later
// Schiebebalken 1..100 % mit − / + Knoepfen und Maus-Ziehen (nutzt ausschliesslich Theme-Farben Ui.c.*)
import QtQuick

Row {
    id: sb
    spacing: 8 * Ui.f
    property int value: 70
    property int minVal: 1
    property int maxVal: 100
    property int step: 5
    property real meterW: Math.min(180 * Ui.f, Ui.screenW * 0.24)
    property string minusKey: ""
    property string plusKey: ""
    property int dragVal: value
    property bool dragging: false
    readonly property int displayVal: dragging ? dragVal : value
    readonly property real frac: Math.max(0, Math.min(1, (displayVal - minVal) / Math.max(1, maxVal - minVal)))

    signal preview(int val)
    signal committed(int val)

    onValueChanged: if (!dragging) dragVal = value

    function clampVal(v) {
        return Math.max(minVal, Math.min(maxVal, Math.round(v)))
    }
    function stepBy(delta) {
        var next = clampVal(value + delta)
        if (next === value) return
        dragVal = next
        committed(next)
    }
    function valAt(mx) {
        var ratio = Math.max(0, Math.min(1, mx / Math.max(1, trackArea.width)))
        return clampVal(minVal + ratio * (maxVal - minVal))
    }

    Pill {
        property string key: sb.minusKey
        text: "−"
        sound: ""
        enabled: sb.enabled && sb.value > sb.minVal
        onTriggered: sb.stepBy(-sb.step)
        anchors.verticalCenter: parent.verticalCenter
    }

    Item {
        id: trackArea
        width: sb.meterW
        height: Math.max(32 * Ui.f, thumb.height + 8 * Ui.f)
        anchors.verticalCenter: parent.verticalCenter

        Rectangle {
            id: groove
            width: parent.width
            height: Math.max(6, Math.round(6 * Ui.f))
            radius: height / 2
            anchors.verticalCenter: parent.verticalCenter
            color: Ui.c.surfaceRaised
            border.width: 1
            border.color: Ui.c.borderSubtle

            Rectangle {
                width: parent.width * sb.frac
                height: parent.height
                radius: parent.radius
                color: ma.pressed || ma.containsMouse ? Ui.c.borderFocus : Ui.c.textPrimary
                Behavior on width { enabled: !sb.dragging; NumberAnimation { duration: 120 } }
            }
        }

        Rectangle {
            id: thumb
            width: Math.max(12, Math.round(14 * Ui.f))
            height: width
            radius: width / 2
            anchors.verticalCenter: parent.verticalCenter
            x: Math.max(0, Math.min(trackArea.width - width, sb.frac * trackArea.width - width / 2))
            color: ma.pressed || ma.containsMouse ? Ui.c.borderFocus : Ui.c.textPrimary
            border.width: 2
            border.color: Ui.c.bgMain
            Behavior on x { enabled: !sb.dragging; NumberAnimation { duration: 120 } }
        }

        MouseArea {
            id: ma
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            enabled: sb.enabled
            onPressed: function (m) {
                sb.dragging = true
                var v = sb.valAt(m.x)
                if (v !== sb.dragVal) { sb.dragVal = v; sb.preview(v) }
                else sb.preview(v)
            }
            onPositionChanged: function (m) {
                if (!sb.dragging) return
                var v = sb.valAt(m.x)
                if (v !== sb.dragVal) { sb.dragVal = v; sb.preview(v) }
            }
            onReleased: function (m) {
                if (!sb.dragging) return
                var v = sb.valAt(m.x)
                sb.dragVal = v
                sb.dragging = false
                sb.committed(v)
            }
            onCanceled: {
                sb.dragging = false
                sb.dragVal = sb.value
            }
        }
    }

    Pill {
        property string key: sb.plusKey
        text: "+"
        sound: ""
        enabled: sb.enabled && sb.value < sb.maxVal
        onTriggered: sb.stepBy(sb.step)
        anchors.verticalCenter: parent.verticalCenter
    }

    Txt {
        text: Ui.pct(sb.displayVal)
        color: Ui.c.textDim
        font.pixelSize: 14 * Ui.f
        anchors.verticalCenter: parent.verticalCenter
    }
}
