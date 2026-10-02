// SPDX-License-Identifier: GPL-3.0-or-later
// Kurze Meldung unten rechts
import QtQuick
import VS

Rectangle {
    id: t
    property bool err: false
    z: 50
    x: parent.width - width - Ui.padX
    y: parent.height - height - 52 * Ui.f + shift
    property real shift: 10 * Ui.f
    width: Math.min(label.implicitWidth, parent.width * 0.6 - 32 * Ui.f) + 32 * Ui.f
    height: label.height + 20 * Ui.f
    color: err ? Ui.c.statusDangerBg : Ui.c.surfaceCard
    border.width: 1
    border.color: Ui.c.borderSubtle
    opacity: 0
    visible: opacity > 0
    Txt {
        id: label
        x: 16 * Ui.f
        width: Math.min(implicitWidth, t.parent.width * 0.6 - 32 * Ui.f)
        anchors.verticalCenter: parent.verticalCenter
        font.pixelSize: 16 * Ui.f
        wrapMode: Text.Wrap
        elide: Text.ElideNone
    }
    function show(msg, isErr) {
        label.text = msg
        err = isErr
        inAnim.restart()
        timer.interval = Math.max(isErr ? 5000 : 2800, msg.length * 55)
        timer.restart()
    }
    function hide() { timer.stop(); outAnim.restart() }
    Timer { id: timer; onTriggered: outAnim.restart() }
    ParallelAnimation {
        id: inAnim
        NumberAnimation { target: t; property: "opacity"; to: 1; duration: 250 }
        NumberAnimation { target: t; property: "shift"; to: 0; duration: 250 }
    }
    ParallelAnimation {
        id: outAnim
        NumberAnimation { target: t; property: "opacity"; to: 0; duration: 250 }
        NumberAnimation { target: t; property: "shift"; to: 10 * Ui.f; duration: 250 }
    }
}
