# `.SAV` — saved games

`AUTO01.SAV`, 25,585 bytes, is the only save that ships. `colwin` does not read
or write it; this page records what is known.

**The structure is solved; the meanings are not.** All 57 fields have a known
offset and size and they account for the file exactly — 25,585 computed against
25,585 actual.

## Where the layout comes from

Not from periodicity in the bytes: from the routine that writes them.
`1008:a7f6` is the save routine, and it is the only function that calls the
file-write forwarder — **57 times**. Each call is `cdecl`, so the pushes at each
site give the file's fields in order together with the address each is written
from. `1008:9056` is the matching loader, calling the read forwarder 56 times.

## Checks that agree

| | |
| --- | --- |
| write 1 is 9 bytes | the file opens `COLONIZE\0` — magic plus terminator |
| writes 2–4 are 1, 2 and 4 bytes | which puts write 4 at `0x0c`, where the dimension words **58** and **72** sit |
| four 58×72 planes | 4,176 bytes each, the same grid as `AMER2.MP` |

## What is open

Which plane is terrain and which is ownership, and what the 202-, 28- and
18-byte records hold. Nothing carries such a label.
