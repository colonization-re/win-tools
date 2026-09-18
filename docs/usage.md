# Using colwin

`colwin` is a single command-line program with six subcommands. It reads an
installed copy of the game, writes the assets out as ordinary files, and puts
them back into a fresh copy of the install. It never writes to the install it
read from.

## Installing it

There is nothing to install. `colwin` is stdlib-only Python by design — clone
the repository and run it out of the checkout, next to a copy of the game.

### What you need

**Python 3.9 or newer, and nothing else.** No dependencies, no build step, no
virtualenv, no `pip install`. The tools are tested on 3.9, 3.11 and 3.13.

```sh
python3 --version
```

**A retail install of *Colonization for Windows* (1995).** This repository does
not contain the game and cannot get it for you. Point the tools at the directory
the installer produced — the one holding `COLONIZE.EXE`, the `COLDATA*.DLL`
files and the `.WAV`s. [What is in each file](files.md) describes it.

The install is only ever read. Everything written goes to the workspace and
output directories you name on the command line, and nowhere else — no config
file, no cache, nothing in `site-packages`.

### Getting it

```sh
git clone https://github.com/colonization-re/win-tools
cd win-tools
python3 colwin.py --version
```

That last line should print `colwin` and a version number. If it does, you are
done: everything on this page works from here.

### Ways to run it

| | |
| --- | --- |
| `python3 colwin.py ...` | from the checkout. Every example on this page is written this way |
| `./colwin.py ...` | the same thing; the file is executable and carries a `#!/usr/bin/env python3` line |
| `python3 /path/to/win-tools/colwin.py ...` | from anywhere, by absolute path. `colwin.py` puts its own directory on `sys.path`, so no environment variable is needed |
| `PYTHONPATH=/path/to/win-tools python3 -m colwin ...` | as a module, from anywhere the checkout is importable |

On Windows, use `py -3` in place of `python3`.

If you want it on your `PATH`, symlink or alias `colwin.py` — it does not care
where it is called from, only where it lives:

```sh
ln -s "$PWD/colwin.py" ~/.local/bin/colwin
```

### Updating and removing it

`git pull` updates it. To remove it, delete the directory; workspaces and built
installs you made are ordinary directories elsewhere and are unaffected.

## A session

```sh
python3 colwin.py list    ~/games/colonization          # look before you touch
python3 colwin.py extract ~/games/colonization --out=ws
#  ... edit ws/sprites/**/*.png and ws/text/**/*.txt ...
python3 colwin.py status  ws                            # what did I change?
python3 colwin.py build   ws --out=patched              # a complete install
```

`ws` is a *workspace*: the extracted files plus `colwin.json`, a manifest saying
where each one came from and what its bytes hashed to. Every command after
`extract` takes the workspace directory, not the game directory — the game it
came from is recorded in the manifest. [Editing](editing.md) covers what the
workspace holds and what you can do to it; this page is the commands.

---

## `list` — what is in a module, or a whole install

```sh
python3 colwin.py list ~/games/colonization
python3 colwin.py list ~/games/colonization/COLDATA5.DLL
python3 colwin.py list ~/games/colonization/COLDATA5.DLL -v
```

Reads the resource table of every Win16 NE module it is given — a single file,
or every module in a directory — and tallies it by resource type. Nothing is
decoded and nothing is written, so this works on a read-only install.

| Option | |
| --- | --- |
| `-v`, `--verbose` | one line per resource: type, id, name, size |

```
COLDATA0.DLL     534 resources,    733696 bytes
    CVPC                 2      418262 bytes
    RT_NAMETABLE         1        6394 bytes
    SPRT               530      115335 bytes
    TEXT                 1         255 bytes
...
total
    CTAB                43       12664 bytes
    CVPC                96     5889615 bytes
    SPRT               915     4441240 bytes
    TEXT               737      143567 bytes
```

The total is printed only when more than one file was read.

## `extract` — make a workspace

```sh
python3 colwin.py extract ~/games/colonization --out=ws
```

| Option | |
| --- | --- |
| `--out=DIR` | **required.** The workspace directory to create |
| `--palette=RULE` | how sprite indices are coloured for viewing; see below |

Every resource whose format is solved comes out as a file you can edit; the rest
are recorded in the manifest and carried through untouched on rebuild. The
counts at the end are per format:

```
extracted to ws
    bitmap         6
    carried       56
    ctab          43
    cvpc          96
    sprt         915
    text         737

ws/README.md tells you what is there and how to edit it.
```

`extract` also writes a `README.md` inside the workspace repeating the rules
that matter while you are editing, so the workspace stands on its own once you
have moved on to a paint program.

### Palette rules

Sprite pixels are indices into a palette that exists nowhere in the game, so the
colours you see are a *view* over the indices — chosen by this flag, and
changeable afterwards without re-extracting. [Palettes](palettes.md) is the long
version.

| `--palette=` | |
| --- | --- |
| `ctab-auto` | **the default.** Each sprite is viewed through the [`CTAB`](formats/ctab.md) table paired with it by resource id — a measured heuristic, labelled a reconstruction wherever it appears |
| `ctab:<id>` | one named table for every sprite, e.g. `--palette=ctab:111` |
| `index` | an identity grey ramp: index *i* is shown as grey *i*. Claims nothing at all |

Whichever you pick, the PNG pixel values are the game's index bytes verbatim.
The rule only decides what those indices look like on screen.

## `status` — what have I changed

```sh
python3 colwin.py status ws
```

Hashes every extracted file and compares it with what `extract` wrote.

```
edited   text/COLDATA0.DLL/666.txt  (TEXT COLDATA0.DLL/666)

1 changed file(s); the rest go back byte for byte.
```

`edited` means the bytes differ; `missing` means the file is gone (a missing
file is an error at build time, not a licence to drop the resource). With
nothing changed it says so and exits 0.

This is worth running before every build, because it is exactly the set of files
that will pass through an encoder — everything else goes back as the original
bytes.

## `build` — write the patched game

```sh
python3 colwin.py build ws --out=patched
```

| Option | |
| --- | --- |
| `--out=DIR` | **required.** Where to write. Not the install you extracted from |
| `--game=DIR` | the original install to copy from, if it is not the one in the manifest |
| `--nearest` | snap colours the palette does not hold to the closest entry it does — **this changes the art** |
| `--fill-holes=INDEX` | fill interior transparent gaps in a sprite row with this palette index |
| `--modules-only` | write just the rebuilt `.DLL`/`.EXE` modules, not a whole install |

```
COLDATA0.DLL     1 resource(s) replaced, +0 bytes

1 changed asset(s) re-encoded; 13 module(s) written to patched
the rest of the game was copied alongside them, so patched is a complete install.
```

By default the output is a complete, playable directory: the 13 rebuilt modules
plus every other file — the `.WAV`s, the map, `README.TXT` — copied alongside
them. `--modules-only` gives you just the modules, for dropping into an install
you already have.

Resources may grow; the line after each module reports the size change. A
module's resource offsets are 16-bit at a 512-byte alignment, which caps it at
33.5 MB, so there is room.

## `verify` — prove the encoders are honest

```sh
python3 colwin.py verify ws
```

| Option | |
| --- | --- |
| `--game=DIR` | the install to compare against, if not the one in the manifest |

Re-encodes every extracted asset — including the ones you have not touched, which
a build would never re-encode — and compares the result with the bytes the game
ships. Then it rebuilds each container with no replacements at all and checks
that the file comes back byte-identical.

```
  format      exact  content     FAIL
  bitmap          6        0        0
  ctab           43        0        0
  cvpc            0       96        0
  sprt          915        0        0
  text          737        0        0
  total        1701       96        0

container rebuild with no replacements: 13/13 modules byte-identical
```

`exact` is byte-for-byte; `content` decoded to identical pixels and palette
through a different encoding — all 96 `CVPC` canvases land there because our
LZW places its own clear codes. Anything in `FAIL` is named, and the command
exits 1.

Run it on an **unedited** workspace. Verify compares against the original game,
so on an edited one your own edits are reported as failures — which is correct,
just not useful:

```
    FAIL text/COLDATA0.DLL/666.txt: re-encode differs in content (258 bytes vs 255)
```

## `palette` — look at, or change, the view

```sh
python3 colwin.py palette ws                  # what am I looking through?
python3 colwin.py palette ws --set=ctab:111   # look through something else
```

| Option | |
| --- | --- |
| `--set=RULE` | re-view every sprite PNG through another rule (`ctab-auto`, `ctab:<id>`, `index`) |

With no `--set`, it prints every view palette in the workspace and where each
band of it came from — including what it does not know:

```
ctab-111       palettes/ctab-111.pal
    0-9,246-255    Windows 3.1 static system colours (established)
    10-141,239-245 UNKNOWN -- grey ramp (index i -> (i,i,i))
    142-238        CTAB 111 payload (RECONSTRUCTION: which CTAB a sprite uses is a measured heuristic)
    (injective)    13 entr(ies) nudged to keep colour -> index exact
```

With `--set`, it rewrites the PLTE chunk of every sprite PNG **and touches no
pixel index**:

```
re-viewed 915 sprite PNGs through `ctab:111`; no pixel index changed
```

So a better palette costs one command rather than a re-extraction, and edits you
made under the old view survive it intact.

---

## When colwin refuses

Four things are stopped with an explanation instead of being silently mangled.
The message names the file and what to do about it:

```
colwin: 1 asset(s) could not be encoded:
  sprites/COLDATA5.DLL/9001.png: ... introduces 1 colour(s) the sprite's palette
  does not hold: #07c86f.
The game stores palette INDICES, not colours, so every pixel has to land on an
entry that exists. Either draw only with the palette (load palettes/*.pal or
.gpl into your editor and work in indexed mode), or re-run with --nearest to
snap each new colour to the closest entry, which changes the art.
```

| Refused | Override |
| --- | --- |
| a colour the palette does not hold | `--nearest`, which changes the art |
| a row with a transparent gap between two opaque stretches — [`SPRT`](formats/sprt.md) stores one run per row | `--fill-holes=INDEX` |
| resizing a sprite — the canvas size is part of the resource | none; edit within the canvas |
| a character cp1252 cannot hold, in a text resource | none; use the cp1252 spelling |

[Editing](editing.md) explains why each of these is a hard rule of the format
rather than a limitation of the tool.

## Exit codes

| | |
| --- | --- |
| `0` | it worked |
| `1` | `verify` found a difference, or a module did not rebuild byte-identical |
| `2` | the command could not proceed — the message is on stderr, prefixed `colwin:` |

## Running the tests

```sh
python3 tests/test_roundtrip.py /path/to/game   # 19 tests
python3 tests/test_docs.py      /path/to/game   # the figures on these pages
```

Both take the game directory as the first argument or in `$COLWIN_GAME`. Without
one, the tests that need assets skip and the codec, palette and PNG tests still
run — which is what CI does, since the game cannot be checked in.
