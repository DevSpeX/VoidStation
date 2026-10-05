#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""
Baut die Webseite voidstation.de (statisch, ohne Fremdpakete – nur Python 3).

  python3 tools/build-site.py              wie auf GitHub: Webseite + Update-Kanaele nach _site/
  python3 tools/build-site.py --preview    alles zeigen, auch wenn das Impressum noch fehlt (nur zum Ansehen)
  python3 -m http.server -d _site 8000     ansehen unter http://<rechner>:8000

Quellen (alles unter site/):
  config.json                     Links und ISO-Download (Version, Datei, Adresse, SHA-256)
  impressum.json                  Anbieterangaben – fehlen sie, gibt es nur eine Baustellenseite
  i18n.json                       Texte der Seitenelemente, deutsch und englisch
  pages/<seite>.<de|en>.md        Inhaltsseiten (erste Zeile "# Titel")
  news/JJJJ-MM-TT-<name>.<de|en>.md   eigene Beitraege (erste Zeile "# Titel")
  assets/                         CSS, Skript, Logo, Schriften
Dazu aus dem Repo:
  CHANGELOG.md / CHANGELOG.en.md  aus --stable: jede freigegebene Version wird eine News
  docs/screenshots/               Bilder fuer Start- und Funktionsseite
  dist/                           aus --src (Kanal Testing) -> /main/dist, aus --stable -> /stable/dist

Auf GitHub baut .github/workflows/pages.yml die Seite bei jedem Push nach main oder stable:
  --src = Zweig main, --stable = Zweig stable.
"""
import argparse, hashlib, html, json, re, shutil, sys
from datetime import date, datetime, timezone
from email.utils import format_datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LANGS = ("de", "en")
# Seiten-Schluessel -> Pfad je Sprache ("" = Startseite)
SLUGS = {
    "home":       {"de": "",            "en": ""},
    "download":   {"de": "download",    "en": "download"},
    "news":       {"de": "news",        "en": "news"},
    "features":   {"de": "funktionen",  "en": "features"},
    "help":       {"de": "hilfe",       "en": "help"},
    "contribute": {"de": "mitmachen",   "en": "contribute"},
    "impressum":  {"de": "impressum",   "en": "legal-notice"},
    "privacy":    {"de": "datenschutz", "en": "privacy"},
}
NAV = ("download", "news", "features", "help", "contribute")
MONTHS = {
    "de": ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober", "November", "Dezember"],
    "en": ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"],
}

def esc(s):
    return html.escape(str(s), quote=True)

def die(msg):
    sys.exit(f"build-site: {msg}")

def warn(msg):
    print(f"build-site: [!] {msg}", file=sys.stderr)


# ===================================================================== Symbole
# dieselben Strichsymbole wie auf der Startseite der Geraete (launcher/web/index.html)
ICONS = {
    "download": '<svg viewBox="0 0 48 48" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M24 7v23M14 21l10 10 10-10M8 35v4a2 2 0 0 0 2 2h28a2 2 0 0 0 2-2v-4"/></svg>',
    "play":     '<svg viewBox="0 0 48 48" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linejoin="round"><rect x="5" y="10" width="38" height="28" rx="7"/><path d="M20 17.5v13l11-6.5z" fill="currentColor"/></svg>',
    "tv":       '<svg viewBox="0 0 48 48" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linejoin="round" stroke-linecap="round"><rect x="5" y="11" width="38" height="25" rx="3"/><path d="M17 42h14M24 36v6M18 4l6 7 6-7"/></svg>',
    "radio":    '<svg viewBox="0 0 48 48" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linejoin="round" stroke-linecap="round"><rect x="5" y="16" width="38" height="24" rx="3"/><path d="M12 16l22-9"/><circle cx="31" cy="28" r="5.5"/><path d="M11 24h9M11 29h9M11 34h9"/></svg>',
    "store":    '<svg viewBox="0 0 48 48" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linejoin="round" stroke-linecap="round"><rect x="7" y="7" width="14" height="14" rx="2"/><rect x="27" y="7" width="14" height="14" rx="2"/><rect x="7" y="27" width="14" height="14" rx="2"/><path d="M34 27v14M27 34h14"/></svg>',
    "gamepad":  '<svg viewBox="0 0 64 40" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linejoin="round" stroke-linecap="round"><path d="M18 6h28c8 0 13 8 15 20 1 7-6 10-10 5l-5-6H18l-5 6c-4 5-11 2-10-5C5 14 10 6 18 6z"/><path d="M15 16h8M19 12v8"/><circle cx="44" cy="14" r="1.8" fill="currentColor"/><circle cx="48" cy="19" r="1.8" fill="currentColor"/></svg>',
    "monitor":  '<svg viewBox="0 0 48 48" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linejoin="round" stroke-linecap="round"><rect x="5" y="8" width="38" height="25" rx="3"/><path d="M17 41h14M24 33v8"/></svg>',
    "terminal": '<svg viewBox="0 0 48 48" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><rect x="5" y="9" width="38" height="30" rx="3"/><path d="M13 19l6 5-6 5M23 30h11"/></svg>',
    "chat":     '<svg viewBox="0 0 48 48" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linejoin="round" stroke-linecap="round"><path d="M8 9h32a3 3 0 0 1 3 3v19a3 3 0 0 1-3 3H22l-9 7v-7H8a3 3 0 0 1-3-3V12a3 3 0 0 1 3-3z"/><path d="M15 19h18M15 25h11"/></svg>',
    "update":   '<svg viewBox="0 0 48 48" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linejoin="round" stroke-linecap="round"><path d="M39 20A15.5 15.5 0 0 0 10.5 15M9 28a15.5 15.5 0 0 0 28.5 5"/><path d="M10 7v8.5h8.5M38 41v-8.5h-8.5"/></svg>',
    "check":    '<svg viewBox="0 0 48 48" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><circle cx="24" cy="24" r="18"/><path d="M15.5 24.5l6 6 11-12"/></svg>',
    "cube":     '<svg viewBox="0 0 48 48" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linejoin="round"><path d="M24 5l17 9.5v19L24 43 7 33.5v-19z"/><path d="M7 14.5L24 24l17-9.5M24 24v19"/></svg>',
    "gear":     '<svg viewBox="0 0 48 48" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linejoin="round"><circle cx="24" cy="24" r="6"/><path d="M24 5l3 5 6-2 1 6 6 1-2 6 5 3-5 3 2 6-6 1-1 6-6-2-3 5-3-5-6 2-1-6-6-1 2-6-5-3 5-3-2-6 6-1 1-6 6 2z"/></svg>',
    "rss":      '<svg viewBox="0 0 48 48" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><path d="M10 22a16 16 0 0 1 16 16M10 11a27 27 0 0 1 27 27"/><circle cx="12" cy="36" r="2.4" fill="currentColor"/></svg>',
    "bug":      '<svg viewBox="0 0 48 48" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><rect x="15" y="14" width="18" height="26" rx="9"/><path d="M19 14a5 5 0 0 1 10 0M24 22v18M15 24H7M41 24h-8M15 33l-7 4M33 33l7 4M16 17l-6-5M32 17l6-5"/></svg>',
    "help":     '<svg viewBox="0 0 48 48" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><circle cx="24" cy="24" r="18"/><path d="M18.5 19a5.5 5.5 0 1 1 7.7 5c-1.4.6-2.2 1.7-2.2 3.2V29"/><circle cx="24" cy="34.5" r="1.2" fill="currentColor"/></svg>',
    "scale":    '<svg viewBox="0 0 48 48" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M24 6v36M14 42h20M8 12h32M8 12l-5 13a6 6 0 0 0 10 0zM40 12l-5 13a6 6 0 0 0 10 0z"/></svg>',
    "github":   '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 .5a11.5 11.5 0 0 0-3.64 22.41c.58.1.79-.25.79-.56v-2c-3.2.7-3.88-1.37-3.88-1.37-.53-1.33-1.28-1.69-1.28-1.69-1.05-.72.08-.7.08-.7 1.16.08 1.77 1.19 1.77 1.19 1.03 1.77 2.71 1.26 3.37.96.1-.75.4-1.26.73-1.55-2.56-.29-5.25-1.28-5.25-5.69 0-1.26.45-2.29 1.19-3.09-.12-.29-.52-1.46.11-3.05 0 0 .97-.31 3.17 1.18a11 11 0 0 1 5.77 0c2.2-1.49 3.17-1.18 3.17-1.18.63 1.59.23 2.76.11 3.05.74.8 1.19 1.83 1.19 3.09 0 4.42-2.7 5.39-5.27 5.68.41.36.78 1.06.78 2.14v3.17c0 .31.21.67.8.56A11.5 11.5 0 0 0 12 .5z"/></svg>',
}


# ===================================================================== Markdown (kleiner Ausschnitt)
#  # Ueberschrift {#anker}   Absaetze   - Listen (auch verschachtelt)   1. Listen   > Hinweis
#  ```Code```   `code`   **fett**   *kursiv*   [Text](ziel)   ![Bild](pfad)   | Tabellen |
#  Zeilen, die mit "<" beginnen, sind HTML.   {{name}} allein in einer Zeile = Baustein (siehe Site.directive)
#  Link-Ziel "seite:hilfe#bedienung" zeigt auf eine Seite in der aktuellen Sprache (Schluessel aus SLUGS).
UML = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss", "Ä": "ae", "Ö": "oe", "Ü": "ue"})

def slugify(s):
    s = re.sub(r"<[^>]+>", "", s).translate(UML).lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-") or "abschnitt"

LIST_RE = re.compile(r"^(\s*)([-*]|\d+\.)\s+(.*)$")
ALLOWED_TAGS = re.compile(r"&lt;(/?)(kbd|br|span|abbr|small|strong|em)((?:\s+[a-z-]+=&quot;[^&]*&quot;)*)\s*/?&gt;")

class Markdown:
    def __init__(self, link=None, directive=None):
        self.link = link or (lambda u: u)
        self.directive = directive or (lambda name, arg: "")
        self.title = None
        self.ids = set()

    def inline(self, text):
        out, pos = [], 0
        for m in re.finditer(r"`([^`]+)`", text):
            out.append(self._inline_plain(text[pos:m.start()]))
            out.append(f"<code>{esc(m.group(1))}</code>")
            pos = m.end()
        out.append(self._inline_plain(text[pos:]))
        return "".join(out)

    def _inline_plain(self, t):
        t = html.escape(t, quote=True)
        t = ALLOWED_TAGS.sub(lambda m: "<" + m.group(1) + m.group(2) + html.unescape(m.group(3)) + ">", t)
        def img(m):
            return f'<img src="{esc(self.link(html.unescape(m.group(2))))}" alt="{m.group(1)}" loading="lazy">'
        def a(m):
            href = self.link(html.unescape(m.group(2)))
            ext = href.startswith("http") and "voidstation.de" not in href
            rel = ' rel="noopener"' if ext else ""
            return f'<a href="{esc(href)}"{rel}>{m.group(1)}</a>'
        t = re.sub(r"!\[([^\]]*)\]\(([^)\s]+)\)", img, t)
        t = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", a, t)
        t = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", t)
        t = re.sub(r"(?<![\*\w])\*(?!\s)(.+?)(?<!\s)\*(?![\*\w])", r"<em>\1</em>", t)
        return t

    def _uid(self, base):
        i, s = 2, base
        while s in self.ids:
            s = f"{base}-{i}"; i += 1
        self.ids.add(s)
        return s

    def render(self, src):
        lines = src.replace("\r\n", "\n").split("\n")
        return self._blocks(lines)

    def _starts_block(self, line):
        s = line.strip()
        return (not s or s.startswith(("#", "```", ">", "|", "<", "{{")) or LIST_RE.match(line) is not None)

    def _blocks(self, lines):
        out, i, n = [], 0, len(lines)
        while i < n:
            line = lines[i]; s = line.strip()
            if not s:
                i += 1; continue
            if s.startswith("```"):
                j = i + 1; code = []
                while j < n and not lines[j].strip().startswith("```"):
                    code.append(lines[j]); j += 1
                out.append(f"<pre><code>{esc(chr(10).join(code))}</code></pre>")
                i = j + 1; continue
            m = re.match(r"^\{\{\s*(\w+)\s*(.*?)\s*\}\}$", s)
            if m:
                out.append(self.directive(m.group(1), m.group(2))); i += 1; continue
            m = re.match(r"^(#{1,4})\s+(.*?)(?:\s+\{#([\w-]+)\})?\s*$", s)
            if m:
                lvl, txt, anchor = len(m.group(1)), m.group(2), m.group(3)
                if lvl == 1 and self.title is None:
                    self.title = txt
                else:
                    hid = self._uid(anchor or slugify(txt))
                    out.append(f'<h{lvl} id="{hid}">{self.inline(txt)}</h{lvl}>')
                i += 1; continue
            if s.startswith(">"):
                j = i; inner = []
                while j < n and lines[j].strip().startswith(">"):
                    inner.append(re.sub(r"^\s*>\s?", "", lines[j])); j += 1
                out.append(f'<div class="note">{Markdown(self.link, self.directive)._blocks(inner)}</div>')
                i = j; continue
            if s.startswith("|"):
                j = i; rows = []
                while j < n and lines[j].strip().startswith("|"):
                    rows.append(lines[j].strip()); j += 1
                out.append(self._table(rows)); i = j; continue
            if s.startswith("<"):
                j = i; raw = []
                while j < n and lines[j].strip():
                    raw.append(lines[j]); j += 1
                out.append("\n".join(raw)); i = j; continue
            if LIST_RE.match(line):
                j = i; items = []
                while j < n:
                    l = lines[j]
                    lm = LIST_RE.match(l)
                    if lm:
                        items.append([len(lm.group(1).expandtabs(4)), lm.group(2)[-1] == ".", lm.group(3)])
                    elif l.strip() and items and (l.startswith("  ") or not self._starts_block(l)):
                        items[-1][2] += " " + l.strip()
                    elif not l.strip() and j + 1 < n and (LIST_RE.match(lines[j + 1]) or lines[j + 1].startswith("  ")):
                        pass
                    else:
                        break
                    j += 1
                out.append(self._list(items)); i = j; continue
            j = i; para = []
            while j < n and lines[j].strip() and not (j > i and self._starts_block(lines[j])):
                para.append(lines[j].strip()); j += 1
            out.append(f"<p>{self.inline(' '.join(para))}</p>"); i = j
        return "\n".join(out)

    def _list(self, items):
        def build(k, indent):
            ordered = items[k][1]
            tag = "ol" if ordered else "ul"
            parts = [f"<{tag}>"]
            while k < len(items) and items[k][0] >= indent:
                if items[k][0] > indent:
                    sub, k = build(k, items[k][0])
                    parts[-1] = parts[-1][:-5] + sub + "</li>"
                    continue
                parts.append(f"<li>{self.inline(items[k][2])}</li>")
                k += 1
            parts.append(f"</{tag}>")
            return "".join(parts), k
        res, k, out = "", 0, []
        while k < len(items):
            res, k = build(k, items[k][0]); out.append(res)
        return "".join(out)

    def _table(self, rows):
        cells = lambda r: [c.strip() for c in r.strip("|").split("|")]
        head = cells(rows[0])
        body = [cells(r) for r in rows[2:]] if len(rows) > 1 and re.match(r"^\|[\s:|-]+\|?$", rows[1]) else [cells(r) for r in rows[1:]]
        h = "".join(f"<th>{self.inline(c)}</th>" for c in head)
        b = "".join("<tr>" + "".join(f"<td>{self.inline(c)}</td>" for c in r) + "</tr>" for r in body)
        return f'<div class="tablewrap"><table><thead><tr>{h}</tr></thead><tbody>{b}</tbody></table></div>'


def strip_tags(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s))).strip()

def shorten(s, n):
    s = strip_tags(s)
    return s if len(s) <= n else s[: n - 1].rsplit(" ", 1)[0].rstrip(",;:–-") + " …"


# ===================================================================== CHANGELOG
def parse_changelog(path):
    """[{version, date, body}] – body = Markdown der Stichpunkte (auch eingerueckte)."""
    if not path.exists():
        return []
    entries, cur = [], None
    for line in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^##\s+(\S+)\s+[–-]\s+(\d{4}-\d{2}-\d{2})", line)
        if m:
            cur = {"version": m.group(1), "date": m.group(2), "body": []}
            entries.append(cur)
        elif cur is not None and line.startswith("#"):
            cur = None
        elif cur is not None:
            cur["body"].append(line)
    for e in entries:
        e["body"] = "\n".join(e["body"]).strip()
    return entries


# ===================================================================== Seite bauen
class Site:
    def __init__(self, src, stable, out, preview):
        self.src, self.stable, self.out, self.preview = src, stable, out, preview
        sd = src / "site"
        self.sd = sd
        self.cfg = json.loads((sd / "config.json").read_text(encoding="utf-8"))
        self.imp = json.loads((sd / "impressum.json").read_text(encoding="utf-8"))
        self.i18n = json.loads((sd / "i18n.json").read_text(encoding="utf-8"))
        missing = [k for k in self.i18n["de"] if k not in self.i18n["en"]]
        if missing:
            die("site/i18n.json: auf Englisch fehlt " + ", ".join(missing))
        self.base = self.cfg["site_url"].rstrip("/")
        self.legal_ok = all(str(self.imp.get(k, "")).strip() for k in ("name", "email"))
        self.has_address = all(str(self.imp.get(k, "")).strip() for k in ("street", "city"))
        self.changelog = {"de": parse_changelog(stable / "CHANGELOG.md"), "en": parse_changelog(stable / "CHANGELOG.en.md")}
        if not self.changelog["de"]:
            die(f"keine Versionen in {stable / 'CHANGELOG.md'}")
        self.latest = self.changelog["de"][0]
        self.asset_ver = {}
        self.sitemap = []

    # ---------------------------------------------------------- Helfer
    def t(self, lang, key, **kw):
        s = self.i18n[lang].get(key, self.i18n["de"].get(key, key))
        for k, v in kw.items():
            s = s.replace("{" + k + "}", str(v))
        return s

    def url(self, key, lang, anchor=""):
        slug = SLUGS[key][lang]
        u = ("/" if lang == "de" else "/en/") + (slug + "/" if slug else "")
        return u + (("#" + anchor) if anchor else "")

    def fmt_date(self, d, lang):
        y, m, dd = (int(x) for x in d.split("-"))
        mon = MONTHS[lang][m - 1]
        return f"{dd}. {mon} {y}" if lang == "de" else f"{mon} {dd}, {y}"

    def linker(self, lang):
        def link(u):
            m = re.match(r"^(?:seite|page):([\w-]+)(?:#([\w-]+))?$", u)
            if m:
                if m.group(1) not in SLUGS:
                    die(f"unbekanntes Link-Ziel {u}")
                return self.url(m.group(1), lang, m.group(2) or "")
            return u
        return link

    def write(self, rel, content, sitemap=True):
        p = self.out / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        if sitemap and rel.endswith("index.html"):
            self.sitemap.append("/" + rel[: -len("index.html")])

    def asset(self, name):
        return f"/assets/{name}?v={self.asset_ver.get(name, '1')}"

    # ---------------------------------------------------------- Rahmen
    def page(self, lang, key, title, body, *, desc=None, alt=None, cls="", h1=None, lead=None, crumbs=None, full_title=None):
        alt = alt or {l: self.url(key, l) for l in LANGS}
        other = "en" if lang == "de" else "de"
        desc = desc or self.t(lang, "meta.desc")
        canonical = self.base + alt[lang]
        doc_title = full_title or f"{title} – VoidStation"
        cur = ' aria-current="page"'
        nav = "".join(
            f'<a class="pill{" on" if k == key else ""}" href="{self.url(k, lang)}"'
            f'{cur if k == key else ""}>{esc(self.t(lang, "nav." + k))}</a>' for k in NAV)
        banner = ""
        robots = ""
        if self.preview and not self.legal_ok:
            banner = f'<div class="preview">{esc(self.t(lang, "preview.banner"))}</div>'
            robots = '<meta name="robots" content="noindex">'
        head_h1 = ""
        if h1 is not False:
            crumb = f'<p class="crumb">{crumbs}</p>' if crumbs else ""
            lead_html = f'<p class="lead">{lead}</p>' if lead else ""
            head_h1 = f'<div class="pagehead">{crumb}<h1>{h1 or esc(title)}</h1>{lead_html}</div>'
        hreflang = "".join(f'<link rel="alternate" hreflang="{l}" href="{self.base}{alt[l]}">' for l in LANGS)
        foot_links = " · ".join([
            f'<a href="{self.url("impressum", lang)}">{esc(self.t(lang, "foot.impressum"))}</a>',
            f'<a href="{self.url("privacy", lang)}">{esc(self.t(lang, "foot.privacy"))}</a>',
            f'<a href="{esc(self.cfg["github"])}" rel="noopener">GitHub</a>',
            f'<a href="{self.url("news", lang)}feed.xml">RSS</a>',
            f'<a href="{alt[other]}" hreflang="{other}" lang="{other}">{esc(self.t(other, "lang.name"))}</a>',
        ])
        return f"""<!doctype html>
<html lang="{lang}" data-copy="{esc(self.t(lang, 'copy'))}" data-copied="{esc(self.t(lang, 'copied'))}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(doc_title)}</title>
<meta name="description" content="{esc(desc)}">
{robots}<link rel="canonical" href="{canonical}">
{hreflang}
<link rel="icon" href="/assets/favicon.svg" type="image/svg+xml">
<link rel="apple-touch-icon" href="/assets/apple-touch-icon.png">
<link rel="alternate" type="application/rss+xml" title="VoidStation News" href="{self.url('news', lang)}feed.xml">
<meta name="theme-color" content="#0e1012">
<meta property="og:type" content="website">
<meta property="og:site_name" content="VoidStation">
<meta property="og:title" content="{esc(doc_title)}">
<meta property="og:description" content="{esc(desc)}">
<meta property="og:url" content="{canonical}">
<meta property="og:image" content="{self.base}/assets/og.png">
<meta property="og:locale" content="{'de_DE' if lang == 'de' else 'en_US'}">
<link rel="stylesheet" href="{self.asset('style.css')}">
<script src="{self.asset('site.js')}" defer></script>
</head>
<body class="{cls}">
{banner}<a class="skip" href="#inhalt">{esc(self.t(lang, 'skip'))}</a>
<header class="top">
  <a class="brand" href="{self.url('home', lang)}"><img src="/assets/logo.svg" alt="VoidStation" width="170" height="30"></a>
  <nav class="nav" aria-label="{esc(self.t(lang, 'nav.label'))}">{nav}</nav>
  <div class="tools">
    <a class="round lang" href="{alt[other]}" hreflang="{other}" lang="{other}" title="{esc(self.t(other, 'lang.name'))}">{other.upper()}</a>
    <a class="round" href="{esc(self.cfg['github'])}" rel="noopener" title="GitHub" aria-label="GitHub">{ICONS['github']}</a>
  </div>
</header>
<main id="inhalt">
{head_h1}
{body}
</main>
<footer class="foot">
  <div class="fl"><img src="/assets/logo.svg" alt="" width="120" height="21"></div>
  <p>{foot_links}</p>
  <p class="dim">{esc(self.t(lang, 'foot.license'))} · {esc(self.t(lang, 'foot.ai'))}</p>
</footer>
</body>
</html>
"""

    # ---------------------------------------------------------- Bausteine
    def directive(self, lang):
        def d(name, arg):
            if name == "iso":
                return self.iso_card(lang)
            if name == "screens":
                return self.screens(lang)
            if name == "impressum":
                return self.address(lang, full=True)
            if name == "controller":
                return self.address(lang, full=False)
            if name == "latest":
                return (f'<p class="dim">{esc(self.t(lang, "latest.line", v=self.latest["version"], d=self.fmt_date(self.latest["date"], lang)))} '
                        f'<a href="{self.url("news", lang)}v{esc(self.latest["version"])}/">{esc(self.t(lang, "latest.more"))}</a></p>')
            die(f"unbekannter Baustein {{{{{name}}}}}")
        return d

    def iso_file(self):
        iso = self.cfg.get("iso", {})
        for part in reversed(iso.get("url", "").split("?")[0].split("/")):
            if part.endswith(".iso"):
                return part
        return f'voidstation-{iso.get("version") or self.latest["version"]}.iso'

    def iso_card(self, lang):
        iso = self.cfg.get("iso", {})
        sf = self.cfg.get("sourceforge", "")
        if iso.get("url"):
            ver = iso.get("version", "")
            meta = []
            if iso.get("size_mb"):
                meta.append(self.t(lang, "iso.size", mb=iso["size_mb"]))
            if iso.get("date"):
                meta.append(self.fmt_date(iso["date"], lang))
            meta.append("x86_64")
            sha = (f'<p class="sha"><span>SHA-256</span> <code>{esc(iso["sha256"])}</code></p>' if iso.get("sha256") else "")
            more = f'<a href="{esc(sf)}" rel="noopener">{esc(self.t(lang, "iso.all"))}</a>' if sf else ""
            return f"""<div class="isocard">
  <a class="tile large dl" style="--c:#2b5f46" href="{esc(iso['url'])}" rel="noopener">
    <span class="sub">{esc(" · ".join(meta))}</span>
    <span class="icon">{ICONS['download']}</span>
    <span class="label">{esc(self.t(lang, 'iso.button'))}</span>
  </a>
  <div class="isotext">
    <h2 id="iso">{esc(self.t(lang, 'iso.title', v=ver))}</h2>
    <p>{esc(self.t(lang, 'iso.text'))}</p>
    {sha}
    <p>{more}</p>
  </div>
</div>"""
        sf_link = f' <a href="{esc(sf)}" rel="noopener">SourceForge</a>' if sf else ""
        return f"""<div class="isocard soon">
  <div class="tile large dl static" style="--c:#2b5f46">
    <span class="sub">{esc(self.t(lang, 'iso.soon.sub'))}</span>
    <span class="icon">{ICONS['download']}</span>
    <span class="label">{esc(self.t(lang, 'iso.soon.label'))}</span>
  </div>
  <div class="isotext">
    <h2 id="iso">{esc(self.t(lang, 'iso.soon.title'))}</h2>
    <p>{esc(self.t(lang, 'iso.soon.text'))}{sf_link}</p>
  </div>
</div>"""

    def shot(self, lang, f):
        """Screenshot in der Sprache der Seite (docs/screenshots/en/…), sonst der deutsche"""
        if lang != "de" and (self.out / "assets" / "screens" / lang / f).exists():
            return f"/assets/screens/{lang}/{f}"
        return f"/assets/screens/{f}"

    def screens(self, lang):
        figs = []
        for f, key in (("1-start.webp", "s.start"), ("2-fernsehen.webp", "s.tv"), ("3-appcenter.webp", "s.appcenter"),
                       ("4-radio.webp", "s.radio"), ("5-installer.webp", "s.installer"), ("6-ziel-ssd.webp", "s.disk")):
            if (self.out / "assets" / "screens" / f).exists():
                cap = esc(self.t(lang, key))
                src = self.shot(lang, f)
                figs.append(f'<figure><a href="{src}"><img src="{src}" alt="{cap}" loading="lazy" width="1600" height="900"></a><figcaption>{cap}</figcaption></figure>')
        return f'<div class="screens">{"".join(figs)}</div>'

    def address(self, lang, full):
        g = lambda k, ph: esc(self.imp.get(k) or ph)
        name = g("name", "‹Name›"); street = g("street", "‹Straße Nr.›"); city = g("city", "‹PLZ Ort›")
        email = self.imp.get("email") or "‹E-Mail›"
        mail_html = "".join(f"&#{ord(c)};" for c in email)       # einfache Verschleierung gegen Adress-Sammler
        mail = f'<a href="&#109;&#97;&#105;&#108;&#116;&#111;&#58;{mail_html}">{mail_html}</a>' if self.imp.get("email") else esc(email)
        lines = [name, street, city] if (self.has_address or not self.legal_ok) else [name]
        if self.imp.get("country"):
            lines.append(esc(self.imp["country"]))
        contact = f'{esc(self.t(lang, "imp.email"))}: {mail}'
        if self.imp.get("phone"):
            contact += f'<br>{esc(self.t(lang, "imp.phone"))}: {esc(self.imp["phone"])}'
        return f'<div class="address"><p>{"<br>".join(lines)}</p><p>{contact}</p></div>'

    # ---------------------------------------------------------- News
    def version_entry(self, lang, version):
        for e in self.changelog[lang]:
            if e["version"] == version:
                return e, False
        for e in self.changelog["de"]:
            if e["version"] == version:
                return e, lang != "de"
        return None, False

    def collect_news(self):
        items = []
        for e in self.changelog["de"]:
            item = {"kind": "version", "date": e["date"], "slug": "v" + e["version"], "version": e["version"], "title": {}, "html": {}, "excerpt": {}, "fallback": {}}
            for lang in LANGS:
                entry, fb = self.version_entry(lang, e["version"])
                md = Markdown(self.linker(lang))
                body = md.render(entry["body"])
                item["title"][lang] = self.t(lang, "news.version_title", v=e["version"])
                item["fallback"][lang] = fb
                item["html"][lang] = body
                first = re.search(r"<li>(.*?)(?:</li>|<ul>|<ol>)", body, re.S)
                item["excerpt"][lang] = shorten(first.group(1) if first else body, 170)
            items.append(item)
        posts = {}
        for p in sorted((self.sd / "news").glob("*.md")):
            m = re.match(r"^(\d{4}-\d{2}-\d{2})-([\w-]+)\.(de|en)\.md$", p.name)
            if not m:
                warn(f"News-Datei ignoriert (Name: JJJJ-MM-TT-name.de.md): {p.name}")
                continue
            posts.setdefault((m.group(1), m.group(2)), {})[m.group(3)] = p
        for (d, slug), files in posts.items():
            if "de" not in files and "en" not in files:
                continue
            item = {"kind": "post", "date": d, "slug": slug, "title": {}, "html": {}, "excerpt": {}, "fallback": {}}
            for lang in LANGS:
                f = files.get(lang) or files.get("de") or files.get("en")
                md = Markdown(self.linker(lang), self.directive(lang))
                body = md.render(f.read_text(encoding="utf-8"))
                item["title"][lang] = md.title or slug
                item["html"][lang] = body
                item["fallback"][lang] = lang not in files
                first = re.search(r"<p>(.*?)</p>", body, re.S)
                item["excerpt"][lang] = shorten(first.group(1) if first else body, 190)
            items.append(item)
        items.sort(key=lambda x: (x["date"], x["kind"] == "post"), reverse=True)
        return items

    def news_row(self, it, lang, h="h2"):
        icon = ICONS["update"] if it["kind"] == "version" else ICONS["chat"]
        color = "#2d3763" if it["kind"] == "version" else "#24414a"
        kind = self.t(lang, "news.kind." + it["kind"])
        return (f'<a class="newsrow" data-kind="{it["kind"]}" href="{self.url("news", lang)}{esc(it["slug"])}/">'
                f'<span class="sq" style="--c:{color}">{icon}</span>'
                f'<span class="nb"><span class="meta"><span class="badge">{esc(kind)}</span> <time datetime="{it["date"]}">{esc(self.fmt_date(it["date"], lang))}</time></span>'
                f'<{h}>{esc(it["title"][lang])}</{h}><span class="ex">{esc(it["excerpt"][lang])}</span></span></a>')

    def build_news(self, items):
        for lang in LANGS:
            chips = "".join(f'<button type="button" class="pill{" on" if k == "all" else ""}" data-filter="{k}" aria-pressed="{str(k == "all").lower()}">{esc(self.t(lang, "news." + k))}</button>'
                            for k in ("all", "version", "post"))
            rows = "".join(self.news_row(it, lang) for it in items)
            body = f'<div class="page wide"><div class="chips" role="group">{chips}<a class="pill" href="feed.xml">{ICONS["rss"]} RSS</a></div><div class="newslist">{rows}</div></div>'
            self.write(self.url("news", lang).lstrip("/") + "index.html",
                       self.page(lang, "news", self.t(lang, "news.title"), body, lead=esc(self.t(lang, "news.lead")), desc=self.t(lang, "news.lead"), cls="newspage"))
            for k, it in enumerate(items):
                alt = {l: f'{self.url("news", l)}{it["slug"]}/' for l in LANGS}
                note = f'<div class="note"><p>{esc(self.t(lang, "news.only_de"))}</p></div>' if it["fallback"][lang] else ""
                if it["kind"] == "version":
                    content = (f'<p>{esc(self.t(lang, "news.version_intro", v=it["version"]))}</p>{it["html"][lang]}'
                               f'<div class="note"><p>{self.t(lang, "news.update_hint", dl=self.url("download", lang))}</p></div>')
                else:
                    content = it["html"][lang]
                newer = items[k - 1] if k > 0 else None
                older = items[k + 1] if k + 1 < len(items) else None
                pn = '<nav class="pn">'
                pn += (f'<a class="prev" href="../{esc(older["slug"])}/"><small>{esc(self.t(lang, "news.older"))}</small>{esc(older["title"][lang])}</a>' if older else "<span></span>")
                pn += (f'<a class="next" href="../{esc(newer["slug"])}/"><small>{esc(self.t(lang, "news.newer"))}</small>{esc(newer["title"][lang])}</a>' if newer else "<span></span>")
                pn += "</nav>"
                kind = esc(self.t(lang, "news.kind." + it["kind"]))
                crumbs = (f'<a href="{self.url("news", lang)}">{esc(self.t(lang, "news.title"))}</a> · <span class="badge">{kind}</span> '
                          f'<time datetime="{it["date"]}">{esc(self.fmt_date(it["date"], lang))}</time>')
                body = f'<article class="page prose">{note}{content}{pn}</article>'
                self.write(f'{alt[lang].lstrip("/")}index.html',
                           self.page(lang, "news", it["title"][lang], body, alt=alt, crumbs=crumbs, desc=it["excerpt"][lang]))
            self.feed(items, lang)

    def feed(self, items, lang):
        now = format_datetime(datetime.now(timezone.utc))
        out = []
        for it in items[:30]:
            link = f'{self.base}{self.url("news", lang)}{it["slug"]}/'
            d = datetime.strptime(it["date"], "%Y-%m-%d").replace(hour=12, tzinfo=timezone.utc)
            out.append(f"<item><title>{esc(it['title'][lang])}</title><link>{link}</link><guid>{link}</guid>"
                       f"<pubDate>{format_datetime(d)}</pubDate><description>{esc(it['html'][lang])}</description></item>")
        xml = (f'<?xml version="1.0" encoding="utf-8"?>\n<rss version="2.0"><channel><title>VoidStation News</title>'
               f'<link>{self.base}{self.url("news", lang)}</link><description>{esc(self.t(lang, "news.lead"))}</description>'
               f'<language>{"de-de" if lang == "de" else "en-us"}</language><lastBuildDate>{now}</lastBuildDate>{"".join(out)}</channel></rss>\n')
        self.write(self.url("news", lang).lstrip("/") + "feed.xml", xml, sitemap=False)

    # ---------------------------------------------------------- Startseite
    def tile(self, size, color, href, label, icon=None, sub="", extra="", cls="", img=None, ext=False):
        rel = ' rel="noopener"' if ext else ""
        inner = ""
        if img:
            inner += f'<img class="cover" src="{img}" alt="" loading="lazy">'
        if sub:
            inner += f'<span class="sub">{esc(sub)}</span>'
        if icon:
            inner += f'<span class="icon">{ICONS[icon]}</span>'
        inner += extra
        inner += f'<span class="label">{esc(label)}</span>'
        return f'<a class="tile {size} {cls}" style="--c:{color}" href="{href}"{rel}>{inner}</a>'

    def build_home(self, items):
        # 3 Gruppen, je 3 Kachelreihen hoch, zusammen 8 Spalten (3 + 2 + 3) – passt zu --u in style.css
        v = self.latest["version"]
        for lang in LANGS:
            t = lambda k, **kw: self.t(lang, k, **kw)
            u = lambda k, a="": self.url(k, lang, a)
            posts = [i for i in items if i["kind"] == "post"] or items
            news = posts[0]
            gh = self.cfg["github"]
            g1 = "".join([
                self.tile("large", "#2b5f46", u("download"), t("t.download"), "download", t("t.download.sub"), cls="dl"),
                self.tile("wide", "#2d3763", f'{u("news")}v{v}/', t("t.latest"), cls="ver",
                          extra=f'<span class="kick">{esc(self.fmt_date(self.latest["date"], lang))}</span><span class="big">{esc(v)}</span>'),
                self.tile("medium", "#3a3f46", u("download", "installieren" if lang == "de" else "install"), t("t.install"), "cube"),
                self.tile("medium", "#3b2f4f", u("help", "bedienung" if lang == "de" else "controls"), t("t.controls"), "gamepad"),
                self.tile("medium", "#284843", u("download", "voraussetzungen" if lang == "de" else "requirements"), t("t.req"), "monitor"),
            ])
            g2 = "".join([
                self.tile("large", "#22262b", u("features", "screenshots"), t("t.screens"), img=self.shot(lang, "1-start.webp"), cls="pic"),
                self.tile("wide", "#6e2b2b", u("features"), t("t.features"), "play", t("t.features.sub")),
            ])
            g3 = "".join([
                # links drei breite (News, GitHub, Fragen), rechts drei kleine (Fehler, Mitmachen, Lizenz)
                self.tile("wide", "#24414a", f'{u("news")}{news["slug"]}/', t("t.news"),
                          extra=f'<span class="kick">{esc(self.fmt_date(news["date"], lang))}</span><span class="txt">{esc(news["title"][lang])}</span>', cls="text"),
                self.tile("wide", "#2f3238", gh, "GitHub", sub=t("t.github.sub"), extra=f'<span class="icon">{ICONS["github"]}</span>', ext=True),
                self.tile("wide", "#2b5f46", gh + "/discussions", t("t.discuss"), "help", t("t.discuss.sub"), ext=True),
                self.tile("medium", "#6e2b2b", gh + "/issues", t("t.issues"), "bug", ext=True),
                self.tile("medium", "#39414d", u("contribute"), t("t.contribute"), "chat"),
                self.tile("medium", "#3a3f46", u("contribute", "lizenz" if lang == "de" else "license"), "GPL-3.0", "scale"),
            ])
            groups = (f'<section class="group g1"><h2>{esc(t("g.start"))}</h2><div class="grid">{g1}</div></section>'
                      f'<section class="group g2"><h2>{esc(t("g.explore"))}</h2><div class="grid">{g2}</div></section>'
                      f'<section class="group g3"><h2>{esc(t("g.project"))}</h2><div class="grid">{g3}</div></section>')
            hero = (f'<div class="hero"><h1>{esc(t("home.h1"))}</h1><p class="lead">{esc(t("home.lead"))}</p></div>')
            body = f'{hero}<div class="track">{groups}</div>'
            self.write(u("home").lstrip("/") + "index.html",
                       self.page(lang, "home", "VoidStation", body, h1=False, cls="home", full_title=t("home.title")))

    # ---------------------------------------------------------- Inhaltsseiten
    def build_pages(self):
        for key in ("download", "features", "help", "contribute", "impressum", "privacy"):
            for lang in LANGS:
                f = self.sd / "pages" / f"{key}.{lang}.md"
                if not f.exists():
                    die(f"fehlt: {f.relative_to(self.src)}")
                src = f.read_text(encoding="utf-8").replace("{{v}}", self.latest["version"]).replace("{{isofile}}", self.iso_file())
                md = Markdown(self.linker(lang), self.directive(lang))
                body = md.render(src)
                title = md.title or key
                lead = ""
                m = re.match(r"^<p>(.*?)</p>\n?", body, re.S)
                if m:                                    # erster Absatz = Vorspann unter dem Titel
                    lead, body = m.group(1), body[m.end():]
                self.write(self.url(key, lang).lstrip("/") + "index.html",
                           self.page(lang, key, strip_tags(title), f'<div class="page prose">{body}</div>', lead=lead, desc=strip_tags(lead) or None))

    # ---------------------------------------------------------- Sonstiges
    def build_404(self):
        body = (f'<div class="page prose center"><p class="big404">404</p>'
                f'<p>{esc(self.t("de", "404.text"))} <a href="/">{esc(self.t("de", "404.home"))}</a></p>'
                f'<p lang="en">{esc(self.t("en", "404.text"))} <a href="/en/">{esc(self.t("en", "404.home"))}</a></p></div>')
        self.write("404.html", self.page("de", "home", self.t("de", "404.title"), body, h1=False), sitemap=False)

    def build_construction(self):
        for lang in LANGS:
            other = "en" if lang == "de" else "de"
            doc = f"""<!doctype html>
<html lang="{lang}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>VoidStation</title><meta name="robots" content="noindex"><link rel="icon" href="/assets/favicon.svg" type="image/svg+xml">
<link rel="stylesheet" href="{self.asset('style.css')}"></head>
<body class="construction"><main><img src="/assets/logo.svg" alt="VoidStation" width="340" height="61">
<p>{esc(self.t(lang, 'wip.text'))}</p>
<p><a class="btn" href="{esc(self.cfg['github'])}" rel="noopener">{esc(self.t(lang, 'wip.github'))}</a></p>
<p class="dim"><a href="{'/' if other == 'de' else '/en/'}" lang="{other}">{esc(self.t(other, 'lang.name'))}</a></p></main></body></html>
"""
            self.write(("" if lang == "de" else "en/") + "index.html", doc, sitemap=False)
        self.write("404.html", '<!doctype html><meta charset="utf-8"><title>404</title><p>404 – <a href="/">voidstation.de</a></p>\n', sitemap=False)
        self.write("robots.txt", "User-agent: *\nDisallow: /\n", sitemap=False)

    def copy_static(self):
        a = self.out / "assets"
        shutil.copytree(self.sd / "assets", a)
        for name in ("style.css", "site.js"):
            self.asset_ver[name] = hashlib.sha256((a / name).read_bytes()).hexdigest()[:10]
        shots = self.src / "docs" / "screenshots"
        if shots.is_dir():
            shutil.copytree(shots, a / "screens")

    def copy_channels(self):
        for name, repo in (("main", self.src), ("stable", self.stable)):
            d = repo / "dist"
            if d.is_dir() and any(d.iterdir()):
                shutil.copytree(d, self.out / name / "dist")
            else:
                warn(f"kein dist/ in {repo} – Kanal {name} fehlt auf der Seite")
        (self.out / "CNAME").write_text(self.base.split("://", 1)[1] + "\n")

    def build(self):
        if self.out.exists():
            shutil.rmtree(self.out)
        self.out.mkdir(parents=True)
        self.copy_static()
        self.copy_channels()
        if not self.legal_ok and not self.preview:
            warn("site/impressum.json: name und email fehlen – nur Baustellenseite gebaut.")
            warn("Ansehen trotzdem moeglich mit:  python3 tools/build-site.py --preview")
            self.build_construction()
            return
        if self.legal_ok and not self.has_address:
            warn("site/impressum.json: ohne Anschrift (street, city) – Impressum zeigt nur Name und E-Mail.")
        items = self.collect_news()
        self.build_home(items)
        self.build_pages()
        self.build_news(items)
        self.build_404()
        robots = "User-agent: *\nDisallow: /main/\nDisallow: /stable/\n"
        if self.preview and not self.legal_ok:
            robots = "User-agent: *\nDisallow: /\n"
        self.write("robots.txt", robots + f"Sitemap: {self.base}/sitemap.xml\n", sitemap=False)
        today = date.today().isoformat()
        urls = "".join(f"<url><loc>{self.base}{p}</loc><lastmod>{today}</lastmod></url>" for p in sorted(set(self.sitemap)))
        self.write("sitemap.xml", f'<?xml version="1.0" encoding="utf-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>\n', sitemap=False)
        n = len(list(self.out.rglob("*.html")))
        print(f"Webseite gebaut: {n} Seiten, {len(items)} News, Version {self.latest['version']} -> {self.out}")


def main():
    ap = argparse.ArgumentParser(description="Webseite voidstation.de bauen")
    ap.add_argument("--src", default=str(ROOT), help="Repo mit site/ und dist/ des Kanals Testing (Standard: dieses Repo)")
    ap.add_argument("--stable", default=None, help="Stand des Kanals Stable (CHANGELOG, dist/); Standard: --src")
    ap.add_argument("--out", default=None, help="Ausgabeordner (Standard: <src>/_site)")
    ap.add_argument("--preview", action="store_true", help="komplette Seite auch ohne Impressum bauen (nur zum Ansehen)")
    a = ap.parse_args()
    src = Path(a.src).resolve()
    stable = Path(a.stable).resolve() if a.stable else src
    out = Path(a.out).resolve() if a.out else src / "_site"
    if not (src / "site" / "config.json").exists():
        die(f"{src}/site/config.json fehlt")
    Site(src, stable, out, a.preview).build()


if __name__ == "__main__":
    main()
