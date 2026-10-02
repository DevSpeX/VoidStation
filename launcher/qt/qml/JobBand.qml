// SPDX-License-Identifier: GPL-3.0-or-later
// Laufender Auftrag (Installieren, Entfernen, Updates): Band unten mit den letzten Zeilen des Protokolls
import QtQuick
import VS

Rectangle {
    id: jb
    property bool shown: false
    z: 35
    width: parent.width
    height: col.implicitHeight + 28 * Ui.f
    y: parent.height - height
    visible: shown
    color: Ui.c.surfaceBase
    Rectangle { width: parent.width; height: 1; color: Ui.c.divider }
    Column {
        id: col
        x: Ui.padX; y: 14 * Ui.f
        width: parent.width - 2 * Ui.padX
        spacing: 6
        Row {
            spacing: 12
            Spinner { id: spin; size: 14 * Ui.f; line: 2; anchors.verticalCenter: parent.verticalCenter }
            Txt { id: title; font.pixelSize: 17 * Ui.f; anchors.verticalCenter: parent.verticalCenter }
        }
        Text {
            id: logText
            width: parent.width
            font.family: "DejaVu Sans Mono"
            font.pixelSize: 12.5 * Ui.f
            color: Ui.c.textDim
            wrapMode: Text.WrapAnywhere
            maximumLineCount: 6
            elide: Text.ElideRight
            height: Math.min(implicitHeight, 110 * Ui.f)
            clip: true
        }
    }
    Timer { id: poll; interval: 1000; repeat: true; onTriggered: jb.tick() }
    Timer { id: hideLater; onTriggered: jb.shown = false }
    function watch() {
        hideLater.stop()
        shown = true
        tick()
        poll.start()
    }
    function tick() {
        Api.get("/api/apps/job", function (js) {
            if (!js || !js.state) return
            app.jobState = js
            var name = Ui.l(js.name)
            var what = js.action === "update" ? Ui.t("job.update")
                     : (js.action === "install" || js.action === "remove") ? Ui.t("job." + js.action, { name: name }) : name
            title.text = what + Ui.t(js.state === "running" ? "job.running" : js.state === "done" ? "job.done" : "job.failed")
            spin.visible = js.state === "running"
            logText.text = (js.log || []).slice(-6).join("\n")
            if (js.state === "running") return
            poll.stop()
            var upd = js.action === "update", r = js.result
            if (upd && r && r.busy) app.toast(Ui.t("upd.xbpsBusy"), true)
            else if (upd) app.toast(Ui.t(js.state === "done" ? "upd.toastDone" : "upd.toastFailed"), js.state !== "done")
            else app.toast(js.state === "done" ? Ui.t("job.toastDone", { name: name }) + (r && typeof r === "string" ? " – " + r : "")
                                              : Ui.t("job.toastFailed", { name: name }), js.state !== "done")
            hideLater.interval = js.state === "done" ? 2500 : 9000
            hideLater.restart()
            app.load()
            if (apps.open) apps.load()
            if (settings.open) { settings.refreshVs(false); settings.load() }
            if (js.reboot) {
                var rb = { kernel: !!(r && r.kernel) }
                Qt.callLater(function () { app.rebootPrompt(rb) })
            } else if (js.state === "done" && js.action === "install" && typeof js.result === "string")
                app.dialog(Ui.t("apps.isInstalled", { name: name }), Ui.t("app." + js.app + ".note", null, js.result), [[Ui.t("common.ok")]])
        })
    }
}
