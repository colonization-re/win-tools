# Editing

```sh
python3 colwin.py extract ~/games/colonization --out=ws
#  ... edit ws/sprites/**/*.png, ws/text/**/*.txt ...
python3 colwin.py status ws
python3 colwin.py build  ws --out=patched
```

`build` writes a complete install: the rebuilt modules plus every other file
copied alongside them.

This page is the workflow and the rules the formats impose. Every command and
every option is in [Using the tool](usage.md).

## What a workspace holds

```
ws/
  colwin.json     the manifest: where each file came from and what it was
  sprites/        indexed PNGs; pixel values ARE the game's palette indices
  canvases/       indexed PNGs whose palette IS the game's
  bitmaps/        Windows DIBs, likewise self-contained
  colortables/    the 43 CTAB tables as JASC .pal files
  text/           the game's authored text, UTF-8
  palettes/       .pal (JASC) and .gpl (GIMP) for every view palette
  reference/      icons, cursors and the FLC frames — readable, not rebuilt
```

## Working with the palette

Load the matching `palettes/*.pal` or `.gpl` into your editor. If it has an
indexed mode, use it: the round trip is then bit for bit and the palette never
enters into it.

Truecolour editing works too, because every view palette is injective — no two
indices share a colour, so each colour maps back to exactly one index. See
[Palettes](palettes.md) for why that is arranged and what the colours mean.

## What will be refused, and why

These are stopped with an explanation rather than silently mangled.

**A colour that is not in the palette.** The game stores indices, so every pixel
has to land on an entry that exists. `--nearest` snaps each new colour to the
closest entry instead, which changes the art.

**Resizing a sprite.** The canvas size is part of the resource; the game places
the sprite on it.

**A row with a gap in it.** A [`SPRT`](formats/sprt.md) row is exactly one
horizontal run, so it cannot have transparent pixels *between* two opaque
stretches. Real art never does. `--fill-holes=INDEX` fills them with a palette
index if that is what you want.

**A character cp1252 cannot hold**, in a text resource — including in place of
`¤`, byte `0xA4`, which is the game's gold glyph.

## Growing things

Resources may get bigger. A module's resource offsets are 16-bit at a 512-byte
alignment, which caps a module at 33.5 MB, so there is a lot of room. Growing a
text resource tenfold and rebuilding was checked: the tail reflows and all 717
other resources in that module still read back identically.

## Proving it still works

```sh
python3 colwin.py verify ws
```

re-encodes every extracted asset and compares it with the bytes the game ships.
On an unmodified extract:

| Format | Count | Result |
| --- | ---: | --- |
| `SPRT`, `TEXT`, `CTAB`, `RT_BITMAP` | 1,701 | byte for byte identical |
| `CVPC` | 96 | identical pixels and palette |
| containers | 13 / 13 | rebuild byte-identical |

A file whose hash has not changed is never re-encoded — its original bytes go
straight back — which is why a build from an untouched workspace reproduces the
install exactly, and why only what you actually edited passes through an
encoder.

`python3 tests/test_roundtrip.py /path/to/game` runs the same ground as 19
tests, including a full edit → build → re-extract cycle.

`python3 tests/test_docs.py /path/to/game` re-derives all 38 numbers on these
pages from the install and fails if any of them has drifted — a document is the
one artefact nothing re-runs.
