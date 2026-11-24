#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""
VoidStation Sound Synthesizer
-----------------------------
Erzeugt lizenzfreie, konsolenartige Standard-Oberflaechentoene (48 kHz, 16-Bit PCM WAV)
fuer die drei Klangstile `void`, `retro` und `minimal`.

Aufruf:
  python3 tools/gen-sounds.py                          # erzeugt launcher/web/sounds/{void,retro,minimal}/*.wav
  python3 tools/gen-sounds.py --preset void --out ~/.local/share/voidstation/sounds
"""
from __future__ import annotations

import argparse
import math
import random
import struct
import wave
from pathlib import Path
from typing import Callable

SR = 48000
REPO = Path(__file__).resolve().parent.parent
DEFAULT_OUT = REPO / "launcher" / "web" / "sounds"
PRESETS = ("void", "retro", "minimal")


# ---------------------------------------------------------------------------
#  DSP-Bausteine
# ---------------------------------------------------------------------------
def _zeros(dur: float) -> list[float]:
    return [0.0] * max(1, int(round(dur * SR)))


def _env(n: int, att_ms: float = 3.0, dec_exp: float = 4.5, tail_ms: float = 12.0) -> list[float]:
    """Klickfreie Huellkurve: weicher Cosinus-Anstieg + exponentieller Abfall + Auslauf."""
    a = min(n, max(1, int(SR * att_ms / 1000.0)))
    r = min(n, max(1, int(SR * tail_ms / 1000.0)))
    out = [0.0] * n
    for i in range(n):
        t = i / max(1, n - 1)
        g = math.exp(-dec_exp * t)
        if i < a:
            g *= 0.5 - 0.5 * math.cos(math.pi * i / a)
        if i >= n - r:
            rem = (n - 1 - i) / max(1, r)
            g *= 0.5 - 0.5 * math.cos(math.pi * rem)
        out[i] = g
    return out


def _synth_sweep(
    dur: float,
    f0: float,
    f1: float,
    *,
    sweep_exp: float = 1.0,
    shape: str = "sine",
    harmonics: tuple[tuple[int, float], ...] = (),
    att_ms: float = 3.0,
    dec_exp: float = 5.0,
    tail_ms: float = 10.0,
    amp: float = 1.0,
) -> list[float]:
    """Oszillator mit Frequenzverlauf (Pitch-Envelope) und Oberschwingungen."""
    n = max(1, int(round(dur * SR)))
    env = _env(n, att_ms=att_ms, dec_exp=dec_exp, tail_ms=tail_ms)
    out = [0.0] * n
    phase = 0.0
    two_pi = 2.0 * math.pi
    for i in range(n):
        u = i / max(1, n - 1)
        k = u ** sweep_exp
        f = f0 + (f1 - f0) * k
        phase += two_pi * f / SR
        if shape == "tri":
            # Bandbegrenztes warmes Dreieck (3 ungerade Harmonische)
            v = math.sin(phase) - math.sin(3.0 * phase) / 9.0 + math.sin(5.0 * phase) / 25.0
            v *= 8.0 / (math.pi * math.pi)
        elif shape == "soft_pulse":
            # Warmer 16-Bit-Puls mit sanft gerollten Oberschwingungen
            v = (
                math.sin(phase)
                + 0.45 * math.sin(2.0 * phase)
                + 0.28 * math.sin(3.0 * phase)
                + 0.14 * math.sin(4.0 * phase)
            ) * 0.62
        else:
            v = math.sin(phase)
        for mult, weight in harmonics:
            v += weight * math.sin(mult * phase)
        out[i] = v * env[i] * amp
    return out


def _lowpass(buf: list[float], cutoff_hz: float) -> list[float]:
    rc = 1.0 / (2.0 * math.pi * max(20.0, cutoff_hz))
    dt = 1.0 / SR
    a = dt / (rc + dt)
    out = [0.0] * len(buf)
    y = 0.0
    for i, x in enumerate(buf):
        y += a * (x - y)
        out[i] = y
    return out


def _highpass(buf: list[float], cutoff_hz: float) -> list[float]:
    rc = 1.0 / (2.0 * math.pi * max(20.0, cutoff_hz))
    dt = 1.0 / SR
    a = rc / (rc + dt)
    out = [0.0] * len(buf)
    y = 0.0
    prev_x = 0.0
    for i, x in enumerate(buf):
        y = a * (y + x - prev_x)
        prev_x = x
        out[i] = y
    return out


def _noise_burst(
    rng: random.Random,
    dur: float,
    *,
    lp_hz: float = 3500.0,
    hp_hz: float = 400.0,
    att_ms: float = 1.5,
    dec_exp: float = 10.0,
    amp: float = 0.3,
) -> list[float]:
    n = max(1, int(round(dur * SR)))
    raw = [rng.uniform(-1.0, 1.0) for _ in range(n)]
    shaped = _highpass(_lowpass(raw, lp_hz), hp_hz)
    env = _env(n, att_ms=att_ms, dec_exp=dec_exp, tail_ms=4.0)
    return [shaped[i] * env[i] * amp for i in range(n)]


def _mix_into(dst: list[float], src: list[float], offset_s: float = 0.0, gain: float = 1.0) -> None:
    off = max(0, int(round(offset_s * SR)))
    need = off + len(src)
    if need > len(dst):
        dst.extend([0.0] * (need - len(dst)))
    for i, v in enumerate(src):
        dst[off + i] += v * gain


def _reverb_tail(
    buf: list[float],
    taps_ms: tuple[tuple[float, float], ...] = ((19.0, 0.24), (37.0, 0.16), (61.0, 0.10), (89.0, 0.06)),
    lp_hz: float = 3800.0,
) -> list[float]:
    """Subtiles Multi-Tap-Raumdelay fuer modernen Konsolen-Glanz."""
    max_d = max(int(round(ms * SR / 1000.0)) for ms, _ in taps_ms)
    out = list(buf) + [0.0] * (max_d + int(0.02 * SR))
    wet = _zeros(len(out) / SR)
    for ms, g in taps_ms:
        d = int(round(ms * SR / 1000.0))
        for i, v in enumerate(buf):
            wet[i + d] += v * g
    wet = _lowpass(wet, lp_hz)
    for i in range(len(out)):
        out[i] += wet[i]
    return out


def _finalize_mono(buf: list[float], peak: float = 0.72) -> list[float]:
    fade = min(len(buf), int(0.012 * SR))
    out = [math.tanh(v * 0.9) for v in buf]
    for i in range(fade):
        idx = len(out) - 1 - i
        out[idx] *= i / max(1, fade)
    mx = max((abs(v) for v in out), default=1.0)
    if mx > 1e-6:
        scale = peak / mx
        out = [v * scale for v in out]
    return out


def _finalize_stereo(left: list[float], right: list[float], peak: float = 0.76) -> tuple[list[float], list[float]]:
    n = max(len(left), len(right))
    left = left + [0.0] * (n - len(left))
    right = right + [0.0] * (n - len(right))
    fade = min(n, int(0.025 * SR))
    l_out = [math.tanh(v * 0.88) for v in left]
    r_out = [math.tanh(v * 0.88) for v in right]
    for i in range(fade):
        idx = n - 1 - i
        g = i / max(1, fade)
        l_out[idx] *= g
        r_out[idx] *= g
    mx = max(max((abs(v) for v in l_out), default=0.0), max((abs(v) for v in r_out), default=0.0), 1e-6)
    scale = peak / mx
    return [v * scale for v in l_out], [v * scale for v in r_out]


def _write_wav(path: Path, channels: list[list[float]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    nch = len(channels)
    nframes = len(channels[0])
    pcm = bytearray(nframes * nch * 2)
    off = 0
    for i in range(nframes):
        for ch in range(nch):
            s = max(-1.0, min(1.0, channels[ch][i]))
            struct.pack_into("<h", pcm, off, int(round(s * 32767.0)))
            off += 2
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(nch)
        wf.setsampwidth(2)
        wf.setframerate(SR)
        wf.writeframes(pcm)


# ---------------------------------------------------------------------------
#  Preset 1: VOID (Standard – modern, warm, tiefraeumlich, knackig)
# ---------------------------------------------------------------------------
def _build_void(rng: random.Random) -> dict[str, list[list[float]]]:
    sounds: dict[str, list[list[float]]] = {}

    # navigate: weicher Sub-Thock + feiner Seiden-Klick (~55 ms)
    nav = _zeros(0.058)
    _mix_into(nav, _synth_sweep(0.048, 340.0, 175.0, sweep_exp=0.55, harmonics=((2, 0.14),), att_ms=2.0, dec_exp=7.0), 0.0, 0.8)
    _mix_into(nav, _noise_burst(rng, 0.018, lp_hz=3800.0, hp_hz=900.0, dec_exp=11.0, amp=0.22), 0.0, 1.0)
    sounds["navigate"] = [_finalize_mono(nav, 0.56)]

    # select: eleganter harmonischer Doppel-Akzent (C5 -> G5 + Schimmer)
    sel = _zeros(0.14)
    _mix_into(sel, _synth_sweep(0.065, 523.25, 540.0, harmonics=((2, 0.22), (3, 0.06)), att_ms=2.0, dec_exp=6.5), 0.0, 0.72)
    _mix_into(sel, _synth_sweep(0.115, 783.99, 783.99, harmonics=((2, 0.18), (3, 0.05)), att_ms=2.5, dec_exp=4.8), 0.032, 0.85)
    _mix_into(sel, _noise_burst(rng, 0.014, lp_hz=4500.0, hp_hz=1200.0, dec_exp=12.0, amp=0.16), 0.0, 1.0)
    sounds["select"] = [_finalize_mono(_reverb_tail(sel, ((18.0, 0.18), (39.0, 0.10)), lp_hz=3600.0), 0.70)]

    # back: weicher absteigender Intervall-Impuls (G4 -> D4)
    bak = _zeros(0.12)
    _mix_into(bak, _synth_sweep(0.060, 415.30, 392.0, harmonics=((2, 0.12),), att_ms=2.5, dec_exp=6.5), 0.0, 0.70)
    _mix_into(bak, _synth_sweep(0.095, 293.66, 265.0, harmonics=((2, 0.08),), att_ms=2.5, dec_exp=5.5), 0.030, 0.80)
    sounds["back"] = [_finalize_mono(_reverb_tail(bak, ((20.0, 0.14),), lp_hz=2400.0), 0.66)]

    # group: luftiger Whoosh + heller Quart-Wechsel
    grp = _zeros(0.14)
    _mix_into(grp, _noise_burst(rng, 0.085, lp_hz=2800.0, hp_hz=450.0, att_ms=14.0, dec_exp=5.5, amp=0.35), 0.0, 1.0)
    _mix_into(grp, _synth_sweep(0.110, 392.0, 587.33, sweep_exp=0.7, harmonics=((2, 0.20),), att_ms=5.0, dec_exp=5.0), 0.010, 0.75)
    sounds["group"] = [_finalize_mono(_reverb_tail(grp, ((22.0, 0.18), (45.0, 0.10)), lp_hz=3400.0), 0.68)]

    # toggle: knackiges Switch-Pop + klarer Aufwaerts-Lift
    tog = _zeros(0.095)
    _mix_into(tog, _noise_burst(rng, 0.015, lp_hz=5000.0, hp_hz=1100.0, dec_exp=12.0, amp=0.25), 0.0, 1.0)
    _mix_into(tog, _synth_sweep(0.085, 440.0, 659.25, sweep_exp=0.65, harmonics=((2, 0.22),), att_ms=2.0, dec_exp=6.0), 0.008, 0.85)
    sounds["toggle"] = [_finalize_mono(_reverb_tail(tog, ((16.0, 0.14),), lp_hz=3200.0), 0.68)]

    # volume: runder, nicht ermuedender Pegel-Blip
    vol = _zeros(0.072)
    _mix_into(vol, _synth_sweep(0.068, 560.0, 620.0, sweep_exp=0.5, harmonics=((2, 0.12),), att_ms=2.5, dec_exp=7.0), 0.0, 0.85)
    sounds["volume"] = [_finalize_mono(vol, 0.60)]

    # notify: warmer zweistimmiger Aufstieg (F4 -> A4 -> C5) mit Glanz
    ntf = _zeros(0.25)
    _mix_into(ntf, _synth_sweep(0.14, 523.25, 523.25, harmonics=((2, 0.22), (3, 0.08)), att_ms=3.0, dec_exp=4.2), 0.0, 0.68)
    _mix_into(ntf, _synth_sweep(0.19, 659.25, 659.25, harmonics=((2, 0.20), (3, 0.06)), att_ms=3.0, dec_exp=3.8), 0.055, 0.78)
    _mix_into(ntf, _synth_sweep(0.21, 783.99, 783.99, harmonics=((2, 0.16),), att_ms=4.0, dec_exp=3.6), 0.105, 0.72)
    sounds["notify"] = [_finalize_mono(_reverb_tail(ntf, ((22.0, 0.24), (48.0, 0.16), (78.0, 0.09)), lp_hz=4200.0), 0.72)]

    # error: gedaempfter tiefer Doppelschlag (Tritonus/kleine Sekunde, nie grell)
    err = _zeros(0.26)
    _mix_into(err, _synth_sweep(0.11, 210.0, 175.0, shape="tri", harmonics=((2, 0.25),), att_ms=3.0, dec_exp=5.5), 0.0, 0.85)
    _mix_into(err, _synth_sweep(0.15, 165.0, 128.0, shape="tri", harmonics=((2, 0.28),), att_ms=3.0, dec_exp=4.5), 0.095, 0.90)
    sounds["error"] = [_finalize_mono(_lowpass(_reverb_tail(err, ((18.0, 0.14),), lp_hz=1400.0), 1600.0), 0.72)]

    # startup: Stereo Deep-Space Bloom (warmer Sub + Quinte/None-Akkord + seidiger Shimmer, ~1.25 s)
    st_l, st_r = _zeros(1.25), _zeros(1.25)
    # Sub-Fundament (D2 -> A2 weich einblendend)
    sub = _synth_sweep(1.10, 73.42, 73.42, harmonics=((2, 0.25),), att_ms=65.0, dec_exp=2.2, tail_ms=120.0)
    _mix_into(st_l, sub, 0.02, 0.55)
    _mix_into(st_r, sub, 0.02, 0.55)
    # Arpeggio-Blueprints L/R leicht versetzt fuer Stereo-Breite
    notes = [
        (0.04, 293.66, 0.75, 0.70, 0.55),   # D4
        (0.13, 440.00, 0.80, 0.55, 0.75),   # A4
        (0.22, 587.33, 0.85, 0.72, 0.62),   # D5
        (0.32, 659.25, 0.85, 0.58, 0.78),   # E5 (None)
        (0.43, 880.00, 0.80, 0.70, 0.70),   # A5
    ]
    for off, freq, dur, gl, gr in notes:
        tone = _synth_sweep(dur, freq * 0.996, freq, harmonics=((2, 0.22), (3, 0.07)), att_ms=14.0, dec_exp=3.4, tail_ms=90.0)
        _mix_into(st_l, tone, off, gl * 0.52)
        _mix_into(st_r, tone, off + 0.006, gr * 0.52)
    shimmer = _noise_burst(rng, 0.45, lp_hz=4200.0, hp_hz=1200.0, att_ms=90.0, dec_exp=4.0, amp=0.09)
    _mix_into(st_l, shimmer, 0.18, 0.8)
    _mix_into(st_r, shimmer, 0.21, 0.8)
    st_l = _reverb_tail(st_l, ((23.0, 0.26), (47.0, 0.18), (79.0, 0.12), (118.0, 0.07)), lp_hz=4000.0)
    st_r = _reverb_tail(st_r, ((29.0, 0.26), (53.0, 0.18), (83.0, 0.12), (127.0, 0.07)), lp_hz=4000.0)
    l_f, r_f = _finalize_stereo(st_l, st_r, 0.76)
    sounds["startup"] = [l_f, r_f]

    # shutdown: warmlaufender Stereo-Ausklang nach unten (~1.05 s)
    sd_l, sd_r = _zeros(1.05), _zeros(1.05)
    sd_notes = [
        (0.02, 659.25, 0.42, 0.68, 0.56),   # E5
        (0.14, 587.33, 0.45, 0.58, 0.68),   # D5
        (0.26, 440.00, 0.55, 0.66, 0.60),   # A4
        (0.40, 293.66, 0.62, 0.62, 0.62),   # D4
    ]
    for off, freq, dur, gl, gr in sd_notes:
        tone = _synth_sweep(dur, freq, freq * 0.992, harmonics=((2, 0.14),), att_ms=12.0, dec_exp=3.6, tail_ms=90.0)
        _mix_into(sd_l, tone, off, gl * 0.52)
        _mix_into(sd_r, tone, off + 0.005, gr * 0.52)
    sd_sub = _synth_sweep(0.85, 146.83, 73.42, sweep_exp=1.3, harmonics=((2, 0.16),), att_ms=30.0, dec_exp=2.8, tail_ms=110.0)
    _mix_into(sd_l, sd_sub, 0.12, 0.48)
    _mix_into(sd_r, sd_sub, 0.12, 0.48)
    sd_l = _reverb_tail(sd_l, ((24.0, 0.22), (52.0, 0.14), (88.0, 0.08)), lp_hz=2800.0)
    sd_r = _reverb_tail(sd_r, ((31.0, 0.22), (59.0, 0.14), (95.0, 0.08)), lp_hz=2800.0)
    l_s, r_s = _finalize_stereo(sd_l, sd_r, 0.72)
    sounds["shutdown"] = [l_s, r_s]
    return sounds


# ---------------------------------------------------------------------------
#  Preset 2: RETRO (warme 16-Bit-Konsole, sanft tiefpassgefiltert)
# ---------------------------------------------------------------------------
def _build_retro(rng: random.Random) -> dict[str, list[list[float]]]:
    sounds: dict[str, list[list[float]]] = {}

    # navigate: klassischer weicher Konsole-Blip
    nav = _synth_sweep(0.045, 480.0, 560.0, shape="tri", att_ms=2.0, dec_exp=7.5)
    sounds["navigate"] = [_finalize_mono(_lowpass(nav, 2800.0), 0.55)]

    # select: fröhlicher 16-Bit-Doppelsprung (G5 -> D6)
    sel = _zeros(0.13)
    _mix_into(sel, _synth_sweep(0.055, 783.99, 783.99, shape="soft_pulse", att_ms=2.0, dec_exp=6.0), 0.0, 0.65)
    _mix_into(sel, _synth_sweep(0.095, 1174.66, 1174.66, shape="soft_pulse", att_ms=2.0, dec_exp=5.0), 0.038, 0.72)
    sounds["select"] = [_finalize_mono(_lowpass(_reverb_tail(sel, ((20.0, 0.15),), lp_hz=3200.0), 4200.0), 0.68)]

    # back: klassisches kurzes Runter-Bloop
    bak = _synth_sweep(0.095, 520.0, 250.0, shape="tri", sweep_exp=0.75, att_ms=2.0, dec_exp=5.5)
    sounds["back"] = [_finalize_mono(_lowpass(bak, 2400.0), 0.64)]

    # group: schnelles 3-Ton-Arpeggio
    grp = _zeros(0.14)
    for idx, f in enumerate((440.0, 554.37, 659.25)):
        _mix_into(grp, _synth_sweep(0.060, f, f, shape="soft_pulse", att_ms=2.0, dec_exp=6.5), idx * 0.028, 0.68)
    sounds["group"] = [_finalize_mono(_lowpass(_reverb_tail(grp, ((18.0, 0.14),), lp_hz=3200.0), 3800.0), 0.66)]

    # toggle: knackiger Schalter-Pip
    tog = _zeros(0.085)
    _mix_into(tog, _synth_sweep(0.038, 587.33, 587.33, shape="tri", att_ms=1.5, dec_exp=7.0), 0.0, 0.7)
    _mix_into(tog, _synth_sweep(0.058, 880.00, 880.00, shape="tri", att_ms=1.5, dec_exp=6.0), 0.026, 0.8)
    sounds["toggle"] = [_finalize_mono(_lowpass(tog, 3400.0), 0.66)]

    # volume: kurzer warmer Pegel-Pip
    vol = _synth_sweep(0.058, 660.0, 690.0, shape="tri", att_ms=2.0, dec_exp=7.5)
    sounds["volume"] = [_finalize_mono(_lowpass(vol, 2800.0), 0.58)]

    # notify: 3-stimmiger Retro-Jingle (C5 - E5 - G5)
    ntf = _zeros(0.24)
    for idx, f in enumerate((523.25, 659.25, 783.99)):
        _mix_into(ntf, _synth_sweep(0.10, f, f, shape="soft_pulse", att_ms=2.0, dec_exp=4.8), idx * 0.052, 0.72)
    sounds["notify"] = [_finalize_mono(_lowpass(_reverb_tail(ntf, ((22.0, 0.18), (46.0, 0.10)), lp_hz=3400.0), 4200.0), 0.70)]

    # error: tiefer Retro-Brummer (G2 -> F2)
    err = _zeros(0.24)
    _mix_into(err, _synth_sweep(0.095, 196.0, 175.0, shape="soft_pulse", att_ms=2.5, dec_exp=5.5), 0.0, 0.78)
    _mix_into(err, _synth_sweep(0.130, 146.83, 123.47, shape="soft_pulse", att_ms=2.5, dec_exp=4.5), 0.095, 0.82)
    sounds["error"] = [_finalize_mono(_lowpass(err, 1400.0), 0.70)]

    # startup: nostalgischer Stereo-16-Bit-Startakkord
    st_l, st_r = _zeros(1.15), _zeros(1.15)
    arp = [(0.02, 261.63), (0.09, 329.63), (0.16, 392.00), (0.23, 523.25), (0.31, 659.25), (0.40, 783.99)]
    for idx, (off, freq) in enumerate(arp):
        dur = 0.65 if idx >= 4 else 0.30
        t = _lowpass(_synth_sweep(dur, freq, freq, shape="soft_pulse", att_ms=4.0, dec_exp=3.8, tail_ms=60.0), 3800.0)
        pan_l = 0.72 if idx % 2 == 0 else 0.52
        pan_r = 0.52 if idx % 2 == 0 else 0.72
        _mix_into(st_l, t, off, pan_l * 0.55)
        _mix_into(st_r, t, off, pan_r * 0.55)
    pad = _lowpass(_synth_sweep(0.95, 130.81, 130.81, shape="tri", att_ms=40.0, dec_exp=2.5, tail_ms=90.0), 1800.0)
    _mix_into(st_l, pad, 0.05, 0.55)
    _mix_into(st_r, pad, 0.05, 0.55)
    st_l = _reverb_tail(st_l, ((24.0, 0.20), (50.0, 0.12)), lp_hz=3200.0)
    st_r = _reverb_tail(st_r, ((30.0, 0.20), (57.0, 0.12)), lp_hz=3200.0)
    l_f, r_f = _finalize_stereo(st_l, st_r, 0.74)
    sounds["startup"] = [l_f, r_f]

    # shutdown: Retro Power-Down Sweep + warmer Ausklang
    sd_l, sd_r = _zeros(0.98), _zeros(0.98)
    for idx, (off, freq) in enumerate([(0.02, 783.99), (0.12, 659.25), (0.22, 523.25), (0.34, 261.63)]):
        t = _lowpass(_synth_sweep(0.45, freq, freq * 0.96, shape="tri", att_ms=6.0, dec_exp=3.8, tail_ms=70.0), 3000.0)
        _mix_into(sd_l, t, off, (0.68 if idx % 2 == 0 else 0.55) * 0.55)
        _mix_into(sd_r, t, off, (0.55 if idx % 2 == 0 else 0.68) * 0.55)
    sweep = _lowpass(_synth_sweep(0.75, 261.63, 73.42, shape="tri", sweep_exp=1.4, att_ms=20.0, dec_exp=2.8, tail_ms=90.0), 1600.0)
    _mix_into(sd_l, sweep, 0.18, 0.55)
    _mix_into(sd_r, sweep, 0.18, 0.55)
    l_s, r_s = _finalize_stereo(_reverb_tail(sd_l, ((24.0, 0.18),), lp_hz=2600.0), _reverb_tail(sd_r, ((30.0, 0.18),), lp_hz=2600.0), 0.70)
    sounds["shutdown"] = [l_s, r_s]
    _ = rng
    return sounds


# ---------------------------------------------------------------------------
#  Preset 3: MINIMAL (dezentes Hi-Fi-Glas / Studio-Clicks)
# ---------------------------------------------------------------------------
def _build_minimal(rng: random.Random) -> dict[str, list[list[float]]]:
    sounds: dict[str, list[list[float]]] = {}

    # navigate: hauchzarter Mikro-Klick
    nav = _zeros(0.035)
    _mix_into(nav, _synth_sweep(0.028, 620.0, 380.0, att_ms=2.0, dec_exp=10.0), 0.0, 0.7)
    _mix_into(nav, _noise_burst(rng, 0.010, lp_hz=2600.0, hp_hz=800.0, dec_exp=13.0, amp=0.14), 0.0, 1.0)
    sounds["navigate"] = [_finalize_mono(nav, 0.45)]

    # select: reiner Glas-Tap (A5 + zarte Oktave)
    sel = _synth_sweep(0.090, 880.0, 880.0, harmonics=((2, 0.09),), att_ms=2.5, dec_exp=6.5)
    sounds["select"] = [_finalize_mono(_reverb_tail(sel, ((18.0, 0.12),), lp_hz=3200.0), 0.58)]

    # back: gedämpfter tiefer Tropfen
    bak = _synth_sweep(0.085, 440.0, 330.0, att_ms=3.0, dec_exp=6.5)
    sounds["back"] = [_finalize_mono(bak, 0.54)]

    # group: sanftes Gleiten
    grp = _synth_sweep(0.110, 440.0, 660.0, sweep_exp=0.75, att_ms=6.0, dec_exp=5.5)
    sounds["group"] = [_finalize_mono(_reverb_tail(grp, ((20.0, 0.12),), lp_hz=2800.0), 0.56)]

    # toggle: dezenter Kristall-Switch
    tog = _zeros(0.075)
    _mix_into(tog, _synth_sweep(0.068, 587.33, 740.0, sweep_exp=0.6, att_ms=2.0, dec_exp=7.0), 0.0, 0.8)
    sounds["toggle"] = [_finalize_mono(tog, 0.56)]

    # volume: leiser Sinuspunkt
    vol = _synth_sweep(0.048, 600.0, 600.0, att_ms=2.5, dec_exp=8.0)
    sounds["volume"] = [_finalize_mono(vol, 0.48)]

    # notify: ruhiger Zweiklang (E5 -> B5)
    ntf = _zeros(0.22)
    _mix_into(ntf, _synth_sweep(0.14, 659.25, 659.25, att_ms=4.0, dec_exp=4.5), 0.0, 0.65)
    _mix_into(ntf, _synth_sweep(0.18, 987.77, 987.77, att_ms=4.0, dec_exp=4.2), 0.065, 0.72)
    sounds["notify"] = [_finalize_mono(_reverb_tail(ntf, ((22.0, 0.16), (48.0, 0.09)), lp_hz=3500.0), 0.60)]

    # error: sanftes tiefes Doppel-Klopfen
    err = _zeros(0.22)
    _mix_into(err, _synth_sweep(0.085, 220.0, 190.0, att_ms=3.0, dec_exp=6.5), 0.0, 0.75)
    _mix_into(err, _synth_sweep(0.110, 185.0, 155.0, att_ms=3.0, dec_exp=5.5), 0.090, 0.80)
    sounds["error"] = [_finalize_mono(err, 0.60)]

    # startup: ruhiger Stereo-Glasklang (~0.98 s)
    st_l, st_r = _zeros(0.98), _zeros(0.98)
    for idx, (off, freq) in enumerate([(0.02, 392.00), (0.14, 587.33), (0.27, 783.99)]):
        t = _synth_sweep(0.65, freq, freq, harmonics=((2, 0.06),), att_ms=18.0, dec_exp=3.5, tail_ms=90.0)
        _mix_into(st_l, t, off, 0.62 if idx != 1 else 0.48)
        _mix_into(st_r, t, off + 0.006, 0.48 if idx != 1 else 0.62)
    l_f, r_f = _finalize_stereo(_reverb_tail(st_l, ((26.0, 0.18), (58.0, 0.10)), lp_hz=3400.0), _reverb_tail(st_r, ((32.0, 0.18), (64.0, 0.10)), lp_hz=3400.0), 0.64)
    sounds["startup"] = [l_f, r_f]

    # shutdown: sanftes Ausatmen (~0.92 s)
    sd_l, sd_r = _zeros(0.92), _zeros(0.92)
    for idx, (off, freq) in enumerate([(0.02, 587.33), (0.18, 392.00), (0.34, 293.66)]):
        t = _synth_sweep(0.54, freq, freq * 0.99, att_ms=16.0, dec_exp=3.5, tail_ms=90.0)
        _mix_into(sd_l, t, off, 0.58 if idx != 1 else 0.46)
        _mix_into(sd_r, t, off + 0.006, 0.46 if idx != 1 else 0.58)
    l_s, r_s = _finalize_stereo(_reverb_tail(sd_l, ((24.0, 0.15),), lp_hz=2600.0), _reverb_tail(sd_r, ((30.0, 0.15),), lp_hz=2600.0), 0.60)
    sounds["shutdown"] = [l_s, r_s]
    return sounds


BUILDERS: dict[str, Callable[[random.Random], dict[str, list[list[float]]]]] = {
    "void": _build_void,
    "retro": _build_retro,
    "minimal": _build_minimal,
}


def generate(out_dir: Path, preset: str = "all", flat: bool = False) -> list[Path]:
    rng = random.Random(20261124)
    targets = list(PRESETS) if preset == "all" else [preset]
    written: list[Path] = []
    for p in targets:
        tracks = BUILDERS[p](rng)
        dest_dir = out_dir if (flat and len(targets) == 1) else (out_dir / p)
        for name, chans in tracks.items():
            fn = dest_dir / f"{name}.wav"
            _write_wav(fn, chans)
            written.append(fn)
    return written


def main() -> None:
    ap = argparse.ArgumentParser(description="VoidStation Standard-Oberflaechentoene erzeugen")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT, help="Zielordner (Standard: launcher/web/sounds)")
    ap.add_argument("--preset", choices=(*PRESETS, "all"), default="all", help="Klangstil (Standard: all)")
    ap.add_argument("--flat", action="store_true", help="Bei einzelnem Preset direkt in --out schreiben (z. B. Nutzer-Override)")
    args = ap.parse_args()
    files = generate(args.out, preset=args.preset, flat=args.flat)
    total = sum(f.stat().st_size for f in files)
    print(f"{len(files)} WAV-Dateien erzeugt ({total // 1024} KiB) in {args.out}")


if __name__ == "__main__":
    main()
