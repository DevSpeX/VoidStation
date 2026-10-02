// SPDX-License-Identifier: GPL-3.0-or-later
import QtQuick

Text {
    color: Ui.c.textPrimary
    font.family: Ui.font
    font.pixelSize: 15 * Ui.f
    elide: Text.ElideRight
    textFormat: Text.PlainText
    renderType: Text.QtRendering
}
