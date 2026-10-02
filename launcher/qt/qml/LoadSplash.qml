// SPDX-License-Identifier: GPL-3.0-or-later
// Ladebild bis die Kacheln stehen: Logo mittig, drei pulsierende Punkte darunter – wie das Startbild
// beim Hochfahren (Plymouth) und die WebKit-Shell, damit der Bildschirm nie leer ist. Feste Farben, kein Theme.
import QtQuick

Rectangle {
    id: ls
    property bool done: false
    z: 60
    color: "#0e1012"
    opacity: done ? 0 : 1
    visible: opacity > 0
    Behavior on opacity { NumberAnimation { duration: 250 } }
    MouseArea { anchors.fill: parent; acceptedButtons: Qt.AllButtons; hoverEnabled: true }
    Image {
        id: logo
        source: vsLogo
        width: Math.min(ls.width * 0.42, implicitWidth)
        height: implicitWidth > 0 ? implicitHeight * width / implicitWidth : 0
        x: (ls.width - width) / 2
        y: ls.height * 0.45 - height / 2
        smooth: true
        fillMode: Image.PreserveAspectFit
    }
    property real t: 0
    NumberAnimation on t { from: 0; to: 1000; duration: 1000000; running: ls.visible; loops: Animation.Infinite }
    readonly property real ds: Math.max(8, Math.min(18, Math.floor(width / 120)))
    Row {
        spacing: ls.ds * 2
        x: (ls.width - (3 * ls.ds + 4 * ls.ds)) / 2
        y: ls.height * 0.45 + logo.height / 2 + ls.height * 0.08
        Repeater {
            model: 3
            Rectangle {
                width: ls.ds; height: ls.ds; radius: ls.ds / 2
                color: "#ecebe8"
                opacity: 0.2 + 0.8 * Math.max(0, Math.sin(ls.t * 4 - index * 0.9))
            }
        }
    }
}
