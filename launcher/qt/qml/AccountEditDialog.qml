// SPDX-License-Identifier: GPL-3.0-or-later
// Dialog zum Anlegen und Bearbeiten von Benutzerkonten inkl. PIN/Passwort, Avatar, Farbe und Loeschen.
import QtQuick
import VS

Rectangle {
    id: ed
    property string scope: "acctEdit"
    property bool open: false
    property var account: null                    // null = neues Konto erstellen
    property string subView: "form"               // form | pin | password | delete
    property bool busy: false
    property var onSavedCb: null

    // Formularzustand
    property string editRole: "standard"
    property string editParentId: ""
    property string editAvatar: "user"
    property string editColor: "#2d4a6b"
    property bool editAutoLogin: false
    property string pendingPin: ""                // nur beim Erstellen vorgemerkt
    property string pendingPassword: ""           // nur beim Erstellen vorgemerkt
    property var pinTargetAccount: null

    readonly property bool isNew: !account
    readonly property bool isAdmin: !!(app.session && app.session.role === "admin" && !app.session.is_guest)
    readonly property var avatarChoices: ["user", "star", "gamepad", "music", "tv", "smile"]
    readonly property var colorChoices: ["#2d4a6b", "#2f6d4f", "#553a6e", "#74461f", "#6e2b3c", "#2b5b66"]
    readonly property var adminAccounts: (app.accountsList || []).filter(function (a) {
        return a.role === "admin" && a.active !== false && (!ed.account || a.id !== ed.account.id)
    })
    readonly property var unprotectedNonChildAccounts: (app.accountsList || []).filter(function (a) {
        return a.active !== false && a.role !== "child" && !a.has_pin && !a.has_password
            && (!ed.account || a.id !== ed.account.id)
    })
    readonly property var selectedParentAccount: {
        var admins = adminAccounts
        if (!admins.length) return null
        for (var i = 0; i < admins.length; i++)
            if (admins[i].id === editParentId) return admins[i]
        return admins[0]
    }
    readonly property bool childNeedsParentAuth: ed.isAdmin && ed.editRole === "child"
        && !!selectedParentAccount && !selectedParentAccount.has_pin && !selectedParentAccount.has_password

    z: 29
    color: Ui.c.surfaceOverlay
    visible: open

    MouseArea {
        anchors.fill: parent
        acceptedButtons: Qt.AllButtons
        onClicked: ed.handleBack()
        onWheel: function (w) { w.accepted = true }
    }

    function openFor(acc, onSaved) {
        account = acc || null
        onSavedCb = onSaved || null
        subView = "form"
        busy = false
        pinTargetAccount = null
        pendingPin = ""
        pendingPassword = ""
        nameField.value = acc ? (acc.display_name || "") : ""
        editRole = acc ? (acc.role || "standard") : "standard"
        editParentId = acc && acc.parent_id ? acc.parent_id : (adminAccounts.length ? adminAccounts[0].id : "")
        editAvatar = acc && acc.avatar ? acc.avatar : "user"
        editColor = acc && acc.color ? acc.color : "#2d4a6b"
        editAutoLogin = acc ? !!acc.auto_login : false
        pwInput.value = ""
        pwInput.password = true
        editPinPad.reset()
        formScroll.contentY = 0
        open = true
        app.updateLayer()
        focusView()
    }

    function close() {
        if (!open) return
        open = false
        busy = false
        pinTargetAccount = null
        subView = "form"
        editPinPad.reset()
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
        if (subView !== "form") {
            pinTargetAccount = null
            subView = "form"
            focusView()
            return true
        }
        close()
        return true
    }

    function startPinForAccount(acc) {
        if (!acc) return
        pinTargetAccount = acc
        editPinPad.reset()
        subView = "pin"
        focusView()
    }

    function startParentPinFlow() {
        startPinForAccount(ed.selectedParentAccount)
    }

    function focusView() {
        Qt.callLater(function () {
            if (!ed.open) return
            if (ed.subView === "pin") {
                var fk = editPinPad.firstKey()
                if (fk) app.setFocus(fk, true)
            } else if (ed.subView === "password") {
                app.setFocus(pwInput, true)
            } else if (ed.subView === "delete") {
                app.setFocus(delCancelBtn, true)
            } else {
                app.setFocus(nameField, true)
            }
        })
    }

    function notifySaved(res) {
        app.loadSession(false)
        if (onSavedCb) onSavedCb(res)
    }

    function saveAccount() {
        if (busy) return
        var nm = nameField.value.trim()
        if (!nm.length) {
            app.toast(Ui.t("account.err.nameRequired"), true)
            app.setFocus(nameField, true)
            return
        }
        if (ed.childNeedsParentAuth) {
            app.toast(Ui.t("account.err.parentAuthRequired"), true)
            ed.startParentPinFlow()
            return
        }
        busy = true
        if (isNew) {
            var cbody = {
                display_name: nm,
                role: editRole,
                avatar: editAvatar,
                color: editColor,
                auto_login: editAutoLogin
            }
            if (editRole === "child" && editParentId) cbody.parent_id = editParentId
            if (pendingPin) cbody.pin = pendingPin
            if (pendingPassword) cbody.password = pendingPassword
            Api.post("/api/accounts/create", cbody, function (res) {
                busy = false
                app.toast(Ui.t("account.created"))
                notifySaved(res)
                close()
            }, function (err) {
                busy = false
                app.toast(Ui.t(err, null, Ui.t("common.failed")), true)
                if (err === "account.err.parentAuthRequired") ed.startParentPinFlow()
            })
            return
        }
        // RBAC: Nicht-Admin darf beim eigenen Profil keine role/parent_id/active/auto_login-Felder mitsenden
        var ubody = {
            account_id: account.id,
            display_name: nm,
            avatar: editAvatar,
            color: editColor
        }
        if (isAdmin) {
            ubody.role = editRole
            ubody.parent_id = editRole === "child" ? (editParentId || (app.session ? app.session.account_id : "")) : ""
            ubody.auto_login = editAutoLogin
        }
        Api.post("/api/accounts/update", ubody, function (res) {
            busy = false
            if (res && res.account) account = res.account
            if (res && res.session) app.session = res.session
            app.toast(Ui.t("account.saved"))
            notifySaved(res)
            close()
        }, function (err) {
            busy = false
            app.toast(Ui.t(err, null, Ui.t("common.failed")), true)
            if (err === "account.err.parentAuthRequired") ed.startParentPinFlow()
        })
    }

    function withCurrentAuth(fn) {
        if (isAdmin || !account || (!account.has_pin && !account.has_password)) {
            fn({})
            return
        }
        app.openAuthDialog(account, {
            title: Ui.t("account.confirmCurrent"),
            customSubmit: function (factor, secret, done) {
                var extra = factor === "pin" ? { current_pin: secret } : { current_password: secret }
                fn(extra, done)
            }
        })
    }

    function submitPin(pin) {
        if (ed.pinTargetAccount) {
            var targetAcc = ed.pinTargetAccount
            busy = true
            editPinPad.busy = true
            Api.post("/api/accounts/credentials", { account_id: targetAcc.id, action: "set", factor: "pin", pin: pin }, function (res) {
                busy = false
                editPinPad.busy = false
                pinTargetAccount = null
                if (res && res.account) {
                    var list = (app.accountsList || []).slice()
                    for (var i = 0; i < list.length; i++) {
                        if (list[i].id === res.account.id) list[i] = res.account
                    }
                    app.accountsList = list
                }
                subView = "form"
                focusView()
                app.toast(res && res.weak_pin ? Ui.t("account.weakPinWarn") : Ui.t("account.pinSaved"))
                notifySaved(res)
            }, function (err) {
                busy = false
                editPinPad.busy = false
                editPinPad.errorText = Ui.t(err, null, Ui.t("account.err.pinFormat"))
                vs.playSound("error")
            })
            return
        }
        if (isNew) {
            pendingPin = pin
            subView = "form"
            focusView()
            return
        }
        withCurrentAuth(function (extra, authDone) {
            busy = true
            editPinPad.busy = true
            var body = Object.assign({ account_id: account.id, action: "set", factor: "pin", pin: pin }, extra || {})
            Api.post("/api/accounts/credentials", body, function (res) {
                busy = false
                editPinPad.busy = false
                if (authDone) authDone(true, res)
                if (res && res.account) account = res.account
                subView = "form"
                focusView()
                app.toast(res && res.weak_pin ? Ui.t("account.weakPinWarn") : Ui.t("account.pinSaved"))
                notifySaved(res)
            }, function (err, data, status) {
                busy = false
                editPinPad.busy = false
                if (authDone) {
                    if (status === 401 || status === 423 || status === 429) authDone(false, data, err, data, status)
                    else {
                        authDone(true, null)
                        app.toast(Ui.t(err, null, Ui.t("common.failed")), true)
                    }
                } else {
                    editPinPad.errorText = Ui.t(err, null, Ui.t("account.err.pinFormat"))
                    vs.playSound("error")
                }
            })
        })
    }

    function submitPassword(pw) {
        if (!pw || pw.length < 1 || pw.length > 200) {
            app.toast(Ui.t("account.err.pwFormat"), true)
            return
        }
        if (isNew) {
            pendingPassword = pw
            subView = "form"
            focusView()
            return
        }
        withCurrentAuth(function (extra, authDone) {
            busy = true
            var body = Object.assign({ account_id: account.id, action: "set", factor: "password", password: pw }, extra || {})
            Api.post("/api/accounts/credentials", body, function (res) {
                busy = false
                if (authDone) authDone(true, res)
                if (res && res.account) account = res.account
                subView = "form"
                focusView()
                app.toast(Ui.t("account.passwordSaved"))
                notifySaved(res)
            }, function (err, data, status) {
                busy = false
                if (authDone) {
                    if (status === 401 || status === 423 || status === 429) authDone(false, data, err, data, status)
                    else {
                        authDone(true, null)
                        app.toast(Ui.t(err, null, Ui.t("common.failed")), true)
                    }
                } else {
                    app.toast(Ui.t(err, null, Ui.t("common.failed")), true)
                }
            })
        })
    }

    function removeCredential(factor) {
        if (isNew) {
            if (factor === "pin") pendingPin = ""
            else pendingPassword = ""
            return
        }
        withCurrentAuth(function (extra, authDone) {
            busy = true
            var body = Object.assign({ account_id: account.id, action: "remove", factor: factor }, extra || {})
            Api.post("/api/accounts/credentials", body, function (res) {
                busy = false
                if (authDone) authDone(true, res)
                if (res && res.account) account = res.account
                app.toast(Ui.t(factor === "pin" ? "account.pinRemoved" : "account.passwordRemoved"))
                notifySaved(res)
            }, function (err, data, status) {
                busy = false
                if (authDone) {
                    if (status === 401 || status === 423 || status === 429) authDone(false, data, err, data, status)
                    else {
                        authDone(true, null)
                        app.toast(Ui.t(err, null, Ui.t("common.failed")), true)
                    }
                } else {
                    app.toast(Ui.t(err, null, Ui.t("common.failed")), true)
                }
            })
        })
    }

    function unlockPin() {
        if (!account || busy) return
        busy = true
        Api.post("/api/accounts/credentials", { account_id: account.id, action: "unlock", factor: "pin" }, function (res) {
            busy = false
            if (res && res.account) account = res.account
            app.toast(Ui.t("account.unlockDone"))
            notifySaved(res)
        }, function (err) {
            busy = false
            app.toast(Ui.t(err, null, Ui.t("common.failed")), true)
        })
    }

    function confirmDelete() {
        if (!account || busy) return
        busy = true
        Api.post("/api/accounts/delete", { account_id: account.id }, function (res) {
            busy = false
            app.toast(Ui.t("account.deleted"))
            notifySaved(res)
            close()
        }, function (err) {
            busy = false
            subView = "form"
            focusView()
            app.toast(Ui.t(err, null, Ui.t("common.failed")), true)
        })
    }

    function keyFilter(e) {
        if (subView === "pin") return editPinPad.handleKey(e)
        return false
    }

    function padFilter(k) {
        if (subView === "pin") return editPinPad.handlePad(k)
        return false
    }

    Rectangle {
        id: card
        width: Math.min(720 * Ui.f, ed.width - 2 * Ui.padX)
        readonly property real maxCardH: ed.height - 2 * Math.max(54 * Ui.f, Ui.hintH)
        height: subView === "form"
              ? Math.min(formCol.implicitHeight + 56 * Ui.f, maxCardH)
              : subView === "pin" ? (pinSubCol.implicitHeight + 56 * Ui.f)
              : subView === "password" ? (pwSubCol.implicitHeight + 56 * Ui.f)
              : (delSubCol.implicitHeight + 56 * Ui.f)
        anchors.centerIn: parent
        color: Ui.c.surfaceDialog
        border.width: 1
        border.color: Ui.c.borderSubtle

        MouseArea { anchors.fill: parent; acceptedButtons: Qt.AllButtons }

        // ---- Hauptformular (scrollbar fuer hohe Skalierung)
        Flickable {
            id: formScroll
            visible: ed.subView === "form"
            x: 32 * Ui.f
            y: 28 * Ui.f
            width: parent.width - 64 * Ui.f
            height: parent.height - 56 * Ui.f
            contentWidth: width
            contentHeight: formCol.implicitHeight + 4
            clip: true
            interactive: false

            function ensureVisible(item, instant) {
                if (contentHeight <= height + 1) return
                var p = item.mapToItem(formScroll.contentItem, 0, 0)
                var m = Math.max(0, Math.min(36 * Ui.f, (height - item.height) / 2))
                var y = formAnim.running ? formAnim.to : contentY
                if (p.y + item.height + m <= height) y = 0
                else if (p.y < y + m) y = p.y - m
                else if (p.y + item.height > y + height - m) y = p.y + item.height - height + m
                y = Math.max(0, Math.min(contentHeight - height, y))
                formAnim.stop()
                if (instant) contentY = y
                else { formAnim.from = contentY; formAnim.to = y; formAnim.start() }
            }
            NumberAnimation { id: formAnim; target: formScroll; property: "contentY"; duration: 220; easing.type: Easing.OutQuad }
            WheelHandler { onWheel: function (ev) { formScroll.contentY = Math.max(0, Math.min(Math.max(0, formScroll.contentHeight - formScroll.height), formScroll.contentY - ev.angleDelta.y)) } }

            Column {
                id: formCol
                width: formScroll.width
                spacing: 14 * Ui.f

                Txt {
                    width: parent.width
                    text: ed.isNew ? Ui.t("account.createTitle") : Ui.t("account.editTitle")
                    font.pixelSize: 28 * Ui.f
                    font.weight: Font.Light
                }

                // Name
                Column {
                    width: parent.width
                    spacing: 6 * Ui.f
                    Txt { text: Ui.t("account.name"); color: Ui.c.textFaint; font.pixelSize: 14 * Ui.f }
                    Field {
                        id: nameField
                        width: Math.min(parent.width, 360 * Ui.f)
                        placeholder: Ui.t("account.namePlaceholder")
                    }
                }

                // Rolle (nur Admin)
                Column {
                    visible: ed.isAdmin
                    width: parent.width
                    spacing: 6 * Ui.f
                    Txt { text: Ui.t("account.role"); color: Ui.c.textFaint; font.pixelSize: 14 * Ui.f }
                    Flow {
                        width: parent.width
                        spacing: 8 * Ui.f
                        Repeater {
                            model: ["admin", "standard", "child"]
                            Pill {
                                text: Ui.t("account.role." + modelData)
                                on: ed.editRole === modelData
                                sound: "toggle"
                                onTriggered: {
                                    ed.editRole = modelData
                                    if (modelData === "child" && !ed.editParentId && ed.adminAccounts.length)
                                        ed.editParentId = ed.adminAccounts[0].id
                                }
                            }
                        }
                    }
                }

                // Eltern-Konto bei Kinder-Profil
                Column {
                    visible: ed.isAdmin && ed.editRole === "child" && ed.adminAccounts.length > 0
                    width: parent.width
                    spacing: 6 * Ui.f
                    Txt { text: Ui.t("account.parent"); color: Ui.c.textFaint; font.pixelSize: 14 * Ui.f }
                    Flow {
                        width: parent.width
                        spacing: 8 * Ui.f
                        Repeater {
                            model: ed.adminAccounts
                            Pill {
                                text: modelData.display_name
                                on: ed.editParentId === modelData.id
                                sound: "toggle"
                                onTriggered: ed.editParentId = modelData.id
                            }
                        }
                    }
                }

                // Hinweis + Direkteinstieg zur PIN, wenn Eltern- oder andere Nicht-Kinderkonten noch keinen Schutz haben
                Column {
                    visible: ed.isAdmin && ed.editRole === "child" && ed.unprotectedNonChildAccounts.length > 0
                    width: parent.width
                    spacing: 8 * Ui.f
                    Txt {
                        visible: ed.childNeedsParentAuth
                        width: parent.width
                        wrapMode: Text.Wrap
                        elide: Text.ElideNone
                        font.pixelSize: 14 * Ui.f
                        color: Ui.c.textDim
                        text: ed.selectedParentAccount
                            ? Ui.t("account.childNeedsParentAuth", { name: ed.selectedParentAccount.display_name })
                            : ""
                    }
                    Txt {
                        width: parent.width
                        wrapMode: Text.Wrap
                        elide: Text.ElideNone
                        font.pixelSize: 14 * Ui.f
                        color: Ui.c.textDim
                        text: Ui.t("account.childUnprotectedAccounts", {
                            names: ed.unprotectedNonChildAccounts.map(function (a) { return a.display_name }).join(", ")
                        })
                    }
                    Flow {
                        width: parent.width
                        spacing: 8 * Ui.f
                        Repeater {
                            model: ed.unprotectedNonChildAccounts
                            Pill {
                                text: Ui.t("account.setPinForAccount", { name: modelData.display_name })
                                on: !!ed.selectedParentAccount && modelData.id === ed.selectedParentAccount.id
                                onTriggered: ed.startPinForAccount(modelData)
                            }
                        }
                    }
                }

                // Avatar
                Column {
                    width: parent.width
                    spacing: 6 * Ui.f
                    Txt { text: Ui.t("account.avatar"); color: Ui.c.textFaint; font.pixelSize: 14 * Ui.f }
                    Flow {
                        width: parent.width
                        spacing: 10 * Ui.f
                        Repeater {
                            model: ed.avatarChoices
                            Focusable {
                                id: avBtn
                                width: 46 * Ui.f
                                height: width
                                sound: "toggle"
                                onTriggered: ed.editAvatar = modelData
                                Rectangle {
                                    anchors.fill: parent
                                    radius: width / 2
                                    color: ed.editAvatar === modelData ? ed.editColor : Ui.c.surfaceCard
                                    border.width: avBtn.focused ? 2 : 1
                                    border.color: avBtn.focused ? Ui.c.borderFocus
                                                : ed.editAvatar === modelData ? Ui.c.borderFocus : Ui.c.borderSubtle
                                }
                                Glyph {
                                    anchors.centerIn: parent
                                    width: parent.width * 0.52
                                    height: width
                                    name: modelData
                                    color: ed.editAvatar === modelData ? Ui.c.tileText : Ui.c.textPrimary
                                }
                            }
                        }
                    }
                }

                // Farbe
                Column {
                    width: parent.width
                    spacing: 6 * Ui.f
                    Txt { text: Ui.t("account.color"); color: Ui.c.textFaint; font.pixelSize: 14 * Ui.f }
                    Flow {
                        width: parent.width
                        spacing: 10 * Ui.f
                        Repeater {
                            model: ed.colorChoices
                            Focusable {
                                id: colBtn
                                width: 42 * Ui.f
                                height: width
                                sound: "toggle"
                                onTriggered: ed.editColor = modelData
                                Rectangle {
                                    anchors.fill: parent
                                    radius: 4 * Ui.f
                                    color: modelData
                                    border.width: colBtn.focused ? 3 : ed.editColor === modelData ? 2 : 1
                                    border.color: colBtn.focused || ed.editColor === modelData ? Ui.c.borderFocus : Ui.c.borderSubtle
                                }
                                Glyph {
                                    visible: ed.editColor === modelData
                                    anchors.centerIn: parent
                                    width: 18 * Ui.f
                                    height: width
                                    name: "ok"
                                    color: Ui.c.tileText
                                }
                            }
                        }
                    }
                }

                // Auto-Login (nur Admin)
                Column {
                    visible: ed.isAdmin
                    width: parent.width
                    spacing: 6 * Ui.f
                    Txt { text: Ui.t("account.autoLogin"); color: Ui.c.textFaint; font.pixelSize: 14 * Ui.f }
                    Flow {
                        width: parent.width
                        spacing: 8 * Ui.f
                        Repeater {
                            model: [true, false]
                            Pill {
                                text: Ui.t(modelData ? "common.on" : "common.off")
                                on: ed.editAutoLogin === modelData
                                sound: "toggle"
                                onTriggered: ed.editAutoLogin = modelData
                            }
                        }
                    }
                }

                // Sicherheit (PIN / Passwort)
                Column {
                    id: secCol
                    width: parent.width
                    spacing: 8 * Ui.f
                    readonly property bool hasPinNow: ed.isNew ? ed.pendingPin !== "" : !!(ed.account && ed.account.has_pin)
                    readonly property bool hasPwNow: ed.isNew ? ed.pendingPassword !== "" : !!(ed.account && ed.account.has_password)
                    Txt { text: Ui.t("account.security"); color: Ui.c.textFaint; font.pixelSize: 14 * Ui.f }
                    Txt {
                        width: parent.width
                        font.pixelSize: 14 * Ui.f
                        color: Ui.c.textDim
                        text: {
                            var parts = []
                            if (secCol.hasPinNow) parts.push(Ui.t("account.pinSet"))
                            if (secCol.hasPwNow) parts.push(Ui.t("account.passwordSet"))
                            return parts.length ? parts.join(" · ") : Ui.t("account.noAuth")
                        }
                    }
                    Flow {
                        width: parent.width
                        spacing: 8 * Ui.f
                        Pill {
                            text: Ui.t(secCol.hasPinNow ? "account.changePin" : "account.setPin")
                            onTriggered: {
                                editPinPad.reset()
                                ed.subView = "pin"
                                ed.focusView()
                            }
                        }
                        Pill {
                            visible: secCol.hasPinNow
                            text: Ui.t("account.removePin")
                            onTriggered: ed.removeCredential("pin")
                        }
                        Pill {
                            text: Ui.t(secCol.hasPwNow ? "account.changePassword" : "account.setPassword")
                            onTriggered: {
                                pwInput.value = ""
                                pwInput.password = true
                                ed.subView = "password"
                                ed.focusView()
                            }
                        }
                        Pill {
                            visible: secCol.hasPwNow
                            text: Ui.t("account.removePassword")
                            onTriggered: ed.removeCredential("password")
                        }
                        Pill {
                            visible: !ed.isNew && ed.isAdmin && secCol.hasPinNow
                            text: Ui.t("account.unlockPin")
                            onTriggered: ed.unlockPin()
                        }
                    }
                }

                Item { width: 1; height: 6 * Ui.f }

                // Fusszeile
                Flow {
                    width: parent.width
                    spacing: 10 * Ui.f
                    Btn {
                        text: ed.busy ? "…" : Ui.t("account.save")
                        on: true
                        onTriggered: ed.saveAccount()
                    }
                    Btn {
                        visible: !ed.isNew && ed.isAdmin
                        text: Ui.t("account.delete")
                        danger: true
                        onTriggered: {
                            ed.subView = "delete"
                            ed.focusView()
                        }
                    }
                    Btn {
                        text: Ui.t("common.cancel")
                        sound: "back"
                        onTriggered: ed.handleBack()
                    }
                }
            }
        }

        // ---- PIN setzen
        Column {
            id: pinSubCol
            visible: ed.subView === "pin"
            x: 32 * Ui.f
            y: 28 * Ui.f
            width: parent.width - 64 * Ui.f
            spacing: 16 * Ui.f

            Txt {
                width: parent.width
                text: ed.pinTargetAccount
                    ? Ui.t("account.setPinForAccount", { name: ed.pinTargetAccount.display_name })
                    : Ui.t((ed.account && ed.account.has_pin) || ed.pendingPin ? "account.changePin" : "account.setPin")
                font.pixelSize: 24 * Ui.f
                font.weight: Font.Light
            }
            PinPad {
                id: editPinPad
                anchors.horizontalCenter: parent.horizontalCenter
                submitLabel: Ui.t("account.save")
                onSubmitted: function (pin) { ed.submitPin(pin) }
            }
            Btn {
                anchors.horizontalCenter: parent.horizontalCenter
                text: Ui.t("common.cancel")
                sound: "back"
                onTriggered: ed.handleBack()
            }
        }

        // ---- Passwort setzen
        Column {
            id: pwSubCol
            visible: ed.subView === "password"
            x: 32 * Ui.f
            y: 28 * Ui.f
            width: parent.width - 64 * Ui.f
            spacing: 16 * Ui.f

            Txt {
                width: parent.width
                text: Ui.t((ed.account && ed.account.has_password) || ed.pendingPassword ? "account.changePassword" : "account.setPassword")
                font.pixelSize: 24 * Ui.f
                font.weight: Font.Light
            }
            Row {
                width: parent.width
                spacing: 10 * Ui.f
                Field {
                    id: pwInput
                    width: parent.width - pwReveal.width - 10 * Ui.f
                    password: true
                    revealable: true
                    placeholder: Ui.t("account.enterPassword")
                    onSubmitted: function (txt) { ed.submitPassword(txt) }
                }
                Pill {
                    id: pwReveal
                    text: Ui.t(pwInput.password ? "settings.pwShow" : "settings.pwHide")
                    on: !pwInput.password
                    sound: "toggle"
                    toggleFlip: true
                    onTriggered: pwInput.password = !pwInput.password
                }
            }
            Flow {
                width: parent.width
                spacing: 10 * Ui.f
                Btn {
                    text: ed.busy ? "…" : Ui.t("account.save")
                    on: pwInput.value.length > 0
                    onTriggered: ed.submitPassword(pwInput.value)
                }
                Btn {
                    text: Ui.t("common.cancel")
                    sound: "back"
                    onTriggered: ed.handleBack()
                }
            }
        }

        // ---- Loeschen bestaetigen
        Column {
            id: delSubCol
            visible: ed.subView === "delete"
            x: 32 * Ui.f
            y: 28 * Ui.f
            width: parent.width - 64 * Ui.f
            spacing: 18 * Ui.f

            Txt {
                width: parent.width
                text: Ui.t("account.delete")
                font.pixelSize: 26 * Ui.f
                font.weight: Font.Light
            }
            Txt {
                width: parent.width
                wrapMode: Text.Wrap
                elide: Text.ElideNone
                font.pixelSize: 16 * Ui.f
                color: Ui.c.textDim
                text: ed.account ? Ui.t("account.deleteConfirm", { name: ed.account.display_name }) : ""
            }
            Flow {
                width: parent.width
                spacing: 12 * Ui.f
                Btn {
                    text: ed.busy ? "…" : Ui.t("account.delete")
                    danger: true
                    onTriggered: ed.confirmDelete()
                }
                Btn {
                    id: delCancelBtn
                    text: Ui.t("common.cancel")
                    sound: "back"
                    onTriggered: ed.handleBack()
                }
            }
        }
    }
}
