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
from colwin.tileset import (BANDS, BASE_CELLS, Tileset, band_cell,   # noqa: E402
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
        count, corners = mapview.scan_neighbours(p, 1, 1)
        self.assertEqual(count, 0)              # the land square itself is centre
        count, corners = mapview.scan_neighbours(p, 0, 0)
        self.assertEqual(count, 1)              # the land square, diagonally
        self.assertEqual(corners, [0, 0, 2, 0])

    def test_hilly_mask_matches_only_the_same_kind(self):
        hills, mountains = 0x20, 0xa0
        p = self.plane([[0, mountains, 0], [hills, hills, mountains], [0, 0, 0]])
        self.assertEqual(mapview.hilly_mask(p, 1, 1, hills), 2)
        self.assertEqual(mapview.hilly_mask(p, 1, 1, mountains), 9)


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
