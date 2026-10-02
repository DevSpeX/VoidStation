// SPDX-License-Identifier: GPL-3.0-or-later
// − [Balken] + 45 %
import QtQuick

Row {
    id: v
    spacing: 8 * Ui.f
    property real meterW: Math.min(120 * Ui.f, Ui.screenW * 0.2)
    property bool showMute: false
    Pill { text: "−"; onTriggered: Ui.app.volume("down"); anchors.verticalCenter: parent.verticalCenter }
    Rectangle {
        width: v.meterW; height: 5 * Ui.f; color: Ui.c.surfaceRaised
        anchors.verticalCenter: parent.verticalCenter
        Rectangle { height: parent.height; color: Ui.c.textPrimary; width: parent.width * Math.min(100, Ui.app ? Ui.app.volLevel : 0) / 100
            Behavior on width { NumberAnimation { duration: 200 } } }
    }
    Pill { text: "+"; onTriggered: Ui.app.volume("up"); anchors.verticalCenter: parent.verticalCenter }
    Txt { text: Ui.app ? Ui.app.volText : ""; color: Ui.c.textDim; font.pixelSize: 14 * Ui.f; anchors.verticalCenter: parent.verticalCenter }
    Pill { visible: v.showMute; text: Ui.t("settings.mute"); onTriggered: Ui.app.volume("mute"); anchors.verticalCenter: parent.verticalCenter }
}
