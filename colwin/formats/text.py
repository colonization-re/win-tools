"""TEXT -- the game's authored text, under the developers' own resource names.

Plain 8-bit text, LF-separated, with a small directive header:

    @width=380          dialog width in pixels
    @default=1          index of the default answer
    @x= / @y=           explicit dialog placement
    Shall we indeed {abandon} our %STRING0 colony, ...

    Yes, it is God's will.
    Never! That would be folly.

`{...}` is emphasis (1,125 opens and 1,125 closes across the corpus, perfectly
balanced), `^` delimits sections, `%STRING0..4` / `%NUMBER0..3` / `%COUNTRY`
are runtime substitutions, and byte **0xA4** is the game's gold/coin glyph --
in cp1252 that is the currency sign, so the editable file shows it as `¤` and
it goes back as 0xA4.

Encoding is cp1252 in and out.  Anything an editor introduces that cp1252
cannot hold is refused by name rather than silently replaced, because a
mangled byte here is a mangled string in a shipped dialog.
"""

CODEC = "cp1252"


class TextError(Exception):
    pass


def decode(body):
    """Resource bytes -> str with LF line endings."""
    return body.decode(CODEC, "strict").replace("\r\n", "\n")


def encode(s):
    """str -> resource bytes.  CRLF is normalised to LF, as the game stores it."""
    s = s.replace("\r\n", "\n")
    try:
        return s.encode(CODEC, "strict")
    except UnicodeEncodeError as e:
        bad = s[e.start:e.end]
        line = s.count("\n", 0, e.start) + 1
        raise TextError("line %d: %r cannot be written in %s, which is the "
                        "encoding the game reads. Replace it with a character "
                        "that can." % (line, bad, CODEC))


def directives(s):
    """The leading @name=value header, as a dict, in order."""
    out = {}
    for line in s.split("\n"):
        if not line.startswith("@"):
            break
        if "=" in line:
            k, v = line[1:].split("=", 1)
            out[k.strip()] = v.strip()
    return out
