// SPDX-License-Identifier: GPL-3.0-or-later
// Belegung einer SSD als Balken: segs = [{ flex, cls }], cls = esp | swap | reserved | recovery | free | (Partition)
import QtQuick
import VS

Row {
    id: db
    property var segs: []
    height: 10 * Ui.f
    spacing: 2
    readonly property real total: { var t = 0; for (var i = 0; i < segs.length; i++) t += segs[i].flex; return t || 1 }
    Repeater {
        model: db.segs.length ? db.segs : [{ flex: 1, cls: "free" }]
        Rectangle {
            width: Math.max(3, (db.width - db.spacing * (db.segs.length - 1)) * modelData.flex / db.total)
            height: db.height
            color: modelData.cls === "free" ? "transparent"
                 : modelData.cls === "esp" ? "#e6ffffff"
                 : (modelData.cls === "swap" || modelData.cls === "reserved" || modelData.cls === "recovery") ? "#47ffffff" : "#80ffffff"
            border.width: modelData.cls === "free" ? 2 : 0
            border.color: "#66ffffff"
        }
    }
}
