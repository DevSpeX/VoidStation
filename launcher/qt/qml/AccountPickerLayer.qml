// SPDX-License-Identifier: GPL-3.0-or-later
// Vollbild-Profilauswahl & Sperrbildschirm: aktive Konten, optional Gast-Modus, Schutzschloss & Wechsel.
import QtQuick
import VS

Layer {
    id: picker
    scope: "accounts"
    track: trk
    z: 26

    property bool lockedMode: false
    property var accountsList: []
    property var policy: null
    property bool busy: false

    readonly property bool fromChildSession: !!(app.session && app.session.role === "child" && !app.session.is_guest)
    readonly property bool hasActiveChild: (accountsList || []).some(function (a) { return a.active !== false && a.role === "child" })
    readonly property var fit: Ui.fitRows(stage.height - 24 * Ui.f, Ui.u * 1.05, Ui.gap, 2)
    readonly property var tileItems: {
        var list = (accountsList || []).filter(function (a) {
            if (a.active === false) return false
            if (hasActiveChild && a.role !== "child" && !a.has_pin && !a.has_password) return false
            return true
        }).map(function (a) { return Object.assign({ kind: "account" }, a) })
        if (policy && policy.guest_enabled && !fromChildSession) {
            list.push({
                kind: "guest",
                id: "guest",
                display_name: Ui.t("account.guest"),
                role: "guest",
                avatar: "user",
                color: "#3a3f46",
                auth_configured: false,
                has_pin: false,
                has_password: false
            })
        }
        return list
    }

    title: lockedMode ? Ui.t("account.pickerTitleLocked") : Ui.t("account.pickerTitle")

    Component.onCompleted: updateBackBtn()
    onLockedModeChanged: updateBackBtn()
    function updateBackBtn() {
        backButton.visible = !lockedMode
        backButton.navigable = !lockedMode
    }

    headRight: NowLine {
        main: !picker.lockedMode && app.session ? app.session.display_name : ""
        sub: app.hdrTime
    }

    bar: Pill {
        visible: !picker.lockedMode && !!app.session && app.session.role === "admin" && !app.session.is_guest
        iconName: "gear"
        text: Ui.t("account.manage")
        onTriggered: {
            app.closeLayer(picker)
            app.openLayer(settings)
            settings.openCat("accounts")
        }
    }

    function openPicker(locked) {
        lockedMode = !!locked
        busy = false
        if (!open) app.openLayer(picker)
        else app.updateLayer()
        refresh()
    }

    function refresh() {
        Api.get("/api/accounts", function (r) {
            accountsList = r.accounts || []
            policy = r.device_policy || null
            if (r.session) app.session = r.session
            if (r.device_policy) app.devicePolicy = r.device_policy
            app.accountsList = accountsList
            app.accountsCount = accountsList.length
            Qt.callLater(function () {
                if (!picker.open || app.layerRoot !== picker) return
                var f = firstFocus()
                if (f) app.setFocus(f, true)
            })
        }, function () {
            app.toast(Ui.t("common.failed"), true)
        })
    }

    function firstFocus() {
        var it = Nav.collect(trk)
        if (!it.length) return null
        if (app.session && !lockedMode) {
            for (var i = 0; i < it.length; i++) {
                if (it[i].entry && it[i].entry.id === app.session.account_id) return it[i]
            }
        }
        return it[0]
    }

    function closeAfterSwitch() {
        lockedMode = false
        if (open) app.closeLayer(picker)
    }

    function chooseEntry(entry) {
        if (busy || !entry) return
        if (entry.kind === "guest") {
            busy = true
            Api.post("/api/session/guest", { display_name: Ui.t("account.guest") }, function (res) {
                busy = false
                app.applySessionSwitch(res)
                closeAfterSwitch()
            }, function (err) {
                busy = false
                app.toast(Ui.t(err, null, Ui.t("common.failed")), true)
            })
            return
        }
        var isCurrent = !lockedMode && app.session && !app.session.is_guest && app.session.account_id === entry.id
        if (isCurrent) {
            closeAfterSwitch()
            return
        }
        if (entry.has_pin || entry.has_password) {
            app.openAuthDialog(entry, {
                onSuccess: function () { picker.closeAfterSwitch() }
            })
            return
        }
        busy = true
        Api.post("/api/session/switch", { account_id: entry.id }, function (res) {
            busy = false
            app.applySessionSwitch(res)
            closeAfterSwitch()
        }, function (err) {
            busy = false
            app.toast(Ui.t(err, null, Ui.t("common.failed")), true)
        })
    }

    function handleBack() {
        if (lockedMode) return true
        return false
    }

    Track {
        id: trk
        anchors.fill: parent
        Group {
            showTitle: false
            topPadding: 12 * Ui.f + Ui.u * 0.03
            TileGrid {
                items: picker.tileItems
                rows: picker.fit.n
                cellW: Ui.u * 1.45 * picker.fit.k
                cellH: Ui.u * 1.05 * picker.fit.k
                delegate: Component {
                    Tile {
                        property var entry: modelData
                        readonly property bool isCurrent: !picker.lockedMode && !!app.session && !app.session.is_guest
                                                        && entry.kind === "account" && entry.id === app.session.account_id
                        readonly property real uu: Ui.u * picker.fit.k
                        tileColor: entry.color || Ui.c.tileDefaultC
                        enterDelay: index * 40
                        onTriggered: picker.chooseEntry(entry)

                        Rectangle {
                            x: parent.width * 0.08
                            y: parent.height * 0.11
                            width: uu * 0.34
                            height: width
                            radius: width / 2
                            color: Ui.alpha("#000000", 0.24)
                            Glyph {
                                anchors.centerIn: parent
                                width: parent.width * 0.58
                                height: width
                                name: entry.avatar || "user"
                                color: Ui.c.tileText
                            }
                        }

                        Glyph {
                            visible: !!entry.auth_configured
                            anchors.right: parent.right
                            anchors.top: parent.top
                            anchors.margins: parent.width * 0.08
                            width: uu * 0.14
                            height: width
                            name: "lock"
                            color: Ui.c.tileSub
                        }

                        Txt {
                            x: parent.width * 0.08
                            width: parent.width * 0.84
                            anchors.bottom: subTxt.top
                            anchors.bottomMargin: 2 * Ui.f
                            text: entry.display_name || ""
                            font.pixelSize: uu * 0.135
                            color: Ui.c.tileText
                        }

                        Txt {
                            id: subTxt
                            x: parent.width * 0.08
                            width: parent.width * 0.84
                            anchors.bottom: parent.bottom
                            anchors.bottomMargin: parent.height * 0.09
                            text: entry.kind === "guest" ? Ui.t("account.guestSub")
                                : isCurrent ? Ui.t("account.active")
                                : Ui.t("account.role." + entry.role)
                            font.pixelSize: uu * 0.092
                            color: Ui.c.tileSub
                        }
                    }
                }
            }
        }
    }
}
