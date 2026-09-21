"""`.MP` maps and the map region of a `.SAV`, as plain byte planes.

    .MP                                     .SAV
    0x00  WORD  width                       0x00  9     "COLONIZE\\0"
    0x02  WORD  height                      0x0c  WORD  width
    0x04  WORD  UNKNOWN (4 in AMER2.MP)     0x0e  WORD  height
    0x06  BYTE  plane0[w*h]                 0x2a  WORD  count of 18-byte records
          BYTE  plane1[w*h]                 0x2c  WORD  count of 28-byte records
          BYTE  plane2[w*h]                 0x2e  WORD  count of 202-byte records
                                            ....  4 planes of w*h, at `map_start` below

Both layouts are closed arithmetic, and this module checks them rather than
trusting them: `6 + 3*w*h` is exactly the size of a `.MP`, and for a save

    map_start = 3005 + 202*c202 + 28*c28 + 18*c18
    map_start + 4*w*h + 1502 == file size

Where those two constants come from: `1008:a7f6` is the save routine and the
only caller of the file-write forwarder, which it calls 57 times, each one
`cdecl`, so the pushes give the fields in order with their sizes. Writes 46-49
are the four map planes -- their counts come from four consecutive globals
rather than literals -- writes 8, 9 and 11 are `IMUL` of a counter by 202, 28
and 18, and those three counters live in write 5's own buffer, which lands at
file offset 0x10, putting them at 0x2a, 0x2c and 0x2e. 3005 is the sum of the
fixed writes before the map, 1502 the sum of the eight after it. See
win-decomp's `docs/formats/save-file.md` and `tools/save_layout.py`.

A save also carries the **scenery seed**, which is what decides where the prime
resources are: `tile_decoration` hashes each square's position against it. It is
write 56 of the 57, two bytes big-endian, 890 from the end of the file, and
`generate_map` sets it once with `rand_range(1, 0x7fff)` when the map is made.
A `.MP` has none -- a map has no resources until a game starts on it.

What the planes hold is in `colwin/mapview.py`, which draws them; this module
only cuts them out. Plane 0 is terrain in both files. A save's other three are
the bitfield, the nation nibbles and the nation bitmask (win-decomp
`docs/findings/map-planes.md`); a `.MP`'s other two are **UNKNOWN** -- plane 1
is uniformly zero in the only shipped file and plane 2 merely correlates with
land and water -- so nothing here reads them.
"""
import struct

SAV_MAGIC = b"COLONIZE\0"

# The save's field table, as far as this module needs it.
SAV_FIXED_BEFORE_MAP = 3005     # writes 1-45, minus the three record arrays
SAV_FIXED_AFTER_MAP = 1502      # writes 50-57
SAV_RECORDS = ((0x2a, 18), (0x2c, 28), (0x2e, 202))
# The scenery seed is write 56 of 57: two bytes, big-endian, between the four
# 4-byte fields after the map and the final 888-byte block. `save_game_to_file`
# byte-swaps it on the way out and `load_saved_game` swaps it back.
SAV_AFTER_SEED = 888
SAV_SEED_SIZE = 2
SAV_DIMS = 0x0c
SAV_PLANES = 4
MP_PLANES = 3
MP_HEADER = 6


class MapError(Exception):
    pass


def _planes(data, start, n, count):
    return [data[start + i * count:start + (i + 1) * count] for i in range(n)]


def decode_mp(data):
    if len(data) < MP_HEADER:
        raise MapError("too short for a .MP header: %d bytes" % len(data))
    w, h, unknown = struct.unpack_from("<HHH", data, 0)
    if not w or not h:
        raise MapError("a %dx%d map has no squares" % (w, h))
    n = w * h
    if MP_HEADER + MP_PLANES * n != len(data):
        raise MapError("not a .MP: 6 + 3*%d*%d = %d but the file is %d bytes"
                       % (w, h, MP_HEADER + MP_PLANES * n, len(data)))
    return {"kind": "MP", "width": w, "height": h, "unknown_at_4": unknown,
            "planes": _planes(data, MP_HEADER, MP_PLANES, n), "map_start": MP_HEADER}


def decode_sav(data):
    if data[:len(SAV_MAGIC)] != SAV_MAGIC:
        raise MapError("not a .SAV: the file does not open %r" % SAV_MAGIC)
    w, h = struct.unpack_from("<HH", data, SAV_DIMS)
    if not w or not h:
        raise MapError("a %dx%d map has no squares" % (w, h))
    n = w * h
    counts = {}
    start = SAV_FIXED_BEFORE_MAP
    for off, size in SAV_RECORDS:
        c = struct.unpack_from("<H", data, off)[0]
        counts["%dB" % size] = c
        start += size * c
    total = start + SAV_PLANES * n + SAV_FIXED_AFTER_MAP
    if total != len(data):
        raise MapError("the save's arithmetic does not close: %d computed "
                       "against %d actual, for a %dx%d map with records %s"
                       % (total, len(data), w, h, counts))
    seed_at = len(data) - SAV_AFTER_SEED - SAV_SEED_SIZE
    seed = struct.unpack_from(">H", data, seed_at)[0]
    return {"kind": "SAV", "width": w, "height": h, "record_counts": counts,
            "planes": _planes(data, start, SAV_PLANES, n), "map_start": start,
            "scenery_seed": seed, "seed_at": seed_at}


def decode(data):
    """Either format, told apart by the save's magic.

    A file that is neither is reported as neither: the `.MP` arithmetic is the
    only test left once the magic has failed, so its message alone would blame
    the wrong format.
    """
    if data[:len(SAV_MAGIC)] == SAV_MAGIC:
        return decode_sav(data)
    try:
        return decode_mp(data)
    except MapError as e:
        raise MapError("neither a .SAV (the file does not open %r) nor a .MP "
                       "(%s)" % (SAV_MAGIC, e))


def load(path):
    with open(path, "rb") as f:
        return decode(f.read())
