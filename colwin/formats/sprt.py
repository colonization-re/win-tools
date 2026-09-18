"""SPRT -- the sprite format: one horizontal run per row, on a fixed canvas.

Header, 0x19 (25) bytes, little-endian:

    0x00  2 x  WORD  signed, UNKNOWN: a pair, non-zero in 141 of 915 and always
                     negative there.  Preserved verbatim, never computed.
    0x04  2 x  WORD  0 in all 915
    0x08  WORD  full_width      the canvas the sprite sits on
    0x0a  WORD  full_height
    0x0c  WORD  x0  \
    0x0e  WORD  y0   |  bounding box of the non-transparent pixels
    0x10  WORD  x1   |
    0x12  WORD  y1  /
    0x14  WORD  UNKNOWN -- preserved verbatim, never recomputed (see below)
    0x16  WORD  UNKNOWN -- likewise; 0x14 and 0x16 may be one 32-bit field
    0x18  BYTE  0

Then exactly `y1 - y0` rows, each ONE run:

    WORD skip    transparent pixels before the run, measured from x = 0
    WORD count   opaque pixel count
    BYTE[count]  palette indices

Nothing is padded on the right: past `skip + count` the row is transparent.  A
degenerate bounding box (0,0,0,0) is an empty sprite with no pixel data.

Every invariant the encoder relies on was measured over all 915 shipped
sprites, not assumed:

    x0 == min skip over non-blank rows                      837/837
    x1 == max (skip + count)                                837/837
    the first and last row of the box are never blank        837/837
    blank rows inside the box encode as skip=0, count=0       32 sprites have them
    index 0 never appears inside a run                       837/837

The last one is what lets index 0 mean "transparent" on the way out and back
in without colliding with real pixel data; `encode` re-checks it per sprite.

Four of the header's fields are copied, not computed, because nobody knows what
they are.  The pair at 0x00 is related to the canvas without being determined by
it -- 0x00 is exactly -(full_width / 2) in 66 of the 141 sprites that have one,
and both coordinates are the canvas centre in 49 -- which looks like a draw
origin and is not established as one.  The 0x14/0x16 pair reads as one 32-bit
counter (its low word carries into the high word) that matches nothing in the
image: seven image quantities against three readings of the field is 21
hypotheses, and the best matches 89 of 915.  A field nobody understands is a
field to carry through untouched.
"""
import struct

HDR = 0x19
TRANSPARENT = 0


class SprtError(Exception):
    pass


def decode(body):
    """-> dict with the header fields and a full-canvas index bitmap."""
    if len(body) < HDR:
        raise SprtError("too short: %d bytes" % len(body))
    origin = struct.unpack_from("<4h", body, 0)
    w, h, x0, y0, x1, y1 = struct.unpack_from("<6H", body, 8)
    u14, u16 = struct.unpack_from("<HH", body, 0x14)
    u18 = body[0x18]

    canvas = bytearray(w * h)
    p = HDR
    for r in range(y1 - y0):
        if p + 4 > len(body):
            raise SprtError("row %d: run header past end of resource" % r)
        skip, count = struct.unpack_from("<HH", body, p)
        p += 4
        if p + count > len(body):
            raise SprtError("row %d: %d pixels past end of resource" % (r, count))
        if skip + count > w:
            raise SprtError("row %d: skip+count=%d exceeds width %d" % (r, skip + count, w))
        y = y0 + r
        if y >= h:
            raise SprtError("row %d lies below the %d-pixel canvas" % (y, h))
        canvas[y * w + skip:y * w + skip + count] = body[p:p + count]
        p += count

    return {"origin": list(origin), "width": w, "height": h,
            "bbox": [x0, y0, x1, y1], "unknown14": u14, "unknown16": u16,
            "unknown18": u18, "pixels": bytes(canvas), "consumed": p}


def encode(pixels, width, height, origin=(0, 0, 0, 0), unknown14=0,
           unknown16=0, unknown18=0, fill_holes=None):
    """Canvas index bitmap -> SPRT bytes.

    `fill_holes` is the answer to the one thing the format cannot express: a
    row with two separate runs.  The original art never has one, because each
    row is a single run by construction.  Edited art can.  With `fill_holes`
    None the encoder refuses and names the rows; given an index it fills the
    interior gaps with it, which is a visible change the caller has asked for.
    """
    if len(pixels) != width * height:
        raise SprtError("%d pixels for a %dx%d canvas" % (len(pixels), width, height))

    rows = []
    for y in range(height):
        row = pixels[y * width:(y + 1) * width]
        first, last = -1, -1
        for x, v in enumerate(row):
            if v != TRANSPARENT:
                if first < 0:
                    first = x
                last = x
        rows.append((first, last, row))

    solid = [y for y, (f, _l, _r) in enumerate(rows) if f >= 0]
    if not solid:
        return (struct.pack("<4h", *origin) +
                struct.pack("<6H", width, height, 0, 0, 0, 0) +
                struct.pack("<HH", unknown14, unknown16) +
                bytes([unknown18]))

    y0, y1 = solid[0], solid[-1] + 1
    x0 = min(rows[y][0] for y in solid)
    x1 = max(rows[y][1] for y in solid) + 1

    holes, out = [], bytearray()
    for y in range(y0, y1):
        first, last, row = rows[y]
        if first < 0:
            out += struct.pack("<HH", 0, 0)
            continue
        run = bytearray(row[first:last + 1])
        gap = [i for i, v in enumerate(run) if v == TRANSPARENT]
        if gap:
            if fill_holes is None:
                holes.append((y, len(gap)))
            else:
                for i in gap:
                    run[i] = fill_holes
        out += struct.pack("<HH", first, len(run)) + bytes(run)

    if holes:
        shown = ", ".join("row %d (%d px)" % t for t in holes[:6])
        raise SprtError(
            "SPRT stores one run per row, so a row cannot have a transparent "
            "gap between two opaque stretches. %d row(s) do: %s%s. Either close "
            "the gaps in the image, or re-run with --fill-holes=INDEX to fill "
            "them with that palette index."
            % (len(holes), shown, ", ..." if len(holes) > 6 else ""))

    return (struct.pack("<4h", *origin) +
            struct.pack("<6H", width, height, x0, y0, x1, y1) +
            struct.pack("<HH", unknown14, unknown16) +
            bytes([unknown18]) + bytes(out))


def header_meta(d):
    """The fields `encode` cannot derive from pixels, for the manifest."""
    return {"origin": d["origin"], "unknown14": d["unknown14"],
            "unknown16": d["unknown16"], "unknown18": d["unknown18"]}
