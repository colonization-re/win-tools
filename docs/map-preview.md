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
| `--plain` | leave out the seams, the plowed squares and the settlements |

At the default size the shipped 58 × 72 map is a 1856 × 2304 image. `--tile=8`
gives the same map as 464 × 576, which is the size to use for a thumbnail or a
contact sheet: squares are sampled, not filtered, so the art stays crisp.

## What it draws, and where each layer comes from

The layering is not invented here. `1038:d8f8` is the function that paints one
map square, and this applies it to every square in turn:

| Layer | Icon | From |
| --- | --- | --- |
| base square | `kind = class & 7` below `0x18`, else the class | plane 0, low five bits |
| terrain seams | up to four overlays beside the base square | the neighbours' terrain groups |
| forest | `0x41 + mask` | terrain ids 8–23 |
| plowed | `0x96` | plane 1 bit `0x40` |
| hills / mountains | `0x31 + mask` / `0x21 + mask` | plane 0 bit `0x20`, with `0x80` |
| river | `0x11 + mask`, major `0x01 + mask` | plane 0 bit `0x40`, with `0x80` |
| roads | `0x51`, else `0x52 + direction` | plane 1 bits `0xa` |
| coastline | four corner pieces, `0x6d + code × 4 + j`, or one shore square | water with land around it |
| settlements | — | plane 1 bit `0x02`, owner from plane 2's high nibble |

### A coastal water square is drawn on the land behind it

This is the one that makes a beach look like a beach, and it is easy to read
straight past. `neighbor_terrain_scan_1040_02cc` does not only count land and
fill in the corner codes: as it goes it **overwrites the square's own terrain
and class** at DGROUP `0x4c9c`/`0x4c9d` with the last ORTHOGONAL land
neighbour's — west wins over south, south over east, east over north — and
`map_draw_square_1040_14d4` reads those back *after* calling it, to choose the
base tile.

So a water square with land beside it is painted on **that land's tile**, and
the shore art goes over the top. The four shore squares leave their land side
clear, so what shows through is sand against desert, grass against grassland,
tundra against tundra. Open sea takes the ocean tile, which is why the class is
saved into `wter` before the scan runs; a square with land only on its diagonals
has nothing written to it and keeps its own tile too. On the shipped map, **370
of the 517 coastal squares** are drawn on the land behind them.

### The seams are what make terrain meet terrain

`draw_tile_with_overlays` does not just draw the base square: it takes a
four-byte list beside it and draws up to four **overlay** sprites, skipping the
`0xff`s. `build_terrain_seams_1008_7ec9` fills that list, one byte per square
per orthogonal direction, before anything is drawn:

| the neighbour | the seam |
| --- | --- |
| a land terrain whose **group** (`terrain % 8`) differs | `(nb % 8) * 4 + direction` — the neighbour's group |
| arctic (`0x18`) | `direction + 0x20` |
| shallow water, and this square is a sea lane | `direction + 0x28` |
| a sea lane, and this square is shallow water | `direction + 0x24` |
| anything else, including a land square beside open water | none |

The group is why a forest seams as the terrain underneath it, and why
grassland against conifer forest has no seam at all: both are group 4.

A land square beside water asks `cell_draw_terrain_1008_7e2d` what that water
draws as, and the answer is not `0x19` but **the group of the land the water's
own coastline touches** — `coast_neighbours_1008_7cb5` overwrites the remembered
terrain as it walks the eight neighbours, keeping the last orthogonal land one,
so west wins over south, south over east, east over north. The beach belongs to
the land it touches, not to the sea.

### Why desert coasts have no transition, and it is not this tool

The water square seams too, with the land beside it — and the test is
`nb % 8 != base % 8`. **Ocean is terrain 25, and 25 % 8 is 1, which is desert.**
So the one land type an ocean square cannot seam with is the one it collides
with. Measured over `AMER2.MP`:

| land touching a water square | edges | of those, seamed |
| --- | ---: | ---: |
| tundra | 115 | 115 |
| **desert** | **63** | **0** |
| plains | 85 | 85 |
| prairie | 39 | 39 |
| grassland | 49 | 49 |
| savannah | 195 | 195 |
| marsh | 13 | 13 |
| swamp | 40 | 40 |

Every group but desert, every time. The game suppresses that one boundary by
arithmetic, so a desert shore is sand meeting the water square's own coast art
with nothing in between — here and in the game. Sea lane is 26, so the same
collision should silence **plains** against a sea lane; no shipped map can show
it, because no sea lane on `AMER2.MP` touches land.

Every `mask` is the same four-bit neighbour code — **N 8, S 4, W 2, E 1** —
which is how every mask helper in the game weights its four neighbours
(`neighbor_mask_1038_d4b9`, `tile_neighbor_match`, `orthogonal_neighbor_bits`).

## Cells are colour-keyed, the way the game cuts them

`ExtractSprite` takes **one colour and drops every pixel of it**, wherever it
lies, and `load_all_sprite_sheets` passes the key with each rectangle: `0x31`
for almost everything, `0x51` for the sixteen mountain cells — they are drawn on
the orange rule rather than on the ground — and `0x87` for the seam masks and
the coastline pieces. Those are runtime palette indices, so subtract the 40 the
loader installs this canvas at: **9** the grey ground, **41** the orange rule,
**95** black.

A coastline piece is keyed *twice*, because it is extracted twice — and the
**order** decides what a coast looks like. The builder cuts the piece keying out
black, draws a 16 × 16 square of open water, draws the piece over it, and then
extracts *that* keying out the ground. So a pixel the piece paints in the ground
colour covers the water first and is dropped second: it becomes a **hole**, and
what shows through it is the square's base tile — the land behind the coast.

Read the other way round — "the ground colour is transparent, so the water below
shows" — every coastal square comes out a solid block of water and the coastline
steps in squares. Codes 1 and 3 to 7 all carry ground pixels; in code 7 they are
a quarter of the piece.

This tool used to flood the background inward from each cell's border instead,
which is a reasonable thing to do when you are cutting pictures out of a sheet
by eye — and wrong here. Tree canopies and rock faces *enclose* pockets of the
sheet's ground, and flooding leaves them painted: 29,009 pixels of grey over a
shipped save's map, in specks on every wooded square and a block on every
coastal one.

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
pieces, and the sheet has exactly thirty-two. Each piece's three bits say which
of the two edges at that corner, and the diagonal, are land, and **each piece's
art leans that way**: measured on all thirty-two, with code 0 painting nothing
at all and the codes with both edges wrapping the corner.

### The four whole-edge shore squares, found by their own patterns

A water square whose land matches one of four exact patterns is drawn as a
single square instead, icons `0x97`–`0x9a`:

| icon | land at | the cell |
| --- | --- | --- |
| `0x97` | N, W, NW | top-left of the block at (555, 298) |
| `0x98` | N, NE, E | top-right |
| `0x99` | S, SW, W | bottom-left |
| `0x9a` | E, SE, S | bottom-right |

Those four cells sit as a 2 × 2 block that reads as a lake, which is why they
were first taken for a picture of one. They are not: **each carries water
across exactly the two edges its pattern leaves open**, and nothing across the
two the land is on — all four, in reading order. On the shipped map they draw
98 of the 517 coastal squares; the corner pieces draw the other 419.

## What it does not draw, and why

**Prime resources and scenery.** `tile_decoration_1038_c066` picks them by
hashing the square's position against a seed at DGROUP `0x1ca6`, and that seed
is **not one of the 57 fields the save routine writes**. Nothing in the file
determines them, so nothing is drawn. A save that looks bare of beaver and fish
next to the running game is not a bug in this tool.

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
