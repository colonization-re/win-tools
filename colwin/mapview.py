"""Draw a whole map into one image, the way the game draws one square.

The layering is `1038:d8f8`, the function that paints a single map square
(win-decomp `matched/game/draw_terrain_tile_1038_d8f8.c`), applied to every
square in turn:

    every square                   base square    kind = class & 7 below 0x18
                                   terrain seams  up to four, one per side
    water with no land around it   and nothing else
    everything else                forest         icon 0x41 + mask
                                   plowed         icon 0x96
                                   hills          icon 0x31 + mask
                                   mountains      icon 0x21 + mask
                                   river          icon 0x11 + mask, major 0x01
                                   roads          icon 0x51, else 0x52 + direction
    water with land around it      four corner pieces, 0x6d + code * 4 + j

and every mask is the same four-bit neighbour code, **N 8, S 4, W 2, E 1**.
Which cell each icon number is is in `colwin/tileset.py`, with its evidence.

## What is drawn from which plane

Plane 0 is terrain in both file formats: the low five bits are a terrain id
when bit 0x20 is clear, bit 0x20 means hills, with bit 0x80 mountains, and bit
0x40 a river, with bit 0x80 a major one (`terrain_from_map_byte`, `1040:42b5`).

A save's plane 1 is a bitfield -- 0x02 a settlement, 0x08 a road, 0x40 plowed
-- and its plane 2 holds a nation index in each nibble, 15 meaning none
(win-decomp `docs/findings/map-planes.md`). A `.MP` has no such planes: its
plane 1 is uniformly zero in the only shipped file and its plane 2 is
**UNKNOWN**, so a `.MP` draws terrain and coastline only, and says so.

The seams are the layer that makes terrain meet terrain instead of butting up
against it: `draw_tile_with_overlays` takes a four-byte list beside the base
square and draws up to four overlay sprites from it,
`build_terrain_seams_1008_7ec9` fills that list -- `seams()` below carries its
rule -- and `load_all_sprite_sheets` builds the 44 sprites themselves out of a
terrain square and a mask, which `Tileset.seam` reproduces.

## Three things this does not draw

**Scenery and prime resources.** `tile_decoration_1038_c066` hashes the
square's position against `g_scenery_seed` (DGROUP `0x1ca6`), and that seed is
not one of the 57 fields the save routine writes. Without it the decorations
are not reproducible from a file, so none are drawn.

**The four whole-edge coast tiles.** The draw function uses icons 0x97..0x9a
when the land mask matches one of four patterns exactly; no cell is bound to
those numbers, so this always takes the general path -- the four corner pieces,
which the same function uses for every other pattern.

**Units.** Plane 1 bit 0x01 says a square holds one, and nothing in the file
says which.
"""
from . import png
from .formats import mapfile
from .tileset import (Tileset, TILE, BASE_CELLS, COLONY_CELL, CORNER_BACKGROUND,
                      CORNER_WATER, PLOWED_CELL, SHORE_CELLS, VILLAGE_CELLS,
                      band_cell, corner_cell, corner_offset)

# terrain.h, from the game's own TERRAIN0..TERRAIN28 resources.
TERRAIN_MASK = 0x1f
HILLY, RIVER, HIGH = 0x20, 0x40, 0x80
FOREST_FIRST, FOREST_LAST = 8, 23
ARCTIC, OCEAN, SEA_LANE = 24, 25, 26
P1_SETTLEMENT, P1_ROAD, P1_PLOWED = 0x02, 0x08, 0x40
ROAD_BITS = 0x0a        # the draw function tests plane 1 bits 0xa for a road
NIBBLE_NONE = 15
EUROPEAN_COUNT = 4

# SEG27:0x0 and SEG27:0x9 -- the eight-direction ring, N first, clockwise.
RING = ((0, -1), (1, -1), (1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1))
# N 8, S 4, W 2, E 1, in the order every mask helper tests them.
ORTHO = ((0, -1, 8), (0, 1, 4), (-1, 0, 2), (1, 0, 1))
# The four orthogonal neighbours in the order `g_ortho_dx`/`g_ortho_dy` hold
# them, which the seam masks settle: mask 0 speckles the north edge, mask 1 the
# east, mask 2 the south, mask 3 the west. `d` below is that index, the same
# one the seam byte carries.
SEAM_SIDES = ((0, -1, 0), (1, 0, 1), (0, 1, 2), (-1, 0, 3))
# The four whole-edge shore squares, as (pattern, mask) on the ring bits:
# land at N,W,NW / N,NE,E / S,SW,W / E,SE,S -> icons 0x97..0x9a.
SHORE_PATTERNS = ((0xc1, 0xdd), (0x07, 0x77), (0x70, 0x77), (0x1c, 0xdd))

# Presentation, not a finding: no code binds a colour or a building to a
# nation. The four European colours are the flags on the sheet; the villages
# are the four native settlement pictures, handed to tribes by eye.
NATION_COLOURS = {0: (196, 24, 24), 1: (32, 56, 200), 2: (232, 196, 24),
                  3: (255, 132, 0)}
NATIVE_COLOUR = (150, 100, 52)
VILLAGE_BY_NATION = {4: "stone", 5: "pyramid", 6: "hut", 7: "hut", 8: "hut",
                     9: "tipi", 10: "tipi", 11: "tipi"}


class MapviewError(Exception):
    pass


class Plane(object):
    """A plane, with off-map reads answering as ocean.

    `terrain_at` (`1040:42e8`) returns TERRAIN_OCEAN for a square that is not on
    the map, so the edge of the image behaves like the edge of the game's map.
    """

    def __init__(self, data, w, h, off_map=OCEAN):
        self.d, self.w, self.h, self.off = data, w, h, off_map

    def at(self, x, y):
        if 0 <= x < self.w and 0 <= y < self.h:
            return self.d[y * self.w + x]
        return self.off


def terrain_class(b):
    """The low five bits: map mode 0 folds nothing (`terrain_class_1038_c257`)."""
    return b & TERRAIN_MASK


def is_forest(cls):
    return FOREST_FIRST <= cls <= FOREST_LAST


def is_water(cls):
    return cls in (OCEAN, SEA_LANE)


def neighbour_class(p0, x, y):
    """A neighbour as `neighbor_terrain_scan_1038_d520` reads it: five bits,
    then three unless the value is 0x18 or above."""
    t = p0.at(x, y) & TERRAIN_MASK
    return t & 7 if t < 0x18 else t


def scan_neighbours(p0, x, y):
    """(count, corner codes, land mask) for the eight squares around this one.

    Even directions are the orthogonals and set bit 2 of their own corner and
    bit 0 of the next; odd ones are the diagonals and set bit 1 of one corner.
    """
    corners = [0, 0, 0, 0]
    count = 0
    bits = 0
    for i, (dx, dy) in enumerate(RING):
        if is_water(neighbour_class(p0, x + dx, y + dy)):
            continue
        count += 1
        bits |= 1 << i
        if i & 1:
            corners[((i + 1) & 7) >> 1] |= 2
        else:
            j = i >> 1
            corners[j] |= 4
            corners[(j + 1) & 3] |= 1
    return count, corners, bits


def coast_land_group(p0, x, y):
    """What a water square's coastline says the land behind it is, or None.

    `cell_draw_terrain_1008_7e2d` asks `coast_neighbours_1008_7cb5` this, and
    that routine walks the eight neighbours keeping the terrain of the last
    ORTHOGONAL land one -- so west wins over south, south over east, east over
    north -- folded to three bits below 0x18. With no land at all around it the
    square answers -1 and nothing is drawn.

    One faithful gap: when a water square has land only on its diagonals, the
    routine leaves the remembered terrain at whatever the previous call put
    there, and the answer is that stale value. This returns None instead of
    reproducing a global left over from the last square drawn.
    """
    land = None
    any_land = False
    for i, (dx, dy) in enumerate(RING):
        t = p0.at(x + dx, y + dy) & TERRAIN_MASK
        t = t & 7 if t < 0x18 else t
        if is_water(t):
            continue
        any_land = True
        if not i & 1:
            land = t
    return land if any_land else None


def seams(p0, x, y):
    """Which terrain seams this square carries, as (mask, terrain id) pairs.

    `build_terrain_seams_1008_7ec9` precomputes one byte per square per
    orthogonal direction -- `0xff` for none -- and `draw_tile_with_overlays`
    draws the base square plus up to four of them. The rule, on the low five
    bits of plane 0:

        neighbour below 0x18   a seam when its GROUP (terrain % 8) differs,
                               showing that group:  (nb % 8) * 4 + direction
        neighbour is 0x18      the arctic edge:     direction + 0x20
        this square is 0x1a,
        neighbour is 0x19      direction + 0x28
        this square is 0x19,
        neighbour is 0x1a      direction + 0x24

    The water rows are the subtle ones. A land square beside open water asks
    `cell_draw_terrain_1008_7e2d` what that water draws as, and the answer is
    the group of the land the water's own coastline touches -- see
    `coast_land_group`. So a shore seams with whatever is across the water from
    it, and not at all when that is its own group, which is the common case.
    """
    base = p0.at(x, y) & TERRAIN_MASK
    out = []
    for dx, dy, d in SEAM_SIDES:
        nb = p0.at(x + dx, y + dy) & TERRAIN_MASK
        if nb == base:
            continue
        if nb < ARCTIC:
            if nb % 8 != base % 8:
                out.append((d, nb % 8))
        elif nb == ARCTIC:
            out.append((d, ARCTIC))
        elif nb == OCEAN:
            if base < OCEAN:
                # The beach belongs to the land the water touches, not to the
                # sea: the land square asks the water what is behind it.
                t = coast_land_group(p0, x + dx, y + dy)
                if t is None:
                    pass
                elif t < ARCTIC:
                    if t % 8 != base % 8:
                        out.append((d, t % 8))
                elif t == ARCTIC:
                    out.append((d, ARCTIC))
            elif base == SEA_LANE:
                out.append((d, OCEAN))
        elif nb == SEA_LANE:
            if base == OCEAN:
                out.append((d, SEA_LANE))
    return out


def shore_piece(land):
    """Which whole-edge shore square, if any, the land around this water fits.

    Four exact tests on the eight-direction land mask, in the order the draw
    routine makes them; the last match wins, as it does there. A water square
    whose land does not fit one of the four is drawn from the corner pieces.
    """
    shore = None
    for sel, (pattern, mask) in enumerate(SHORE_PATTERNS):
        if land & mask == pattern:
            shore = sel
    return shore


def forest_mask(p0, x, y):
    """Which orthogonal neighbours the forest blends into.

    The predicate itself is `tile_passable_1038_d44f`, which the reconstruction
    carries as a stub, so "the neighbour is also forest" is **inferred** from
    what the band draws rather than read off the code.
    """
    m = 0
    for dx, dy, bit in ORTHO:
        if is_forest(terrain_class(p0.at(x + dx, y + dy))):
            m += bit
    return m


def hilly_mask(p0, x, y, value):
    """`tile_neighbor_match`: neighbours whose byte & 0xa0 equals this one's."""
    m = 0
    for dx, dy, bit in ORTHO:
        if (p0.at(x + dx, y + dy) & 0xa0) == value:
            m += bit
    return m


def river_mask(p0, x, y):
    """`orthogonal_neighbor_bits(0x40)`: neighbours that carry a river."""
    m = 0
    for dx, dy, bit in ORTHO:
        if p0.at(x + dx, y + dy) & RIVER:
            m += bit
    return m


def road_mask(p1, x, y):
    """`neighbor_bits(0xa)`: all eight neighbours, bit i for ring direction i."""
    m = 0
    for i, (dx, dy) in enumerate(RING):
        if p1.at(x + dx, y + dy) & ROAD_BITS:
            m |= 1 << i
    return m


# --------------------------------------------------------------------------- #

class Canvas(object):
    """An RGB image, tile-sized cells blitted into it."""

    def __init__(self, w, h):
        self.w, self.h = w, h
        self.buf = bytearray(w * h * 3)

    def blit(self, cell, px, py):
        w, h, rgb, opaque = cell
        for y in range(h):
            ty = py + y
            if not 0 <= ty < self.h:
                continue
            row = y * w
            base = (ty * self.w + px) * 3
            for x in range(w):
                if not opaque[row + x]:
                    continue
                tx = px + x
                if not 0 <= tx < self.w:
                    continue
                i = base + x * 3
                self.buf[i:i + 3] = rgb[(row + x) * 3:(row + x) * 3 + 3]

    def box(self, px, py, w, h, colour):
        for y in range(py, min(py + h, self.h)):
            if y < 0:
                continue
            for x in range(px, min(px + w, self.w)):
                if x < 0:
                    continue
                i = (y * self.w + x) * 3
                self.buf[i:i + 3] = bytes(colour)


def _seams(canvas, tiles, p0, x, y, px, py, plain):
    """The four overlay slots of `draw_tile_with_overlays`, in the same place."""
    if plain:
        return
    for d, terrain in seams(p0, x, y):
        canvas.blit(tiles.seam(BASE_CELLS[terrain], d), px, py)


def _square(canvas, tiles, p0, p1, x, y, px, py, plain):
    """One map square, in the order `1038:d8f8` paints it."""
    b0 = p0.at(x, y)
    cls = terrain_class(b0)
    water = is_water(cls)
    count = 0
    if water:
        count, corners, land = scan_neighbours(p0, x, y)
    if water and count == 0:
        canvas.blit(tiles.cell(BASE_CELLS[cls]), px, py)
        _seams(canvas, tiles, p0, x, y, px, py, plain)
        return

    kind = cls & 7 if cls < 0x18 else cls
    base = 17 if (kind == 1 and is_forest(cls)) else kind
    canvas.blit(tiles.cell(BASE_CELLS[base]), px, py)
    _seams(canvas, tiles, p0, x, y, px, py, plain)

    if kind != 1 and is_forest(cls):
        canvas.blit(tiles.cell(band_cell("forest", forest_mask(p0, x, y))), px, py)

    if p1 is not None and not plain and (p1.at(x, y) & P1_PLOWED):
        canvas.blit(tiles.cell(PLOWED_CELL), px, py)

    if (b0 & HILLY) and not water:
        mask = hilly_mask(p0, x, y, b0 & 0xa0)
        canvas.blit(tiles.cell(band_cell(
            "mountains" if b0 & HIGH else "hills", mask)), px, py)

    if (b0 & RIVER) and not water:
        mask = river_mask(p0, x, y)
        canvas.blit(tiles.cell(band_cell(
            "river_major" if b0 & HIGH else "river_minor", mask)), px, py)

    if p1 is not None and not water and (p1.at(x, y) & ROAD_BITS):
        mask = road_mask(p1, x, y)
        if mask == 0:
            canvas.blit(tiles.cell(band_cell("road", 0)), px, py)
        else:
            for i in range(8):
                if mask & (1 << i):
                    canvas.blit(tiles.cell(band_cell("road", 1 + i)), px, py)

    if water:
        shore = shore_piece(land)
        if shore is not None:
            canvas.blit(tiles.cell(SHORE_CELLS[shore]), px, py)
        else:
            for j in range(4):
                dx, dy = corner_offset(j)
                # Open water under the piece, as the builder composites it.
                canvas.blit(tiles.cell(CORNER_WATER), px + dx, py + dy)
                canvas.blit(tiles.cell(corner_cell(corners[j], j), CORNER_BACKGROUND),
                            px + dx, py + dy)


def _settlement(canvas, tiles, p1, p2, x, y, px, py):
    """A colony or a village, from plane 1 bit 0x02 and plane 2's high nibble.

    Both the pictures and the colours are a presentation choice; see
    `colwin/tileset.py`.
    """
    if not (p1.at(x, y) & P1_SETTLEMENT):
        return None
    nation = p2.at(x, y) >> 4
    if nation == NIBBLE_NONE:
        nation = None
    if nation is not None and nation < EUROPEAN_COUNT:
        canvas.blit(tiles.cell(COLONY_CELL), px, py)
        colour = NATION_COLOURS[nation]
    else:
        kind = VILLAGE_BY_NATION.get(nation, "hut")
        canvas.blit(tiles.cell(VILLAGE_CELLS[kind]), px, py)
        colour = NATIVE_COLOUR
    canvas.box(px + 1, py + 1, 7, 7, (0, 0, 0))
    canvas.box(px + 2, py + 2, 5, 5, colour)
    return nation


def _shrink(canvas, size):
    """Nearest-neighbour, whole squares only: sample each output pixel."""
    w = canvas.w * size // TILE
    h = canvas.h * size // TILE
    out = Canvas(w, h)
    for y in range(h):
        sy = y * TILE // size
        for x in range(w):
            i = (sy * canvas.w + x * TILE // size) * 3
            o = (y * w + x) * 3
            out.buf[o:o + 3] = canvas.buf[i:i + 3]
    return out


def render(game_map, tiles, plain=False, tile_size=TILE):
    """The whole map as a `Canvas`, plus what was drawn."""
    w, h = game_map["width"], game_map["height"]
    planes = game_map["planes"]
    p0 = Plane(planes[0], w, h)
    p1 = p2 = None
    if game_map["kind"] == "SAV":
        p1 = Plane(planes[1], w, h, off_map=0)
        p2 = Plane(planes[2], w, h, off_map=0xff)

    canvas = Canvas(w * TILE, h * TILE)
    tally = {"squares": w * h, "settlements": 0, "colonies": 0, "villages": 0}
    for y in range(h):
        for x in range(w):
            _square(canvas, tiles, p0, p1, x, y, x * TILE, y * TILE, plain)
    if p1 is not None:
        # Counted whether or not they are drawn, so that --plain still reports
        # what is in the file.
        for y in range(h):
            for x in range(w):
                if not (p1.at(x, y) & P1_SETTLEMENT):
                    continue
                nation = p2.at(x, y) >> 4
                tally["settlements"] += 1
                if nation < EUROPEAN_COUNT:
                    tally["colonies"] += 1
                else:
                    tally["villages"] += 1
                if not plain:
                    _settlement(canvas, tiles, p1, p2, x, y, x * TILE, y * TILE)
    if tile_size != TILE:
        canvas = _shrink(canvas, tile_size)
    return canvas, tally


def render_file(path, game, out, plain=False, tile_size=TILE):
    """Read a `.MP` or `.SAV`, draw it, write the PNG. Returns a report."""
    if not 1 <= tile_size <= TILE:
        raise MapviewError("--tile takes 1 to %d pixels a square, not %d"
                           % (TILE, tile_size))
    game_map = mapfile.load(path)
    tiles = Tileset.from_game(game)
    canvas, tally = render(game_map, tiles, plain=plain, tile_size=tile_size)
    png.write_rgb(out, canvas.w, canvas.h, bytes(canvas.buf))
    tally.update({"kind": game_map["kind"], "width": game_map["width"],
                  "height": game_map["height"], "image": (canvas.w, canvas.h),
                  "map_start": game_map["map_start"]})
    return tally
