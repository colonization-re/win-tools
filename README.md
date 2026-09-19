# win-tools — read and write the assets of *Colonization for Windows* (1995)

`colwin` extracts every asset whose format is solved into files you can edit —
indexed PNGs, `.pal` palettes, UTF-8 text — and puts them back into the game's
own containers afterwards. It is pure Python 3, stdlib only, no dependencies.

It does **not** contain the game. Bring your own copy.

## Install and run

There is nothing to install. You need **Python 3.9 or newer** — tested on 3.9,
3.11 and 3.13 — and a retail install of the game.

```sh
git clone https://github.com/colonization-re/win-tools
cd win-tools
python3 colwin.py --version
```

`colwin.py` runs the package straight out of the checkout, from any directory
(`python3 /path/to/win-tools/colwin.py ...`), and `python3 -m colwin` does the
same wherever the checkout is importable. On Windows use `py -3` in place of
`python3`. To remove it, delete the directory: nothing is written outside the
checkout and the directories you name on the command line.

Then:

```sh
python3 colwin.py extract ~/games/colonization --out=ws
#  ... edit ws/sprites/**/*.png in any paint program ...
python3 colwin.py status ws
python3 colwin.py build  ws --out=patched        # a complete, playable install
```

And to look at a saved game — no workspace needed:

```sh
python3 colwin.py map-preview AUTO01.SAV ~/games/colonization --out=map.png
```

[Using the tool](docs/usage.md) is the long version, with every option.

## Drawing a map

`map-preview` reads a `.SAV` or a `.MP` and writes the whole map as one PNG in
the game's own art:

```
AUTO01.SAV: a 58x72 SAV map, planes at 0x1cd3
    85 settlement(s): 1 colon(ies), 84 village(s)

wrote map.png, 1856x2304 pixels at 32 px a square
```

`--tile=8` draws the same map at 464 × 576 for a thumbnail; `--plain` leaves
out everything whose cell is not pinned by the game's own code.

**It does not have a renderer of its own.** It replays `1040:14d4`, the routine
that paints one map square, once per square — in that routine's order, with its
masks and its arithmetic:

| | |
| --- | --- |
| base square | the terrain's low three bits — and for a **coastal water square**, the land behind it, because the neighbour scan overwrites the square's own class before the drawer reads it back |
| terrain seams | up to four, one per side, each the neighbour's terrain seen through a mask sprite |
| forest, plowed, hills, mountains, rivers, roads | one band each, indexed by a four-bit neighbour code: **N 8, S 4, W 2, E 1** |
| coastline | four corner pieces, or one of four whole-edge shore squares when the land around matches one of four exact patterns |
| river mouths | where a river runs into the sea, or into a lake it feeds |
| settlements | from the settlement bit and the owner nibble |

The art comes out of `CVPC 201` in `COLDATA1.DLL` with the rectangles and key
colours `load_all_sprite_sheets` (`1008:51d4`) uses to cut its 217 sprites at
start-up. Sprites the game *builds* rather than cuts are built the same way
here: a seam is a terrain square masked by one of four mask sprites, and a
coastline corner is open water with a coast piece over it, keyed afterwards —
and in both cases the **order** is what makes the picture, which is the sort of
thing these tools are for finding out.

Two layers are deliberately absent, both because the file cannot supply them:
the scenery and prime resources, which the game hashes out of a seed that is
not one of the 57 fields a save writes, and the fog of war, which needs a
viewer. [Map preview](docs/map-preview.md) is the long version, layer by layer,
with what each one rests on.

No rendered map ships in this repository: the pixels are the game's artwork,
and the same rule applies to them as to everything else here — bring your own
copy and draw your own.

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
including a full edit → build → re-extract cycle;
`python3 tests/test_map.py /path/to/game` puts the map renderer through 42 more,
re-deriving the tile set's rules from the canvas — that each band cell paints
the edge its mask names, that each coastline piece leans the way its code says,
that a seam mask keeps 64 pixels along one edge and no others; and
`python3 tests/test_docs.py /path/to/game` re-derives all 42 numbers in
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
| `map-preview MAP GAME --out=PNG` | draw a `.SAV` or `.MP` map, `--tile=` for the size |

## Documentation

[**docs/**](docs/) is a small reference site. Every push to `main` that touches
it is built with Jekyll and deployed to GitHub Pages by
[.github/workflows/pages.yml](.github/workflows/pages.yml); the repository's
Pages source has to be set to "GitHub Actions" for that to publish.

| | |
| --- | --- |
| [Using the tool](docs/usage.md) | the seven commands, every option, and what each one prints |
| [What is in each file](docs/files.md) | all 64 files of an install, and what each one holds |
| [Formats](docs/formats/) | the layouts, one page each, with the evidence for each |
| [Map preview](docs/map-preview.md) | every layer of a map square and the code each one comes from |
| [Palettes](docs/palettes.md) | why sprite colours are stored nowhere, and the rule that follows |
| [Editing](docs/editing.md) | the workflow, and what gets refused |

## Layout

```
colwin/ne.py          Win16 NE containers: read the resource table, write it back
colwin/png.py         PNG in and out, stdlib only
colwin/palette.py     the palette model and the injectivity rule
colwin/workspace.py   extract / status / build / verify
colwin/tileset.py     the map tile set: which cell, which key colour, what for
colwin/mapview.py     map-preview: 1040:14d4's layering, square by square
colwin/formats/       sprt, cvpc, lzw, ctab (in palette.py), text, dib, flic,
                      mapfile (.MP and the map planes of a .SAV)
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
