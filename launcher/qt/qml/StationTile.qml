// SPDX-License-Identifier: GPL-3.0-or-later
// Sender-Kachel (Radio und Fernsehen): Logo, Name, Stern fuer Favoriten, Qualitaet
import QtQuick
import VS

Tile {
    id: st
    property string logo: ""
    property string name: ""
    property string fallbackIcon: "radio"
    property bool fav: false
    property bool playing: false
    property string quality: ""
    property color accent: Ui.c.accentRadio
    tileColor: playing ? accent : Ui.c.surfaceCard
    readonly property color fg: playing || !Ui.c.light ? (Ui.c.light ? "#ffffff" : Ui.c.textPrimary) : Ui.c.textPrimary

    Item {
        width: parent.width * 0.4; height: parent.height * 0.4
        x: (parent.width - width) / 2
        y: parent.height * 0.36 - height / 2
        Image {
            id: img
            anchors.fill: parent
            source: st.logo
            visible: status === Image.Ready
            fillMode: Image.PreserveAspectFit
            asynchronous: true
            sourceSize: Qt.size(Math.ceil(width * 1.5), Math.ceil(height * 1.5))
        }
        Glyph {
            visible: img.status !== Image.Ready
            anchors.centerIn: parent
            width: parent.width * 0.75; height: parent.height * 0.75
            name: st.fallbackIcon
            color: st.fg
            opacity: 0.7
        }
    }
    Txt {
        visible: st.quality !== ""
        x: parent.width * 0.07; y: parent.height * 0.07
        text: st.quality
        font.pixelSize: st.width * 0.0875
        color: Ui.c.light && !st.playing ? Ui.c.textDim : "#8cffffff"
    }
    Txt {
        visible: st.fav
        anchors.right: parent.right; anchors.rightMargin: parent.width * 0.07
        y: parent.height * 0.07
        text: "★"
        font.pixelSize: st.width * 0.1
        color: Ui.c.light && !st.playing ? Ui.c.textDim : "#a6ffffff"
    }
    Txt {
        x: parent.width * 0.07
        width: parent.width * 0.86
        anchors.bottom: parent.bottom; anchors.bottomMargin: parent.height * 0.06
        text: st.name
        font.pixelSize: st.width * 0.106
        color: st.fg
        wrapMode: Text.WordWrap
        maximumLineCount: 2
        lineHeight: 1.1
        elide: Text.ElideRight
    }
}
