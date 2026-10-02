// SPDX-License-Identifier: GPL-3.0-or-later
// Hinweiszeile unten: welche Taste was tut; rechts der gelbe Update-Hinweis
import QtQuick
import VS

Item {
    id: hb
    x: Ui.padX
    width: parent.width - 2 * Ui.padX
    height: Math.max(flow.height, note.visible ? note.height : 0)
    y: parent.height - height - 14 * Ui.f
    z: 31
    property var list: hintsFor(app.layerName)
    readonly property bool noteOn: !!app.updInfo && ["home", "radio", "tv", "apps", "settings"].indexOf(app.layerName) >= 0

    function b(s) {           // <b>…</b> wie im Web: halbfett in der Zweitfarbe
        return String(s).replace(/<b>(.*?)<\/b>/g, "<b><font color='" + Ui.c.textSecondary + "'>$1</font></b>")
    }
    function hintsFor(l) {
        var T = Ui.t, h
        Nav.serial
        if (l === "home") h = [T("hint.open"), T("hint.close"), T("hint.home")]
        else if (l === "radio") h = [T("hint.play"), T("hint.fav"), T("hint.volume"), T("hint.back")]
        else if (l === "settings") h = [settings.cat ? T("hint.select") : T("hint.open"), T("hint.back")]
        else if (l === "roms") h = [T("hint.romLaunch"), T("hint.back")]
        else if (l === "tv") h = [T("hint.tvOn"), T("hint.fav"), T("hint.homeShort"), T("hint.back")]
        else if (l === "apps") h = [Nav.current && Nav.current.isCat ? T("hint.appCat") : T("hint.appInstall"), T("hint.appCats"), T("hint.back")]
        else if (l === "adlg") h = (adlg.fits ? [] : [T("hint.scrollText")]).concat([T("hint.cancel")])
        else if (l === "dialog") h = [T("hint.cancel")]
        else if (l === "osk") h = [T("hint.select"), T("osk.space"), T("osk.backspace"), T("common.cancel")]
        else h = [T("hint.back")]
        var tr = app.curTrack()
        if (tr && tr.scrollable) h.splice(h.length - (l === "home" ? 0 : 1), 0, T("hint.pages"))
        return h
    }
    Flow {
        id: flow
        width: hb.width - (hb.noteOn ? note.width + 24 * Ui.f : 0)
        anchors.bottom: parent.bottom
        spacing: 24 * Ui.f
        Repeater {
            model: hb.list
            Txt {
                text: hb.b(modelData)
                textFormat: Text.StyledText
                color: Ui.c.textFaint
                font.pixelSize: 14 * Ui.f
                elide: Text.ElideNone
            }
        }
    }
    Rectangle {
        id: note
        visible: hb.noteOn
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        width: nrow.width + 24 * Ui.f
        height: nrow.height + 10 * Ui.f
        color: Ui.c.statusWarnBg
        border.width: 1
        border.color: Ui.c.statusWarnBorder
        Row {
            id: nrow
            anchors.centerIn: parent
            spacing: 9 * Ui.f
            Glyph { name: "updwarn"; width: 18 * Ui.f; height: width; anchors.verticalCenter: parent.verticalCenter }
            Txt { text: app.updInfo ? app.updNoteText(app.updInfo) : ""; color: Ui.c.statusWarnText; font.weight: Font.DemiBold; font.pixelSize: 14 * Ui.f
                  anchors.verticalCenter: parent.verticalCenter; elide: Text.ElideNone }
            Txt { text: Ui.t("upd.noteKey"); color: Ui.c.textSecondary; font.pixelSize: 14 * Ui.f; anchors.verticalCenter: parent.verticalCenter; elide: Text.ElideNone }
        }
        MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: app.openUpdate() }
    }
}
