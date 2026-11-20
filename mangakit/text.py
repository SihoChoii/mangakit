"""Typesetting with pinned fonts: HarfBuzz shaping, fontTools outlines.

Text is emitted as vector outlines (SVG <path>), so the rasterizer never
substitutes a font and the exact pinned bytes decide the letterforms.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

import uharfbuzz as hb
from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont


class Font:
    def __init__(self, path):
        self.path = str(path)
        self.tt = TTFont(self.path)
        self.upem = self.tt["head"].unitsPerEm
        self.glyphset = self.tt.getGlyphSet()
        self.order = self.tt.getGlyphOrder()
        blob = hb.Blob.from_file_path(self.path)
        self.hbfont = hb.Font(hb.Face(blob))
        os2 = self.tt["OS/2"]
        self.ascender = getattr(os2, "sTypoAscender", self.tt["hhea"].ascent)
        self.descender = getattr(os2, "sTypoDescender", self.tt["hhea"].descent)
        self.cap = getattr(os2, "sCapHeight", 0) or int(self.ascender * 0.7)
        self._bounds: dict[str, tuple | None] = {}

    def shape(self, text: str):
        buf = hb.Buffer()
        buf.add_str(text)
        buf.guess_segment_properties()
        hb.shape(self.hbfont, buf, {"kern": True, "liga": True})
        out = []
        x = 0
        for info, pos in zip(buf.glyph_infos, buf.glyph_positions):
            out.append((self.order[info.codepoint], x + pos.x_offset, pos.y_offset))
            x += pos.x_advance
        return out, x  # font units

    def glyph_bounds(self, name):
        if name not in self._bounds:
            bp = BoundsPen(self.glyphset)
            self.glyphset[name].draw(bp)
            self._bounds[name] = bp.bounds
        return self._bounds[name]

    def draw(self, name, pen, x, y, size, x_off=0, y_off=0, skew=0.0):
        s = size / self.upem
        tp = TransformPen(pen, (s, 0, skew * s, -s, x + x_off * s, y - y_off * s))
        self.glyphset[name].draw(tp)


@lru_cache(maxsize=32)
def load_font(path) -> Font:
    return Font(path)


@dataclass
class Run:
    text: str
    font: Font
    size: float
    width: float = 0.0  # page units


_EMPH = re.compile(r"\*(.+?)\*")


def parse_markup(text: str) -> list[tuple[str, bool]]:
    """'*word*' marks emphasis. Returns [(segment, emphasized)]."""
    out, pos = [], 0
    for m in _EMPH.finditer(text):
        if m.start() > pos:
            out.append((text[pos:m.start()], False))
        out.append((m.group(1), True))
        pos = m.end()
    if pos < len(text):
        out.append((text[pos:], False))
    return out


@dataclass
class Line:
    words: list[tuple[str, bool]]  # (word, emphasized)
    width: float = 0.0


class Typesetter:
    def __init__(self, regular: Font, emphasis: Font | None, size: float, line_height: float = 1.12,
                 uppercase=False, tracking=0.0):
        self.reg, self.emp = regular, emphasis or regular
        self.size, self.lh, self.upper, self.tracking = size, line_height, uppercase, tracking

    def _font(self, emph):
        return self.emp if emph else self.reg

    def word_width(self, w, emph):
        _, adv = self._font(emph).shape(w)
        return adv * self.size / self._font(emph).upem + self.tracking * max(0, len(w) - 1)

    def space(self):
        _, adv = self.reg.shape(" ")
        return adv * self.size / self.reg.upem

    def words(self, text):
        if self.upper:
            text = text.upper()
        ws = []
        for seg, emph in parse_markup(text):
            for w in seg.split():
                ws.append((w, emph))
        return ws

    def measure(self, words) -> float:
        if not words:
            return 0.0
        return sum(self.word_width(w, e) for w, e in words) + self.space() * (len(words) - 1)

    def wrap(self, text, max_width) -> list[Line]:
        lines, cur = [], []
        for w in self.words(text):
            trial = cur + [w]
            if cur and self.measure(trial) > max_width:
                lines.append(Line(cur, self.measure(cur)))
                cur = [w]
            else:
                cur = trial
        if cur:
            lines.append(Line(cur, self.measure(cur)))
        return lines

    def manual(self, breaks: list[str]) -> list[Line]:
        return [Line(ws, self.measure(ws)) for ws in (self.words(b) for b in breaks)]

    def balanced(self, text, aspect=1.6) -> list[Line]:
        """Pick a wrap width that gives a block close to `aspect` (w/h), favoring balloon-friendly shapes."""
        ws = self.words(text)
        total = self.measure(ws)
        best, best_score = None, 1e18
        lh = self.size * self.lh
        steps = 40
        longest = max((self.word_width(w, e) for w, e in ws), default=0)
        for k in range(steps + 1):
            width = longest + (total - longest) * k / steps
            lines = self.wrap(text, width + 0.01)
            bw = max(l.width for l in lines)
            bh = lh * len(lines)
            score = abs(bw / bh - aspect) + 0.08 * len(lines)
            # prefer diamond: middle lines longer than first/last
            if len(lines) >= 3 and lines[0].width > lines[1].width * 1.15:
                score += 0.3
            if score < best_score:
                best, best_score = lines, score
        return best or []

    def block_height(self, lines):
        return self.size * self.lh * len(lines)

    def render(self, lines: list[Line], cx: float, cy: float, align="center"):
        """Return (svg path d, list of per-line ink bboxes) for a block centered at (cx, cy)."""
        pen = SVGPathPen(None)
        lh = self.size * self.lh
        n = len(lines)
        # vertically center on cap height
        cap = self.reg.cap * self.size / self.reg.upem
        first_base = cy - (n - 1) * lh / 2 + cap / 2
        boxes = []
        sp = self.space()
        for i, line in enumerate(lines):
            base = first_base + i * lh
            if align == "center":
                x = cx - line.width / 2
            elif align == "left":
                x = cx
            else:
                x = cx - line.width
            x0 = x
            ink = [1e9, 1e9, -1e9, -1e9]
            for wi, (w, emph) in enumerate(line.words):
                f = self._font(emph)
                s = self.size / f.upem
                glyphs, adv = f.shape(w)
                for gi, (name, gx, gy) in enumerate(glyphs):
                    gxp = x + gx * s + self.tracking * gi
                    f.draw(name, pen, gxp, base, self.size, 0, gy)
                    b = f.glyph_bounds(name)
                    if b:
                        ink = [min(ink[0], gxp + b[0] * s), min(ink[1], base - b[3] * s),
                               max(ink[2], gxp + b[2] * s), max(ink[3], base - b[1] * s)]
                x += adv * s + self.tracking * max(0, len(w) - 1) + sp
            if ink[0] < 1e9:
                boxes.append(tuple(ink))
            else:
                boxes.append((x0, base - cap, x0 + line.width, base))
        return pen.getCommands(), boxes


def text_path(font: Font, text: str, x: float, y: float, size: float, anchor="middle",
              tracking=0.0, skew=0.0):
    """Single-line text outline, baseline at y. Returns (d, ink bbox)."""
    pen = SVGPathPen(None)
    s = size / font.upem
    glyphs, adv = font.shape(text)
    width = adv * s + tracking * max(0, len(glyphs) - 1)
    x0 = {"start": x, "middle": x - width / 2, "end": x - width}[anchor]
    ink = [1e9, 1e9, -1e9, -1e9]
    for gi, (name, gx, gy) in enumerate(glyphs):
        gxp = x0 + gx * s + tracking * gi
        font.draw(name, pen, gxp, y, size, 0, gy, skew)
        b = font.glyph_bounds(name)
        if b:
            ink = [min(ink[0], gxp + b[0] * s - skew * b[3] * s), min(ink[1], y - b[3] * s),
                   max(ink[2], gxp + b[2] * s + abs(skew) * b[3] * s), max(ink[3], y - b[1] * s)]
    return pen.getCommands(), tuple(ink)
