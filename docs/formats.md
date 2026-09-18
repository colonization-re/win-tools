# The on-disk formats

Everything `colwin` reads and writes, in one place. Each layout is implemented
in the module named beside it, and the evidence for each is cited there.

Addresses of the form `1068:0180` are segment:offset in `COLONIZE.EXE`; the
decompilation they refer to is in
[win-decomp](https://github.com/colonization-re/win-decomp).

## Container: Win16 NE — `colwin/ne.py`

The eleven data DLLs, `COLONIZE.EXE` and `SETUP.EXE` all have one shape:

```
[ NE header + segments ]  [ resources: one contiguous run, to EOF ]
```

Measured over all twelve: no overlaps, one run, and a single gap at the front.
Resource offsets and lengths live in 12-byte table entries in the header, in
units of `1 << align_shift` (512 bytes in every module), so every body is
NUL-padded to that boundary. Rebuilding therefore never moves a segment or
touches a relocation — it re-lays the tail and patches the table.

Resource *names* come from `RT_NAMETABLE` (type 15), which Microsoft never
documented:

| | |
| --- | --- |
| `WORD cbEntry` | size of this entry, including this field |
| `WORD wTypeId` | `0x8000\|ordinal`, else a name offset |
| `WORD wResId` | likewise |
| `char[]` | NUL-terminated type name, then resource name |

`6 + len(type)+1 + len(name)+1 == cbEntry` holds for every entry of every
module, which is what verifies the layout.

## `SPRT` — sprite — `colwin/formats/sprt.py`

25-byte header, little-endian, then `y1 - y0` rows of exactly one run each.

| Offset | | |
| --- | --- | --- |
| `0x00` | 4 × `WORD` | signed placement offsets; zero in 774 of 915, a negative pair in the rest |
| `0x08` | `WORD` | `full_width` — the canvas the sprite sits on |
| `0x0a` | `WORD` | `full_height` |
| `0x0c`–`0x12` | 4 × `WORD` | `x0, y0, x1, y1` — bounding box of the opaque pixels |
| `0x14` | `WORD` | **UNKNOWN** |
| `0x16` | `WORD` | **UNKNOWN** |
| `0x18` | `BYTE` | 0 |

Each row: `WORD skip`, `WORD count`, `BYTE pixels[count]`. Nothing is padded on
the right. A degenerate box `(0,0,0,0)` is an empty sprite.

Invariants, measured over all 915 and relied on by the encoder:

- `x0` is the minimum `skip`, `x1` the maximum `skip + count` — 837/837
- the first and last row of the box are never blank — 837/837
- blank rows *inside* the box encode as `skip = 0, count = 0` — 32 sprites have them
- index 0 never appears inside a run — 837/837, which is what lets index 0 mean
  transparent on the way out and back

The two `UNKNOWN` words are copied, never computed: tested against row count,
pixel count, byte count and both dimensions over all 915 sprites, the best
match is 86/915. Nobody knows what they are, so nothing here pretends to.

## `CVPC` — canvas image — `colwin/formats/cvpc.py`, `lzw.py`

| Offset | | |
| --- | --- | --- |
| `0x00` | `WORD` **BE** | width |
| `0x02` | `WORD` **BE** | height |
| `0x04` | `BYTE` | `bpp` / LZW minimum code size — 3, 5, 6, 7, 8 observed |
| `0x05` | `BYTE` | pixel mask, always `(1 << bpp) - 1` |
| `0x06` | RGB × `2^bpp` | palette; entry 0 is white |
| `6 + 3·2^bpp` | | LZW codestream in length-prefixed sub-blocks |

The palette offset comes from the call site: `1068:4c05` computes the
decompressor's source as `base + (mask + 1) * 3 + 6` and passes the palette as
`base + 6`. An earlier reading took the leading `ff ff ff` for padding and
decoded 14 pixels out of 307,200; with the three-byte correction, 96 of 96.

The codestream is GIF's LZW exactly — LSB-first, initial width `bpp + 1`, clear
`1 << bpp`, end `+1`, first free `+2`, growing to 12 — read off the game's own
decompressor at `1088:0000`, 1,002 bytes of hand-written 386 assembly that
allocates three 4,096-entry WORD tables. `CVPC` is not a GIF file; the art was
authored as GIF and converted at build time, which is why it shares the
parameters and none of the container.

## `CTAB` — colour table — `colwin/palette.py`

`WORD start` = 142, `WORD count` = 97, then 97 packed RGB triples: 295 bytes,
identical in shape in all 43. Not a reading of the bytes — the loader at
`1068:0180` takes those two words as `start` and `count` and passes `data + 4`
to the routine that calls `SetPaletteEntries`.

A table whose last entries are black ends short once the resource's NUL padding
is trimmed; that is not corruption.

Index 142 is pure white in all 43. A saturated teal `(0,173,173)` appears
exactly once in 42 of them, at a table-specific index, and fills solid regions
of sprite art in long runs — which is what a colour key looks like, and is
**not** established as one. `colwin` records the index and renders it as an
ordinary colour.

## `TEXT` — authored text — `colwin/formats/text.py`

Plain 8-bit text, LF-separated, with `@name=value` directives at the top
(`@width`, `@default`, `@x`, `@y`). `{...}` is emphasis, `^` delimits sections,
`%STRING0`–`%STRING4` / `%NUMBER0`–`%NUMBER3` / `%COUNTRY` are runtime
substitutions. Byte `0xA4` is the gold glyph. cp1252 throughout.

Not all of them are prose: `ARAWAK` is a list of map coordinates, so some of
the game's *scenario data* lives here too.

## `FLIC` — `colwin/formats/flic.py`

A stock Autodesk FLC (magic `0xAF12`): 640×480, 8 bpp, 66 frames at 71 ms.
Chunk types present are `PSTAMP`, `COLOR_256`, `BYTE_RUN` and `DELTA_FLC`; the
decoder also implements `COLOR_64`, `DELTA_FLI`, `BLACK` and `FLI_COPY`.

The encoder writes all-keyframe files (`COLOR_256` + `BYTE_RUN`, no deltas).
That is lossless and about 7× larger than the shipped animation, so `colwin`
carries the original through rather than rebuilding it.

## Windows resources — `colwin/formats/dib.py`

`RT_BITMAP` is six 32×32 4-bpp DIBs with a `BITMAPINFOHEADER` — ordinary
indexed images carrying their own palette, and they round-trip.

`RT_ICON` (32×64 8-bpp) and `RT_CURSOR` (4-byte hotspot, then 32×64 1-bpp)
stack a colour image and a 1-bpp AND mask in one DIB of doubled height. Only
the top half is at the declared depth — reading the whole thing at 8 bpp is
what makes an icon look truncated. They decode for viewing; `colwin` carries
the originals through on a rebuild.

## Not solved

`CRDS`, `CRED`, `MONS` and `SHIP` are record tables whose layout is unknown.
They are carried through untouched rather than shaped into a plausible-looking
CSV.
