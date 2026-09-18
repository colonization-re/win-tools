# Formats

Every layout `colwin` reads or writes. Each page names the module that
implements it and the evidence the layout rests on; addresses of the form
`1068:0180` are segment:offset in `COLONIZE.EXE`, and the decompilation they
refer to is in
[win-decomp](https://github.com/colonization-re/win-decomp).

| Format | Where it is | Status |
| --- | --- | --- |
| [NE container](ne-container.md) | every `.DLL` and `.EXE` | rebuilds byte-identical |
| [`SPRT`](sprt.md) | 915 across 7 modules | re-encodes byte-identical |
| [`CVPC`](cvpc.md) | 96 across 8 modules | re-encodes pixel-identical |
| [`CTAB`](ctab.md) | 43, all in `COLDATA8` | re-encodes byte-identical |
| [`TEXT`](text.md) | 737, mostly `COLTEXT0` | re-encodes byte-identical |
| [`FLIC`](flic.md) | 1, in `COLDATA7` | decoded; carried through on rebuild |
| [Windows DIBs](dib.md) | bitmaps, icons, cursors | bitmaps round-trip |
| [`.MP` maps](mp-map.md) | `AMER2.MP` | solved, not written by `colwin` |
| [`.SAV` saves](save.md) | `AUTO01.SAV` | structure solved, meanings open |
| [ARCV](arcv.md) | `COLONIZE.$00` | solved |

## Not solved

`CRDS`, `CRED`, `MONS` and `SHIP` — five record tables in `COLDATA5` and
`COLDATA9` — have no known layout. They are carried through untouched rather
than shaped into a plausible-looking table.

`COLWIN.PRF` (412 bytes of preferences) and `SETUP.INF` (the installer's own
compressed script) are likewise unread.
