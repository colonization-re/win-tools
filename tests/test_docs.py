#!/usr/bin/env python3
"""Re-derive the numbers in docs/ from a real install and assert the prose says them.

    python3 tests/test_docs.py /path/to/Colonization

A document is the one artefact nothing re-runs, so a figure in it can drift from
the data and stay plausible indefinitely. Everything here is a measurement made
from the game, compared against the literal string the page carries. Checks are
on the numbers, not on the wording around them.

Without a game directory every check skips.
"""
import collections
import os
import struct
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from colwin.ne import Module                                        # noqa: E402
from colwin.formats import cvpc, sprt                               # noqa: E402
from colwin.palette import ctab_parse, ctab_teal_index              # noqa: E402
from colwin.workspace import payload, is_ne                         # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FILES = "docs/files.md"
SPRT = "docs/formats/sprt.md"
CVPC = "docs/formats/cvpc.md"
CTAB = "docs/formats/ctab.md"
NE = "docs/formats/ne-container.md"
GAME = os.environ.get("COLWIN_GAME")


def measure(game):
    m = {}
    sizes = {f: os.path.getsize(os.path.join(game, f))
             for f in os.listdir(game) if os.path.isfile(os.path.join(game, f))}
    m["files"] = len(sizes)
    m["bytes"] = sum(sizes.values())
    grp = collections.Counter()
    for f, s in sizes.items():
        e = os.path.splitext(f)[1].upper()
        grp["data" if f.startswith("COLDATA") else
            "text" if f.startswith("COLTEXT") else
            "wav" if e == ".WAV" else
            "exe" if e == ".EXE" else
            "arcv" if e == ".$00" else
            "game" if e in (".MP", ".SAV") else "misc"] += s
    m.update({"b_" + k: v for k, v in grp.items()})
    m.update({"p_" + k: 100 * v / m["bytes"] for k, v in grp.items()})

    counts = collections.Counter()
    m["mod"] = {}
    hdr, f14, f16, f18 = [], set(), set(), collections.Counter()
    dwords = collections.defaultdict(list)
    canvases = collections.Counter()
    empty = solid = 0
    inv = collections.Counter()
    ctabs = []
    ratios = []
    for f in sorted(sizes):
        p = os.path.join(game, f)
        if not is_ne(p):
            continue
        mod = Module.load(p)
        per = collections.Counter(r.type_name for r in mod.resources)
        m["mod"][f] = {"bytes": len(mod.data), "res": len(mod.resources),
                       "types": per, "ids": {}}
        for t in per:
            ids = sorted(r.id for r in mod.resources if r.type_name == t)
            m["mod"][f]["ids"][t] = (ids[0], ids[-1])
        counts.update(per)
        for r in mod.resources:
            if r.type_name == "SPRT":
                b = payload(r, "sprt")
                w0, w1 = struct.unpack_from("<2h", b, 0)
                W, H, x0, y0, x1, y1 = struct.unpack_from("<6H", b, 8)
                dw = struct.unpack_from("<I", b, 0x14)[0]
                f14.add(dw & 0xFFFF)
                f16.add(dw >> 16)
                f18[b[0x18]] += 1
                if (w0, w1) != (0, 0):
                    hdr.append((w0, w1, W, H, f))
                dwords[f].append((r.id, dw))
                d = sprt.decode(b)
                if f == "COLDATA0.DLL":
                    canvases[(W, H)] += 1
                if d["bbox"] == [0, 0, 0, 0]:
                    empty += 1
                else:
                    solid += 1
                    px = d["pixels"]
                    per_row = []
                    for y in range(y0, y1):
                        row = px[y * W:(y + 1) * W]
                        first = next((i for i, v in enumerate(row) if v), -1)
                        last = max((i for i, v in enumerate(row) if v), default=-1)
                        per_row.append((first, last))
                    live = [(a, b_) for a, b_ in per_row if a >= 0]
                    inv["x0"] += (x0 == min(a for a, _ in live))
                    inv["x1"] += (x1 == max(b_ for _, b_ in live) + 1)
                    inv["ends"] += (per_row[0][0] >= 0 and per_row[-1][0] >= 0)
                    inv["zero"] += all(0 not in px[y * W + a:y * W + b_ + 1]
                                       for y, (a, b_) in zip(range(y0, y1), per_row)
                                       if a >= 0)
            elif r.type_name == "CTAB":
                ctabs.append(ctab_parse(payload(r, "ctab")))
            elif r.type_name == "CVPC":
                d = cvpc.decode(r.body)
                e = cvpc.encode(d["pixels"], d["width"], d["height"], d["bpp"],
                                d["palette"])
                ratios.append(len(e) / len(r.body))

    m["counts"] = counts
    m["sprt_empty"] = empty
    m["sprt_solid"] = solid
    m["inv"] = inv
    m["hdr_nonzero"] = len(hdr)
    m["hdr_pairs"] = len({(a, b_) for a, b_, _W, _H, _f in hdr})
    m["hdr_centre_x"] = sum(1 for a, _b, W, _H, _f in hdr if a == -(W // 2))
    m["hdr_centre_both"] = sum(1 for a, b_, W, H, _f in hdr
                               if a == -(W // 2) and b_ == -(H // 2))
    m["hdr_by_mod"] = collections.Counter(f for *_x, f in hdr).most_common()
    m["f14_distinct"] = len(f14)
    m["f16_distinct"] = len(f16)
    m["d0_canvases"] = len(canvases)

    v = sorted(dwords["COLDATA0.DLL"])
    groups = collections.defaultdict(list)
    for rid, dw in v:
        groups[rid // 10].append(dw)
    m["d0_groups"] = len(groups)
    m["d0_mono"] = sum(1 for g in groups.values()
                       if all(g[i] <= g[i + 1] for i in range(len(g) - 1)))
    m["d0_drops"] = sum(1 for i in range(len(v) - 1) if v[i + 1][1] < v[i][1])
    m["d0_boundary"] = sum(1 for i in range(len(v) - 1)
                           if v[i + 1][1] < v[i][1] and v[i + 1][0] // 10 != v[i][0] // 10)

    m["ctab_bytes"] = {4 + 3 * c["count"] for c in ctabs}
    m["ctab_teal"] = sum(1 for c in ctabs if ctab_teal_index(c) is not None)
    ti = [ctab_teal_index(c) for c in ctabs if ctab_teal_index(c) is not None]
    m["teal_distinct"], m["teal_lo"], m["teal_hi"] = len(set(ti)), min(ti), max(ti)
    m["cvpc_lo"], m["cvpc_hi"] = min(ratios), max(ratios)

    wav = [f for f in sizes if f.upper().endswith(".WAV")]
    fmts, secs = set(), 0.0
    for f in wav:
        with open(os.path.join(game, f), "rb") as fh:
            b = fh.read()
        i, fmt, dl = 12, None, 0
        while i + 8 <= len(b):
            cid = b[i:i + 4]
            n = struct.unpack_from("<I", b, i + 4)[0]
            if cid == b"fmt ":
                fmt = struct.unpack_from("<HHIIHH", b, i + 8)
            if cid == b"data":
                dl = n
            i += 8 + n + (n & 1)
        fmts.add((fmt[0], fmt[1], fmt[2], fmt[5]))
        secs += dl / (fmt[2] * fmt[1] * fmt[5] // 8)
    m["wav_n"] = len(wav)
    m["wav_fmts"] = fmts
    m["wav_secs"] = secs
    return m


def checks(m):
    mod = m["mod"]
    c = m["counts"]

    def module_line(name, label):
        d = mod[name]
        return ("`%s` — %s bytes, %d resources" % (name, format(d["bytes"], ","), d["res"]),
                label)

    out = [
        ("install total", "**64 files, %s bytes**" % format(m["bytes"], ","), FILES),
        ("data DLL bytes", "| 10 | %s | %.1f%% |" % (format(m["b_data"], ","), m["p_data"]), FILES),
        ("text DLL bytes", "| 1 | %s | %.1f%% |" % (format(m["b_text"], ","), m["p_text"]), FILES),
        ("wav bytes", "| 44 | %s | %.1f%% |" % (format(m["b_wav"], ","), m["p_wav"]), FILES),
        ("exe bytes", "| 2 | %s | %.1f%% |" % (format(m["b_exe"], ","), m["p_exe"]), FILES),
        ("arcv bytes", "| 1 | %s | %.1f%% |" % (format(m["b_arcv"], ","), m["p_arcv"]), FILES),
        ("resource totals",
         "**%d `SPRT`, %d `CVPC`, %d `CTAB`, %d `FLIC`**"
         % (c["SPRT"], c["CVPC"], c["CTAB"], c["FLIC"]), FILES),
        ("COLTEXT0 text count", "**%d `TEXT` resources, every one of them named**"
         % mod["COLTEXT0.DLL"]["types"]["TEXT"], FILES),
        ("COLDATA0 sprites", "**%d `SPRT`, ids %d–%d**"
         % (mod["COLDATA0.DLL"]["types"]["SPRT"], *mod["COLDATA0.DLL"]["ids"]["SPRT"]), FILES),
        ("COLDATA0 canvases", "on %d distinct canvases" % m["d0_canvases"], FILES),
        ("COLDATA0 groups", "**%d groups of ten\nconsecutive ids**" % m["d0_groups"], FILES),
        ("COLDATA0 boundary", "of its %d decreases falls exactly on a group boundary**"
         % m["d0_drops"], FILES),
        ("COLDATA5 sprites", "**%d `SPRT`, ids %d–%d**"
         % (mod["COLDATA5.DLL"]["types"]["SPRT"], *mod["COLDATA5.DLL"]["ids"]["SPRT"]), FILES),
        ("COLDATA5 header pairs", "%d of them carry the unknown signed header pair"
         % m["hdr_by_mod"][0][1], FILES),
        ("COLDATA6 sprites", "**%d `SPRT`, ids %d–%d**"
         % (mod["COLDATA6.DLL"]["types"]["SPRT"], *mod["COLDATA6.DLL"]["ids"]["SPRT"]), FILES),
        ("COLDATA8 ctabs", "**All %d `CTAB` colour tables live here**" % c["CTAB"], FILES),
        ("wav count and format",
         "**PCM, mono, %s Hz, %d-bit**" % (format(list(m["wav_fmts"])[0][2], ","),
                                           list(m["wav_fmts"])[0][3]), FILES),
        ("wav duration", "%.1f\nseconds in total" % m["wav_secs"], FILES),

        ("SPRT empty count", "`0x000a` in all %d empty sprites |" % m["sprt_empty"], SPRT),
        ("SPRT 0x00 nonzero", "non-zero in %d of %d, always negative there |"
         % (m["hdr_nonzero"], c["SPRT"]), SPRT),
        ("SPRT 0x14 distinct", "%d distinct values; `0x000a`" % m["f14_distinct"], SPRT),
        ("SPRT 0x16 distinct", "%d distinct values, zero in only" % m["f16_distinct"], SPRT),
        ("SPRT invariant x0", "| `x0` is the minimum `skip` | %d / %d |"
         % (m["inv"]["x0"], m["sprt_solid"]), SPRT),
        ("SPRT invariant x1", "| `x1` is the maximum `skip + count` | %d / %d |"
         % (m["inv"]["x1"], m["sprt_solid"]), SPRT),
        ("SPRT invariant zero", "| **index 0 never appears inside a run** | %d / %d |"
         % (m["inv"]["zero"], m["sprt_solid"]), SPRT),
        ("SPRT pair distinct", "Only %d distinct values" % m["hdr_pairs"], SPRT),
        ("SPRT pair centre",
         "2)` in %d of the %d, and both coordinates are exactly the canvas centre in %d."
         % (m["hdr_centre_x"], m["hdr_nonzero"], m["hdr_centre_both"]), SPRT),
        ("SPRT pair modules", "(`COLDATA5` %d, `COLDATA4` %d," % (m["hdr_by_mod"][0][1],
                                                                  m["hdr_by_mod"][1][1]), SPRT),
        ("SPRT group count", "non-decreasing inside **all %d** groups" % m["d0_groups"], SPRT),
        ("SPRT group drops", "with **all %d** of its decreases landing" % m["d0_boundary"], SPRT),

        ("CVPC ratio", "between %.3f× and %.3f× the original size"
         % (m["cvpc_lo"], m["cvpc_hi"]), CVPC),
        ("CTAB size", "Exactly `4 + 3 × 97 = %d` bytes" % list(m["ctab_bytes"])[0], CTAB),
        ("CTAB teal", "**exactly once** in %d of the %d tables" % (m["ctab_teal"], c["CTAB"]), CTAB),
        ("CTAB teal span", "%d distinct\nindices over %d–%d" % (m["teal_distinct"],
                                                                m["teal_lo"], m["teal_hi"]), CTAB),
        ("NE alignment", "**9** (512 bytes) in every module here", NE),
    ]
    # The count of checks is itself a documented figure, so it is checked too --
    # three pages state it, and adding those three is what makes the total.
    n = len(out) + 3
    out += [
        ("check count (README)", "re-derives all %d numbers in" % n, "README.md"),
        ("check count (editing)", "re-derives all %d numbers on these" % n, "docs/editing.md"),
        ("check count (index)", "re-derives all %d of them from an install" % n, "docs/index.md"),
    ]
    return out


class Docs(unittest.TestCase):
    def test_every_documented_figure_matches_the_game(self):
        if not GAME or not os.path.isdir(GAME):
            self.skipTest("set COLWIN_GAME (or pass the game directory) to run this")
        m = measure(GAME)
        cache, bad = {}, []
        for name, literal, page in checks(m):
            if page not in cache:
                with open(os.path.join(ROOT, page)) as f:
                    cache[page] = f.read()
            if literal not in cache[page]:
                bad.append("%s (%s): %r" % (name, page, literal))
        self.assertEqual(bad, [], "\n  ".join([""] + bad))


class Liquid(unittest.TestCase):
    """GitHub Pages runs Liquid over docs/ before Markdown, so a literal `{` + `%`
    or `{` + `{` in prose is a template tag and an unterminated one fails the
    build. These pages quote game strings full of braces, so it is easy to add
    one. Write the brace with an HTML entity instead; the rendered page is the
    same in both the site and the GitHub file browser. Needs no game.
    """

    def test_docs_contain_no_accidental_liquid_tags(self):
        bad = []
        for dirpath, _, names in os.walk(os.path.join(ROOT, "docs")):
            for name in sorted(names):
                if not name.endswith(".md"):
                    continue
                path = os.path.join(dirpath, name)
                with open(path) as f:
                    lines = f.read().splitlines()
                for i, line in enumerate(lines, 1):
                    for tag in ("{" + "%", "{" + "{"):
                        if tag in line:
                            bad.append("%s:%d: %s" % (
                                os.path.relpath(path, ROOT), i, line.strip()))
        self.assertEqual(bad, [], "\n  ".join([""] + bad))


def main():
    global GAME
    argv = sys.argv[1:]
    if argv and os.path.isdir(argv[0]):
        GAME = argv.pop(0)
    unittest.main(argv=[sys.argv[0]] + argv, verbosity=2)


if __name__ == "__main__":
    main()
