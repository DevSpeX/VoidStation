// SPDX-License-Identifier: GPL-3.0-or-later
// Blaetter-Anzeige oben rechts: Pfeile + ein Punkt je Gruppe
import QtQuick

Row {
    id: si
    property Item track
    visible: !!track && track.scrollable
    spacing: 8 * Ui.f
    property var groups: track && Nav.serial >= 0 ? track.groupList() : []
    property Item cur: Nav.current && track ? track.groupOf(Nav.current) : null
    RoundBtn {
        navigable: false
        size: 34 * Ui.f; iconName: "chevleft"
        off: !si.track || si.track.contentX < 2
        anchors.verticalCenter: parent.verticalCenter
        onTriggered: Ui.app.jumpGroup(-1)
    }
    Row {
        spacing: 6 * Ui.f
        anchors.verticalCenter: parent.verticalCenter
        visible: si.groups.length > 1 && si.groups.length <= 12
        Repeater {
            model: si.groups.length
            Rectangle {
                width: 7 * Ui.f; height: width; radius: width / 2
                color: si.groups[index] === si.cur ? Ui.c.textPrimary : Ui.c.borderMuted
                scale: si.groups[index] === si.cur ? 1.3 : 1
                Behavior on scale { NumberAnimation { duration: 200 } }
            }
        }
    }
    RoundBtn {
        navigable: false
        size: 34 * Ui.f; iconName: "chevright"
        off: !si.track || si.track.contentX > si.track.maxX - 2
        anchors.verticalCenter: parent.verticalCenter
        onTriggered: Ui.app.jumpGroup(1)
    }
}
