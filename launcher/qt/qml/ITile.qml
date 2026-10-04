// SPDX-License-Identifier: GPL-3.0-or-later
// Kachel im Installer, Inhalt je nach d.kind:
//   tile  Symbol, Name, Zusatz (Standard)        info  Wert oder Symbol, Haken/Kreuz, Beschriftung (nicht waehlbar)
//   disk  SSD mit Groesse, Modell, Belegung      set   Einstellung: Titel, Wert gross, Erklaerung
//   hold  Installieren: A gedrueckt halten (Ring zeigt den Fortschritt)
import QtQuick
import VS

Tile {
    id: it
    property var d: ({})
    property real u: Ui.u                         // Kachelgroesse des Installers
    property string key: d.key || ""
    property real holdP: 0
    property bool mouseDown: false
    signal holdBegin()
    // Installieren: mit der Maus gedrueckt halten (Klick allein loest nichts aus)
    property var clickActivate: isHold ? function () {} : undefined
    function pressStart() { if (isHold) { mouseDown = true; app.setFocus(it); holdBegin() } }
    function pressEnd() { mouseDown = false }
    readonly property bool isHold: d.kind === "hold"
    readonly property bool large: width > u * 1.5 && height > u * 1.5
    navigable: d.kind !== "info"
    tileColor: d.color || (d.kind === "info" ? Ui.c.surfaceRaised : "#2f3238")
    opacity: d.off ? 0.4 : 1
    readonly property color fg: Ui.c.tileText
    readonly property color dim: Ui.c.light ? "#ccffffff" : Ui.c.textDim

    // ---- tile
    Glyph {
        visible: (it.d.kind === "tile" || it.isHold) && !!it.d.icon
        name: it.d.icon || ""
        color: it.fg
        width: it.width > it.height * 1.5 ? it.width * 0.18 : it.width * 0.34
        height: it.width > it.height * 1.5 ? it.height * 0.36 : it.height * 0.34
        x: (parent.width - width) / 2
        y: parent.height * 0.42 - height / 2
    }
    Txt {
        visible: (it.d.kind === "tile" || it.isHold) && !!it.d.sub
        text: it.d.sub || ""
        anchors.right: it.isHold ? undefined : parent.right
        anchors.rightMargin: parent.width * 0.06
        x: it.isHold ? parent.width * 0.07 : 0
        y: parent.height * 0.08
        width: Math.min(implicitWidth, parent.width * (it.isHold ? 0.6 : 0.88))
        font.pixelSize: it.u * 0.08
        color: Ui.c.tileSub
    }
    Txt {
        visible: it.d.kind === "tile" || it.isHold
        text: it.d.label || ""
        x: parent.width * 0.07
        width: parent.width * 0.86
        anchors.bottom: parent.bottom
        anchors.bottomMargin: it.isHold ? parent.height * 0.15 : parent.height * 0.07
        font.pixelSize: it.large ? it.u * 0.15 : it.u * 0.105
        color: it.fg
        wrapMode: Text.WordWrap
        maximumLineCount: 2
        lineHeight: 1.1
    }
    // ---- hold
    Txt {
        visible: it.isHold
        text: Ui.t("inst.hold")
        x: parent.width * 0.07; width: parent.width * 0.86
        anchors.bottom: parent.bottom; anchors.bottomMargin: parent.height * 0.07
        font.pixelSize: it.u * 0.075
        color: "#bfffffff"
    }
    Item {
        visible: it.isHold
        width: it.u * 0.34; height: width
        anchors.right: parent.right; anchors.rightMargin: parent.width * 0.07
        y: parent.height * 0.08
        Canvas {
            id: ring
            anchors.fill: parent
            property real p: it.holdP
            property color base: Ui.c.borderMuted
            property color fill: Ui.c.textPrimary
            onPChanged: requestPaint()
            onPaint: {
                var c = getContext("2d"), r = width / 2, lw = width * 0.12
                c.reset(); c.lineWidth = lw
                c.strokeStyle = base; c.beginPath(); c.arc(r, r, r - lw / 2, 0, 2 * Math.PI); c.stroke()
                if (p > 0) { c.strokeStyle = fill; c.beginPath(); c.arc(r, r, r - lw / 2, -Math.PI / 2, -Math.PI / 2 + p * 2 * Math.PI); c.stroke() }
            }
        }
        Txt { anchors.centerIn: parent; text: "A"; font.pixelSize: it.u * 0.13; font.weight: Font.DemiBold; elide: Text.ElideNone }
    }
    // ---- info
    Rectangle {                                     // roter Rand: hier fehlt etwas
        visible: it.d.kind === "info" && it.d.state === "bad"
        anchors.fill: parent; z: 52
        color: "transparent"
        border.width: 2; border.color: Ui.c.statusDangerText
    }
    Glyph {
        visible: it.d.kind === "info" && !it.d.big && !!it.d.icon
        name: it.d.icon || ""
        color: Ui.c.textPrimary
        x: parent.width * 0.09; y: parent.height * 0.1
        width: it.u * 0.2; height: width
    }
    Txt {
        visible: it.d.kind === "info" && !!it.d.big
        text: it.d.big || ""
        x: parent.width * 0.09; y: parent.height * 0.1
        width: parent.width * 0.69
        font.pixelSize: it.u * 0.15
        font.weight: Font.Light
    }
    Glyph {
        visible: it.d.kind === "info" && (it.d.state === "ok" || it.d.state === "bad")
        name: it.d.state === "ok" ? "ok" : "bad"
        color: it.d.state === "ok" ? Ui.c.statusOkText : Ui.c.statusDangerText
        anchors.right: parent.right; anchors.rightMargin: parent.width * 0.08
        y: parent.height * 0.09
        width: it.u * 0.14; height: width
    }
    Column {
        visible: it.d.kind === "info"
        x: parent.width * 0.09; width: parent.width * 0.84
        anchors.bottom: parent.bottom; anchors.bottomMargin: parent.height * 0.08
        spacing: 2
        Txt { width: parent.width; text: it.d.k || ""; font.pixelSize: it.u * 0.081; color: Ui.c.textDim }
        Txt { width: parent.width; text: it.d.v || "–"; font.pixelSize: it.u * 0.095; wrapMode: Text.WordWrap; maximumLineCount: 2; lineHeight: 1.15 }
    }
    // ---- set
    Txt {
        visible: it.d.kind === "set"
        text: it.d.k || ""
        x: parent.width * 0.07; y: parent.height * 0.09; width: parent.width * 0.86
        font.pixelSize: it.u * 0.085; color: it.dim
    }
    Txt {
        visible: it.d.kind === "set"
        text: it.d.v || ""
        x: parent.width * 0.07; y: parent.height * 0.3; width: parent.width * 0.86
        font.pixelSize: it.u * 0.16; font.weight: Font.Light; color: it.fg
    }
    Txt {
        visible: it.d.kind === "set"
        text: it.d.desc || ""
        x: parent.width * 0.07; width: parent.width * 0.86
        anchors.bottom: parent.bottom; anchors.bottomMargin: parent.height * 0.09
        font.pixelSize: it.u * 0.075; color: it.dim
        wrapMode: Text.WordWrap; maximumLineCount: 2; lineHeight: 1.2
    }
    // ---- disk
    Glyph {
        visible: it.d.kind === "disk"
        name: it.d.tran === "nvme" ? "nvme" : "sata"
        color: it.fg
        x: parent.width * 0.07; y: parent.height * 0.07
        width: it.u * 0.24; height: width
    }
    Txt {
        visible: it.d.kind === "disk"
        text: it.d.bus || ""
        anchors.right: parent.right; anchors.rightMargin: parent.width * 0.06
        y: parent.height * 0.08
        font.pixelSize: it.u * 0.08; color: Ui.c.tileSub
    }
    Txt {
        visible: it.d.kind === "disk"
        text: it.d.gb || ""
        x: parent.width * 0.07; y: parent.height * 0.32
        font.pixelSize: it.u * 0.3; font.weight: Font.Light; color: it.fg; elide: Text.ElideNone
    }
    Txt {
        visible: it.d.kind === "disk"
        text: it.d.model || ""
        x: parent.width * 0.07; y: parent.height * 0.53; width: parent.width * 0.86
        font.pixelSize: it.u * 0.105; color: it.fg
    }
    Column {
        visible: it.d.kind === "disk"
        x: parent.width * 0.07; width: parent.width * 0.86
        anchors.bottom: parent.bottom; anchors.bottomMargin: parent.height * 0.08
        spacing: 7 * Ui.f
        DiskBar { width: parent.width; segs: it.d.segs || [] }
        Txt { width: parent.width; text: it.d.legend || ""; font.pixelSize: it.u * 0.08; color: Ui.c.tileSub }
    }
}
