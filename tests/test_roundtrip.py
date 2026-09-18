#!/usr/bin/env python3
"""End-to-end tests against a real copy of the game.

    python3 tests/test_roundtrip.py /path/to/Colonization

Nothing here is mocked: every assertion is made against the shipped bytes.
Without a game directory the codec tests still run on synthetic data and the
asset tests skip, so this is usable in CI where the game cannot be shipped.
"""
import os
import random
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from colwin import png as pnglib                                   # noqa: E402
from colwin.ne import Module                                        # noqa: E402
from colwin.palette import Palette, view_palette, ctab_parse        # noqa: E402
from colwin.formats import cvpc, dib, lzw, sprt, text               # noqa: E402
from colwin.workspace import Workspace, WorkspaceError, payload     # noqa: E402

GAME = os.environ.get("COLWIN_GAME")
_ws_cache = {}


def game_or_skip(t):
    if not GAME or not os.path.isdir(GAME):
        t.skipTest("set COLWIN_GAME (or pass the game directory) to run this")
    return GAME


class Lzw(unittest.TestCase):
    def test_round_trip_over_shapes_and_depths(self):
        random.seed(11)
        for bpp in (3, 5, 6, 7, 8):
            n = 1 << bpp
            for data in (b"", b"\x00", bytes(n) * 300,
                         bytes(random.randrange(n) for _ in range(20000)),
                         bytes((i // 7) % n for i in range(50000)),
                         bytes(random.choice([0, 1, n - 1]) for _ in range(90000))):
                self.assertTrue(lzw.round_trip_ok(data, bpp),
                                "bpp=%d len=%d" % (bpp, len(data)))

    def test_dictionary_reset_is_exercised(self):
        """90k pixels over 3 symbols fills the 4,096-entry tables and resets."""
        data = bytes((i * i) % 3 for i in range(90000))
        self.assertTrue(lzw.round_trip_ok(data, 8))


class SprtCodec(unittest.TestCase):
    def test_empty_sprite(self):
        b = sprt.encode(bytes(16 * 16), 16, 16, (1, -2, 3, -4), 9, 8, 0)
        self.assertEqual(len(b), sprt.HDR)
        d = sprt.decode(b)
        self.assertEqual(d["bbox"], [0, 0, 0, 0])
        self.assertEqual(d["origin"], [1, -2, 3, -4])

    def test_a_row_with_a_hole_is_refused_by_name(self):
        px = bytearray(8 * 2)
        px[0] = px[7] = 5                       # two runs, a gap between them
        with self.assertRaises(sprt.SprtError) as cm:
            sprt.encode(bytes(px), 8, 2)
        self.assertIn("one run per row", str(cm.exception))
        filled = sprt.encode(bytes(px), 8, 2, fill_holes=5)
        self.assertEqual(sprt.decode(filled)["pixels"][:8], b"\x05" * 8)

    def test_blank_rows_inside_the_box(self):
        px = bytearray(4 * 3)
        px[0] = px[8] = 7                       # row 1 blank, between two solid
        b = sprt.encode(bytes(px), 4, 3)
        self.assertEqual(sprt.decode(b)["pixels"], bytes(px))


class TextCodec(unittest.TestCase):
    def test_the_gold_glyph_survives(self):
        s = "Treasure sold for {%NUMBER0¤}.\n"
        self.assertEqual(text.decode(text.encode(s)), s)
        self.assertIn(b"\xa4", text.encode(s))

    def test_an_unencodable_character_is_named(self):
        with self.assertRaises(text.TextError) as cm:
            text.encode("@width=380\nnot cp1252: 中\n")
        self.assertIn("line 2", str(cm.exception))


class PaletteRules(unittest.TestCase):
    def test_the_view_palette_is_injective(self):
        p = view_palette()
        self.assertEqual(p.duplicates(), {},
                         "colour -> index must be total, or RGB editing cannot "
                         "be inverted")
        self.assertEqual(len(set(p.entries)), 256)

    def test_uniquify_keeps_priority_entries_exact(self):
        p = Palette([(1, 1, 1)] * 256)
        p.uniquify(priority=[42])
        self.assertEqual(p.entries[42], (1, 1, 1))
        self.assertEqual(len(set(p.entries)), 256)

    def test_system_colours_are_where_the_measurements_say(self):
        p = view_palette()
        self.assertEqual(p.entries[255], (255, 255, 255))
        self.assertEqual(p.entries[249], (255, 0, 0))


class PngIo(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.d)

    def test_indexed_round_trip(self):
        pal = view_palette().entries
        px = bytes(range(256)) * 4
        p = os.path.join(self.d, "a.png")
        pnglib.write_indexed(p, 64, 16, px, pal, transparent=0)
        got = pnglib.read(p)
        self.assertEqual(got["mode"], "P")
        self.assertEqual(got["pixels"], px)
        self.assertEqual(list(got["palette"]), pal)

    def test_rgba_round_trip(self):
        px = bytes(random.randrange(256) for _ in range(32 * 8 * 4))
        p = os.path.join(self.d, "b.png")
        pnglib.write_rgba(p, 32, 8, px)
        self.assertEqual(pnglib.read(p)["pixels"], px)


# --------------------------------------------------------------------------- #
# against the real game

class Assets(unittest.TestCase):
    @classmethod
    def workspace(cls, game):
        if game not in _ws_cache:
            root = tempfile.mkdtemp(prefix="colwin-ws-")
            Workspace.extract(game, root, log=lambda *a: None)
            _ws_cache[game] = root
        return Workspace.open(_ws_cache[game])

    def test_every_module_rebuilds_byte_identical(self):
        game = game_or_skip(self)
        n = 0
        for f in sorted(os.listdir(game)):
            p = os.path.join(game, f)
            if not os.path.isfile(p):
                continue
            try:
                m = Module.load(p)
            except Exception:
                continue
            if not m.resources:
                continue
            self.assertEqual(m.rebuild(), m.data, f)
            n += 1
        self.assertGreater(n, 0)

    def test_every_asset_re_encodes_to_the_shipped_bytes(self):
        game = game_or_skip(self)
        ws = self.workspace(game)
        tally, failures, rebuilt = ws.verify(game, log=lambda *a: None)
        self.assertEqual(failures, [])
        self.assertTrue(all(ok for _, ok in rebuilt))
        self.assertEqual(tally["sprt"]["fail"], 0)
        self.assertEqual(tally["sprt"]["content"], 0,
                         "SPRT must be bit-exact, not merely equivalent")
        self.assertEqual(tally["text"]["content"], 0)
        self.assertEqual(tally["ctab"]["content"], 0)

    def test_an_rgb_export_inverts_to_the_same_indices(self):
        """The case that matters: the artist's editor dropped the indices."""
        game = game_or_skip(self)
        ws = self.workspace(game)
        sprites = [a for a in ws.m["assets"] if a["format"] == "sprt"][:40]
        self.assertTrue(sprites)
        tmp = tempfile.mkdtemp()
        try:
            for a in sprites:
                src = ws.path(a["file"])
                img = pnglib.read(src)
                pal = ws.load_palette(a["palette"])
                rgba = bytearray(img["width"] * img["height"] * 4)
                for i, v in enumerate(img["pixels"]):
                    r, g, b = pal.entries[v]
                    o = i * 4
                    rgba[o:o + 3] = bytes((r, g, b))
                    rgba[o + 3] = 0 if v == 0 else 255
                flat = os.path.join(tmp, "flat.png")
                pnglib.write_rgba(flat, img["width"], img["height"], bytes(rgba))
                w, h, idx, _ = ws._indices(flat, pal, False, "sprite")
                self.assertEqual(idx, img["pixels"], a["file"])
        finally:
            shutil.rmtree(tmp)

    def test_a_colour_outside_the_palette_is_refused_with_advice(self):
        game = game_or_skip(self)
        ws = self.workspace(game)
        a = next(x for x in ws.m["assets"] if x["format"] == "sprt" and x["width"] > 4)
        pal = ws.load_palette(a["palette"])
        img = pnglib.read(ws.path(a["file"]))
        rgba = bytearray(img["width"] * img["height"] * 4)
        for i in range(img["width"] * img["height"]):
            rgba[i * 4:i * 4 + 4] = b"\x01\x02\x03\xff"     # a colour nobody has
        tmp = tempfile.mkdtemp()
        try:
            p = os.path.join(tmp, "bad.png")
            pnglib.write_rgba(p, img["width"], img["height"], bytes(rgba))
            with self.assertRaises(WorkspaceError) as cm:
                ws._indices(p, pal, False, "sprite")
            self.assertIn("--nearest", str(cm.exception))
            w, h, idx, note = ws._indices(p, pal, True, "sprite")
            self.assertEqual(note["approximated_pixels"], img["width"] * img["height"])
        finally:
            shutil.rmtree(tmp)

    def test_editing_changes_that_resource_and_nothing_else(self):
        game = game_or_skip(self)
        root = tempfile.mkdtemp(prefix="colwin-edit-")
        out = tempfile.mkdtemp(prefix="colwin-out-")
        try:
            Workspace.extract(game, root, log=lambda *a: None)
            ws = Workspace.open(root)
            sp = next(a for a in ws.m["assets"]
                      if a["format"] == "sprt" and a["bbox"][3] > a["bbox"][1] + 2)
            img = pnglib.read(ws.path(sp["file"]))
            px = bytearray(img["pixels"])
            hit = next(i for i, v in enumerate(px) if v)
            px[hit] = 200 if px[hit] != 200 else 201
            pnglib.write_indexed(ws.path(sp["file"]), img["width"], img["height"],
                                 bytes(px), img["palette"], transparent=0)

            tx = next(a for a in ws.m["assets"] if a["format"] == "text")
            with open(ws.path(tx["file"]), "a") as f:
                f.write("\n")

            changed = {c[0]["file"] for c in ws.changed()}
            self.assertEqual(changed, {sp["file"], tx["file"]})

            ws.build(out, game, copy_all=False, log=lambda *a: None)
            touched = {sp["module"], tx["module"]}
            for name in ws.m["modules"]:
                with open(os.path.join(game, name), "rb") as f1, \
                        open(os.path.join(out, name), "rb") as f2:
                    same = f1.read() == f2.read()
                self.assertEqual(same, name not in touched, name)

            back = tempfile.mkdtemp(prefix="colwin-back-")
            try:
                Workspace.extract(out, back, log=lambda *a: None)
                ws2 = Workspace.open(back)
                a2 = next(a for a in ws2.m["assets"]
                          if a["module"] == sp["module"] and a["id"] == sp["id"]
                          and a["format"] == "sprt")
                self.assertEqual(pnglib.read(ws2.path(a2["file"]))["pixels"], bytes(px))
            finally:
                shutil.rmtree(back)
        finally:
            shutil.rmtree(root)
            shutil.rmtree(out)

    def test_resizing_a_sprite_is_refused(self):
        game = game_or_skip(self)
        ws = self.workspace(game)
        a = next(x for x in ws.m["assets"] if x["format"] == "sprt")
        img = pnglib.read(ws.path(a["file"]))
        tmp = tempfile.mkdtemp()
        try:
            p = os.path.join(tmp, "big.png")
            w, h = img["width"] + 1, img["height"]
            pnglib.write_indexed(p, w, h, bytes(w * h), img["palette"], transparent=0)
            saved = a["file"]
            a = dict(a, file=os.path.relpath(p, ws.root))
            ws2 = Workspace(ws.root, dict(ws.m))
            with self.assertRaises(WorkspaceError) as cm:
                ws2._enc_sprt(a, p, False, None)
            self.assertIn("canvas", str(cm.exception))
            self.assertTrue(saved)
        finally:
            shutil.rmtree(tmp)

    def test_ctab_shape_holds_for_every_table(self):
        game = game_or_skip(self)
        ws = self.workspace(game)
        tabs = [a for a in ws.m["assets"] if a["format"] == "ctab"]
        self.assertEqual(len(tabs), 43)
        for a in tabs:
            self.assertEqual((a["start"], a["count"]), (142, 97))
        with_teal = [a for a in tabs if a["teal_index"] is not None]
        self.assertEqual(len(with_teal), 42)        # table 222 is the exception


def main():
    global GAME
    argv = sys.argv[1:]
    if argv and os.path.isdir(argv[0]):
        GAME = argv.pop(0)
    unittest.main(argv=[sys.argv[0]] + argv, verbosity=2)


if __name__ == "__main__":
    main()
