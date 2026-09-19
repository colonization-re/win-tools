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

**The four whole-edge shore squares are established too**, by the patterns that
select them: see `SHORE_CELLS`.

**The settlements and the plowed square are NOT.** The draw function names icon
`0x96` for plowing, but nothing binds that number to a cell, and no load site
derives a settlement's art from a nation. Those cells are identified **by eye**
and marked `inferred` in `CELL_EVIDENCE`; the renderer's `--plain` skips them.
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
# A coastline corner is a composite too: the builder draws a 16x16 square of
# open water and the coast piece over it, then extracts. The water quarter is
# the last of a 2x2 block at (547, 434); the builder's inner loop overwrites its
# result four times, so the fourth -- this one -- is the one that survives.
CORNER_WATER = (547, 451, HALF, HALF)

# The four whole-edge shore squares, icons 0x97..0x9a. They sit as a 2x2 block
# that reads as one lake, which is why they were taken for a picture at first,
# and they are identified by MEASUREMENT: the draw routine picks them by four
# exact patterns of the eight-direction land mask --
#
#   0x97  land at N, W, NW      0x98  land at N, NE, E
#   0x99  land at S, SW, W      0x9a  land at E, SE, S
#
# -- and each cell carries water across exactly the two edges its pattern says
# are open, with the other two left as ground for the land to show through. All
# four agree, in reading order. tests/test_map.py re-derives it from the pixels.
SHORE_CELLS = {0: (555, 298, TILE, TILE), 1: (588, 298, TILE, TILE),
               2: (555, 331, TILE, TILE), 3: (588, 331, TILE, TILE)}
# The land directions of each pattern, as the test reads them: (open edges).
SHORE_OPEN = {0: ("s", "e"), 1: ("s", "w"), 2: ("n", "e"), 3: ("n", "w")}

# THE SEAM MASKS, and with them the seams themselves.
#
# `load_all_sprite_sheets` (1008:51d4) builds the game's whole art table at
# start-up out of this canvas, and the 44 seam sprites are BUILT, not drawn:
#
#     for group in 0..7:  for d in 0..3:
#         draw tile[group] into a 32x32 port
#         draw mask[d]     over it
#         extract the result, keying out colour 0x31
#     then the same four for arctic, ocean and sea lane
#
# and mask[d] is icon 0x69+d, cut from this sheet at (553, 24 + 33d) keying out
# colour 0x87. Those two keys are runtime palette indices, and the loader
# installs this canvas at 40 (`load_picture_resource(..., 0x28, 0x60, ...)`), so
# 0x87 is canvas index 95 -- black -- and 0x31 is canvas index 9, the grey
# ground. Net: the seam keeps the terrain wherever the mask cell is BLACK and
# drops it everywhere else.
#
# The masks are a sparse speckle eight pixels deep along one edge -- exactly 64
# of 1,024 pixels each, about six percent -- which is why a terrain boundary in
# this game is a fine scatter and not a band.
MASK_CELLS = {0: (553, 24, TILE, TILE), 1: (553, 57, TILE, TILE),
              2: (553, 90, TILE, TILE), 3: (553, 123, TILE, TILE)}
MASK_KEEP = 95              # canvas black: what the mask lets through
MASK_SIDES = ("n", "e", "s", "w")   # d = 0..3, read off the four masks

# From the builder as well: icon 0x96 is (304, 397), the first furrow cell.
PLOWED_CELL = (304, 397, TILE, TILE)     # icon 0x96, from the builder
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
    "shore": "code: icons 0x97..0x9a, and each cell's open edges match its pattern",
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

    def seam(self, box, d):
        """A terrain seam: the square `box` seen through mask `d`.

        This is what the game builds at start-up, with the same two sprites and
        the same key colours -- see MASK_CELLS. The mask keeps about six percent
        of the square, in a speckle eight pixels deep along one edge, and that
        speckle is the game's own art, not a pattern invented here.
        """
        key = (box, d, "seam")
        if key in self._cells:
            return self._cells[key]
        w, h, rgb, opaque = self.cell(box)
        mx, my, _mw, _mh = MASK_CELLS[d]
        keep = bytearray(w * h)
        for y in range(h):
            row = (my + y) * self.width + mx
            for x in range(w):
                if self.pixels[row + x] == MASK_KEEP and opaque[y * w + x]:
                    keep[y * w + x] = 1
        out = (w, h, rgb, bytes(keep))
        self._cells[key] = out
        return out
