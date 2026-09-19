#!/usr/bin/env python3
"""Tests for `colwin map-preview`.

    python3 tests/test_map.py /path/to/Colonization

The format tests run on synthetic files and need no game. The tile-set tests
need one, and the most interesting of them re-derives the neighbour-mask
convention **from the pixels**: the code that paints a map square weights its
four neighbours N 8, S 4, W 2, E 1, and if that is the right reading of the art
then in every 16-cell band on the sheet, cell 1 carries artwork on its east
edge alone, cell 2 on its west, cell 4 on its south and cell 8 on its north.
Nothing makes that true except the assignment being right.
"""
import os
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from colwin import mapview                                          # noqa: E402
from colwin import png as pnglib                                    # noqa: E402
from colwin.formats import mapfile                                  # noqa: E402
from colwin.tileset import (BANDS, BASE_CELLS, CORNER_BACKGROUND,     # noqa: E402
                            CORNER_WATER, KEY_GROUND, MASK_CELLS, MASK_KEEP,
                            SHORE_CELLS, SHORE_OPEN, Tileset, band_cell,
                            corner_cell, corner_offset)

GAME = os.environ.get("COLWIN_GAME")
_tiles = {}


def game_or_skip(t):
    if not GAME or not os.path.isdir(GAME):
        t.skipTest("set COLWIN_GAME (or pass the game directory) to run this")
    return GAME


def tileset(game):
    if game not in _tiles:
        _tiles[game] = Tileset.from_game(game)
    return _tiles[game]


def make_mp(w, h, planes=None):
    body = struct.pack("<HHH", w, h, 4)
    planes = planes or [bytes(w * h) for _ in range(3)]
    return body + b"".join(planes)


def make_sav(w, h, records=(0, 0, 0), planes=None):
    n = w * h
    c18, c28, c202 = records
    head = bytearray(mapfile.SAV_FIXED_BEFORE_MAP)
    head[0:9] = mapfile.SAV_MAGIC
    struct.pack_into("<HH", head, mapfile.SAV_DIMS, w, h)
    struct.pack_into("<HHH", head, 0x2a, c18, c28, c202)
    body = bytes(18 * c18 + 28 * c28 + 202 * c202)
    planes = planes or [bytes(n) for _ in range(4)]
    return bytes(head) + body + b"".join(planes) + bytes(mapfile.SAV_FIXED_AFTER_MAP)


class MpFormat(unittest.TestCase):
    def test_a_map_is_six_bytes_and_three_planes(self):
        m = mapfile.decode(make_mp(4, 5))
        self.assertEqual((m["kind"], m["width"], m["height"]), ("MP", 4, 5))
        self.assertEqual([len(p) for p in m["planes"]], [20, 20, 20])

    def test_a_size_that_does_not_close_is_refused_with_the_arithmetic(self):
        with self.assertRaises(mapfile.MapError) as cm:
            mapfile.decode(make_mp(4, 5) + b"\0")
        self.assertIn("6 + 3*4*5", str(cm.exception))

    def test_zero_dimensions(self):
        with self.assertRaises(mapfile.MapError):
            mapfile.decode(struct.pack("<HHH", 0, 5, 4))


class SavFormat(unittest.TestCase):
    def test_planes_land_where_the_record_counts_put_them(self):
        m = mapfile.decode(make_sav(4, 5, records=(2, 3, 1)))
        self.assertEqual(m["kind"], "SAV")
        self.assertEqual(m["record_counts"], {"18B": 2, "28B": 3, "202B": 1})
        self.assertEqual(m["map_start"],
                         mapfile.SAV_FIXED_BEFORE_MAP + 18 * 2 + 28 * 3 + 202)
        self.assertEqual([len(p) for p in m["planes"]], [20] * 4)

    def test_a_save_whose_arithmetic_does_not_close_is_refused(self):
        with self.assertRaises(mapfile.MapError) as cm:
            mapfile.decode(make_sav(4, 5) + b"\0" * 3)
        self.assertIn("does not close", str(cm.exception))

    def test_the_planes_are_the_bytes_at_that_offset(self):
        n = 4 * 5
        planes = [bytes([i + 1]) * n for i in range(4)]
        m = mapfile.decode(make_sav(4, 5, records=(1, 0, 0), planes=planes))
        self.assertEqual([p[0] for p in m["planes"]], [1, 2, 3, 4])


class Masks(unittest.TestCase):
    """The mask helpers, against hand-built planes."""

    def plane(self, rows):
        h = len(rows)
        w = len(rows[0])
        return mapview.Plane(bytes(b for row in rows for b in row), w, h)

    def test_river_mask_weights_n8_s4_w2_e1(self):
        R = mapview.RIVER
        p = self.plane([[0, R, 0], [0, R, 0], [0, 0, 0]])
        self.assertEqual(mapview.river_mask(p, 1, 1), 8)
        p = self.plane([[0, 0, 0], [R, R, R], [0, 0, 0]])
        self.assertEqual(mapview.river_mask(p, 1, 1), 3)
        p = self.plane([[0, R, 0], [R, R, R], [0, R, 0]])
        self.assertEqual(mapview.river_mask(p, 1, 1), 15)

    def test_off_the_map_answers_as_ocean(self):
        p = self.plane([[mapview.OCEAN]])
        self.assertEqual(p.at(-1, 0), mapview.OCEAN)
        self.assertEqual(p.at(0, 99), mapview.OCEAN)
        self.assertEqual(mapview.scan_neighbours(p, 0, 0)[0], 0)

    def test_a_lone_land_square_gives_every_corner_the_full_code(self):
        land, sea = 4, mapview.OCEAN
        p = self.plane([[sea] * 3, [sea, land, sea], [sea] * 3])
        count, corners, _land, _behind = mapview.scan_neighbours(p, 1, 1)
        self.assertEqual(count, 0)              # the land square itself is centre
        count, corners, _land, _behind = mapview.scan_neighbours(p, 0, 0)
        self.assertEqual(count, 1)              # the land square, diagonally
        self.assertEqual(corners, [0, 0, 2, 0])

    def test_the_scan_reports_the_land_behind_a_coast(self):
        """It overwrites the square's own class, and the drawer reads it back.

        The last ORTHOGONAL land neighbour wins -- west over south, south over
        east, east over north -- and a water square with land only on its
        diagonals reports nothing, so it keeps its own tile.
        """
        sea, desert, grass = mapview.OCEAN, 1, 4
        p = self.plane([[sea, grass, sea], [desert, sea, sea], [sea, sea, sea]])
        self.assertEqual(mapview.scan_neighbours(p, 1, 1)[3], desert)  # west wins
        p = self.plane([[sea, grass, sea], [sea, sea, sea], [sea, sea, sea]])
        self.assertEqual(mapview.scan_neighbours(p, 1, 1)[3], grass)
        p = self.plane([[grass, sea, sea], [sea, sea, sea], [sea, sea, sea]])
        count, _c, _b, behind = mapview.scan_neighbours(p, 1, 1)
        self.assertEqual(count, 1)              # a diagonal, so it is a coast
        self.assertIsNone(behind)               # but nothing was written

    def test_hilly_mask_matches_only_the_same_kind(self):
        hills, mountains = 0x20, 0xa0
        p = self.plane([[0, mountains, 0], [hills, hills, mountains], [0, 0, 0]])
        self.assertEqual(mapview.hilly_mask(p, 1, 1, hills), 2)
        self.assertEqual(mapview.hilly_mask(p, 1, 1, mountains), 9)


class Seams(unittest.TestCase):
    """`build_terrain_seams_1008_7ec9`, on hand-built planes."""

    def plane(self, rows):
        h = len(rows)
        w = len(rows[0])
        return mapview.Plane(bytes(b for row in rows for b in row), w, h)

    def test_the_same_group_has_no_seam_between_it(self):
        # 4 is grassland and 12 is conifer forest: the same group, 4 % 8.
        p = self.plane([[4, 12, 4], [12, 4, 12], [4, 12, 4]])
        self.assertEqual(mapview.seams(p, 1, 1), [])

    def test_a_different_group_seams_on_that_side_showing_the_neighbour(self):
        p = self.plane([[4, 1, 4], [4, 4, 4], [4, 4, 4]])
        self.assertEqual(mapview.seams(p, 1, 1), [(0, 1)])
        p = self.plane([[4, 4, 4], [4, 4, 2], [4, 6, 4]])
        self.assertEqual(sorted(mapview.seams(p, 1, 1)), [(1, 2), (2, 6)])

    def test_a_forest_seams_as_its_group_not_its_id(self):
        # 13 is tropical forest: group 5, savannah. Against grassland, group 4.
        p = self.plane([[4, 13, 4], [4, 4, 4], [4, 4, 4]])
        self.assertEqual(mapview.seams(p, 1, 1), [(0, 5)])

    def test_arctic_seams_as_itself(self):
        p = self.plane([[4, 24, 4], [4, 4, 4], [4, 4, 4]])
        self.assertEqual(mapview.seams(p, 1, 1), [(0, mapview.ARCTIC)])

    def test_land_beside_open_water_gets_no_seam(self):
        """cell_draw_terrain answers 0x19 or -1, and the branch takes neither."""
        p = self.plane([[4, 25, 4], [26, 4, 25], [4, 25, 4]])
        self.assertEqual(mapview.seams(p, 1, 1), [])

    def test_water_seams_with_the_land_it_touches_except_desert(self):
        """The `% 8` collision: ocean is 25, and 25 % 8 is 1, which is desert.

        The seam test is `nb % 8 != base % 8`, so an ocean square seams with
        every land group but the one whose number it shares. Desert coasts get
        nothing, in the game as here. Sea lane is 26, so it collides with plains
        the same way -- a prediction no shipped map can test, because no sea
        lane on AMER2.MP touches land.
        """
        sea = mapview.OCEAN
        for group, seamed in ((4, True), (2, True), (7, True), (1, False)):
            p = self.plane([[sea, group, sea], [sea, sea, sea], [sea] * 3])
            got = mapview.seams(p, 1, 1)
            self.assertEqual(bool(got), seamed,
                             "ocean beside group %d: %r" % (group, got))
            if seamed:
                self.assertEqual(got, [(0, group)])
        p = self.plane([[mapview.SEA_LANE, 2, mapview.SEA_LANE],
                        [mapview.SEA_LANE] * 3, [mapview.SEA_LANE] * 3])
        self.assertEqual(mapview.seams(p, 1, 1), [],
                         "sea lane should collide with plains")

    def test_a_shore_asks_the_water_what_is_across_it(self):
        """`cell_draw_terrain` answers with the water's own last land neighbour."""
        sea, desert, grass = mapview.OCEAN, 1, 4
        # The water's west neighbour is grassland, so the desert across it seams
        # with grassland; west wins over the other orthogonals.
        p = self.plane([[sea, sea, sea], [grass, sea, desert], [sea, sea, sea]])
        self.assertEqual(mapview.coast_land_group(p, 1, 1), grass)
        self.assertEqual(mapview.seams(p, 2, 1), [(3, grass)])
        # Water with no land around it answers nothing at all.
        p = self.plane([[sea] * 3, [sea, sea, desert], [sea] * 3])
        self.assertIsNone(mapview.coast_land_group(p, 0, 0))

    def test_the_two_waters_seam_against_each_other_both_ways(self):
        p = self.plane([[25, 26, 25], [25, 25, 25], [25, 25, 25]])
        self.assertEqual(mapview.seams(p, 1, 1), [(0, mapview.SEA_LANE)])
        p = self.plane([[26, 25, 26], [26, 26, 26], [26, 26, 26]])
        self.assertEqual(mapview.seams(p, 1, 1), [(0, mapview.OCEAN)])


class SeamArt(unittest.TestCase):
    """The seam masks, which are the game's own sprites (icons 0x69..0x6c)."""

    def test_each_mask_keeps_sixty_four_pixels_along_its_own_edge(self):
        """Eight pixels deep, about six percent of the square, one edge each.

        `load_all_sprite_sheets` cuts these four cells keying out colour 0x87 --
        canvas index 95, black, since the canvas is installed at palette 40 --
        so the black pixels are what the seam keeps. Sixty-four of 1,024, in a
        speckle along one edge, is what makes a terrain boundary in this game a
        scatter rather than a band.
        """
        tiles = tileset(game_or_skip(self))
        depth = 8
        for d, (mx, my, w, h) in sorted(MASK_CELLS.items()):
            kept = [(x, y) for y in range(h) for x in range(w)
                    if tiles.pixels[(my + y) * tiles.width + mx + x] == MASK_KEEP]
            self.assertEqual(len(kept), 64, "mask %d keeps %d" % (d, len(kept)))
            near = {0: lambda x, y: y < depth, 1: lambda x, y: x >= w - depth,
                    2: lambda x, y: y >= h - depth, 3: lambda x, y: x < depth}[d]
            outside = [p for p in kept if not near(*p)]
            self.assertEqual(outside, [],
                             "mask %d keeps %d pixels off its edge"
                             % (d, len(outside)))

    def test_no_row_of_a_seam_is_solid(self):
        """A speckle, not a band: both sides of a boundary draw one."""
        tiles = tileset(game_or_skip(self))
        w, h, _rgb, keep = tiles.seam(BASE_CELLS[1], 0)
        rows = [sum(keep[y * w + x] for x in range(w)) for y in range(h)]
        self.assertLess(max(rows), w * 0.6, "a row is nearly solid: %r" % rows[:8])
        self.assertEqual(sum(rows[8:]), 0, "the seam reaches past 8 pixels")
        self.assertGreater(sum(rows), 40, "the seam is barely there: %d" % sum(rows))

    def test_a_seam_paints_its_own_edge_and_not_the_far_one(self):
        tiles = tileset(game_or_skip(self))
        box = BASE_CELLS[1]
        for d, near, far in ((0, 0, 31), (2, 31, 0), (3, 0, 31), (1, 31, 0)):
            w, h, _rgb, keep = tiles.seam(box, d)
            if d in (0, 2):
                on = sum(keep[near * w + x] for x in range(w))
                off = sum(keep[far * w + x] for x in range(w))
            else:
                on = sum(keep[y * w + near] for y in range(h))
                off = sum(keep[y * w + far] for y in range(h))
            self.assertGreater(on, 0, "mask %d misses its edge" % d)
            self.assertEqual(off, 0, "mask %d reaches the far edge" % d)

    def test_a_seam_is_a_subset_of_the_square_it_is_cut_from(self):
        tiles = tileset(game_or_skip(self))
        box = BASE_CELLS[3]
        _w, _h, rgb, full = tiles.cell(box)
        _w, _h, seam_rgb, part = tiles.seam(box, 0)
        self.assertEqual(rgb, seam_rgb)             # same pixels, fewer shown
        self.assertLess(sum(part), sum(full))
        for i, v in enumerate(part):
            if v:
                self.assertTrue(full[i], "seam paints where the square does not")


class Cells(unittest.TestCase):
    def test_corner_pieces_tile_the_square(self):
        seen = set()
        for j in range(4):
            dx, dy = corner_offset(j)
            seen.add((dx, dy))
        self.assertEqual(seen, {(0, 0), (16, 0), (16, 16), (0, 16)})

    def test_every_corner_cell_is_a_distinct_16x16_box(self):
        boxes = [corner_cell(code, j) for code in range(8) for j in range(4)]
        self.assertEqual(len(set(boxes)), 32)
        for b in boxes:
            self.assertEqual(b[2:], (16, 16))


class Art(unittest.TestCase):
    """The cell table, against the pixels of a real install."""

    def edges(self, tiles, box):
        w, h, _rgb, opaque = tiles.cell(box)
        at = lambda x, y: opaque[y * w + x]
        return {"n": sum(at(x, 0) for x in range(w)),
                "s": sum(at(x, h - 1) for x in range(w)),
                "w": sum(at(0, y) for y in range(h)),
                "e": sum(at(w - 1, y) for y in range(h))}

    def test_the_bands_are_indexed_by_the_neighbour_mask_the_code_uses(self):
        """N 8, S 4, W 2, E 1 -- re-derived from which edge each cell paints."""
        tiles = tileset(game_or_skip(self))
        for band in ("river_major", "river_minor", "hills", "forest"):
            for mask, side in ((1, "e"), (2, "w"), (4, "s"), (8, "n")):
                e = self.edges(tiles, band_cell(band, mask))
                busiest = max(e, key=lambda k: e[k])
                self.assertEqual(busiest, side,
                                 "%s cell %d paints %s, not %s: %r"
                                 % (band, mask, busiest, side, e))
            full = self.edges(tiles, band_cell(band, 15))
            self.assertTrue(min(full.values()) > 0,
                            "%s cell 15 leaves an edge empty: %r" % (band, full))
            lone = self.edges(tiles, band_cell(band, 0))
            self.assertLess(sum(lone.values()), sum(full.values()) / 4,
                            "%s cell 0 reaches as far as cell 15: %r vs %r"
                            % (band, lone, full))

    def test_every_cell_in_the_table_is_on_the_canvas_and_paints_something(self):
        tiles = tileset(game_or_skip(self))
        boxes = list(BASE_CELLS.values())
        boxes += [band_cell(b, m) for b in BANDS for m in range(16)]
        for box in boxes:
            w, h, _rgb, opaque = tiles.cell(box)
            self.assertEqual((w, h), (32, 32), "%r" % (box,))
            self.assertTrue(any(opaque), "cell %r is empty" % (box,))

    def test_each_shore_square_is_open_on_the_edges_its_pattern_names(self):
        """0x97..0x9a are picked by four exact land patterns; the art agrees.

        A shore square carries water across the two edges its pattern leaves
        open and nothing across the two the land is on. That, in reading order,
        is what identifies the 2x2 block as those four icons.
        """
        tiles = tileset(game_or_skip(self))
        for sel, box in sorted(SHORE_CELLS.items()):
            w, h, _rgb, opaque = tiles.cell(box)
            cover = {"n": sum(opaque[x] for x in range(w)),
                     "s": sum(opaque[(h - 1) * w + x] for x in range(w)),
                     "w": sum(opaque[y * w] for y in range(h)),
                     "e": sum(opaque[y * w + w - 1] for y in range(h))}
            for side in ("n", "e", "s", "w"):
                if side in SHORE_OPEN[sel]:
                    self.assertGreater(cover[side], w * 0.8,
                                       "shore %d should be open on %s: %r"
                                       % (sel, side, cover))
                else:
                    self.assertLess(cover[side], w * 0.4,
                                    "shore %d should be closed on %s: %r"
                                    % (sel, side, cover))

    def test_each_corner_piece_leans_the_way_its_code_calls_land(self):
        """`g_4c6e[j] * 4 + j + 0x6d`, checked against the art.

        The corner code's three bits say which of the two edges at that corner,
        and the diagonal, are land. Each piece is a shore blob rather than a
        clean band, so the test is where its painted pixels LEAN: toward the
        sides the code calls land -- and code 0, which calls none, paints
        nothing at all. Where both edges are land the shore wraps the corner
        and sits centrally, so there only its size is asserted.
        """
        tiles = tileset(game_or_skip(self))
        # For each position: the direction of the bit-4 edge, the bit-1 edge
        # and the bit-2 diagonal, as (dx, dy) out of the corner.
        lean = {0: ((0, -1), (-1, 0), (-1, -1)), 1: ((1, 0), (0, -1), (1, -1)),
                2: ((0, 1), (1, 0), (1, 1)), 3: ((-1, 0), (0, 1), (-1, 1))}
        for code in range(8):
            for j in range(4):
                w, h, _rgb, opaque = tiles.cell(corner_cell(code, j),
                                                CORNER_BACKGROUND)
                n = sum(opaque)
                if code == 0:
                    self.assertEqual(n, 0, "code 0 piece %d paints %d" % (j, n))
                    continue
                if code & 5 == 5:
                    # Land on both edges: the shore wraps the corner, so the
                    # blob is central and only its size says anything.
                    self.assertGreater(n, w * h * 0.35,
                                       "code %d piece %d paints only %d"
                                       % (code, j, n))
                    continue
                cx = sum(i % w for i in range(w * h) if opaque[i]) / n - (w - 1) / 2.0
                cy = sum(i // w for i in range(w * h) if opaque[i]) / n - (h - 1) / 2.0
                vx = vy = 0
                for bit, (dx, dy) in zip((4, 1, 2), lean[j]):
                    if code & bit:
                        vx += dx
                        vy += dy
                if vx == vy == 0:
                    continue
                self.assertGreater(cx * vx + cy * vy, 0,
                                   "code %d piece %d leans (%.1f, %.1f), "
                                   "the code says (%d, %d)"
                                   % (code, j, cx, cy, vx, vy))

    def test_the_key_colour_is_dropped_everywhere_it_appears(self):
        """Colour-keyed, not flooded: the game's ExtractSprite drops a colour.

        The forest band's canopies enclose pockets of the sheet's ground, and
        flooding inward from the border leaves them painted -- which put grey
        specks over every wooded square. Nothing keyed may survive anywhere.
        """
        tiles = tileset(game_or_skip(self))
        for box in [band_cell("forest", m) for m in range(16)] + [BASE_CELLS[4]]:
            w, h, _rgb, opaque = tiles.cell(box, KEY_GROUND)
            x0, y0 = box[0], box[1]
            for y in range(h):
                for x in range(w):
                    if tiles.pixels[(y0 + y) * tiles.width + x0 + x] == KEY_GROUND:
                        self.assertFalse(opaque[y * w + x],
                                         "%r paints the key at (%d, %d)"
                                         % (box, x, y))

    def test_a_composited_corner_keeps_water_black_and_holes_the_ground(self):
        """The builder's order: water, then the piece, then key out the ground.

        A pixel the piece paints in the ground colour covers the water first and
        is dropped second, so it becomes a hole for the land behind the coast to
        show through. Reading it the other way -- ground transparent, water
        below showing -- gives a solid block of water and a coastline that steps
        in squares. Codes 1 and 3..7 all carry ground pixels.
        """
        tiles = tileset(game_or_skip(self))
        holes = 0
        for code in range(8):
            for j in range(4):
                w, h, rgb, opaque = tiles.corner(code, j)
                px, py, _w, _h = corner_cell(code, j)
                for y in range(h):
                    for x in range(w):
                        v = tiles.pixels[(py + y) * tiles.width + px + x]
                        i = y * w + x
                        if v == KEY_GROUND:
                            self.assertFalse(opaque[i],
                                             "code %d/%d paints the ground" % (code, j))
                            holes += 1
                        else:
                            self.assertTrue(opaque[i],
                                            "code %d/%d drops a painted pixel"
                                            % (code, j))
        self.assertGreater(holes, 500, "no holes at all: %d" % holes)

    def test_a_corner_piece_is_water_where_it_is_black(self):
        tiles = tileset(game_or_skip(self))
        w, h, rgb, opaque = tiles.corner(0, 0)      # all black: plain water
        self.assertEqual(sum(opaque), w * h)
        wx, wy, _w, _h = CORNER_WATER
        for y in range(h):
            for x in range(w):
                i = y * w + x
                want = tiles.palette[tiles.pixels[(wy + y) * tiles.width + wx + x]]
                self.assertEqual(tuple(rgb[i * 3:i * 3 + 3]), want)

    def test_a_coastline_piece_is_keyed_twice(self):
        """Once on black when it is cut, once on the ground when composited."""
        tiles = tileset(game_or_skip(self))
        for code in range(8):
            for j in range(4):
                box = corner_cell(code, j)
                w, h, _rgb, opaque = tiles.cell(box, CORNER_BACKGROUND)
                for y in range(h):
                    for x in range(w):
                        v = tiles.pixels[(box[1] + y) * tiles.width + box[0] + x]
                        if v in CORNER_BACKGROUND:
                            self.assertFalse(opaque[y * w + x],
                                             "corner %d/%d keeps %d" % (code, j, v))

    def test_the_ocean_square_is_solid_and_the_forest_overlay_is_not(self):
        tiles = tileset(game_or_skip(self))
        _w, _h, _rgb, ocean = tiles.cell(BASE_CELLS[25])
        self.assertEqual(sum(ocean), 32 * 32)
        _w, _h, _rgb, forest = tiles.cell(band_cell("forest", 0))
        self.assertLess(sum(forest), 32 * 32)


class Render(unittest.TestCase):
    def render(self, name, **kw):
        game = game_or_skip(self)
        src = os.path.join(game, name)
        if not os.path.exists(src):
            self.skipTest("%s does not ship with this install" % name)
        fd, out = tempfile.mkstemp(suffix=".png")
        os.close(fd)
        self.addCleanup(os.unlink, out)
        return mapview.render_file(src, game, out, **kw), out

    def test_the_shipped_map_draws_at_its_own_size(self):
        r, out = self.render("AMER2.MP")
        self.assertEqual((r["width"], r["height"]), (58, 72))
        self.assertEqual(r["image"], (58 * 32, 72 * 32))
        d = pnglib.read(out)
        self.assertEqual((d["width"], d["height"]), (58 * 32, 72 * 32))

    def test_the_shipped_save_draws_its_settlements(self):
        r, _out = self.render("AUTO01.SAV", tile_size=4)
        self.assertEqual(r["kind"], "SAV")
        self.assertEqual(r["settlements"], r["colonies"] + r["villages"])
        self.assertTrue(r["settlements"] > 0)

    def test_tile_size_scales_the_image(self):
        r, _out = self.render("AMER2.MP", tile_size=4)
        self.assertEqual(r["image"], (58 * 4, 72 * 4))

    def test_an_impossible_tile_size_is_refused(self):
        game = game_or_skip(self)
        with self.assertRaises(mapview.MapviewError):
            mapview.render_file(os.path.join(game, "AMER2.MP"), game,
                                os.devnull, tile_size=99)


def main():
    global GAME
    argv = sys.argv[1:]
    if argv and os.path.isdir(argv[0]):
        GAME = argv.pop(0)
    unittest.main(argv=[sys.argv[0]] + argv, verbosity=2)


if __name__ == "__main__":
    main()
