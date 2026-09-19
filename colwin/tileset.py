"""The map tile set, cut out of `CVPC 201` in `COLDATA1.DLL`.

`CVPC 201` is a 1280x480 canvas whose left page is the map art: base terrain
squares, then six bands of overlay tiles, the coastline corner pieces, and the
settlements. Cells are ruled off in orange (palette index 41) on a grey ground
(index 9), so a cell is lifted out by flooding those two values inward from its
border -- flooding rather than colour-keying, because a grey or orange pixel
*enclosed* by artwork has to stay painted. Corner pieces are painted on black,
which is flooded the same way.

A canvas carries its own palette in its header, so a cell arrives in true
colour and no palette question arises -- unlike `SPRT`, which stores indices
into a palette the game builds at runtime. See `docs/palettes.md`.

## Which cell is which, and how much of that is established

**The five 16-cell bands are established**, from `1038:d8f8`, the function that
paints one map square (win-decomp `matched/game/draw_terrain_tile_1038_d8f8.c`).
It draws its overlays as `icon = base + mask` with the bases

    0x01 major river   0x11 minor river   0x21 mountains   0x31 hills
    0x41 forest        0x51 road

and the sheet has exactly six bands in that order down the page, at y = 232,
265, 298, 331, 364 and 397. `mask` is a four-bit neighbour code, and every
helper that computes one -- `neighbor_mask_1038_d4b9`, `tile_neighbor_match`,
`orthogonal_neighbor_bits` -- weights the four neighbours **N 8, S 4, W 2,
E 1**.

That convention is also *visible in the art*, which is the cross-check that
makes the band assignment more than a coincidence of counts: in each band, cell
1 carries artwork on its east edge only, cell 2 on its west, cell 4 on its
south, cell 8 on its north, and cell 15 on all four. `tests/test_map.py`
re-derives that from the pixels and fails if it stops holding.

**The base squares are established** the same way: the draw function takes
`kind = class & 7` below 0x18 and the class itself above it, which is why the
eight unforested squares at y=39 serve the forest ids too, and why classes
0x18, 0x19 and 0x1a -- arctic, ocean, sea lane -- are a separate column. Its
one special case, `kind == 1` inside a forest band drawing tile `0x11` instead,
is the scrub-forest square below the desert one.

**The coastline corners are established**: water with land around it is drawn
as four 16x16 pieces, `g_4c6e[j] * 4 + j + 0x6d`, where `j` runs top-left,
top-right, bottom-right, bottom-left and `g_4c6e[j]` is a three-bit corner code
from `neighbor_terrain_scan_1038_d520`. The sheet's eight 2x2 quads of 16x16
coast cells are exactly `code * 4 + j`.

**The settlements, the plowed square and the four whole-edge coast tiles are
NOT established.** The draw function names icons `0x96` (plowed) and
`0x97..0x9a` (whole-edge coast) but nothing binds an icon number to a cell
outside the bands above, and no load site derives a settlement's art from a
nation. Those cells are identified **by eye** and marked `inferred` in
`CELL_EVIDENCE`; the renderer's `--plain` skips every one of them.
"""
import os

from .ne import Module
from .formats import cvpc

CANVAS_MODULE = "COLDATA1.DLL"
CANVAS_ID = 201
TILE = 32
HALF = TILE // 2
BACKGROUND = (9, 41)        # the sheet's grey ground and its orange rule
# The coastline corner pieces are painted on black -- palette index 95, 3,782 of
# the 4,540 pixels it covers on the left page -- and the black is the part of the
# square the piece does not cover. It is flooded away with the ground, for those
# cells only: elsewhere on the sheet index 95 is an outline colour.
CORNER_BACKGROUND = BACKGROUND + (95,)

# -- the cells -------------------------------------------------------------- #
# Every box is (x, y, w, h) on the canvas.

BAND_X0, BAND_PITCH = 7, 33
BANDS = {"river_major": 232, "river_minor": 265, "mountains": 298,
         "hills": 331, "forest": 364, "road": 397}

# Base squares: terrain id -> box. 0..7 are the eight unforested rows; 17 is the
# scrub-forest square the draw function substitutes for kind 1; 24, 25 and 26
# are arctic, ocean and sea lane.
BASE_CELLS = dict((k, (18 + 33 * k, 39, TILE, TILE)) for k in range(8))
BASE_CELLS[17] = (51, 72, TILE, TILE)
BASE_CELLS.update({24: (321, 39, TILE, TILE), 25: (321, 72, TILE, TILE),
                   26: (321, 105, TILE, TILE)})

CORNER_X0, CORNER_PITCH, CORNER_INNER = 7, 36, 17
CORNER_Y = (438, 455)

# How deep the terrain seam reaches into the square, pixel by pixel along the
# edge, and how many rows of thinning dither follow it. The numbers are a
# drawing, not a measurement: the game's own 44 seam sprites are not among the
# bytes it ships (see Tileset.seam), so this is chosen to look like what the
# game draws rather than derived from it. One profile serves all four edges.
#
# It tapers to nothing at both ends, which is what keeps two seams meeting at a
# corner from stacking into a square blob, and it is deliberately uneven so the
# boundary reads as terrain rather than as a border.
SEAM_PROFILE = (1, 2, 4, 5, 7, 6, 9, 11, 9, 7, 8, 10, 12, 10, 8, 7,
                9, 11, 13, 11, 9, 8, 10, 12, 10, 8, 6, 7, 5, 4, 2, 1)
SEAM_FRINGE = 5
# Which pixel of the dithered fringe survives, row by row: the further in, the
# sparser. Read as a 4x4 threshold, thinning from every other pixel to none.
SEAM_DITHER = (2, 3, 5, 8, 12)
_ORDERED_4X4 = (0, 8, 2, 10, 12, 4, 14, 6, 3, 11, 1, 9, 15, 7, 13, 5)

# Inferred, not established -- see the module docstring.
PLOWED_CELL = (337, 397, TILE, TILE)
COLONY_CELL = (663, 203, TILE, TILE)
VILLAGE_CELLS = {"tipi": (659, 310, TILE, TILE), "hut": (692, 310, TILE, TILE),
                 "pyramid": (725, 310, TILE, TILE), "stone": (758, 310, TILE, TILE)}

CELL_EVIDENCE = {
    "base": "code: draw_terrain_tile_1038_d8f8 takes kind = class & 7 below 0x18",
    "river_major": "code: icon 0x01 + mask, and the art's edges agree",
    "river_minor": "code: icon 0x11 + mask, and the art's edges agree",
    "mountains": "code: icon 0x21 + mask, and the art's edges agree",
    "hills": "code: icon 0x31 + mask, and the art's edges agree",
    "forest": "code: icon 0x41 + mask, and the art's edges agree",
    "road": "code: icon 0x51 isolated, else 0x52 + direction",
    "coast": "code: icon g_4c6e[j] * 4 + j + 0x6d, four 16x16 pieces",
    "plowed": "inferred: icon 0x96 has no established cell; identified by eye",
    "settlement": "inferred: no load site derives settlement art from a nation",
}


class TilesetError(Exception):
    pass


def band_cell(band, index):
    """Cell `index` of one of the six 16-wide overlay bands."""
    if band not in BANDS:
        raise TilesetError("no band called %r" % band)
    return (BAND_X0 + BAND_PITCH * index, BANDS[band], TILE, TILE)


def corner_cell(code, j):
    """One 16x16 coastline piece: corner code 0..7, position j = TL, TR, BR, BL."""
    x0 = CORNER_X0 + CORNER_PITCH * code
    return ((x0 + (CORNER_INNER if j in (1, 2) else 0),
             CORNER_Y[1] if j in (2, 3) else CORNER_Y[0], HALF, HALF))


def corner_offset(j):
    """Where piece `j` is drawn inside the square, as the draw function computes it."""
    return (((j + 1) & 3) >> 1) * HALF, (j >> 1) * HALF


# -- the sheet -------------------------------------------------------------- #

class Tileset:
    """The canvas, plus a cache of cells cut out of it as RGB + mask."""

    def __init__(self, canvas):
        self.width = canvas["width"]
        self.height = canvas["height"]
        self.pixels = canvas["pixels"]
        self.palette = canvas["palette"]
        self._cells = {}

    @classmethod
    def from_game(cls, game):
        path = os.path.join(game, CANVAS_MODULE)
        if not os.path.exists(path):
            # The install may be lower-cased, as it is when copied off a CD.
            alt = os.path.join(game, CANVAS_MODULE.lower())
            if not os.path.exists(alt):
                raise TilesetError("%s holds no %s -- point --game at an "
                                   "installed copy of the game" % (game, CANVAS_MODULE))
            path = alt
        module = Module.load(path)
        for r in module.resources:
            if r.type_name == "CVPC" and r.id == CANVAS_ID:
                return cls(cvpc.decode(r.body))
        raise TilesetError("%s has no CVPC %d, the map tile sheet"
                           % (path, CANVAS_ID))

    def cell(self, box, background=BACKGROUND):
        """(w, h, rgb, opaque) for one cell, its background flooded away.

        `rgb` is 3 bytes per pixel and `opaque` one byte, 1 where the cell
        paints and 0 where the flood reached.
        """
        key = (box, background)
        if key in self._cells:
            return self._cells[key]
        x0, y0, w, h = box
        if x0 < 0 or y0 < 0 or x0 + w > self.width or y0 + h > self.height:
            raise TilesetError("cell %r falls outside the %dx%d canvas"
                               % (box, self.width, self.height))
        px = bytearray(w * h)
        for y in range(h):
            row = (y0 + y) * self.width + x0
            px[y * w:(y + 1) * w] = self.pixels[row:row + w]
        clear = bytearray(w * h)
        stack = [(x, y) for x in range(w) for y in (0, h - 1)]
        stack += [(x, y) for y in range(h) for x in (0, w - 1)]
        while stack:
            x, y = stack.pop()
            if not (0 <= x < w and 0 <= y < h):
                continue
            i = y * w + x
            if clear[i] or px[i] not in background:
                continue
            clear[i] = 1
            stack += [(x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)]
        rgb = bytearray(w * h * 3)
        opaque = bytearray(w * h)
        for i in range(w * h):
            if clear[i]:
                continue
            opaque[i] = 1
            rgb[i * 3:i * 3 + 3] = bytes(self.palette[px[i]])
        out = (w, h, bytes(rgb), bytes(opaque))
        self._cells[key] = out
        return out

    def seam(self, box, side):
        """A terrain seam: the square `box`, kept only along one edge.

        The game draws seams from a table of its own, `g_overlay_sprites`, and
        **this is not that art**: no block of 44 seam cells is on the sheet, and
        no canvas the game ships is one. What is reproduced is the *shape* of
        the layer -- a ragged, dithered band of the neighbouring terrain lying
        over this square's edge -- cut from that terrain's own square, so every
        colour on the map is still the game's. See `SEAM_PROFILE`.
        """
        key = (box, side, "seam")
        if key in self._cells:
            return self._cells[key]
        w, h, rgb, opaque = self.cell(box)
        keep = bytearray(w * h)
        for i in range(w):
            depth = SEAM_PROFILE[i % len(SEAM_PROFILE)]
            for j in range(depth + SEAM_FRINGE):
                if j >= depth:
                    # The fringe thins with depth: a 4x4 ordered dither, its
                    # threshold falling row by row through SEAM_DITHER.
                    thr = SEAM_DITHER[min(j - depth, len(SEAM_DITHER) - 1)]
                    if _ORDERED_4X4[(j % 4) * 4 + i % 4] >= thr:
                        continue
                if side == "n":
                    x, y = i, j
                elif side == "s":
                    x, y = i, h - 1 - j
                elif side == "w":
                    x, y = j, i
                else:
                    x, y = w - 1 - j, i
                if 0 <= x < w and 0 <= y < h:
                    keep[y * w + x] = 1
        masked = bytearray(w * h)
        for i in range(w * h):
            masked[i] = 1 if (keep[i] and opaque[i]) else 0
        out = (w, h, rgb, bytes(masked))
        self._cells[key] = out
        return out
