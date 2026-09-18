"""Win16 NE containers: read the resource table, and write a new one back.

The eleven data DLLs and COLONIZE.EXE all have the same shape, which is what
makes rebuilding them safe:

    [ NE header + segments ] [ resources, one contiguous run, to EOF ]

Measured over all twelve modules: `overlap_bytes = 0`, `contiguous_runs = 1`,
and the single gap is the front one.  So a rebuild never has to move a segment
or touch a relocation -- it re-lays the tail and patches the 12-byte table
entries, which live in the header and do not move.

Resource offsets and lengths in the table are stored in units of
`1 << align_shift` (512 bytes in every module here), so every resource body is
padded to that boundary.  The padding is not content; `Resource.body` trims it
and `Resource.raw` keeps it.
"""
import struct

# Standard Win16 resource type ordinals.  Private types (SPRT, CVPC, CTAB,
# FLIC, TEXT, ...) are not in this table: their names come from RT_NAMETABLE.
STD_TYPES = {
    1: "RT_CURSOR", 2: "RT_BITMAP", 3: "RT_ICON", 4: "RT_MENU",
    5: "RT_DIALOG", 6: "RT_STRING", 7: "RT_FONTDIR", 8: "RT_FONT",
    9: "RT_ACCELERATOR", 10: "RT_RCDATA", 11: "RT_MESSAGETABLE",
    12: "RT_GROUP_CURSOR", 14: "RT_GROUP_ICON", 15: "RT_NAMETABLE",
    16: "RT_VERSION",
}
RT_NAMETABLE = 15


class NotAnNEFile(Exception):
    pass


class Resource:
    __slots__ = ("type_ord", "type_name", "id", "id_raw", "flags", "offset",
                 "length", "entry_off", "_data", "name")

    def __init__(self, type_ord, id_, id_raw, flags, offset, length, entry_off, data):
        self.type_ord = type_ord
        self.id = id_
        self.id_raw = id_raw
        self.flags = flags
        self.offset = offset        # byte offset in the file
        self.length = length        # declared length, INCLUDING alignment padding
        self.entry_off = entry_off  # where the 12-byte table entry lives
        self._data = data           # exactly `length` bytes
        self.type_name = STD_TYPES.get(type_ord, "0x%04x" % type_ord)
        self.name = ""              # from RT_NAMETABLE, "" when unnamed

    @property
    def raw(self):
        """The declared bytes, padding included."""
        return self._data

    @property
    def body(self):
        """The content: the declared bytes up to the last non-zero one.

        Every payload in these modules is NUL-padded to the 512-byte resource
        alignment, and no shipped payload ends on a NUL that matters -- the
        decoders all verify they consume exactly up to this point.
        """
        end = len(self._data)
        while end and not self._data[end - 1]:
            end -= 1
        return self._data[:end]

    @property
    def key(self):
        """Stable identity of a resource inside its module."""
        return (self.type_name, self.id)

    def label(self):
        return "%s/%d%s" % (self.type_name, self.id,
                            "_" + self.name if self.name else "")

    def __repr__(self):
        return "<Resource %s %d bytes @%#x>" % (self.label(), self.length, self.offset)


class Module:
    """One NE file, parsed far enough to put resources back."""

    def __init__(self, path, data):
        self.path = path
        self.data = data
        self.align_shift = 0
        self.resources = []
        self._parse()
        self._read_nametable()

    @classmethod
    def load(cls, path):
        with open(path, "rb") as f:
            return cls(path, f.read())

    # -- reading ---------------------------------------------------------- #

    def _parse(self):
        b = self.data
        if b[:2] != b"MZ":
            raise NotAnNEFile("%s: no MZ signature" % self.path)
        ne = struct.unpack_from("<I", b, 0x3C)[0]
        if b[ne:ne + 2] != b"NE":
            raise NotAnNEFile("%s: no NE signature at %#x" % (self.path, ne))
        self.ne_off = ne
        rt = struct.unpack_from("<H", b, ne + 0x24)[0]
        rn = struct.unpack_from("<H", b, ne + 0x26)[0]
        if rt == rn:
            return                                    # no resource table
        p = ne + rt
        self.align_shift = struct.unpack_from("<H", b, p)[0]
        p += 2
        while True:
            rtype = struct.unpack_from("<H", b, p)[0]
            if rtype == 0:
                break
            count = struct.unpack_from("<H", b, p + 2)[0]
            p += 8
            for _ in range(count):
                off, ln, flags, rid, _h, _u = struct.unpack_from("<6H", b, p)
                boff = off << self.align_shift
                blen = ln << self.align_shift
                self.resources.append(Resource(
                    rtype & 0x7FFF, rid & 0x7FFF, rid, flags,
                    boff, blen, p, b[boff:boff + blen]))
                p += 12
        self.res_table_end = p + 2

    def _read_nametable(self):
        """RT_NAMETABLE carries the developers' own name for every resource.

        Undocumented by Microsoft; the layout below is verified by exact-length
        agreement on every entry of every module (`6 + len(type)+1 +
        len(name)+1 == cbEntry`).
        """
        blob = None
        for r in self.resources:
            if r.type_ord == RT_NAMETABLE:
                blob = r.raw
                break
        if blob is None:
            return
        names, i = {}, 0
        while i + 6 <= len(blob):
            cb, wtype, wid = struct.unpack_from("<HHH", blob, i)
            if cb < 6 or i + cb > len(blob):
                break                                  # trailing padding
            parts = blob[i + 6:i + cb].split(b"\x00")
            tname = parts[0].decode("latin-1") if parts else ""
            rname = parts[1].decode("latin-1") if len(parts) > 1 else ""
            names[(wtype & 0x7FFF, wid & 0x7FFF)] = (tname, rname)
            i += cb
        for r in self.resources:
            hit = names.get((r.type_ord, r.id))
            if hit:
                if hit[0]:
                    r.type_name = hit[0]
                r.name = hit[1]

    def by_key(self):
        return {r.key: r for r in self.resources}

    # -- writing ---------------------------------------------------------- #

    def rebuild(self, replacements=None):
        """Return new file bytes with `replacements` ({key: body}) substituted.

        Resources keep their original order in the file.  Anything not replaced
        is copied with its padding intact, so a rebuild with no replacements
        reproduces the input byte for byte -- which `colwin verify` checks.
        """
        replacements = replacements or {}
        if not self.resources:
            if replacements:
                raise ValueError("%s has no resource table" % self.path)
            return self.data

        unit = 1 << self.align_shift
        ordered = sorted(self.resources, key=lambda r: r.offset)
        prefix_end = ordered[0].offset
        for a, z in zip(ordered, ordered[1:]):
            if a.offset + a.length > z.offset:
                raise ValueError("%s: resources overlap at %#x" % (self.path, z.offset))
        if prefix_end % unit:
            raise ValueError("%s: resource run starts unaligned at %#x"
                             % (self.path, prefix_end))

        out = bytearray(self.data[:prefix_end])
        table = bytearray(self.data[:prefix_end])   # patched in place below
        for r in ordered:
            body = replacements.get(r.key)
            if body is None:
                chunk = r.raw                        # verbatim, padding and all
            else:
                pad = (-len(body)) % unit
                chunk = bytes(body) + b"\x00" * pad
                if not chunk:
                    chunk = b"\x00" * unit           # a resource may not be 0 long
            off, ln = len(out), len(chunk)
            if off >> self.align_shift > 0xFFFF:
                raise ValueError("%s: resource offset %#x exceeds the 16-bit "
                                 "field at alignment %d" % (self.path, off, unit))
            struct.pack_into("<HH", table, r.entry_off,
                             off >> self.align_shift, ln >> self.align_shift)
            out += chunk
        out[:prefix_end] = table
        return bytes(out)
