# colwin

Tools for reading and writing the asset files of **Sid Meier's Colonization for
Windows** (1995). Pure Python 3, stdlib only.

These pages are the reference: what is in each file the game installs, how each
format is laid out, and — for the map — how the game draws it. The tools
themselves are in
[the repository](https://github.com/colonization-re/win-tools); the research the
formats come from is in
[win-decomp](https://github.com/colonization-re/win-decomp).

## Start here

| | |
| --- | --- |
| [**Using the tool**](usage.md) | the seven commands, every option, and what each one prints |
| [**What is in each file**](files.md) | all 64 files of an install, and what each one holds |
| [**Formats**](formats/) | the layouts, one page each |
| [**Map preview**](map-preview.md) | drawing a `.SAV` or `.MP` as one PNG, and what each layer rests on |
| [**Palettes**](palettes.md) | why sprite colours are not stored anywhere, and what to do about it |
| [**Editing**](editing.md) | extracting, changing art or text, and putting it back |

## The rule these tools follow

Where something is established, it is stated with its evidence — a call site, a
loader, a measured count. Where it is not, it is marked `UNKNOWN` and the bytes
are carried through untouched rather than given an invented meaning. Four fields
of the sprite header are like that, and they are copied on every rebuild.

That is also why the tools can prove themselves: re-encoding every extracted
asset reproduces 1,701 of 1,797 resources **byte for byte**, the remaining 96
reproduce identical pixels and palettes, and all 13 modules rebuild
byte-identical when nothing has been edited.

The map preview follows the same rule in a different way. It has no renderer of
its own: it replays the game's own square-painting routine, layer by layer, and
every cell it cuts out of the tile sheet is the rectangle and key colour the
game's start-up code uses. Where it draws a square differently from the game,
that is a bug in the reading and there is a test for it.

The numbers on these pages are checked the same way. `tests/test_docs.py`
re-derives all 42 of them from an install and fails if a page has drifted.
