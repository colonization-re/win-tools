"""FLIC -- a stock Autodesk FLC animation (magic 0xAF12), not a private format.

The single FLIC resource (COLDATA7.DLL id 9600) is 640x480, 8bpp, 66 frames at
71 ms: the Declaration-of-Independence celebration outside Independence Hall,
which pairs it with WINFLC.WAV.  Nothing below is Colonization-specific; it is
the published FLC layout.

Chunk types read: 4 COLOR_256, 11 COLOR_64, 7 DELTA_FLC, 12 DELTA_FLI,
13 BLACK, 15 BYTE_RUN, 16 FLI_COPY, 18 PSTAMP (skipped).

`encode` writes the simplest legal file that reproduces the frames: one
COLOR_256 chunk whenever the palette changes and one BYTE_RUN keyframe per
frame -- no inter-frame deltas.  That is correct and lossless, and it is
BIGGER than the shipped animation, which does use deltas.  The round trip is
checked against this module's own reader; it has NOT been checked by playing
the result in the game, and the tools say so where they offer it.
"""
import struct

FLC_MAGIC, FLI_MAGIC = 0xAF12, 0xAF11
FRAME_MAGIC, PREFIX_MAGIC = 0xF1FA, 0xF100


class FlicError(Exception):
    pass


def header(b):
    size, magic, frames, w, h, depth, flags, speed = struct.unpack_from("<IHHHHHHI", b, 0)
    if magic not in (FLC_MAGIC, FLI_MAGIC):
        raise FlicError("not a FLIC: magic %#06x" % magic)
    return {"size": size, "magic": magic, "frames": frames, "width": w,
            "height": h, "depth": depth, "flags": flags, "speed_ms": speed,
            "oframe1": struct.unpack_from("<I", b, 0x50)[0],
            "oframe2": struct.unpack_from("<I", b, 0x54)[0]}


# -- reading ---------------------------------------------------------------- #

def _colour(b, p, pal, shift):
    npkt = struct.unpack_from("<H", b, p)[0]
    p += 2
    idx = 0
    for _ in range(npkt):
        idx += b[p]
        cnt = b[p + 1] or 256
        p += 2
        for _ in range(cnt):
            if idx < 256:
                pal[idx] = (b[p] << shift, b[p + 1] << shift, b[p + 2] << shift)
            p += 3
            idx += 1
    return p


def _byte_run(b, p, fb, w, h):
    for y in range(h):
        p += 1                                  # declared packet count, ignored
        x = 0
        while x < w:
            n = struct.unpack_from("<b", b, p)[0]
            p += 1
            if n >= 0:
                fb[y * w + x:y * w + x + n] = bytes([b[p]]) * n
                p += 1
            else:
                n = -n
                fb[y * w + x:y * w + x + n] = b[p:p + n]
                p += n
            x += n
        if x != w:
            raise FlicError("BYTE_RUN line %d produced %d of %d pixels" % (y, x, w))
    return p


def _delta_fli(b, p, fb, w):
    y, lines = struct.unpack_from("<HH", b, p)
    p += 4
    for _ in range(lines):
        npkt = b[p]
        p += 1
        x = 0
        for _ in range(npkt):
            x += b[p]
            n = struct.unpack_from("<b", b, p + 1)[0]
            p += 2
            if n >= 0:
                fb[y * w + x:y * w + x + n] = b[p:p + n]
                p += n
                x += n
            else:
                n = -n
                fb[y * w + x:y * w + x + n] = bytes([b[p]]) * n
                p += 1
                x += n
        y += 1
    return p


def _delta_flc(b, p, fb, w):
    lines = struct.unpack_from("<H", b, p)[0]
    p += 2
    y = 0
    while lines:
        op = struct.unpack_from("<H", b, p)[0]
        p += 2
        kind = op & 0xC000
        if kind == 0xC000:                      # skip lines (op is negative)
            y += -struct.unpack_from("<h", b, p - 2)[0]
        elif kind == 0x8000:                    # odd width: last pixel of line
            fb[y * w + w - 1] = op & 0xFF
        elif kind == 0x0000:                    # op = packet count for this line
            x = 0
            for _ in range(op):
                x += b[p]
                n = struct.unpack_from("<b", b, p + 1)[0]
                p += 2
                if n >= 0:
                    fb[y * w + x:y * w + x + n * 2] = b[p:p + n * 2]
                    p += n * 2
                    x += n * 2
                else:
                    n = -n
                    fb[y * w + x:y * w + x + n * 2] = b[p:p + 2] * n
                    p += 2
                    x += n * 2
            y += 1
            lines -= 1
        else:
            raise FlicError("DELTA_FLC opcode %#06x" % op)
    return p


def frames(b, validate=True):
    """Yield {index, pixels, palette, delay_ms} for every frame, in order."""
    hdr = header(b)
    w, h = hdr["width"], hdr["height"]
    fb = bytearray(w * h)
    pal = [(0, 0, 0)] * 256
    p = hdr["oframe1"] or 128
    n = 0
    while p + 16 <= len(b) and n < hdr["frames"]:
        fsize, magic, nchunks, delay = struct.unpack_from("<IHHH", b, p)
        if magic == PREFIX_MAGIC:
            p += fsize
            continue
        if magic != FRAME_MAGIC:
            raise FlicError("frame %d: magic %#06x at %#x" % (n, magic, p))
        end, q = p + fsize, p + 16
        for _ in range(nchunks):
            csize, ctype = struct.unpack_from("<IH", b, q)
            cend, c = q + csize, q + 6
            if ctype == 4:
                c = _colour(b, c, pal, 0)
            elif ctype == 11:
                c = _colour(b, c, pal, 2)
            elif ctype == 7:
                c = _delta_flc(b, c, fb, w)
            elif ctype == 12:
                c = _delta_fli(b, c, fb, w)
            elif ctype == 13:
                fb = bytearray(w * h)
                c = cend
            elif ctype == 15:
                c = _byte_run(b, c, fb, w, h)
            elif ctype == 16:
                fb[:] = b[c:c + w * h]
                c = cend
            elif ctype == 18:                   # postage-stamp preview
                c = cend
            else:
                raise FlicError("frame %d: unknown chunk type %d" % (n, ctype))
            if validate and c > cend:
                raise FlicError("frame %d: chunk %d read %d of %d" % (n, ctype, c - q, csize))
            q = cend
        if validate and q != end:
            raise FlicError("frame %d: chunks ended at %d, frame ends %d" % (n, q, end))
        yield {"index": n, "pixels": bytes(fb), "palette": list(pal),
               "delay_ms": delay or hdr["speed_ms"]}
        p, n = end, n + 1


# -- writing ---------------------------------------------------------------- #

def _rle_row(row):
    out = bytearray([0])                        # packet count, patched below
    x, npkt, w = 0, 0, len(row)
    while x < w:
        run = 1
        while x + run < w and row[x + run] == row[x] and run < 127:
            run += 1
        if run >= 3:
            out += bytes([run, row[x]])
            x += run
        else:
            lit = 0
            while (x + lit < w and lit < 127 and
                   not (x + lit + 2 < w and row[x + lit] == row[x + lit + 1] == row[x + lit + 2])):
                lit += 1
            lit = lit or 1
            out += bytes([(256 - lit) & 0xFF]) + row[x:x + lit]
            x += lit
        npkt += 1
    out[0] = npkt & 0xFF
    return bytes(out)


def _chunk(ctype, data):
    return struct.pack("<IH", len(data) + 6, ctype) + data


def _colour_chunk(pal):
    data = struct.pack("<HBB", 1, 0, 0)         # one packet, skip 0, count 0 = 256
    data += b"".join(bytes(c[:3]) for c in pal)
    return _chunk(4, data)


def encode(frame_list, width, height, speed_ms):
    """[{pixels, palette, delay_ms}] -> FLC bytes, all keyframes."""
    if not frame_list:
        raise FlicError("no frames")
    bodies, prev_pal = [], None
    for f in frame_list:
        px = f["pixels"]
        if len(px) != width * height:
            raise FlicError("frame %d has %d pixels, expected %d"
                            % (f.get("index", -1), len(px), width * height))
        chunks = []
        if f["palette"] != prev_pal:
            chunks.append(_colour_chunk(f["palette"]))
            prev_pal = list(f["palette"])
        run = bytearray()
        for y in range(height):
            run += _rle_row(px[y * width:(y + 1) * width])
        chunks.append(_chunk(15, bytes(run)))
        body = b"".join(chunks)
        delay = f.get("delay_ms") or speed_ms
        bodies.append(struct.pack("<IHHH", len(body) + 16, FRAME_MAGIC,
                                  len(chunks), delay if delay != speed_ms else 0)
                      + b"\x00" * 6 + body)

    total = 128 + sum(len(x) for x in bodies)
    head = bytearray(128)
    struct.pack_into("<IHHHHHHI", head, 0, total, FLC_MAGIC, len(bodies),
                     width, height, 8, 0, speed_ms)
    struct.pack_into("<HH", head, 0x26, 1, 1)               # aspect 1:1
    struct.pack_into("<II", head, 0x50, 128, 128 + len(bodies[0]))
    return bytes(head) + b"".join(bodies)
