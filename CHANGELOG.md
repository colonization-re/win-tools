# Changelog

Every released version of `colwin`, newest first. Versions are
[semantic](https://semver.org/spec/v2.0.0.html): the major number moves when a
workspace written by an older version stops rebuilding, the minor when formats
or commands are added, the patch for fixes. Cut a release with
`python3 tools/release.py`.

## 0.1.0 - 2026-09-19

First release. `colwin` takes the assets of *Sid Meier's Colonization for
Windows* (1995) out of their Win16 NE containers, hands you files you can edit
— indexed PNGs, `.pal` palettes, UTF-8 text — and puts them back into the
game's own containers afterwards. Pure Python 3, stdlib only, no dependencies,
3.9 or newer. It does not contain the game; bring a retail install.

```sh
python3 colwin.py extract ~/games/colonization --out=ws
#  ... edit ws/sprites/**/*.png in any paint program ...
python3 colwin.py build ws --out=patched        # a complete, playable install
```

### What round-trips

Measured against a retail install with `colwin.py verify`, every asset
re-encoded and compared with the bytes the game ships:

| Format | Count | Re-encodes to |
| --- | ---: | --- |
| `SPRT` sprites | 915 | the same bytes, all 915 |
| `TEXT` messages | 737 | the same bytes, all 737 |
| `CTAB` colour tables | 43 | the same bytes, all 43 |
| `RT_BITMAP` | 6 | the same bytes, all 6 |
| `CVPC` canvases | 96 | the same pixels and palette; our LZW places its own clear codes, so the compressed bytes differ by under 1% in size |
| everything else | 56 | carried through untouched |

**13 of 13 modules rebuild byte-identical** from an untouched workspace: a
file whose hash has not changed is never re-encoded, its original bytes go
straight back.

### Two things worth knowing

**Indices are the data; a palette is a way of looking at them.** Sprite pixels
are indices into a palette that is stored nowhere in the game — it is built at
runtime from `GetSystemPaletteEntries` and overwritten from `CTAB` blobs. The
extracted PNGs carry the index bytes verbatim, the view palette is a labelled
reconstruction, and `colwin.py palette ws --set=...` re-views every sprite
without touching a single pixel index. See
[docs/palettes.md](https://colonization-re.github.io/win-tools/palettes).

**It refuses rather than mangles.** A resized sprite, a row with an interior
transparent gap, a colour outside the palette, a character outside cp1252 —
each stops the build with an explanation naming the file. `--nearest` and
`--fill-holes` are the explicit overrides.

### Downloads

- **`colwin-0.1.0.pyz`** — the whole tool in one runnable file:
  `python3 colwin-0.1.0.pyz extract ~/games/colonization --out=ws`
- **`colwin-0.1.0.zip`** — the source tree, with the docs and the tests

Formats, evidence and every command are documented at
[colonization-re.github.io/win-tools](https://colonization-re.github.io/win-tools/).

[Commits](https://github.com/colonization-re/win-tools/commits/v0.1.0)
