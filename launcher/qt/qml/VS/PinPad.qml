// SPDX-License-Identifier: GPL-3.0-or-later
// Ziffernblock fuer 4-8-stellige PINs: Gamepad/Fernbedienung/Tastatur/Maus + Cooldown-Anzeige.
// Tasten bleiben auch waehrend Cooldown/Sperre navigierbar (nur gedimmt), damit der Fokus nicht gefangen wird.
import QtQuick

Column {
    id: pad
    property string value: ""
    property int minLength: 4
    property int maxLength: 8
    property bool busy: false
    property int cooldown: 0
    property bool locked: false
    property string errorText: ""
    property string submitLabel: Ui.t("common.ok")
    property real keyW: 92 * Ui.f
    property real keyH: 48 * Ui.f
    property real keyGap: 8 * Ui.f
    readonly property bool disabled: busy || locked || cooldown > 0
    readonly property bool canSubmit: !disabled && value.length >= minLength && value.length <= maxLength
    readonly property real padWidth: 3 * keyW + 2 * keyGap

    signal submitted(string pin)

    spacing: 12 * Ui.f
    width: padWidth

    function clear() {
        value = ""
        errorText = ""
    }
    function reset() {
        value = ""
        errorText = ""
        cooldown = 0
        locked = false
        busy = false
    }
    function setCooldown(seconds) {
        cooldown = Math.max(0, Math.ceil(Number(seconds) || 0))
    }
    function appendDigit(d) {
        if (disabled || value.length >= maxLength) return
        errorText = ""
        value += String(d)
    }
    function backspace() {
        if (disabled || value.length === 0) return
        errorText = ""
        value = value.slice(0, -1)
    }
    function submit() {
        if (disabled) return
        if (value.length < minLength || value.length > maxLength) {
            errorText = Ui.t("account.err.pinFormat")
            vs.playSound("error")
            return
        }
        submitted(value)
    }
    function handleKey(e) {
        if (e.text && /^[0-9]$/.test(e.text)) {
            if (!disabled) {
                appendDigit(e.text)
                vs.playSound("navigate")
            }
            return true
        }
        if (e.key === Qt.Key_Delete) {
            if (value.length > 0 && !disabled) {
                backspace()
                vs.playSound("back")
            }
            return true
        }
        if (e.key === Qt.Key_Backspace && value.length > 0) {
            if (!disabled) {
                backspace()
                vs.playSound("back")
            }
            return true
        }
        return false
    }
    function handlePad(k) {
        if (k === "x") {
            if (value.length > 0 && !disabled) {
                backspace()
                vs.playSound("back")
            }
            return true
        }
        if (k === "start") {
            submit()
            return true
        }
        return false
    }
    function firstKey() {
        return Nav.collect(padGrid)[0] || null
    }

    Timer {
        interval: 1000
        repeat: true
        running: pad.cooldown > 0
        onTriggered: {
            if (pad.cooldown > 1) pad.cooldown -= 1
            else pad.cooldown = 0
        }
    }

    // PIN-Punktanzeige
    Rectangle {
        width: pad.padWidth
        height: 48 * Ui.f
        color: Ui.c.surfaceRaised
        border.width: 2
        border.color: (pad.errorText || pad.locked) ? Ui.c.statusDangerText
                    : pad.cooldown > 0 ? Ui.c.statusWarnBorder
                    : Ui.c.borderSubtle
        Row {
            anchors.centerIn: parent
            spacing: 12 * Ui.f
            Repeater {
                model: pad.maxLength
                Rectangle {
                    readonly property bool filled: index < pad.value.length
                    readonly property bool requiredSlot: index < pad.minLength
                    width: 14 * Ui.f
                    height: width
                    radius: width / 2
                    color: filled ? Ui.c.textPrimary : "transparent"
                    border.width: 2
                    border.color: filled ? Ui.c.textPrimary
                                : requiredSlot ? Ui.c.borderMuted
                                : Ui.c.borderSubtle
                }
            }
        }
    }

    // Status- & Cooldown-Bereich mit fester Hoehe (kein Layout-Springen)
    Item {
        width: pad.padWidth
        height: Math.max(36 * Ui.f, statusMsg.implicitHeight + 12 * Ui.f)
        Rectangle {
            anchors.fill: parent
            visible: pad.cooldown > 0
            color: Ui.c.statusWarnBg
            border.width: 1
            border.color: Ui.c.statusWarnBorder
        }
        Txt {
            id: statusMsg
            anchors.centerIn: parent
            width: parent.width - 16 * Ui.f
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.WordWrap
            elide: Text.ElideNone
            font.pixelSize: 14 * Ui.f
            color: pad.cooldown > 0 ? Ui.c.statusWarnText
                 : (pad.errorText || pad.locked) ? Ui.c.statusDangerText
                 : Ui.c.textDim
            text: pad.cooldown > 0 ? Ui.t("account.cooldown", { seconds: pad.cooldown })
                : pad.locked ? (pad.errorText || Ui.t("account.err.pinLocked"))
                : pad.errorText
        }
    }

    // 3x4 Tastenfeld
    Grid {
        id: padGrid
        columns: 3
        spacing: pad.keyGap
        Repeater {
            model: ["1", "2", "3", "4", "5", "6", "7", "8", "9"]
            Focusable {
                id: numBtn
                property bool pressFlash: true
                sound: pad.disabled ? "" : "navigate"
                width: pad.keyW
                height: pad.keyH
                opacity: pad.disabled ? 0.45 : 1
                onTriggered: if (!pad.disabled) pad.appendDigit(modelData)
                Rectangle {
                    anchors.fill: parent
                    color: numBtn.focused ? Ui.c.surfaceActive : Ui.c.surfaceCard
                    border.width: numBtn.focused ? 2 : 1
                    border.color: numBtn.focused ? Ui.c.borderFocus : Ui.c.borderSubtle
                }
                Txt {
                    anchors.centerIn: parent
                    text: modelData
                    font.pixelSize: 22 * Ui.f
                    color: Ui.c.textPrimary
                }
            }
        }
        Focusable {
            id: delBtn
            property bool pressFlash: true
            sound: (!pad.disabled && pad.value.length > 0) ? "back" : ""
            width: pad.keyW
            height: pad.keyH
            opacity: pad.disabled ? 0.45 : 1
            onTriggered: if (!pad.disabled) pad.backspace()
            Rectangle {
                anchors.fill: parent
                color: delBtn.focused ? Ui.c.surfaceActive : Ui.c.surfaceCard
                border.width: delBtn.focused ? 2 : 1
                border.color: delBtn.focused ? Ui.c.borderFocus : Ui.c.borderSubtle
            }
            Glyph {
                anchors.centerIn: parent
                width: 22 * Ui.f
                height: width
                name: "backspace"
                color: Ui.c.textPrimary
            }
        }
        Focusable {
            id: zeroBtn
            property bool pressFlash: true
            sound: pad.disabled ? "" : "navigate"
            width: pad.keyW
            height: pad.keyH
            opacity: pad.disabled ? 0.45 : 1
            onTriggered: if (!pad.disabled) pad.appendDigit("0")
            Rectangle {
                anchors.fill: parent
                color: zeroBtn.focused ? Ui.c.surfaceActive : Ui.c.surfaceCard
                border.width: zeroBtn.focused ? 2 : 1
                border.color: zeroBtn.focused ? Ui.c.borderFocus : Ui.c.borderSubtle
            }
            Txt {
                anchors.centerIn: parent
                text: "0"
                font.pixelSize: 22 * Ui.f
                color: Ui.c.textPrimary
            }
        }
        Focusable {
            id: okBtn
            property bool pressFlash: true
            sound: pad.canSubmit ? "select" : ""
            width: pad.keyW
            height: pad.keyH
            opacity: pad.disabled ? 0.45 : 1
            onTriggered: pad.submit()
            Rectangle {
                anchors.fill: parent
                color: pad.canSubmit ? Ui.c.statusOkBg : (okBtn.focused ? Ui.c.surfaceActive : Ui.c.surfaceCard)
                border.width: okBtn.focused ? 2 : 1
                border.color: okBtn.focused ? Ui.c.borderFocus : Ui.c.borderSubtle
            }
            Txt {
                anchors.centerIn: parent
                width: parent.width - 12 * Ui.f
                horizontalAlignment: Text.AlignHCenter
                fontSizeMode: Text.HorizontalFit
                minimumPixelSize: 11 * Ui.f
                text: pad.busy ? "…" : pad.submitLabel
                font.pixelSize: 16 * Ui.f
                color: Ui.c.textPrimary
            }
        }
    }
}
