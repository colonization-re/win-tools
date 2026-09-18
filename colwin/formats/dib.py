"""Windows DIBs: RT_BITMAP round-trips; RT_ICON and RT_CURSOR are read only.

RT_BITMAP in this game is six 32x32 4-bpp bitmaps with a BITMAPINFOHEADER --
ordinary indexed images carrying their own palette, so they round-trip the same
way a CVPC does.

RT_ICON (32x64 8-bpp) and RT_CURSOR (4-byte hotspot, then 32x64 1-bpp) store
the colour image and a 1-bpp AND mask stacked in one DIB of double height.
They decode here for viewing, and the toolkit carries the original bytes
through on a rebuild rather than re-encoding them: putting an edited alpha
channel back into an AND mask plus an indexed image is a lossy choice nobody
has asked this toolkit to make on their behalf.
"""
import struct

BI_RGB = 0


class DibError(Exception):
    pass


def _rows(body, off, w, h, bpp):
    """Bottom-up, 4-byte-padded scanlines -> top-down, one byte per pixel."""
    stride = ((w * bpp + 31) // 32) * 4
    per = 8 // bpp if bpp < 8 else 1
    mask = (1 << bpp) - 1
    out = bytearray(w * h)
    for y in range(h):
        src = off + (h - 1 - y) * stride
        row = body[src:src + stride]
        if len(row) < stride:
            raise DibError("scanline %d truncated (%d of %d bytes)" % (y, len(row), stride))
        if bpp == 8:
            out[y * w:(y + 1) * w] = row[:w]
        else:
            for x in range(w):
                byte = row[x // per]
                shift = 8 - bpp * (x % per + 1)
                out[y * w + x] = (byte >> shift) & mask
    return bytes(out)


def _pack_rows(pixels, w, h, bpp):
    stride = ((w * bpp + 31) // 32) * 4
    per = 8 // bpp if bpp < 8 else 1
    out = bytearray()
    for y in range(h - 1, -1, -1):
        row = bytearray(stride)
        line = pixels[y * w:(y + 1) * w]
        if bpp == 8:
            row[:w] = line
        else:
            for x, v in enumerate(line):
                shift = 8 - bpp * (x % per + 1)
                row[x // per] |= (v & ((1 << bpp) - 1)) << shift
        out += row
    return bytes(out)


def decode_bitmap(body):
    hs = struct.unpack_from("<I", body, 0)[0]
    if hs == 12:                                        # BITMAPCOREHEADER
        w, h, planes, bpp = struct.unpack_from("<HHHH", body, 4)
        comp, used, psize = BI_RGB, 0, 3
        xppm = yppm = important = 0
    elif hs >= 40:                                      # BITMAPINFOHEADER
        w, h, planes, bpp, comp, _sz, xppm, yppm, used, important = \
            struct.unpack_from("<iiHHIIiiII", body, 4)
        psize = 4
    else:
        raise DibError("header size %d is neither a core nor an info header" % hs)
    if comp != BI_RGB:
        raise DibError("compression %d; only uncompressed DIBs are handled" % comp)
    if bpp not in (1, 4, 8):
        raise DibError("%d bits per pixel; only indexed DIBs are handled" % bpp)
    ncol = used or (1 << bpp)
    pal = []
    for i in range(ncol):
        o = hs + i * psize
        pal.append((body[o + 2], body[o + 1], body[o]))  # stored BGR(A)
    off = hs + ncol * psize
    return {"width": w, "height": abs(h), "bpp": bpp, "palette": pal,
            "pixels": _rows(body, off, w, abs(h), bpp), "header_size": hs,
            "colours_used": used, "top_down": h < 0,
            "x_ppm": xppm, "y_ppm": yppm, "colours_important": important}


def encode_bitmap(pixels, w, h, bpp, palette, header_size=40, colours_used=0,
                  x_ppm=0, y_ppm=0, colours_important=0):
    if len(pixels) != w * h:
        raise DibError("%d pixels for a %dx%d bitmap" % (len(pixels), w, h))
    ncol = colours_used or (1 << bpp)
    if len(palette) > ncol:
        raise DibError("palette has %d entries, %d bpp allows %d" % (len(palette), bpp, ncol))
    pal = list(palette) + [(0, 0, 0)] * (ncol - len(palette))
    bits = _pack_rows(pixels, w, h, bpp)
    if header_size == 12:
        head = struct.pack("<IHHHH", 12, w, h, 1, bpp)
        table = b"".join(bytes((b, g, r)) for r, g, b in pal)
    else:
        head = struct.pack("<IiiHHIIiiII", 40, w, h, 1, bpp, BI_RGB,
                           len(bits), x_ppm, y_ppm, colours_used, colours_important)
        table = b"".join(bytes((b, g, r, 0)) for r, g, b in pal)
    return head + table + bits


def decode_icon(body, cursor=False):
    """-> {width, height, rgba} for an icon or cursor, AND mask applied as alpha.

    The header declares one bit depth and a DOUBLE height, but only the top
    half is at that depth: the bottom half is the 1-bpp AND mask.  Reading the
    whole thing at the declared depth is what makes an icon look truncated --
    the 32x64 8-bpp icons here store 32x32x8 plus 32x32x1 = 1,152 bytes, which
    is exactly the biSizeImage they declare.
    """
    off = 4 if cursor else 0
    hot = struct.unpack_from("<HH", body, 0) if cursor else None
    b = body[off:]
    hs = struct.unpack_from("<I", b, 0)[0]
    if hs == 12:
        w, h2, _planes, bpp = struct.unpack_from("<HHHH", b, 4)
        used, psize = 0, 3
    else:
        w, h2, _planes, bpp, comp, _sz, _x, _y, used, _i = \
            struct.unpack_from("<iiHHIIiiII", b, 4)
        psize = 4
        if comp != BI_RGB:
            raise DibError("compression %d in an icon" % comp)
    h = abs(h2) // 2
    ncol = used or (1 << bpp)
    pal = [(b[hs + i * psize + 2], b[hs + i * psize + 1], b[hs + i * psize])
           for i in range(ncol)]
    off_xor = hs + ncol * psize
    colour = _rows(b, off_xor, w, h, bpp)
    stride_xor = ((w * bpp + 31) // 32) * 4
    mask = _rows(b, off_xor + stride_xor * h, w, h, 1)

    rgba = bytearray(w * h * 4)
    for i in range(w * h):
        r, g, bl = pal[colour[i]] if colour[i] < len(pal) else (0, 0, 0)
        o = i * 4
        rgba[o], rgba[o + 1], rgba[o + 2] = r, g, bl
        rgba[o + 3] = 0 if mask[i] else 255
    return {"width": w, "height": h, "rgba": bytes(rgba), "hotspot": hot,
            "bpp": bpp, "palette": pal}
