# `.MP` — map files

One ships with the game: `AMER2.MP`, 12,534 bytes. `colwin` does not currently
read or write it; this page records the layout, which is solved.

```
WORD  width          58
WORD  height         72
WORD  UNKNOWN        4
BYTE  terrain[w*h]   plane 0
BYTE  plane1[w*h]    plane 1
BYTE  plane2[w*h]    plane 2
```

Every byte is accounted for: `6 + 3 × 58 × 72 = 12,534`, exactly the file size.

## Planar, not three bytes per tile

The evidence is plane 1: it is **uniformly zero across all 4,176 tiles**.
Reading the data as interleaved gives three lanes that all look alike (71, 65
and 76 distinct values, similar histograms); reading it as planes gives one
plane with 87 values, one with exactly one value, and one with 15. No
interleaving of three per-tile fields produces a lane that is entirely zero.

## The planes

**Plane 0 — terrain.** 87 distinct values. The two commonest are 25 (2,109
tiles) and 26 (810), together just under half the map. Rendering one colour per
value draws the Americas unmistakably — North, Central and South America, the
Caribbean chain, Florida, the Gulf of Mexico, Baja California — which is what
identifies 25 and 26 as water. The other 85 values are **UNKNOWN**.

**Plane 1 — all zero.** Purpose UNKNOWN. It is not padding: it sits between two
live planes. A second shipped file would settle whether it is always zero, and
there is only one.

**Plane 2 — correlated with land and water, not established as either.**

| | `plane2 = 1` | `= 2` | `= 0` | other |
| --- | ---: | ---: | ---: | ---: |
| terrain 25/26 (water) | 2,664 | 0 | 235 | 20 |
| any other terrain | 21 | 1,162 | 21 | 53 |

1 tracks water and 2 tracks land, but roughly 250 tiles disagree and the values
3, 5, 6 and 7 are unexplained.

## Cross-check

`AUTO01.SAV` carries `3a 00 48 00` — 58 × 72 — at offset `0x0c`: the same
dimensions, in a different file, written by a different routine.
