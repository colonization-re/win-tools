# Map preview

`colwin map-preview` draws a saved game or a map file as one PNG, in the game's
own art:

```sh
python3 colwin.py map-preview ~/games/colonization/AUTO01.SAV \
        ~/games/colonization --out=map.png
```

```
AUTO01.SAV: a 58x72 SAV map, planes at 0x1cd3
    85 settlement(s): 1 colon(ies), 84 village(s)

wrote map.png, 1856x2304 pixels at 32 px a square
```

| | |
| --- | --- |
| `map` | a `.SAV` or a `.MP`; which one is read from the file, not the name |
| `game` | an installed copy — the art comes out of its `COLDATA1.DLL` |
| `--out` | the PNG to write |
| `--tile=PX` | pixels a square, 1 to 32. The default is 32, the size the game draws |
| `--plain` | draw only what the game's own routine establishes: no plowed squares, no settlements |

At the default size the shipped 58 × 72 map is a 1856 × 2304 image. `--tile=8`
gives the same map as 464 × 576, which is the size to use for a thumbnail or a
contact sheet: squares are sampled, not filtered, so the art stays crisp.

## What it draws, and where each layer comes from

The layering is not invented here. `1038:d8f8` is the function that paints one
map square, and this applies it to every square in turn:

| Layer | Icon | From |
| --- | --- | --- |
| base square | `kind = class & 7` below `0x18`, else the class | plane 0, low five bits |
| forest | `0x41 + mask` | terrain ids 8–23 |
| plowed | `0x96` | plane 1 bit `0x40` |
| hills / mountains | `0x31 + mask` / `0x21 + mask` | plane 0 bit `0x20`, with `0x80` |
| river | `0x11 + mask`, major `0x01 + mask` | plane 0 bit `0x40`, with `0x80` |
| roads | `0x51`, else `0x52 + direction` | plane 1 bits `0xa` |
| coastline | four corner pieces, `0x6d + code × 4 + j` | water with land around it |
| settlements | — | plane 1 bit `0x02`, owner from plane 2's high nibble |

Every `mask` is the same four-bit neighbour code — **N 8, S 4, W 2, E 1** —
which is how every mask helper in the game weights its four neighbours
(`neighbor_mask_1038_d4b9`, `tile_neighbor_match`, `orthogonal_neighbor_bits`).

## The tile set is `CVPC 201`, and the art says so

The map art is the left page of `CVPC 201` in `COLDATA1.DLL`, a 1280 × 480
canvas ruled into cells in orange on grey. It was catalogued in the research
repository as *"a two-page reference sheet rather than a run-time atlas"*,
because its only loader blits 640 × 480 halves and no code path binds a cell to
anything. Drawing a map from it makes the case the other way round: the sheet
carries **six 16-cell bands in exactly the order the draw function names its
six icon bases**, at y = 232, 265, 298, 331, 364 and 397.

The second agreement is the one worth the page. Take the mask convention from
the code — N 8, S 4, W 2, E 1 — and it predicts *which edge of each cell the
artwork touches*. Measured on the pixels, in every band:

| cell | 1 | 2 | 4 | 8 | 15 |
| --- | --- | --- | --- | --- | --- |
| edge painted | east | west | south | north | all four |

Nothing forces that but the assignment being right, and `tests/test_map.py`
re-derives it from the canvas on every run.

The eight 2 × 2 quads of 16 × 16 coast cells are the same story: the draw
function asks for `g_4c6e[j] * 4 + j + 0x6d`, where the corner code is three
bits and `j` runs top-left, top-right, bottom-right, bottom-left — thirty-two
pieces, and the sheet has exactly thirty-two.

## What it does not draw, and why

**Prime resources and scenery.** `tile_decoration_1038_c066` picks them by
hashing the square's position against a seed at DGROUP `0x1ca6`, and that seed
is **not one of the 57 fields the save routine writes**. Nothing in the file
determines them, so nothing is drawn. A save that looks bare of beaver and fish
next to the running game is not a bug in this tool.

**The four whole-edge coast tiles** (`0x97`–`0x9a`). The draw function prefers
them when the land around a water square matches one of four patterns exactly.
No cell on the sheet is bound to those icon numbers, so this always takes the
general path — the four corner pieces, which the same function uses for every
other pattern.

**Units.** Plane 1 bit `0x01` says a square holds one. Nothing in the planes
says which, and the tool does not guess.

**Colours and pictures for nations.** The settlement art and the four European
colours are a **presentation choice**, marked `inferred` in
`colwin/tileset.py`: no load site derives a settlement's picture from a nation,
and no colour is bound to one anywhere in the game's data. `--plain` leaves all
of it out and draws only what the code establishes.

## `.MP` files draw terrain only

A `.MP` has three planes, and only the first is solved. Its plane 1 is
uniformly zero in the only shipped file and its plane 2 merely correlates with
land and water, so this reads neither: `AMER2.MP` draws as terrain, rivers,
hills, mountains and coastline, with no settlements, roads or plowed squares.
The tool says so in its output rather than leaving you to wonder.

## A cross-check that fell out of drawing the save

`AUTO01.SAV` has **85 squares with the settlement bit set: 1 owned by a
European nation and 84 by a native one.** Its record counts, read from the
header at `0x2a`–`0x2e`, are **84 records of 18 bytes, 95 of 28 and 1 of 202**.

So the two independent things the file says about settlements agree, twice over
in one file: 84 villages against 84 18-byte records, and 1 colony against the
single 202-byte record — the largest record in the save, for the one thing in a
save that has a name, a population and a warehouse.

That is one save, so it is a cross-check and not a proof; the research
repository lists what those record arrays hold as open. It is recorded here
because it is the kind of agreement that is worth chasing, and because
`tests/test_docs.py` re-measures both numbers on every run.
