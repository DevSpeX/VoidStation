// SPDX-License-Identifier: GPL-3.0-or-later
// Dialog als Band ueber die ganze Breite: Titel, Text (blaettert, wenn er zu lang ist), Knoepfe
import QtQuick
import VS

Rectangle {
    id: d
    property string scope: "adlg"
    property bool open: false
    property string title: ""
    property string text: ""
    property var buttons: []                  // [[Text, Funktion, "danger"], …]
    property int focusIndex: 0
    readonly property bool fits: body.contentHeight <= body.height + 2
    signal closedByUser()
    z: 30
    color: Ui.c.surfaceOverlay
    visible: open
    MouseArea { anchors.fill: parent; acceptedButtons: Qt.AllButtons; onClicked: d.close(); onWheel: function (w) { body.flickBy(w.angleDelta.y) } }

    function openDlg(t, txt, btns, fi) {
        title = t; text = txt || ""; buttons = btns || [[Ui.t("common.ok")]]
        focusIndex = fi === undefined ? 0 : fi
        body.contentY = 0
        open = true
        app.updateLayer()
        Qt.callLater(function () { var b = Nav.collect(btnRow); if (b.length) app.setFocus(b[Math.min(d.focusIndex, b.length - 1)], true) })
    }
    function close() {
        if (!open) return
        open = false
        app.updateLayer()
        var m = Nav.remembered(app.layerName, app.layerRoot)
        if (m) app.setFocus(m, true)
        else { var it = Nav.collect(app.layerRoot); if (it.length) app.setFocus(it[0], true) }
    }
    function scrollText(dir) { body.flickBy(-dir * body.height * 0.6) }

    Rectangle {
        id: band
        width: parent.width
        anchors.verticalCenter: parent.verticalCenter
        height: Math.min(col.implicitHeight + 72 * Ui.f, d.height - 2 * Math.max(60, Ui.hintH))
        color: Ui.c.surfaceDialog
        MouseArea { anchors.fill: parent; onWheel: function (w) { d.scrollText(w.angleDelta.y < 0 ? 1 : -1) } }
        Rectangle { width: parent.width; height: 1; color: Ui.c.divider }
        Rectangle { width: parent.width; height: 1; color: Ui.c.divider; anchors.bottom: parent.bottom }
        Column {
            id: col
            x: Ui.padX
            y: 36 * Ui.f
            width: parent.width - 2 * Ui.padX
            spacing: 0
            Txt { width: parent.width; text: d.title; font.pixelSize: 34 * Ui.f; font.weight: Font.Light; height: implicitHeight + 8 }
            Flickable {
                id: body
                width: parent.width
                height: Math.min(contentHeight, band.parent.height - 2 * Math.max(60, Ui.hintH) - 72 * Ui.f - 34 * Ui.f * 1.4 - 8 - btnRow.height - 24 * Ui.f)
                contentHeight: bodyText.implicitHeight
                clip: true
                interactive: false
                visible: d.text !== ""
                function flickBy(dy) { contentY = Math.max(0, Math.min(contentHeight - height, contentY + dy)) }
                Behavior on contentY { NumberAnimation { duration: 200 } }
                Txt {
                    id: bodyText
                    width: body.width - 10 * Ui.f
                    text: d.text
                    wrapMode: Text.Wrap
                    elide: Text.ElideNone
                    color: Ui.c.textDim
                    font.pixelSize: 16 * Ui.f
                    lineHeight: 1.25
                }
            }
            Item { width: 1; height: d.text !== "" ? 24 * Ui.f : 0 }
            Flow {
                id: btnRow
                width: parent.width
                spacing: 12 * Ui.f
                Repeater {
                    model: d.buttons
                    Btn {
                        text: modelData[0]
                        danger: modelData[2] === "danger"
                        onTriggered: { var fn = modelData[1]; d.close(); if (fn) fn() }
                    }
                }
            }
        }
    }
}
