// SPDX-License-Identifier: GPL-3.0-or-later
// Aufrufe an den Launcher (dieselbe API wie die Web-Oberflaeche). Antworten kommen als Rueckruf:
//   Api.get("/api/status", function (j) { … }, function (fehler) { … })
//   Api.post("/api/volume/up", null, ok, err)
pragma Singleton
import QtQuick

QtObject {
    id: api
    property int seq: 0
    property var pending: ({})

    function call(method, path, body, ok, err) {
        seq++
        pending[seq] = { ok: ok, err: err }
        vs.request(seq, method, path, body === undefined || body === null ? "" : JSON.stringify(body))
    }
    function get(path, ok, err) { call("GET", path, null, ok, err) }
    function post(path, body, ok, err) { call("POST", path, body, ok, err) }

    property Connections conn: Connections {
        target: vs
        function onReplied(id, ok, status, txt) {
            var cb = api.pending[id]
            delete api.pending[id]
            if (!cb) return
            var j = null
            try { j = txt ? JSON.parse(txt) : null } catch (e) { j = null }
            if (ok) { if (cb.ok) cb.ok(j) }
            else if (cb.err) cb.err((j && j.error) ? String(j.error) : (status ? String(status) : "offline"))
        }
    }
}
