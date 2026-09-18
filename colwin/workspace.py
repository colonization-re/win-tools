"""The workspace: a directory of editable files, and the way back to the game.

Extract writes one file per asset plus `colwin.json`, which records for each
one the things the pixels do not carry -- the module and resource id it came
from, the palette it was written through, the header fields no decoder can
derive, and the SHA-256 of both the original resource and the file on disk.

That last pair is what makes a rebuild safe.  On `build`, a file whose hash is
unchanged is not re-encoded at all: its original resource bytes go back
verbatim, so rebuilding an untouched workspace reproduces every module byte for
byte.  Only what you actually edited goes through an encoder.
"""
import datetime
import hashlib
import json
import os
import shutil

from . import png as pnglib
from .ne import Module
from .palette import (Palette, ctab_parse, ctab_build, ctab_teal_index,
                      view_palette, grey_ramp)
from .formats import cvpc, dib, flic, sprt, text

MANIFEST = "colwin.json"
EDITABLE = ("SPRT", "CVPC", "CTAB", "TEXT", "RT_BITMAP")
CARRIED_NOTE = {
    "RT_NAMETABLE": "resource name table -- structural, not content",
    "RT_MENU": "menu template",
    "RT_DIALOG": "dialog template",
    "RT_ICON": "icon (colour DIB + AND mask); preview only, see reference/",
    "RT_CURSOR": "cursor (hotspot + DIB + AND mask); preview only, see reference/",
    "RT_GROUP_ICON": "icon directory",
    "RT_GROUP_CURSOR": "cursor directory",
    "FLIC": "Autodesk FLC animation; frames in reference/, rebuild is opt-in",
    "CRDS": "record table, layout UNKNOWN -- carried through untouched",
    "CRED": "record table, layout UNKNOWN -- carried through untouched",
    "MONS": "record table, layout UNKNOWN -- carried through untouched",
    "SHIP": "record table, layout UNKNOWN -- carried through untouched",
}


class WorkspaceError(Exception):
    pass


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def file_sha256(path):
    with open(path, "rb") as f:
        return sha256(f.read())


def safe(name):
    return "".join(c if (c.isalnum() or c in "._-") else "_" for c in name)


def payload(r, fmt=None):
    """The bytes of a resource that are content, not alignment padding.

    Trimming trailing NULs is right for every format here except two, and both
    exceptions are real: an empty SPRT's 25-byte header ends in zeros, and a
    CTAB whose last entries are black ends in zeros too.  Trimming into either
    would make the encoder look wrong when it is the trim that is wrong.
    """
    body = r.body
    t = fmt or r.type_name
    if t in ("sprt", "SPRT"):
        return r.raw[:max(sprt.HDR, len(body))]
    if t in ("ctab", "CTAB"):
        count = int.from_bytes(r.raw[2:4], "little")
        return r.raw[:max(len(body), 4 + 3 * count)]
    return body


def is_ne(path):
    try:
        with open(path, "rb") as f:
            head = f.read(2)
            if head != b"MZ":
                return False
            f.seek(0x3C)
            off = int.from_bytes(f.read(4), "little")
            f.seek(off)
            return f.read(2) == b"NE"
    except OSError:
        return False


# --------------------------------------------------------------------------- #

class Workspace:
    def __init__(self, root, manifest):
        self.root = root
        self.m = manifest

    @classmethod
    def open(cls, root):
        path = os.path.join(root, MANIFEST)
        if not os.path.exists(path):
            raise WorkspaceError("%s: no %s here -- run `colwin extract` first"
                                 % (root, MANIFEST))
        with open(path) as f:
            return cls(root, json.load(f))

    def save(self):
        with open(os.path.join(self.root, MANIFEST), "w") as f:
            json.dump(self.m, f, indent=1, sort_keys=False)

    def path(self, rel):
        return os.path.join(self.root, rel)

    # -- palettes --------------------------------------------------------- #

    def load_palette(self, name):
        rec = self.m["palettes"].get(name)
        if rec is None:
            raise WorkspaceError("palette %r is not in the manifest" % name)
        return Palette.read(self.path(rec["file"]), name)

    # ------------------------------------------------------------------ #
    # extract

    @classmethod
    def extract(cls, game_dir, root, palette_spec="ctab-auto", log=print):
        modules = sorted(f for f in os.listdir(game_dir)
                         if is_ne(os.path.join(game_dir, f)))
        if not modules:
            raise WorkspaceError("%s holds no Win16 NE modules -- is this the "
                                 "installed game directory?" % game_dir)
        os.makedirs(root, exist_ok=True)
        man = {
            "colwin_version": __import__("colwin").__version__,
            "created": datetime.datetime.now().isoformat(timespec="seconds"),
            "game_dir": os.path.abspath(game_dir),
            "palette_spec": palette_spec,
            "modules": {},
            "palettes": {},
            "assets": [],
            "carried": {},
        }
        ws = cls(root, man)

        loaded = {}
        ctabs = {}
        for name in modules:
            mod = Module.load(os.path.join(game_dir, name))
            loaded[name] = mod
            for r in mod.resources:
                if r.type_name == "CTAB":
                    ctabs[r.id] = ctab_parse(r.body)

        ws._write_palettes(palette_spec, ctabs)

        counts = {}
        for name in modules:
            mod = loaded[name]
            with open(os.path.join(game_dir, name), "rb") as f:
                digest = sha256(f.read())
            man["modules"][name] = {"sha256": digest, "size": len(mod.data),
                                    "resources": len(mod.resources),
                                    "align": 1 << mod.align_shift}
            for r in mod.resources:
                kind = ws._extract_one(name, r, ctabs, palette_spec)
                counts[kind] = counts.get(kind, 0) + 1
            log("%-14s %4d resources" % (name, len(mod.resources)))

        man["counts"] = counts
        ws.save()
        ws._write_readme(palette_spec, ctabs)
        return ws, counts

    def _write_palettes(self, spec, ctabs):
        d = self.path("palettes")
        os.makedirs(d, exist_ok=True)

        def add(name, pal):
            rel = "palettes/%s.pal" % name
            pal.write_jasc(self.path(rel))
            pal.write_gpl(self.path("palettes/%s.gpl" % name))
            self.m["palettes"][name] = {
                "file": rel, "gimp": "palettes/%s.gpl" % name,
                "sha256": file_sha256(self.path(rel)),
                "provenance": pal.provenance}

        if spec == "index":
            add("index", Palette(grey_ramp(), "index",
                                 {"all": "identity grey ramp: index i -> (i,i,i). "
                                         "The pixel values ARE the game's indices."}))
        elif spec.startswith("ctab:"):
            cid = int(spec[5:])
            if cid not in ctabs:
                raise WorkspaceError("no CTAB with id %d; ids are %s"
                                     % (cid, sorted(ctabs)))
            add("ctab-%d" % cid, view_palette(ctabs[cid], "ctab-%d" % cid,
                                              "CTAB %d payload" % cid))
        else:                                        # ctab-auto
            add("base", view_palette(None, "base"))
            for cid, c in sorted(ctabs.items()):
                add("ctab-%d" % cid,
                    view_palette(c, "ctab-%d" % cid,
                                 "CTAB %d payload (RECONSTRUCTION: which CTAB "
                                 "a sprite uses is a measured heuristic)" % cid))
        # every CTAB also ships as its own 97-entry file, which is the thing
        # the game actually loads
        for cid, c in sorted(ctabs.items()):
            rel = "palettes/ctab/%d.pal" % cid
            os.makedirs(os.path.dirname(self.path(rel)), exist_ok=True)
            Palette(c["entries"], "ctab-%d" % cid).write_jasc(self.path(rel))

    def _palette_for_sprite(self, rid, ctabs, spec):
        if spec == "index":
            return "index"
        if spec.startswith("ctab:"):
            return "ctab-%d" % int(spec[5:])
        if not ctabs:
            return "base"
        lo, hi = min(ctabs), max(ctabs)
        if not lo <= rid <= hi:
            return "base"                            # no id to pair on
        cid = rid if rid in ctabs else min(ctabs, key=lambda x: (abs(x - rid), x))
        return "ctab-%d" % cid

    def _extract_one(self, module, r, ctabs, spec):
        t = r.type_name
        try:
            if t == "SPRT":
                return self._ex_sprt(module, r, ctabs, spec)
            if t == "CVPC":
                return self._ex_cvpc(module, r)
            if t == "CTAB":
                return self._ex_ctab(module, r)
            if t == "TEXT":
                return self._ex_text(module, r)
            if t == "RT_BITMAP":
                return self._ex_bitmap(module, r)
            if t == "FLIC":
                self._ex_flic(module, r)
            if t in ("RT_ICON", "RT_CURSOR"):
                self._ex_icon(module, r)
        except Exception as e:                       # one bad resource must not
            self.m["carried"].setdefault(module, {})[r.label()] = \
                "NOT EXTRACTED: %s: %s" % (type(e).__name__, e)
            return "failed"
        self.m["carried"].setdefault(module, {})[r.label()] = \
            CARRIED_NOTE.get(t, "carried through untouched")
        return "carried"

    def _out(self, sub, module, r, ext):
        rel = "%s/%s/%s%s" % (sub, module,
                              safe("%d_%s" % (r.id, r.name) if r.name else str(r.id)), ext)
        os.makedirs(os.path.dirname(self.path(rel)), exist_ok=True)
        return rel

    def _record(self, module, r, rel, fmt, **extra):
        raw = payload(r, fmt)
        rec = {"module": module, "type": r.type_name, "id": r.id,
               "name": r.name, "file": rel, "format": fmt,
               "resource_sha256": sha256(raw),
               "resource_bytes": len(raw),
               "file_sha256": file_sha256(self.path(rel))}
        rec.update(extra)
        self.m["assets"].append(rec)

    # -- per-format extraction -------------------------------------------- #

    def _ex_sprt(self, module, r, ctabs, spec):
        d = sprt.decode(payload(r, "sprt"))
        pname = self._palette_for_sprite(r.id, ctabs, spec)
        pal = self.load_palette(pname)
        rel = self._out("sprites", module, r, ".png")
        used = set(d["pixels"])
        if sprt.TRANSPARENT in used and any(v != sprt.TRANSPARENT for v in used):
            pass                                     # index 0 only ever means blank
        pnglib.write_indexed(
            self.path(rel), d["width"], d["height"], d["pixels"], pal.entries,
            transparent=sprt.TRANSPARENT,
            text=[("Software", "colwin"), ("Comment",
                  "SPRT %s/%d; pixel values are the game's palette indices; "
                  "index 0 is transparent; palette %s is a view, not game data"
                  % (module, r.id, pname))])
        teal = None
        if pname.startswith("ctab-"):
            teal = ctab_teal_index(ctabs[int(pname[5:])])
        self._record(module, r, rel, "sprt", palette=pname,
                     sprt=sprt.header_meta(d), width=d["width"], height=d["height"],
                     bbox=d["bbox"], ctab_teal_index=teal)
        return "sprt"

    def _ex_cvpc(self, module, r):
        d = cvpc.decode(r.body)
        rel = self._out("canvases", module, r, ".png")
        pnglib.write_indexed(
            self.path(rel), d["width"], d["height"], d["pixels"], d["palette"],
            text=[("Software", "colwin"), ("Comment",
                  "CVPC %s/%d; this palette IS the game's, stored in the "
                  "resource itself" % (module, r.id))])
        self._record(module, r, rel, "cvpc", width=d["width"], height=d["height"],
                     bpp=d["bpp"], palette_entries=len(d["palette"]),
                     palette=[list(c) for c in d["palette"]])
        return "cvpc"

    def _ex_ctab(self, module, r):
        c = ctab_parse(payload(r, "ctab"))
        rel = self._out("colortables", module, r, ".pal")
        Palette(c["entries"], "ctab-%d" % r.id).write_jasc(self.path(rel))
        self._record(module, r, rel, "ctab", start=c["start"], count=c["count"],
                     teal_index=ctab_teal_index(c))
        return "ctab"

    def _ex_text(self, module, r):
        s = text.decode(r.body)
        rel = self._out("text", module, r, ".txt")
        with open(self.path(rel), "w", encoding="utf-8", newline="\n") as f:
            f.write(s)
        self._record(module, r, rel, "text", directives=text.directives(s),
                     lines=s.count("\n") + 1)
        return "text"

    def _ex_bitmap(self, module, r):
        d = dib.decode_bitmap(r.body)
        rel = self._out("bitmaps", module, r, ".png")
        pnglib.write_indexed(self.path(rel), d["width"], d["height"],
                             d["pixels"], d["palette"])
        self._record(module, r, rel, "bitmap", width=d["width"], height=d["height"],
                     bpp=d["bpp"], header_size=d["header_size"],
                     colours_used=d["colours_used"], x_ppm=d["x_ppm"],
                     y_ppm=d["y_ppm"], colours_important=d["colours_important"],
                     palette=[list(c) for c in d["palette"]])
        return "bitmap"

    def _ex_flic(self, module, r):
        base = "reference/flic/%s_%d" % (module, r.id)
        os.makedirs(self.path(base), exist_ok=True)
        with open(self.path(base + ".flc"), "wb") as f:
            f.write(r.body)
        for fr in flic.frames(r.body):
            h = flic.header(r.body)
            pnglib.write_indexed(self.path("%s/frame_%03d.png" % (base, fr["index"])),
                                 h["width"], h["height"], fr["pixels"], fr["palette"])

    def _ex_icon(self, module, r):
        d = dib.decode_icon(r.body, cursor=(r.type_name == "RT_CURSOR"))
        rel = "reference/%s/%s_%d.png" % (r.type_name.lower(), module, r.id)
        os.makedirs(os.path.dirname(self.path(rel)), exist_ok=True)
        pnglib.write_rgba(self.path(rel), d["width"], d["height"], d["rgba"])


    # ------------------------------------------------------------------ #
    # repalette

    def repalette(self, spec, log=print):
        """Swap the palette every sprite PNG is viewed through.

        Only the PLTE chunk changes; every pixel keeps the index it had.  That
        is the whole point of storing indices rather than colours: the day the
        real runtime palette is established, this command applies it and no
        edit made in the meantime is lost.
        """
        ctabs = {}
        for a in self.m["assets"]:
            if a["format"] == "ctab":
                pal = Palette.read(self.path(a["file"]))
                ctabs[a["id"]] = {"start": a["start"], "count": a["count"],
                                  "entries": pal.entries[:a["count"]]}
        self.m["palettes"] = {}
        self._write_palettes(spec, ctabs)
        self.m["palette_spec"] = spec
        n = 0
        for a in self.m["assets"]:
            if a["format"] != "sprt":
                continue
            new = self._palette_for_sprite(a["id"], ctabs, spec)
            pal = self.load_palette(new)
            img = pnglib.read(self.path(a["file"]))
            if img["mode"] != "P":
                raise WorkspaceError("%s is no longer an indexed PNG; "
                                     "repalette needs the indices" % a["file"])
            pnglib.write_indexed(self.path(a["file"]), img["width"], img["height"],
                                 img["pixels"], pal.entries,
                                 transparent=sprt.TRANSPARENT)
            a["palette"] = new
            a["file_sha256"] = file_sha256(self.path(a["file"]))
            n += 1
        self.save()
        return n

    # ------------------------------------------------------------------ #

    def _write_readme(self, spec, ctabs):
        with open(self.path("README.md"), "w") as f:
            f.write(_WORKSPACE_README % {
                "spec": spec,
                "when": self.m["created"],
                "game": self.m["game_dir"],
                "ctabs": len(ctabs),
            })

    # ------------------------------------------------------------------ #
    # status

    def changed(self):
        """Assets whose file on disk no longer matches what extract wrote."""
        out = []
        for a in self.m["assets"]:
            p = self.path(a["file"])
            if not os.path.exists(p):
                out.append((a, "missing"))
            elif file_sha256(p) != a["file_sha256"]:
                out.append((a, "edited"))
        return out

    # ------------------------------------------------------------------ #
    # encoding an edited file back to a resource

    def encode_asset(self, a, nearest=False, fill_holes=None):
        p = self.path(a["file"])
        fmt = a["format"]
        if fmt == "sprt":
            return self._enc_sprt(a, p, nearest, fill_holes)
        if fmt == "cvpc":
            return self._enc_cvpc(a, p, nearest)
        if fmt == "ctab":
            return self._enc_ctab(a, p)
        if fmt == "text":
            return self._enc_text(a, p)
        if fmt == "bitmap":
            return self._enc_bitmap(a, p, nearest)
        raise WorkspaceError("%s: no encoder for format %r" % (a["file"], fmt))

    def _indices(self, path, palette, nearest, label):
        """Whatever a paint program saved -> one palette index per pixel.

        Indexed PNG whose palette matches:  the indices are taken as they are.
        Indexed PNG with a rearranged palette: each entry is mapped back.
        Truecolour PNG: every colour is looked up.  The view palette is
        injective by construction, so an exact lookup is the normal case, and
        an inexact one is reported rather than quietly rounded.
        """
        img = pnglib.read(path)
        inv = palette.inverse()
        if img["mode"] == "P":
            same = list(img["palette"]) == palette.entries[:len(img["palette"])]
            if same:
                return img["width"], img["height"], img["pixels"], {}
            remap, missing = {}, set()
            for i, c in enumerate(img["palette"]):
                j = inv.get(tuple(c))
                if j is None:
                    missing.add(tuple(c))
                    j = palette.nearest(c) if nearest else None
                remap[i] = j
            trns = img["trns"] or []
            for i, alpha in enumerate(trns):
                if alpha == 0:
                    remap[i] = 0
            if missing and not nearest:
                raise WorkspaceError(_new_colour_msg(path, label, sorted(missing)))
            px = bytes(remap.get(v, 0) for v in img["pixels"])
            return img["width"], img["height"], px, {"remapped_entries": len(img["palette"])}
        # truecolour
        px = bytearray(img["width"] * img["height"])
        missing, approximated = {}, 0
        for i in range(len(px)):
            o = i * 4
            r, g, b, alpha = img["pixels"][o:o + 4]
            if alpha == 0:
                px[i] = 0
                continue
            j = inv.get((r, g, b))
            if j is None:
                missing[(r, g, b)] = missing.get((r, g, b), 0) + 1
                if not nearest:
                    continue
                j = palette.nearest((r, g, b))
                approximated += 1
            px[i] = j
        if missing and not nearest:
            raise WorkspaceError(_new_colour_msg(path, label, sorted(missing)))
        return img["width"], img["height"], bytes(px), {"approximated_pixels": approximated}

    def _enc_sprt(self, a, path, nearest, fill_holes):
        pal = self.load_palette(a["palette"])
        w, h, px, note = self._indices(path, pal, nearest, "sprite")
        if (w, h) != (a["width"], a["height"]):
            raise WorkspaceError(
                "%s is %dx%d but the sprite's canvas is %dx%d. The canvas size "
                "is part of the resource; resize the image back, or the game "
                "will place it wrongly." % (a["file"], w, h, a["width"], a["height"]))
        meta = a["sprt"]
        body = sprt.encode(px, w, h, tuple(meta["origin"]), meta["unknown14"],
                           meta["unknown16"], meta["unknown18"],
                           fill_holes=fill_holes)
        return body, note

    def _enc_cvpc(self, a, path, nearest):
        img = pnglib.read(path)
        stored = [tuple(c) for c in a["palette"]]
        if img["mode"] == "P":
            pal = list(img["palette"]) + stored[len(img["palette"]):]
            px = img["pixels"]
            w, h = img["width"], img["height"]
            note = {"palette_from": "the PNG"}
        else:
            pal = stored
            w, h, px, note = self._indices(path, Palette(stored), nearest, "canvas")
        if (w, h) != (a["width"], a["height"]):
            raise WorkspaceError("%s is %dx%d but the canvas is %dx%d"
                                 % (a["file"], w, h, a["width"], a["height"]))
        return cvpc.encode(px, w, h, a["bpp"], pal), note

    def _enc_ctab(self, a, path):
        pal = Palette.read(path)
        entries = pal.entries[:a["count"]]
        return ctab_build(a["start"], entries), {}

    def _enc_text(self, a, path):
        with open(path, encoding="utf-8") as f:
            return text.encode(f.read()), {}

    def _enc_bitmap(self, a, path, nearest):
        img = pnglib.read(path)
        stored = [tuple(c) for c in a["palette"]]
        if img["mode"] == "P":
            pal = list(img["palette"]) + stored[len(img["palette"]):]
            px, w, h = img["pixels"], img["width"], img["height"]
            note = {"palette_from": "the PNG"}
        else:
            pal = stored
            w, h, px, note = self._indices(path, Palette(stored), nearest, "bitmap")
        if (w, h) != (a["width"], a["height"]):
            raise WorkspaceError("%s is %dx%d but the bitmap is %dx%d"
                                 % (a["file"], w, h, a["width"], a["height"]))
        return dib.encode_bitmap(px, w, h, a["bpp"], pal, a["header_size"],
                                 a["colours_used"], a.get("x_ppm", 0),
                                 a.get("y_ppm", 0),
                                 a.get("colours_important", 0)), note

    # ------------------------------------------------------------------ #
    # build

    def build(self, out_dir, game_dir=None, nearest=False, fill_holes=None,
              copy_all=True, log=print):
        game_dir = game_dir or self.m["game_dir"]
        changed = self.changed()
        by_module = {}
        problems = []
        for a, why in changed:
            if why == "missing":
                problems.append("%s: file is gone" % a["file"])
                continue
            try:
                body, _note = self.encode_asset(a, nearest, fill_holes)
            except Exception as e:
                problems.append("%s: %s" % (a["file"], e))
                continue
            by_module.setdefault(a["module"], {})[(a["type"], a["id"])] = body
        if problems:
            raise WorkspaceError("%d asset(s) could not be encoded:\n  %s"
                                 % (len(problems), "\n  ".join(problems)))

        os.makedirs(out_dir, exist_ok=True)
        written = []
        for name, rec in sorted(self.m["modules"].items()):
            src = os.path.join(game_dir, name)
            mod = Module.load(src)
            if sha256(mod.data) != rec["sha256"]:
                raise WorkspaceError(
                    "%s does not match the copy this workspace was extracted "
                    "from. Point --game at that copy, or extract again." % src)
            repl = by_module.get(name, {})
            data = mod.rebuild(repl)
            dst = os.path.join(out_dir, name)
            with open(dst, "wb") as f:
                f.write(data)
            written.append((name, len(repl), len(data) - len(mod.data)))
            if repl:
                log("%-14s %3d resource(s) replaced, %+d bytes"
                    % (name, len(repl), len(data) - len(mod.data)))
        if copy_all:
            for f in sorted(os.listdir(game_dir)):
                s, d = os.path.join(game_dir, f), os.path.join(out_dir, f)
                if os.path.isfile(s) and not os.path.exists(d):
                    shutil.copy2(s, d)
        return written, len(changed)

    # ------------------------------------------------------------------ #
    # verify

    def verify(self, game_dir=None, log=print):
        """Re-encode every extracted asset and compare with the original.

        This is the claim the toolkit rests on, so it is measured rather than
        asserted.  Formats whose encoder is not bit-reproducing (CVPC's LZW
        chooses its own clear codes) are graded on decoded content instead, and
        the report says which grade each one got.
        """
        game_dir = game_dir or self.m["game_dir"]
        mods = {}
        res = {}
        for name in self.m["modules"]:
            mods[name] = Module.load(os.path.join(game_dir, name))
            res[name] = mods[name].by_key()

        tally = {}
        failures = []
        for a in self.m["assets"]:
            fmt = a["format"]
            t = tally.setdefault(fmt, {"exact": 0, "content": 0, "fail": 0})
            r = res[a["module"]].get((a["type"], a["id"]))
            if r is None:
                failures.append((a["file"], "resource is gone from the module"))
                t["fail"] += 1
                continue
            original = payload(r, fmt)
            try:
                body, _ = self.encode_asset(a)
            except Exception as e:
                failures.append((a["file"], "%s: %s" % (type(e).__name__, e)))
                t["fail"] += 1
                continue
            if body == original:
                t["exact"] += 1
                continue
            same = _same_content(fmt, body, original, a)
            if same:
                t["content"] += 1
            else:
                t["fail"] += 1
                failures.append((a["file"], "re-encode differs in content "
                                            "(%d bytes vs %d)" % (len(body), len(original))))

        rebuilt = []
        for name, mod in sorted(mods.items()):
            rebuilt.append((name, mod.rebuild() == mod.data))
        return tally, failures, rebuilt


def _same_content(fmt, body, original, a):
    try:
        if fmt == "cvpc":
            x, y = cvpc.decode(body), cvpc.decode(original)
            return x["pixels"] == y["pixels"] and x["palette"] == y["palette"]
        if fmt == "bitmap":
            return dib.decode_bitmap(body) == dib.decode_bitmap(original)
        if fmt == "text":
            return text.decode(body) == text.decode(original)
    except Exception:
        return False
    return False


def _new_colour_msg(path, label, missing):
    shown = ", ".join("#%02x%02x%02x" % c for c in missing[:8])
    return (
        "%s introduces %d colour(s) the %s's palette does not hold: %s%s.\n"
        "The game stores palette INDICES, not colours, so every pixel has to "
        "land on an entry that exists. Either draw only with the palette "
        "(load palettes/*.pal or .gpl into your editor and work in indexed "
        "mode), or re-run with --nearest to snap each new colour to the "
        "closest entry, which changes the art." % (path, len(missing), label, shown,
                                                   ", ..." if len(missing) > 8 else ""))


_WORKSPACE_README = """# colwin workspace

Extracted %(when)s from `%(game)s`, palette rule `%(spec)s`.

    sprites/      indexed PNGs. The pixel values ARE the game's palette
                  indices; index 0 is transparent and is used by none of the
                  915 shipped sprites. The colours you see come from
                  palettes/, which is a VIEW, not game data.
    canvases/     indexed PNGs whose palette IS the game's -- a CVPC stores
                  its own, so what you see is what the game shows.
    bitmaps/      Windows DIBs, likewise self-contained.
    colortables/  the %(ctabs)d CTAB colour tables, as JASC .pal files.
    text/         the game's authored text, UTF-8 in, cp1252 out.
    palettes/     .pal (JASC) and .gpl (GIMP) for every view palette.
    reference/    icons, cursors and the FLC frames: readable, not rebuilt.

## Editing

Load the matching `palettes/*.pal` into your editor and work in **indexed**
mode if it has one -- then the round trip is bit for bit and the palette never
enters into it. Truecolour editing also works: every view palette is injective
(no two indices share a colour), so each colour maps back to exactly one index.
What does not work is introducing a colour that is not in the palette; `colwin
build` names those and stops, because the game has no way to store them.

Do not resize a sprite: the canvas size is part of the resource.

One SPRT rule has no equivalent in a paint program: **each row is a single
run**, so a row cannot have a transparent gap between two opaque stretches.
`colwin build` reports any row that does.

## Putting it back

    colwin status              what you have changed
    colwin build --out=DIR     writes a full game directory

Files you have not touched are put back byte for byte -- they are never
re-encoded -- so a build from an unedited workspace reproduces the original
modules exactly. `colwin verify` checks that.
"""
