"""Palettes: the one part of this toolkit that needs a design, not a decoder.

The problem
-----------
`SPRT` pixel bytes are indices into a palette that **is not stored anywhere in
the game**.  The game builds a 256-entry Win16 LOGPALETTE in memory at startup,
seeds it from `GetSystemPaletteEntries` -- the display driver's state, not game
data -- and then overwrites ranges of it at runtime from `CTAB` blobs.  So there
is no file to read the sprite colours out of, and none of the 75 palettes that
do ship in the game fits the sprites the way a real palette fits its own art.

The rule this toolkit follows
-----------------------------
**Indices are the data.  A palette is a way of looking at them.**

Every extracted image is an *indexed* PNG whose pixel values are the game's own
index bytes, so the export is lossless whatever the palette turns out to be.
The palette lives beside it as an editable file and is recorded in the
manifest.  Three things follow, and they are the whole reason this works:

1.  Editing in an indexed-aware editor (Aseprite, GraphicsGale, GIMP in indexed
    mode) round-trips **bit for bit** -- the importer reads the indices back
    straight out of the PNG and the palette never enters into it.
2.  Editing in an RGB editor still round-trips exactly, because the view
    palette is made *injective* first: `uniquify()` nudges duplicate entries by
    one in the blue channel, so every index has its own colour and colour ->
    index is a lookup, not a guess.  One part in 255 is invisible to the eye
    and decisive for the inverse.
3.  When a better palette is found, `colwin repalette` swaps the PLTE chunk and
    leaves every pixel index alone.  No re-extraction, and no edit is lost.

What is in the default view palette, and what is honestly unknown:

    0-9, 246-255   the Windows 3.1 static system colours.  Known, standard, and
                   corroborated: of these twenty, sprites use exactly 246, 247
                   and 249 -- cream, medium grey and red, the three that look
                   like art colours -- and never the dark system colours.
    142-238        from a CTAB.  That CTAB blobs are the payload written into
                   the runtime palette is established from the loader at
                   1068:0180; WHICH CTAB a given sprite is drawn under is not,
                   so the default pairs them by resource id, which is a
                   measured heuristic (36/57 exact, 1.0/57 by chance) and
                   labelled a reconstruction, not a mechanism.
    10-141, 239-245  UNKNOWN.  Filled with a grey ramp, which says so.
"""
import os
import struct

# The Windows 3.1 default logical palette: 20 static colours, at both ends of
# the 256-entry system palette.
WIN31_LOW = [
    (0, 0, 0), (128, 0, 0), (0, 128, 0), (128, 128, 0), (0, 0, 128),
    (128, 0, 128), (0, 128, 128), (192, 192, 192), (192, 220, 192),
    (166, 202, 240),
]
WIN31_HIGH = [
    (255, 251, 240), (160, 160, 164), (128, 128, 128), (255, 0, 0),
    (0, 255, 0), (255, 255, 0), (0, 0, 255), (255, 0, 255), (0, 255, 255),
    (255, 255, 255),
]

TEAL = (0, 173, 173)          # the one reserved colour per CTAB; see below


class Palette:
    """256 RGB entries, plus where each band came from."""

    def __init__(self, entries, name="view", provenance=None):
        if len(entries) > 256:
            raise ValueError("palette has %d entries" % len(entries))
        self.entries = [tuple(e[:3]) for e in entries]
        while len(self.entries) < 256:
            self.entries.append((0, 0, 0))
        self.name = name
        self.provenance = provenance or {}
        self._inv = None

    def __len__(self):
        return len(self.entries)

    def __getitem__(self, i):
        return self.entries[i]

    def copy(self, name=None):
        return Palette(list(self.entries), name or self.name, dict(self.provenance))

    # -- invertibility ---------------------------------------------------- #

    def duplicates(self):
        """{rgb: [indices]} for every colour held by more than one index."""
        seen = {}
        for i, e in enumerate(self.entries):
            seen.setdefault(e, []).append(i)
        return {k: v for k, v in seen.items() if len(v) > 1}

    def uniquify(self, priority=()):
        """Make colour -> index total, by nudging duplicates a hair.

        Indices in `priority` keep their exact colour; everything else moves if
        it has to.  The nudge walks the blue channel first, then green, then
        red, by the smallest amount that lands on a free colour -- at most a
        few units on one channel, which no eye resolves and which makes the
        inverse exact for any editor that hands back RGB instead of indices.
        """
        pri = set(priority)
        taken, moved = {}, {}
        order = ([i for i in range(256) if i in pri] +
                 [i for i in range(256) if i not in pri])
        for i in order:
            e = self.entries[i]
            if e not in taken:
                taken[e] = i
                continue
            cand = _free_near(e, taken)
            self.entries[i] = cand
            taken[cand] = i
            moved[i] = (e, cand)
        self._inv = None
        if moved:
            self.provenance["uniquified"] = {
                str(i): {"was": list(a), "now": list(b)} for i, (a, b) in sorted(moved.items())}
        return moved

    def inverse(self):
        if self._inv is None:
            self._inv = {}
            for i, e in enumerate(self.entries):
                self._inv.setdefault(e, i)      # first index wins if not unique
        return self._inv

    def nearest(self, rgb):
        """Closest entry by a redmean-weighted distance."""
        r, g, b = rgb[:3]
        best, bd = 0, None
        for i, (pr, pg, pb) in enumerate(self.entries):
            rm = (pr + r) // 2
            dr, dg, db = pr - r, pg - g, pb - b
            d = (((512 + rm) * dr * dr) >> 8) + 4 * dg * dg + (((767 - rm) * db * db) >> 8)
            if bd is None or d < bd:
                best, bd = i, d
        return best

    # -- files ------------------------------------------------------------ #

    def write_jasc(self, path):
        with open(path, "w") as f:
            f.write("JASC-PAL\n0100\n%d\n" % len(self.entries))
            for r, g, b in self.entries:
                f.write("%d %d %d\n" % (r, g, b))

    def write_gpl(self, path):
        with open(path, "w") as f:
            f.write("GIMP Palette\nName: %s\nColumns: 16\n#\n" % self.name)
            for i, (r, g, b) in enumerate(self.entries):
                f.write("%3d %3d %3d\t%d\n" % (r, g, b, i))

    @classmethod
    def read_jasc(cls, path, name=None):
        with open(path) as f:
            lines = [l.strip() for l in f if l.strip()]
        if not lines or lines[0].upper() != "JASC-PAL":
            raise ValueError("%s: not a JASC .pal" % path)
        n = int(lines[2])
        entries = []
        for l in lines[3:3 + n]:
            parts = l.split()
            entries.append(tuple(int(p) for p in parts[:3]))
        return cls(entries, name or os.path.basename(path))

    @classmethod
    def read_gpl(cls, path, name=None):
        entries = []
        with open(path) as f:
            for l in f:
                l = l.strip()
                if not l or l.startswith("#") or l.split()[0] in ("GIMP", "Name:", "Columns:"):
                    continue
                p = l.split()
                if len(p) >= 3 and all(x.isdigit() for x in p[:3]):
                    entries.append(tuple(int(x) for x in p[:3]))
        return cls(entries, name or os.path.basename(path))

    @classmethod
    def read(cls, path, name=None):
        ext = os.path.splitext(path)[1].lower()
        if ext == ".gpl":
            return cls.read_gpl(path, name)
        return cls.read_jasc(path, name)


# --------------------------------------------------------------------------- #
# building the sprite view palette

def _free_near(rgb, taken):
    """The nearest colour to `rgb` that nothing else holds.

    One channel at a time first, because that is what the ordinary case needs
    and it keeps the nudge on a single axis.  The full shell scan behind it is
    for palettes that are mostly one colour, where a single axis runs out of
    room; it always terminates, because 256 indices cannot exhaust 2^24.
    """
    for delta in range(1, 9):
        for ch in (2, 1, 0):
            for sign in (1, -1):
                c = list(rgb)
                c[ch] += sign * delta
                if 0 <= c[ch] <= 255 and tuple(c) not in taken:
                    return tuple(c)
    for r in range(1, 256):
        for dr in range(-r, r + 1):
            for dg in range(-r, r + 1):
                for db in range(-r, r + 1):
                    if max(abs(dr), abs(dg), abs(db)) != r:
                        continue
                    c = (rgb[0] + dr, rgb[1] + dg, rgb[2] + db)
                    if all(0 <= v <= 255 for v in c) and c not in taken:
                        return c
    raise ValueError("no free colour anywhere near %r" % (rgb,))


def grey_ramp():
    return [(i, i, i) for i in range(256)]


def ctab_parse(body):
    """A CTAB: WORD start, WORD count, then `count` packed RGB triples.

    Not a reading of the shape -- the loader at 1068:0180 takes the WORD at 0
    as `start`, the WORD at 2 as `count`, and passes `data + 4` as the RGB
    array to the routine that calls SetPaletteEntries.
    """
    start, count = struct.unpack_from("<HH", body, 0)
    need = 4 + 3 * count
    if need > len(body):
        # A table whose last entries are black ends short once the resource's
        # NUL padding is trimmed. 42 of the 43 shipped tables are 295 bytes;
        # the short ones are not malformed, they just end on black.
        body = body + bytes(need - len(body))
    return {"start": start, "count": count,
            "entries": [tuple(body[4 + i * 3:7 + i * 3]) for i in range(count)]}


def ctab_build(start, entries):
    return struct.pack("<HH", start, len(entries)) + b"".join(bytes(e[:3]) for e in entries)


def view_palette(ctab=None, name="view", label=None):
    """The default way of looking at sprite indices.

    Returns a Palette that is injective, so RGB editing round-trips exactly.
    """
    ent = grey_ramp()
    prov = {"10-141,239-245": "UNKNOWN -- grey ramp (index i -> (i,i,i))"}
    for i, c in enumerate(WIN31_LOW):
        ent[i] = c
    for i, c in enumerate(WIN31_HIGH):
        ent[246 + i] = c
    prov["0-9,246-255"] = "Windows 3.1 static system colours (established)"
    priority = list(range(10)) + list(range(246, 256))
    if ctab:
        for i, rgb in enumerate(ctab["entries"]):
            if ctab["start"] + i < 256:
                ent[ctab["start"] + i] = rgb
                priority.append(ctab["start"] + i)
        prov["%d-%d" % (ctab["start"], ctab["start"] + ctab["count"] - 1)] = (
            label or "CTAB payload (RECONSTRUCTION: which CTAB is a heuristic)")
    p = Palette(ent, name, prov)
    p.uniquify(priority)
    return p


def ctab_teal_index(ctab):
    """The index holding (0,173,173), if this table has one.

    A saturated teal appears exactly once in 42 of the 43 shipped tables, at a
    table-specific index, and fills solid regions of the art in long runs.  That
    is what a colour key looks like; it is NOT established as one -- no code has
    been shown keying it out -- so nothing here treats it as transparent.  It is
    reported so an artist knows which colour behaves oddly.
    """
    for i, e in enumerate(ctab["entries"]):
        if e == TEAL:
            return ctab["start"] + i
    return None
