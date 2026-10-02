// SPDX-License-Identifier: GPL-3.0-or-later
// Farbige Kachel: Fokusrahmen (Abstand in Hintergrundfarbe + heller Rahmen), leicht vergroessert,
// Lichtverlauf, Druck-Effekt, Einflug-Animation
import QtQuick

Focusable {
    id: t
    property color tileColor: Ui.c.tileDefaultC
    property int enterDelay: 0
    property real enterFrom: 60 * Ui.f
    property bool enterUp: false
    property bool animateIn: true
    property bool pressFlash: true
    default property alias content: body.data
    z: focused ? 2 : 0
    scale: pressedNow ? 0.97 : focused ? 1.03 : 1
    Behavior on scale { NumberAnimation { duration: 180; easing.type: Easing.OutQuint } }

    Rectangle {                                    // Fokusrahmen
        anchors.fill: parent
        anchors.margins: -6 * Ui.f
        color: Ui.c.borderFocus
        visible: t.focused
        z: -2
    }
    Rectangle {
        anchors.fill: parent
        anchors.margins: -3 * Ui.f
        color: Ui.c.bgMain
        visible: t.focused
        z: -1
    }
    Rectangle {
        id: body
        anchors.fill: parent
        color: t.tileColor
        clip: true
        Rectangle {                                // Lichtverlauf wie im Web (160°)
            anchors.fill: parent
            z: 50
            gradient: Gradient {
                GradientStop { position: 0.0; color: "#12ffffff" }
                GradientStop { position: 0.45; color: "#00ffffff" }
                GradientStop { position: 1.0; color: "#2e000000" }
            }
        }
        Rectangle {
            anchors.fill: parent
            z: 51
            color: "#000000"
            opacity: t.pressedNow ? 0.1 : 0
        }
    }
    transform: Translate { id: shift; x: 0; y: 0 }
    Component.onCompleted: {
        if (!animateIn) return
        opacity = 0
        if (enterUp) shift.y = 26 * Ui.f; else shift.x = enterFrom
        enter.start()
    }
    SequentialAnimation {
        id: enter
        PauseAnimation { duration: t.enterDelay }
        ParallelAnimation {
            NumberAnimation { target: t; property: "opacity"; to: 1; duration: 600; easing.type: Easing.OutQuint }
            NumberAnimation { target: shift; property: t.enterUp ? "y" : "x"; to: 0; duration: 600; easing.type: Easing.OutQuint }
        }
    }
}
