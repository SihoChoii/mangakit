# Last Train Courier (example)

A text-only cut of the mangakit demo project: story records, art direction, chapter page sources and
procedural roughs. It has no generated art, so every panel shows its rough until final art is
commissioned (`mangakit job request`) and selected.

```
for r in art/roughs/*.py; do mangakit rough make "$(basename "$r" .py)"; done
mangakit story check && mangakit board check 01
mangakit render p002 --view reading
```
`install.sh` copies the pinned fonts into `fonts/`. Layout: see `docs/project-format.md` in the mangakit repo.
