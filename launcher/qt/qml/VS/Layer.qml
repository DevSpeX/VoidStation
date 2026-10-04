// SPDX-License-Identifier: GPL-3.0-or-later
// Unterseite (Radio, Fernsehen, AppCenter, Einstellungen …): Kopfzeile mit Zurueck + Titel,
// rechts was gerade laeuft, darunter optional eine Leiste, dann die Buehne
import QtQuick

Rectangle {
    id: ly
    property string scope: ""
    property bool open: false
    property string title: ""
    property Item track: null
    property var hints: []
    property alias headRight: rightBox.data
    property alias bar: barBox.data
    property alias stage: stageBox
    property alias backButton: backBtn
    property bool hasBar: barBox.children.length > 0
    property bool showBar: true
    default property alias content: stageBox.data
    signal opened()
    signal closed()
    color: Ui.c.bgMain
    visible: false
    opacity: 0
    transform: Translate { id: sh; x: 0 }

    function show() {
        if (open && visible) return
        open = true
        visible = true
        hideAnim.stop()
        sh.x = Ui.screenW * 0.04
        showAnim.start()
        opened()
    }
    function hide(done) {
        if (!open) return
        open = false
        showAnim.stop()
        hideAnim.done = done || null
        hideAnim.start()
    }
    ParallelAnimation {
        id: showAnim
        NumberAnimation { target: ly; property: "opacity"; to: 1; duration: 300; easing.type: Easing.OutQuint }
        NumberAnimation { target: sh; property: "x"; to: 0; duration: 300; easing.type: Easing.OutQuint }
    }
    SequentialAnimation {
        id: hideAnim
        property var done: null
        ParallelAnimation {
            NumberAnimation { target: ly; property: "opacity"; to: 0; duration: 200; easing.type: Easing.OutQuad }
            NumberAnimation { target: sh; property: "x"; to: Ui.screenW * 0.04; duration: 200; easing.type: Easing.OutQuad }
        }
        ScriptAction { script: { ly.visible = false; ly.closed(); if (hideAnim.done) hideAnim.done() } }
    }
    MouseArea { anchors.fill: parent; acceptedButtons: Qt.AllButtons; onWheel: function (w) { w.accepted = true } }  // nichts dahinter anklickbar

    Item {
        id: header
        x: Ui.padX
        width: parent.width - 2 * Ui.padX
        height: 34 * Ui.f + Math.max(htitle.height, rightRow.height) + 20 * Ui.f
        Row {
            id: htitle
            anchors.bottom: parent.bottom
            anchors.bottomMargin: 20 * Ui.f
            spacing: 18 * Ui.f
            RoundBtn {
                id: backBtn
                iconName: "chevleft"
                anchors.verticalCenter: parent.verticalCenter
                onTriggered: Ui.app.back()
            }
            Txt {
                id: h1
                text: ly.title
                font.pixelSize: Math.min(52 * Ui.f, Ui.screenW * 0.07)
                font.weight: Font.Light
                anchors.verticalCenter: parent.verticalCenter
                width: Math.min(implicitWidth, header.width - backBtn.width - 18 * Ui.f - rightRow.width - 24 * Ui.f)
                fontSizeMode: Text.HorizontalFit
                minimumPixelSize: font.pixelSize * 0.6
            }
        }
        Row {
            id: rightRow
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            anchors.bottomMargin: 20 * Ui.f
            spacing: 2 * Ui.screenW * 0.01
            ScrollInd { track: ly.track; anchors.bottom: parent.bottom; anchors.bottomMargin: 4 * Ui.f }
            Item { id: rightBox; width: childrenRect.width; height: childrenRect.height; anchors.bottom: parent.bottom }
        }
    }
    Flow {
        id: barBox
        visible: children.length > 0 && ly.showBar
        anchors.top: header.bottom
        x: Ui.padX
        width: parent.width - 2 * Ui.padX
        spacing: 10 * Ui.f
        height: visible ? implicitHeight + 18 * Ui.f : 0
    }
    Item {
        id: stageBox
        anchors.top: barBox.visible ? barBox.bottom : header.bottom
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.bottomMargin: Ui.hintH
    }
}
