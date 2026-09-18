# NOTICE

## What this repository is, and is not

These are tools for reading and writing the asset files of **Sid Meier's
Colonization for Windows** (1995), **© 1994–1995 MicroProse Software, Inc.**
The rights in that game are held by its present owner, not by this project.

**This repository does not contain the game.** It ships no art, no text, no
sound and no executable from it. You bring your own copy; everything here
operates on files already on your disk. `game/` and any workspace you extract
are gitignored for that reason.

The tools, their tests and their documentation are this project's own work and
are MIT licensed. The *formats* they implement were established by reverse
engineering carried out for interoperability and preservation, on a copy of the
game the author owns; that research lives in the sibling repository
[win-decomp](https://github.com/colonization-re/win-decomp) and is cited
throughout the source here.

## What comes out of these tools is still the game's

A workspace extracted with `colwin extract` holds the game's art and text in a
different file format. Converting it does not make it yours to redistribute. If
you publish a mod, publish the *changes* -- not the extracted originals.
