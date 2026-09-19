"""colwin -- the command line."""
import argparse
import os
import sys

from . import __version__
from .formats.mapfile import MapError
from .mapview import MapviewError, render_file
from .ne import Module
from .tileset import TILE, TilesetError
from .workspace import Workspace, WorkspaceError, is_ne

EPILOG = """\
typical session:
  colwin extract ~/games/colonization  --out=ws
  ... edit ws/sprites/**/*.png in an indexed-mode paint program ...
  colwin status  ws
  colwin build   ws --out=patched
  colwin map-preview save/AUTO01.SAV ~/games/colonization --out=map.png
"""


def _game_arg(p):
    p.add_argument("game", help="the installed game directory")


def cmd_list(args):
    targets = []
    if os.path.isdir(args.target):
        targets = [os.path.join(args.target, f) for f in sorted(os.listdir(args.target))]
    else:
        targets = [args.target]
    total = {}
    for path in targets:
        if not os.path.isfile(path) or not is_ne(path):
            continue
        m = Module.load(path)
        by = {}
        for r in m.resources:
            e = by.setdefault(r.type_name, [0, 0])
            e[0] += 1
            e[1] += len(r.body)
            t = total.setdefault(r.type_name, [0, 0])
            t[0] += 1
            t[1] += len(r.body)
        print("%-14s %5d resources, %9d bytes" % (os.path.basename(path),
                                                  len(m.resources), len(m.data)))
        for k, (n, b) in sorted(by.items()):
            print("    %-16s %5d  %10d bytes" % (k, n, b))
        if args.verbose:
            for r in m.resources:
                print("        %-16s %6d  %-24s %8d bytes" %
                      (r.type_name, r.id, r.name or "-", len(r.body)))
    if len(total) and len(targets) > 1:
        print("\ntotal")
        for k, (n, b) in sorted(total.items()):
            print("    %-16s %5d  %10d bytes" % (k, n, b))
    return 0


def cmd_extract(args):
    ws, counts = Workspace.extract(args.game, args.out, args.palette)
    print("\nextracted to %s" % args.out)
    for k, n in sorted(counts.items()):
        print("    %-10s %5d" % (k, n))
    print("\n%s tells you what is there and how to edit it." %
          os.path.join(args.out, "README.md"))
    return 0


def cmd_status(args):
    ws = Workspace.open(args.workspace)
    changed = ws.changed()
    if not changed:
        print("no changes: every file matches what extract wrote")
        return 0
    for a, why in changed:
        print("%-8s %s  (%s %s/%d)" % (why, a["file"], a["type"], a["module"], a["id"]))
    print("\n%d changed file(s); the rest go back byte for byte." % len(changed))
    return 0


def cmd_build(args):
    ws = Workspace.open(args.workspace)
    fill = None
    if args.fill_holes is not None:
        fill = int(args.fill_holes, 0)
        if not 0 <= fill <= 255:
            raise SystemExit("--fill-holes takes a palette index 0-255")
    written, nchanged = ws.build(args.out, args.game, nearest=args.nearest,
                                 fill_holes=fill, copy_all=not args.modules_only)
    grown = [w for w in written if w[2]]
    print("\n%d changed asset(s) re-encoded; %d module(s) written to %s"
          % (nchanged, len(written), args.out))
    if grown:
        print("size change: " + ", ".join("%s %+d" % (n, d) for n, _, d in grown))
    if not args.modules_only:
        print("the rest of the game was copied alongside them, so %s is "
              "a complete install." % args.out)
    return 0


def cmd_verify(args):
    ws = Workspace.open(args.workspace)
    tally, failures, rebuilt = ws.verify(args.game)
    print("re-encoding every extracted asset and comparing with the game:\n")
    print("  %-8s %8s %8s %8s" % ("format", "exact", "content", "FAIL"))
    tot = [0, 0, 0]
    for fmt, t in sorted(tally.items()):
        print("  %-8s %8d %8d %8d" % (fmt, t["exact"], t["content"], t["fail"]))
        tot[0] += t["exact"]
        tot[1] += t["content"]
        tot[2] += t["fail"]
    print("  %-8s %8d %8d %8d" % ("total", *tot))
    print("\n  exact   = the encoder reproduced the resource byte for byte")
    print("  content = re-encoded differently but decodes to identical pixels")
    print("            (CVPC: our LZW places its own clear codes)")
    bad = [r for r in rebuilt if not r[1]]
    print("\ncontainer rebuild with no replacements: %d/%d modules byte-identical"
          % (len(rebuilt) - len(bad), len(rebuilt)))
    for name, _ in bad:
        print("    FAIL %s" % name)
    for f in failures[:20]:
        print("    FAIL %s: %s" % f)
    if len(failures) > 20:
        print("    ... and %d more" % (len(failures) - 20))
    return 1 if failures or bad else 0


def cmd_map_preview(args):
    r = render_file(args.map, args.game, args.out, plain=args.plain,
                    tile_size=args.tile)
    print("%s: a %dx%d %s map, planes at %#06x"
          % (os.path.basename(args.map), r["width"], r["height"], r["kind"],
             r["map_start"]))
    if r["kind"] == "SAV":
        print("    %d settlement(s): %d colon(ies), %d village(s)"
              % (r["settlements"], r["colonies"], r["villages"]))
    else:
        print("    terrain and coastline only: a .MP has no settlement plane")
    print("\nwrote %s, %dx%d pixels at %d px a square"
          % (args.out, r["image"][0], r["image"][1], args.tile))
    return 0


def cmd_palette(args):
    ws = Workspace.open(args.workspace)
    if args.set:
        n = ws.repalette(args.set)
        print("re-viewed %d sprite PNGs through `%s`; no pixel index changed" % (n, args.set))
        return 0
    for name, rec in sorted(ws.m["palettes"].items()):
        print("%-14s %s" % (name, rec["file"]))
        for band, note in sorted(rec.get("provenance", {}).items()):
            if band == "uniquified":
                print("    %-14s %d entr(ies) nudged to keep colour -> index exact"
                      % ("(injective)", len(note)))
            else:
                print("    %-14s %s" % (band, note))
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(
        prog="colwin", formatter_class=argparse.RawDescriptionHelpFormatter,
        description="Read and write the assets of Colonization for Windows (1995).",
        epilog=EPILOG)
    p.add_argument("--version", action="version", version="colwin " + __version__)
    sub = p.add_subparsers(dest="cmd", required=True)

    q = sub.add_parser("list", help="show what is in a module or a game directory")
    q.add_argument("target")
    q.add_argument("-v", "--verbose", action="store_true", help="one line per resource")
    q.set_defaults(fn=cmd_list)

    q = sub.add_parser("extract", help="extract every solved asset into a workspace")
    _game_arg(q)
    q.add_argument("--out", required=True, help="workspace directory to create")
    q.add_argument("--palette", default="ctab-auto", metavar="RULE",
                   help="how sprite indices are coloured for viewing: "
                        "ctab-auto (default, per-sprite by resource id), "
                        "ctab:<id> (one table for all), or index (grey ramp, "
                        "no colour claimed)")
    q.set_defaults(fn=cmd_extract)

    q = sub.add_parser("status", help="list the files you have edited")
    q.add_argument("workspace")
    q.set_defaults(fn=cmd_status)

    q = sub.add_parser("build", help="write a game directory with your edits in it")
    q.add_argument("workspace")
    q.add_argument("--out", required=True)
    q.add_argument("--game", help="the original install (default: the one recorded "
                                  "in the workspace)")
    q.add_argument("--nearest", action="store_true",
                   help="snap colours that are not in the palette to the closest "
                        "entry instead of refusing; this changes the art")
    q.add_argument("--fill-holes", metavar="INDEX",
                   help="fill interior transparent gaps in a sprite row with this "
                        "palette index (SPRT stores one run per row)")
    q.add_argument("--modules-only", action="store_true",
                   help="write just the rebuilt modules, not a whole install")
    q.set_defaults(fn=cmd_build)

    q = sub.add_parser("verify", help="prove the encoders reproduce the game's own bytes")
    q.add_argument("workspace")
    q.add_argument("--game")
    q.set_defaults(fn=cmd_verify)

    q = sub.add_parser("map-preview",
                       help="draw a .SAV or .MP map as one PNG, in the game's art")
    q.add_argument("map", help="a saved game (.SAV) or a map file (.MP)")
    _game_arg(q)
    q.add_argument("--out", required=True, help="the PNG to write")
    q.add_argument("--tile", type=int, default=TILE, metavar="PX",
                   help="pixels a square, 1 to %d (default %d)" % (TILE, TILE))
    q.add_argument("--plain", action="store_true",
                   help="draw only what the game's own draw routine "
                        "establishes: no plowed icon, no settlements, whose "
                        "cells on the art sheet are identified by eye")
    q.set_defaults(fn=cmd_map_preview)

    q = sub.add_parser("palette", help="show, or change, how indices are coloured")
    q.add_argument("workspace")
    q.add_argument("--set", metavar="RULE",
                   help="re-view every sprite through another rule "
                        "(ctab-auto, ctab:<id>, index); pixel indices never change")
    q.set_defaults(fn=cmd_palette)

    args = p.parse_args(argv)
    try:
        return args.fn(args)
    except (MapError, MapviewError, TilesetError) as e:
        print("colwin: %s" % e, file=sys.stderr)
        return 2
    except WorkspaceError as e:
        print("colwin: %s" % e, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
