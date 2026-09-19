# CLAUDE.md

Guidance for Claude Code when working in this repository.

## What this is

`colwin` extracts the assets of *Sid Meier's Colonization for Windows* (1995)
out of their Win16 NE containers into editable files (indexed PNGs, `.pal`
palettes, UTF-8 text) and puts them back. The repository does **not** contain
the game; a retail install must be supplied by path.

The formats were established by reverse engineering in the sibling repository
`win-decomp` (`../win-decomp`); source files cite specific evidence (call sites
like `1068:4c05`, the LZW assembly at `1088:0000`, the CTAB loader at
`1068:0180`).

## Commands

```sh
python3 colwin.py list TARGET                  # module or game dir contents
python3 colwin.py extract GAME --out=ws        # --palette=ctab-auto|ctab:<id>|index
python3 colwin.py status ws
python3 colwin.py build ws --out=patched       # --nearest, --fill-holes=N, --modules-only
python3 colwin.py verify ws                    # re-encode everything, compare to the game
python3 colwin.py palette ws [--set=RULE]      # swap view palettes, pixel indices untouched

python3 tests/test_roundtrip.py /path/to/game  # 19 tests; codec tests run without a game
python3 tests/test_docs.py /path/to/game       # re-derives the 38 figures in docs/

python3 tools/release.py minor --dry-run       # what the next release would say
python3 tools/release.py minor                 # test, changelog, bump, commit, tag
```

Both test scripts take the game directory as `argv[1]` or via `$COLWIN_GAME`;
without one, asset tests skip and the codec/palette/PNG tests still run. That is
exactly what CI does ([.github/workflows/test.yml](.github/workflows/test.yml)) —
so a change that only passes with a game is not covered by CI, and vice versa.

## Layout

| | |
| --- | --- |
| [colwin/ne.py](colwin/ne.py) | Win16 NE containers: read the resource table, write it back |
| [colwin/png.py](colwin/png.py) | PNG read/write, stdlib only |
| [colwin/palette.py](colwin/palette.py) | the palette model, CTAB parsing, the injectivity rule |
| [colwin/workspace.py](colwin/workspace.py) | extract / status / build / verify, and the manifest |
| [colwin/formats/](colwin/formats/) | `sprt`, `cvpc`, `lzw`, `text`, `dib`, `flic` |
| [colwin/cli.py](colwin/cli.py) | argparse front end; [colwin.py](colwin.py) runs it uninstalled |
| [docs/](docs/) | the reference site (built and deployed to GitHub Pages by [.github/workflows/pages.yml](.github/workflows/pages.yml)) |
| [tools/release.py](tools/release.py) | cuts a release: tests, `CHANGELOG.md`, version bump, tag |

## Releasing

The version is one line, `__version__` in
[colwin/\_\_init\_\_.py](colwin/__init__.py); `colwin --version` and the
`colwin_version` field of a manifest both read it from there, and
[tools/release.py](tools/release.py) is the only thing that edits it. One run
refuses a dirty or stale checkout, runs both suites, drafts the `CHANGELOG.md`
section from the commits since the last `v*` tag, opens it in `$EDITOR`, bumps
the version, commits, and writes an annotated tag `v<version>`.

Pushing that tag is what publishes:
[.github/workflows/release.yml](.github/workflows/release.yml) re-checks the
tag against `__version__`, re-runs the tests, builds a runnable single-file
`colwin-<version>.pyz` (`python3 -m zipapp`, on 3.9) plus a source `.zip`, and
creates the GitHub release with the notes taken from that same changelog
section. The workflow reads the section by its `## <version> - <date>` heading,
so keep that heading line when editing the draft.

## Invariants to preserve

**Stdlib only, Python 3.9+.** No dependencies, ever — the tools must run on a
bare Python 3 next to a copy of the game. CI matrixes 3.9 / 3.11 / 3.13.

**Unedited assets are never re-encoded.** `colwin.json` records the SHA-256 of
both the original resource and the extracted file. On `build`, a file whose hash
is unchanged goes back as its original bytes. This is what makes an untouched
workspace rebuild all 13 modules byte-identically; do not route unchanged assets
through an encoder.

**Indices are the data; a palette is a way of looking at them.** Sprite pixel
values are indices into a palette that exists nowhere in the game (built at
runtime from `GetSystemPaletteEntries` and overwritten from `CTAB` blobs).
Extracted PNGs carry the index bytes verbatim. View palettes are made
*injective* (`uniquify()` nudges duplicates by one in blue) so truecolour
editing still maps colour → index exactly. `palette --set=` rewrites PLTE chunks
and must never touch a pixel index. See [docs/palettes.md](docs/palettes.md).

**`UNKNOWN` means copied, not computed.** Four `SPRT` header fields and the
`CRDS`/`CRED`/`MONS`/`SHIP` record tables have no established meaning; they are
preserved verbatim. Do not infer a meaning for them in code or docs — state the
evidence or say `UNKNOWN`.

**Refuse rather than mangle.** Resizing a sprite, a row with an interior
transparent gap (`SPRT` stores one run per row), a colour outside the palette,
or a character outside cp1252 all raise with an explanation naming the file.
`--nearest` and `--fill-holes` are the explicit overrides.

## Docs are tested

Numbers in `docs/` (counts, percentages, byte totals) are asserted as literal
strings by [tests/test_docs.py](tests/test_docs.py) against measurements from a
real install. Changing a figure in prose without changing the measurement — or
vice versa — fails the suite. Checks are on the numbers, not the wording.

## Style

Existing code uses `%` formatting, no f-strings, and no type annotations
(3.9 compatibility plus the surrounding house style). Module docstrings carry
the format layout and the evidence for it; keep that convention when adding a
format.
