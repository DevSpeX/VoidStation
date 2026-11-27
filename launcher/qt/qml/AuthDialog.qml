// SPDX-License-Identifier: GPL-3.0-or-later
// Authentifizierungs-Dialog fuer Profilwechsel und Bestaetigung aktueller Zugangsdaten (PIN oder Passwort).
import QtQuick
import VS

Rectangle {
    id: ad
    property string scope: "authDlg"
    property bool open: false
    property var account: null
    property string mode: "pin"                  // pin | password
    property string dialogTitle: ""
    property bool busy: false
    property int pwCooldown: 0
    property string pwError: ""
    property var onSuccessCb: null
    property var customSubmitCb: null
    property bool overrideMode: false
    property string overrideReason: ""
    property string overrideTileId: ""
    property string overrideTileName: ""
    property string overrideAction: "allow_once"   // allow_once | add_minutes
    property int overrideMinutes: 15
    property bool allowSwitchProfile: false

    readonly property bool hasPin: !!(account && account.has_pin)
    readonly property bool hasPassword: !!(account && account.has_password)
    readonly property bool isTimeBlock: overrideMode && (overrideReason === "daily_limit" || overrideReason === "bedtime")

    z: 30
    color: Ui.c.surfaceOverlay
    visible: open

    MouseArea {
        anchors.fill: parent
        acceptedButtons: Qt.AllButtons
        onClicked: ad.handleBack()
        onWheel: function (w) { w.accepted = true }
    }

    function openFor(acc, opts) {
        opts = opts || {}
        overrideMode = false
        overrideReason = ""
        overrideTileId = ""
        overrideTileName = ""
        overrideAction = "allow_once"
        overrideMinutes = 15
        allowSwitchProfile = false
        account = acc || null
        dialogTitle = opts.title || ""
        onSuccessCb = opts.onSuccess || null
        customSubmitCb = opts.customSubmit || null
        busy = false
        pwCooldown = 0
        pwError = ""
        pwField.value = ""
        pwField.password = true
        pinPad.reset()
        mode = (acc && acc.has_pin) ? "pin" : "password"
        open = true
        app.updateLayer()
        focusActiveMode()
    }

    function findParentAdmin() {
        var list = app.accountsList || []
        var childPid = ""
        if (app.session && !app.session.is_guest) {
            for (var i = 0; i < list.length; i++) {
                if (list[i].id === app.session.account_id && list[i].parent_id) {
                    childPid = list[i].parent_id
                    break
                }
            }
        }
        var firstAdmin = null
        var firstAuthAdmin = null
        for (var j = 0; j < list.length; j++) {
            var a = list[j]
            if (a.role !== "admin" || a.active === false) continue
            if (!firstAdmin) firstAdmin = a
            if (a.auth_configured && !firstAuthAdmin) firstAuthAdmin = a
            if (childPid && a.id === childPid && a.auth_configured) return a
        }
        return firstAuthAdmin || firstAdmin
    }

    function openForOverride(opts) {
        opts = opts || {}
        var openWith = function (adminAcc) {
            overrideMode = true
            overrideReason = opts.reason || "tile_blocked"
            overrideTileId = opts.tileId || ""
            overrideTileName = opts.tileName || ""
            overrideAction = (overrideReason === "daily_limit" || overrideReason === "bedtime") ? "add_minutes" : "allow_once"
            overrideMinutes = 15
            allowSwitchProfile = opts.allowSwitchProfile !== false
            account = adminAcc || null
            dialogTitle = Ui.t("account.parentPin")
            onSuccessCb = opts.onSuccess || null
            customSubmitCb = null
            busy = false
            pwCooldown = 0
            pwError = (!adminAcc || (!adminAcc.has_pin && !adminAcc.has_password)) ? Ui.t("account.err.parentAuthRequired") : ""
            pwField.value = ""
            pwField.password = true
            pinPad.reset()
            mode = (adminAcc && adminAcc.has_pin) ? "pin" : "password"
            open = true
            app.updateLayer()
            focusActiveMode()
        }
        var adm = findParentAdmin()
        if (adm) {
            openWith(adm)
            return
        }
        Api.get("/api/accounts", function (r) {
            if (r && r.accounts) {
                app.accountsList = r.accounts
                app.accountsCount = r.accounts.length
            }
            openWith(findParentAdmin())
        }, function () { openWith(null) })
    }

    function close() {
        if (!open) return
        open = false
        busy = false
        pwCooldown = 0
        pinPad.reset()
        app.updateLayer()
        var m = Nav.remembered(app.layerName, app.layerRoot)
        if (m) app.setFocus(m, true)
        else {
            var it = Nav.collect(app.layerRoot)
            if (it.length) app.setFocus(it[0], true)
        }
    }

    function handleBack() {
        if (busy) return true
        close()
        return true
    }

    function focusActiveMode() {
        Qt.callLater(function () {
            if (!ad.open) return
            if (ad.mode === "pin") {
                var fk = pinPad.firstKey()
                if (fk && !pinPad.locked) app.setFocus(fk, true)
                else if (switchModeBtn.visible) app.setFocus(switchModeBtn, true)
                else app.setFocus(cancelBtn, true)
            } else {
                app.setFocus(pwField, true)
            }
        })
    }

    function toggleMode() {
        if (busy || !hasPin || !hasPassword) return
        mode = mode === "pin" ? "password" : "pin"
        pwError = ""
        pinPad.errorText = ""
        focusActiveMode()
    }

    function handleError(err, data, status) {
        var retry = data && data.retry_after ? Number(data.retry_after) : 0
        var hardLocked = status === 423 || err === "account.err.pinLocked" || !!(data && data.hard_locked)
        if (mode === "pin") {
            pinPad.busy = false
            pinPad.value = ""
            if (hardLocked) {
                pinPad.locked = true
                pinPad.errorText = Ui.t("account.err.pinLocked")
                vs.playSound("error")
                if (hasPassword && switchModeBtn.visible) Qt.callLater(function () { app.setFocus(switchModeBtn, true) })
                return
            }
            if (status === 429 || err === "account.cooldown" || retry > 0) {
                pinPad.setCooldown(retry > 0 ? retry : 5)
                pinPad.errorText = ""
                vs.playSound("error")
                return
            }
            pinPad.errorText = Ui.t(err, null, Ui.t("account.err.invalid"))
            vs.playSound("error")
        } else {
            pwField.value = ""
            if (status === 429 || err === "account.cooldown" || retry > 0) {
                pwCooldown = Math.max(1, Math.ceil(retry > 0 ? retry : 5))
                pwError = ""
                vs.playSound("error")
                return
            }
            pwError = Ui.t(err, null, Ui.t("account.err.invalid"))
            vs.playSound("error")
        }
    }

    function finishSuccess(res) {
        var cb = onSuccessCb
        close()
        if (cb) cb(res)
    }

    function submitSecret(factor, secret) {
        if (busy || !account) return
        if (factor === "password") {
            if (pwCooldown > 0) return
            if (!secret || !secret.length) {
                pwError = Ui.t("account.err.pwFormat")
                vs.playSound("error")
                return
            }
        }
        busy = true
        if (factor === "pin") pinPad.busy = true
        pwError = ""
        if (customSubmitCb) {
            customSubmitCb(factor, secret, function (ok, res, err, data, status) {
                busy = false
                pinPad.busy = false
                if (ok) finishSuccess(res)
                else handleError(err, data, status)
            })
            return
        }
        if (overrideMode) {
            var ovBody = {
                admin_id: account.id,
                factor: factor,
                action: overrideAction,
                tile_id: overrideTileId,
                minutes: overrideMinutes
            }
            if (factor === "pin") ovBody.pin = secret
            else ovBody.password = secret
            Api.post("/api/accounts/parental/override", ovBody, function (res) {
                busy = false
                pinPad.busy = false
                if (res && res.parental) app.parentalStatus = res.parental
                finishSuccess(res)
            }, function (err, data, status) {
                busy = false
                handleError(err, data, status)
            })
            return
        }
        var body = { account_id: account.id }
        if (factor === "pin") body.pin = secret
        else body.password = secret
        Api.post("/api/session/switch", body, function (res) {
            busy = false
            pinPad.busy = false
            app.applySessionSwitch(res)
            finishSuccess(res)
        }, function (err, data, status) {
            busy = false
            handleError(err, data, status)
        })
    }

    function keyFilter(e) {
        if (mode === "pin") return pinPad.handleKey(e)
        return false
    }

    function padFilter(k) {
        if (mode === "pin") return pinPad.handlePad(k)
        return false
    }

    Timer {
        interval: 1000
        repeat: true
        running: ad.open && ad.pwCooldown > 0
        onTriggered: {
            if (ad.pwCooldown > 1) ad.pwCooldown -= 1
            else ad.pwCooldown = 0
        }
    }

    Rectangle {
        id: card
        width: Math.min(540 * Ui.f, ad.width - 2 * Ui.padX)
        height: col.implicitHeight + 56 * Ui.f
        anchors.centerIn: parent
        color: Ui.c.surfaceDialog
        border.width: 1
        border.color: Ui.c.borderSubtle

        MouseArea { anchors.fill: parent; acceptedButtons: Qt.AllButtons }

        Column {
            id: col
            x: 32 * Ui.f
            y: 28 * Ui.f
            width: parent.width - 64 * Ui.f
            spacing: 16 * Ui.f

            // Profilkopf
            Row {
                width: parent.width
                spacing: 14 * Ui.f
                Rectangle {
                    width: 48 * Ui.f
                    height: width
                    radius: width / 2
                    color: ad.account && ad.account.color ? ad.account.color : Ui.c.tileDefaultC
                    anchors.verticalCenter: parent.verticalCenter
                    Glyph {
                        anchors.centerIn: parent
                        width: parent.width * 0.52
                        height: width
                        name: ad.account && ad.account.avatar ? ad.account.avatar : "user"
                        color: Ui.c.tileText
                    }
                }
                Column {
                    width: parent.width - 62 * Ui.f
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: 2 * Ui.f
                    Txt {
                        width: parent.width
                        text: ad.account ? ad.account.display_name : ""
                        font.pixelSize: 22 * Ui.f
                        font.weight: Font.Light
                    }
                    Txt {
                        width: parent.width
                        text: ad.account ? Ui.t("account.role." + ad.account.role) : ""
                        font.pixelSize: 14 * Ui.f
                        color: Ui.c.textDim
                    }
                }
            }

            Txt {
                width: parent.width
                text: ad.dialogTitle || Ui.t(ad.mode === "pin" ? "account.enterPin" : "account.enterPassword")
                font.pixelSize: 18 * Ui.f
                color: Ui.c.textSecondary
            }

            // Kindersicherungs-Hinweis & Override-Auswahl
            Rectangle {
                visible: ad.overrideMode
                width: parent.width
                height: ovCol.implicitHeight + 16 * Ui.f
                color: Ui.c.statusWarnBg
                border.width: 1
                border.color: Ui.c.statusWarnBorder

                Column {
                    id: ovCol
                    x: 12 * Ui.f
                    y: 8 * Ui.f
                    width: parent.width - 24 * Ui.f
                    spacing: 8 * Ui.f
                    Txt {
                        width: parent.width
                        wrapMode: Text.WordWrap
                        elide: Text.ElideNone
                        font.pixelSize: 14 * Ui.f
                        color: Ui.c.statusWarnText
                        text: Ui.t("parental.reason." + ad.overrideReason, { name: ad.overrideTileName || ad.overrideTileId }, Ui.t("account.err.blocked"))
                    }
                    Row {
                        visible: ad.isTimeBlock
                        spacing: 8 * Ui.f
                        Repeater {
                            model: [15, 30, 60]
                            Pill {
                                text: Ui.t("parental.extraMinutes", { min: modelData })
                                on: ad.overrideMinutes === modelData
                                sound: "toggle"
                                onTriggered: ad.overrideMinutes = modelData
                            }
                        }
                    }
                    Txt {
                        visible: !ad.isTimeBlock
                        width: parent.width
                        font.pixelSize: 13 * Ui.f
                        color: Ui.c.textSecondary
                        text: Ui.t("parental.allowOnce")
                    }
                }
            }

            // PIN-Ansicht
            PinPad {
                id: pinPad
                visible: ad.mode === "pin"
                anchors.horizontalCenter: parent.horizontalCenter
                submitLabel: Ui.t("common.ok")
                onSubmitted: function (pin) { ad.submitSecret("pin", pin) }
            }

            // Passwort-Ansicht
            Column {
                id: pwBox
                visible: ad.mode === "password"
                width: parent.width
                spacing: 12 * Ui.f

                Row {
                    width: parent.width
                    spacing: 10 * Ui.f
                    Field {
                        id: pwField
                        width: parent.width - showPwPill.width - 10 * Ui.f
                        password: true
                        revealable: true
                        placeholder: Ui.t("account.enterPassword")
                        onSubmitted: function (txt) { ad.submitSecret("password", txt) }
                    }
                    Pill {
                        id: showPwPill
                        text: Ui.t(pwField.password ? "settings.pwShow" : "settings.pwHide")
                        on: !pwField.password
                        sound: "toggle"
                        toggleFlip: true
                        onTriggered: pwField.password = !pwField.password
                    }
                }

                Item {
                    width: parent.width
                    height: (ad.pwCooldown > 0 || ad.pwError !== "") ? Math.max(34 * Ui.f, pwMsg.implicitHeight + 10 * Ui.f) : 0
                    visible: height > 0
                    Rectangle {
                        anchors.fill: parent
                        visible: ad.pwCooldown > 0
                        color: Ui.c.statusWarnBg
                        border.width: 1
                        border.color: Ui.c.statusWarnBorder
                    }
                    Txt {
                        id: pwMsg
                        anchors.centerIn: parent
                        width: parent.width - 16 * Ui.f
                        wrapMode: Text.WordWrap
                        elide: Text.ElideNone
                        font.pixelSize: 14 * Ui.f
                        color: ad.pwCooldown > 0 ? Ui.c.statusWarnText : Ui.c.statusDangerText
                        text: ad.pwCooldown > 0 ? Ui.t("account.cooldown", { seconds: ad.pwCooldown }) : ad.pwError
                    }
                }

                Btn {
                    id: pwOkBtn
                    text: ad.busy ? "…" : Ui.t("common.ok")
                    on: !ad.busy && ad.pwCooldown === 0 && pwField.value.length > 0
                    onTriggered: if (!ad.busy && ad.pwCooldown === 0) ad.submitSecret("password", pwField.value)
                }
            }

            // Aktionszeile
            Flow {
                width: parent.width
                spacing: 10 * Ui.f
                Btn {
                    id: switchModeBtn
                    visible: ad.hasPin && ad.hasPassword
                    text: Ui.t(ad.mode === "pin" ? "account.usePassword" : "account.usePin")
                    onTriggered: ad.toggleMode()
                }
                Btn {
                    id: switchProfileBtn
                    visible: ad.overrideMode && ad.allowSwitchProfile
                    text: Ui.t("account.switch")
                    onTriggered: {
                        ad.close()
                        app.openAccountPicker()
                    }
                }
                Btn {
                    id: cancelBtn
                    text: Ui.t("common.cancel")
                    sound: "back"
                    onTriggered: ad.handleBack()
                }
            }
        }
    }
}
