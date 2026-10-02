// SPDX-License-Identifier: GPL-3.0-or-later
// Erklaerender Text in Einstellungen (<b> hervorgehoben)
import QtQuick
import VS

Txt {
    property string html: ""
    width: Ui.screenW * 0.4
    text: String(html).replace(/<b>/g, "<font color='" + Ui.c.textPrimary + "'>").replace(/<\/b>/g, "</font>")
    textFormat: Text.StyledText
    color: Ui.c.textDim
    font.pixelSize: 16 * Ui.f
    wrapMode: Text.Wrap
    elide: Text.ElideNone
    lineHeight: 1.5
}
