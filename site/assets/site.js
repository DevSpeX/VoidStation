/* SPDX-License-Identifier: GPL-3.0-or-later
   voidstation.de – News-Filter, Kopier-Knoepfe, Pfeiltasten zwischen den Kacheln */
(function () {
  'use strict';
  var doc = document.documentElement;

  /* News: Alle / Versionen / Beitraege */
  var chips = document.querySelectorAll('.chips [data-filter]');
  chips.forEach(function (b) {
    b.addEventListener('click', function () {
      var f = b.getAttribute('data-filter');
      chips.forEach(function (c) { var on = c === b; c.classList.toggle('on', on); c.setAttribute('aria-pressed', on); });
      document.querySelectorAll('.newsrow').forEach(function (r) {
        r.hidden = f !== 'all' && r.getAttribute('data-kind') !== f;
      });
    });
  });

  /* Kopier-Knopf an jedem Codeblock */
  if (navigator.clipboard) {
    document.querySelectorAll('.prose pre').forEach(function (pre) {
      var b = document.createElement('button');
      b.type = 'button'; b.className = 'pill copy'; b.textContent = doc.dataset.copy || 'Copy';
      b.addEventListener('click', function () {
        var code = pre.querySelector('code');
        navigator.clipboard.writeText(code ? code.textContent : pre.textContent).then(function () {
          b.textContent = doc.dataset.copied || 'Copied';
          setTimeout(function () { b.textContent = doc.dataset.copy || 'Copy'; }, 1600);
        });
      });
      pre.appendChild(b);
    });
  }

  /* Pfeiltasten springen zur naechsten Kachel in der Richtung – wie am Fernseher */
  var tiles = Array.prototype.slice.call(document.querySelectorAll('a.tile'));
  if (tiles.length) {
    document.addEventListener('keydown', function (e) {
      var dir = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] }[e.key];
      var cur = document.activeElement;
      if (!dir || e.altKey || e.ctrlKey || e.metaKey || tiles.indexOf(cur) < 0) return;
      var r = cur.getBoundingClientRect(), cx = r.left + r.width / 2, cy = r.top + r.height / 2;
      var best = null, bestScore = Infinity;
      tiles.forEach(function (t) {
        if (t === cur) return;
        var q = t.getBoundingClientRect(), dx = q.left + q.width / 2 - cx, dy = q.top + q.height / 2 - cy;
        var along = dx * dir[0] + dy * dir[1];
        if (along <= 1) return;
        var across = Math.abs(dir[0] ? dy : dx);
        var score = along + across * 2;
        if (score < bestScore) { bestScore = score; best = t; }
      });
      if (best) { e.preventDefault(); best.focus(); best.scrollIntoView({ block: 'nearest', inline: 'nearest', behavior: 'smooth' }); }
    });
  }
})();
