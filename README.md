# win-tools — read and write the assets of *Colonization for Windows* (1995)

`colwin` extracts every asset whose format is solved into files you can edit —
indexed PNGs, `.pal` palettes, UTF-8 text — and puts them back into the game's
own containers afterwards. It is pure Python 3, stdlib only, no dependencies.

It does **not** contain the game. Bring your own copy.

```sh
python3 colwin.py extract ~/games/colonization --out=ws
#  ... edit ws/sprites/**/*.png in any paint program ...
python3 colwin.py status ws
python3 colwin.py build  ws --out=patched        # a complete, playable install
```

## What round-trips, and how well

Measured against a retail install, every asset re-encoded and compared with the
bytes the game ships — `python3 colwin.py verify ws`:

| Format | Count | Re-encodes to |
| --- | ---: | --- |
| `SPRT` sprites | 915 | **the same bytes**, all 915 |
| `TEXT` messages | 737 | **the same bytes**, all 737 |
| `CTAB` colour tables | 43 | **the same bytes**, all 43 |
| `RT_BITMAP` | 6 | **the same bytes**, all 6 |
| `CVPC` canvases | 96 | the same *pixels and palette*; our LZW places its own clear codes, so the compressed bytes differ by under 1% in size |
| everything else | 56 | carried through untouched |

And the containers themselves: **13 of 13 modules rebuild byte-identical** when
nothing has been edited. A build from an untouched workspace reproduces the
install file for file, because a file whose hash has not changed is never
re-encoded at all — its original bytes go straight back.

`python3 tests/test_roundtrip.py /path/to/game` runs all of that as 19 tests,
including a full edit → build → re-extract cycle, and
`python3 tests/test_docs.py /path/to/game` re-derives all 38 numbers in
[docs/](docs/) from the install and fails if any page has drifted from it.

## The palette problem, and what this does about it

Sprite pixels are not colours. They are **indices into a palette that is not
stored anywhere in the game**: it is built in memory at startup from
`GetSystemPaletteEntries` — the display driver's state, not game data — and
then overwritten in ranges from `CTAB` blobs at runtime. None of the 75
palettes that *do* ship fits the sprites the way a real palette fits its own
art. So "just save the PNG with the right colours" is not available, and any
tool that pretends otherwise is guessing.

The rule here is: **indices are the data, a palette is a way of looking at
them.** Three things follow.

**1. Every image comes out indexed.** The PNG's pixel values *are* the game's
index bytes, byte for byte. Whatever the palette turns out to be, nothing is
lost. Index 0 is written as transparent — safe, because none of the 915 sprites
uses it, re-checked per sprite on every extract.

**2. You can edit in RGB anyway.** The view palette is made *injective* before
it is written: if two indices would hold the same colour, one is nudged by one
step in a single channel. One part in 255 is invisible, and it makes colour →
index a lookup rather than a guess. So an editor that throws the indices away
and hands back truecolour still round-trips exactly. If you introduce a colour
the palette does not hold, `build` names it and stops, rather than quietly
rounding your art; `--nearest` overrides that when you mean it.

**3. A better palette costs one command, not a re-extraction.**

```sh
python3 colwin.py palette ws --set=ctab:111
```

rewrites the PLTE chunk of every sprite PNG and touches no pixel index. When
the real runtime palette is finally established, applying it will not lose a
single edit made before then.

What the default view palette claims, and what it admits:

| Indices | Where they come from |
| --- | --- |
| 0–9, 246–255 | the Windows 3.1 static system colours. Known and standard — and corroborated here: of those twenty, sprites use exactly 246, 247 and 249 (cream, medium grey, red) and none of the dark system entries. |
| 142–238 | a `CTAB`. That `CTAB` blobs are the payload written into the runtime palette is established from the loader at `1068:0180`. *Which* table a given sprite uses is **not** — the default pairs them by resource id, a heuristic with a measured hit rate (36 of 57, against 1.0 by chance), and it is labelled a reconstruction everywhere it appears. |
| 10–141, 239–245 | **UNKNOWN.** A grey ramp, which says so. |

`--palette=index` drops the reconstruction entirely and views every sprite
through an identity grey ramp, which claims nothing at all.

`CVPC` canvases and `RT_BITMAP`s are a different and easier case: they carry
their own complete palette, so what you see there *is* the game's colour, and
editing the PNG's palette edits the game's.

## Things the formats will not let you do

These are refused with an explanation rather than silently mangled:

- **Resizing a sprite.** The canvas size is part of the resource.
- **A row with a gap in it.** `SPRT` stores exactly one horizontal run per row,
  so a row cannot have transparent pixels *between* two opaque stretches. Real
  art never does; edited art can. `--fill-holes=INDEX` fills them if that is
  what you want.
- **Characters outside cp1252** in the text resources — including in place of
  `¤`, byte `0xA4`, which is the game's gold glyph.

## Commands

| | |
| --- | --- |
| `list TARGET` | what is in a module or a whole game directory |
| `extract GAME --out=WS` | build a workspace; `--palette=` picks the view rule |
| `status WS` | which files you have changed |
| `build WS --out=DIR` | write a complete install with your edits in it |
| `verify WS` | re-encode everything and compare with the game |
| `palette WS [--set=RULE]` | show the view palettes, or swap them |

## Documentation

[**docs/**](docs/) is a small reference site. Every push to `main` that touches
it is built with Jekyll and deployed to GitHub Pages by
[.github/workflows/pages.yml](.github/workflows/pages.yml); the repository's
Pages source has to be set to "GitHub Actions" for that to publish.

| | |
| --- | --- |
| [Using the tool](docs/usage.md) | the six commands, every option, and what each one prints |
| [What is in each file](docs/files.md) | all 64 files of an install, and what each one holds |
| [Formats](docs/formats/) | the layouts, one page each, with the evidence for each |
| [Palettes](docs/palettes.md) | why sprite colours are stored nowhere, and the rule that follows |
| [Editing](docs/editing.md) | the workflow, and what gets refused |

## Layout

```
colwin/ne.py          Win16 NE containers: read the resource table, write it back
colwin/png.py         PNG in and out, stdlib only
colwin/palette.py     the palette model and the injectivity rule
colwin/workspace.py   extract / status / build / verify
colwin/formats/       sprt, cvpc, lzw, ctab (in palette.py), text, dib, flic
docs/                 the reference site
tests/                the test suite; the asset tests need a copy of the game
```

## Where the formats come from

Every format here was established by reverse engineering in the sibling
repository [win-decomp](https://github.com/colonization-re/win-decomp), and the
source files cite the specific evidence — the CVPC palette offset comes from
the call site at `1068:4c05`, the LZW parameters from the hand-written 386
assembly at `1088:0000`, the CTAB field meanings from the loader at
`1068:0180`. Where something is not established, the code says `UNKNOWN` and
carries the bytes through rather than inventing a meaning for them. Four fields
of the sprite header are like that — testing seven image quantities against
three readings of each, over all 915 sprites, the best of the 21 hypotheses
matches 89. They are copied, never computed.
