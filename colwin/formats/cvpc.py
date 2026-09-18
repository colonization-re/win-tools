"""CVPC -- a full canvas image: big-endian header, own palette, LZW pixels.

    0x00  WORD  BE   width
    0x02  WORD  BE   height
    0x04  BYTE       bpp / LZW minimum code size (3, 5, 6, 7, 8 observed)
    0x05  BYTE       pixel value mask, always exactly (1 << bpp) - 1
    0x06  RGB * 2^bpp   palette (entry 0 is white)
    6 + 3*2^bpp      LZW codestream in sub-blocks

The palette offset is not a reading of the bytes -- an early attempt took
`ff ff ff` for padding and decoded 14 pixels out of 307,200.  The call site
settled it: 1068:4c05 computes the decompressor's source as
`base + (mask + 1) * 3 + 6` and passes the palette as `base + 6`, so entry 0 is
that white triple.  With the three-byte correction the decode went from 0/96 to
96/96.

Unlike SPRT, a CVPC carries its own complete palette, so editing one is
self-contained: the PNG's PLTE is the real thing, and writing back only has to
map the colours in the edited image onto entries of the palette it is given.
"""
import struct

from . import lzw


class CvpcError(Exception):
    pass


def decode(body):
    if len(body) < 6:
        raise CvpcError("too short: %d bytes" % len(body))
    w, h = struct.unpack_from(">HH", body, 0)
    bpp, mask = body[4], body[5]
    if mask != (1 << bpp) - 1:
        raise CvpcError("mask %#x does not match bpp %d (expected %#x)"
                        % (mask, bpp, (1 << bpp) - 1))
    npal = 1 << bpp
    need = 6 + npal * 3
    if len(body) < need:
        raise CvpcError("palette of %d entries needs %d bytes, have %d"
                        % (npal, need, len(body)))
    palette = [tuple(body[6 + i * 3:9 + i * 3]) for i in range(npal)]
    pixels = lzw.decode(lzw.deblock(body[need:]), bpp, w * h)
    if len(pixels) != w * h:
        raise CvpcError("decoded %d pixels, header declares %dx%d = %d"
                        % (len(pixels), w, h, w * h))
    return {"width": w, "height": h, "bpp": bpp, "palette": palette,
            "pixels": pixels}


def encode(pixels, width, height, bpp, palette):
    if len(pixels) != width * height:
        raise CvpcError("%d pixels for a %dx%d image" % (len(pixels), width, height))
    npal = 1 << bpp
    if len(palette) > npal:
        raise CvpcError("palette has %d entries, bpp %d allows %d"
                        % (len(palette), bpp, npal))
    hi = max(pixels) if pixels else 0
    if hi >= npal:
        raise CvpcError("pixel index %d does not fit in %d bits; the image needs "
                        "more colours than this canvas's format allows" % (hi, bpp))
    pal = list(palette) + [(0, 0, 0)] * (npal - len(palette))
    head = struct.pack(">HH", width, height) + bytes([bpp, npal - 1])
    head += b"".join(bytes(c[:3]) for c in pal)
    return head + lzw.enblock(lzw.encode(pixels, bpp))


def fits_bpp(n_colours):
    """Smallest shipped bpp that holds `n_colours` distinct entries."""
    for b in (3, 5, 6, 7, 8):
        if n_colours <= (1 << b):
            return b
    raise CvpcError("%d colours exceed the 256 this format can hold" % n_colours)
