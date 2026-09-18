"""GIF-style LZW, both directions, framed in length-prefixed sub-blocks.

`CVPC` is not a GIF file, but its codestream uses GIF's LZW parameters exactly
-- codes packed LSB-first, initial width `bpp + 1`, clear code `1 << bpp`, end
code `+ 1`, first free entry `+ 2`, width growing to 12.  That is not a guess:
the game's decompressor is 1,002 bytes of hand-written 386 assembly at
1088:0000 which allocates three 4,096-entry WORD tables (prefix / suffix /
length), computes `2 << bpp`, `+2` and `+4` as word offsets and `bpp + 1` as
the initial code width.  The developers left GIF loader strings and
`..\\resource\\logo.gif` build paths in the same binary: the art was authored
as GIF and converted at build time by people who already had GIF LZW in hand.

The encoder mirrors the shipped decoder's state machine step for step,
including *when* it widens a code -- the decoder's dictionary lags the
encoder's by one entry, so widening on the encoder's own counter would desync
the stream by one code.  `round_trip_ok` below is not decoration: the encoder
is checked against this module's decoder, which is itself checked against all
96 shipped canvases.
"""


def deblock(data):
    """Unframe the sub-blocks: [len][len bytes][len][len bytes]...

    From the game's decompressor at 1088:0108 -- when the current block runs
    out it reads one length byte and sets block_end = ptr + len.  There is no
    zero-length terminator; the LZW end code is what stops the stream.
    """
    out, i = bytearray(), 0
    while i < len(data):
        n = data[i]
        i += 1
        out += data[i:i + n]
        i += n
        if n == 0:
            break
    return bytes(out)


def enblock(data):
    out = bytearray()
    for i in range(0, len(data), 255):
        chunk = data[i:i + 255]
        out.append(len(chunk))
        out += chunk
    return bytes(out)


def decode(data, bpp, expected):
    """Unframed codestream -> pixel bytes.  Stops at the end code."""
    clear, end = 1 << bpp, (1 << bpp) + 1
    width = bpp + 1
    dic = {i: bytes([i]) for i in range(clear)}
    nxt = end + 1
    out = bytearray()
    acc = nbits = 0
    prev = None
    for byte in data:
        acc |= byte << nbits                      # LSB-first packing
        nbits += 8
        while nbits >= width:
            code = acc & ((1 << width) - 1)
            acc >>= width
            nbits -= width
            if code == clear:
                dic = {i: bytes([i]) for i in range(clear)}
                nxt, width, prev = end + 1, bpp + 1, None
                continue
            if code == end:
                return bytes(out)
            if code in dic:
                entry = dic[code]
            elif code == nxt and prev is not None:
                entry = prev + prev[:1]
            else:
                raise ValueError("invalid LZW code %d (next free %d)" % (code, nxt))
            out += entry
            if prev is not None:
                dic[nxt] = prev + entry[:1]
                nxt += 1
                if nxt > (1 << width) - 1 and width < 12:
                    width += 1
            prev = entry
            if len(out) >= expected:
                return bytes(out)
    return bytes(out)


class _Writer:
    def __init__(self):
        self.out = bytearray()
        self.acc = 0
        self.nbits = 0

    def put(self, code, width):
        self.acc |= code << self.nbits
        self.nbits += width
        while self.nbits >= 8:
            self.out.append(self.acc & 0xFF)
            self.acc >>= 8
            self.nbits -= 8

    def finish(self):
        if self.nbits:
            self.out.append(self.acc & 0xFF)
            self.acc = self.nbits = 0
        return bytes(self.out)


def encode(pixels, bpp):
    """Pixel bytes -> unframed codestream that this module's decoder reads back.

    The width bookkeeping tracks the DECODER's dictionary counter, not the
    encoder's, because that is the one the bit width is agreed on.
    """
    clear, end = 1 << bpp, (1 << bpp) + 1
    first = end + 1
    w = _Writer()

    state = {"width": bpp + 1, "dec_nxt": first, "since_clear": 0}

    def emit(code):
        w.put(code, state["width"])
        state["since_clear"] += 1
        if state["since_clear"] >= 2:              # the decoder adds an entry
            state["dec_nxt"] += 1                  # from the second code on
            if state["dec_nxt"] > (1 << state["width"]) - 1 and state["width"] < 12:
                state["width"] += 1

    def reset():
        state["width"] = bpp + 1
        state["dec_nxt"] = first
        state["since_clear"] = 0

    emit(clear)
    reset()
    if not pixels:
        emit(end)
        return w.finish()

    dic = {}
    nxt = first
    prev = pixels[0:1]
    for i in range(1, len(pixels)):
        c = pixels[i:i + 1]
        cand = prev + c
        code = dic.get(cand)
        if code is not None:
            prev = cand
            continue
        emit(dic.get(prev, prev[0]) if len(prev) > 1 else prev[0])
        if nxt < 4096:
            dic[cand] = nxt
            nxt += 1
        if nxt >= 4096:                            # the tables are 4,096 deep
            emit(clear)
            reset()
            dic = {}
            nxt = first
        prev = c
    emit(dic.get(prev, prev[0]) if len(prev) > 1 else prev[0])
    emit(end)
    return w.finish()


def round_trip_ok(pixels, bpp):
    return decode(encode(pixels, bpp), bpp, len(pixels)) == pixels
