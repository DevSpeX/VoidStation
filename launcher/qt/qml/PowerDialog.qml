// SPDX-License-Identifier: GPL-3.0-or-later
// Ausschalten: Herunterfahren / Neu starten / Standby (wenn das Geraet es kann) / Abbrechen (Fokus auf Abbrechen)
import QtQuick
import VS

Dlg {
    id: pd
    scope: "dialog"
    function openDlg() {
        var standby = !!(app.sett && app.sett.standby)
        var allowPower = !(app.session && app.session.role === "child" && app.parentalStatus && app.parentalStatus.allow_power_menu === false)
        var canSwitch = !app.live && !!app.session && !app.sessionLocked
                     && (app.accountsCount > 1 || !!(app.devicePolicy && app.devicePolicy.guest_enabled) || !!app.session.is_guest)
        var canLock = !app.live && !!app.session && !app.sessionLocked
                   && (app.sessionHasAuth || app.accountsCount > 1 || !!app.session.is_guest || !!(app.devicePolicy && app.devicePolicy.ask_on_boot))
        title = Ui.t("power.title")
        text = Ui.t(standby && allowPower ? "power.textStandby" : "power.text")
        buttons = (canSwitch ? [[Ui.t("account.switch"), function () { app.openAccountPicker() }]] : [])
                  .concat(canLock ? [[Ui.t("account.lock"), function () { app.lockProfile() }]] : [])
                  .concat(allowPower ? [[Ui.t("power.off"), function () { app.power("poweroff") }, "danger"],
                                        [Ui.t("power.reboot"), function () { app.power("reboot") }]] : [])
                  .concat(allowPower && standby ? [[Ui.t("power.standby"), function () { app.power("suspend") }]] : [])
                  .concat([[Ui.t("common.cancel")]])
        open = true
        app.updateLayer()
        Qt.callLater(function () { var b = Nav.collect(pd); if (b.length) app.setFocus(b[b.length - 1], true) })
    }
}
