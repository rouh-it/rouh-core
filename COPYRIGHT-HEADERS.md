# Copyright and licence lines in Rouh's files

1. **No long header in every file.** Rouh does not paste the Apache
   boilerplate into each file. The `LICENSE` and `NOTICE` files at the
   top of the repository cover the whole tree (Apache's appendix
   suggests the boilerplate, but does not require it).

2. **New source files start with one SPDX line** (a standard short tag
   that tools read):

       # SPDX-License-Identifier: Apache-2.0

   (`//` in JavaScript and Swift, `<!-- -->` in HTML). Existing files
   get it when they are next changed; nothing is rewritten in bulk.

3. **One project copyright line, in NOTICE only:**
   `Copyright 2026 Petar Petrov` until the assignment to TwoGears EOOD
   is signed, then `Copyright 2026 TwoGears EOOD`. Contributors do not add their own
   names to file headers; git's history and the `Signed-off-by` lines
   are the record of who wrote what (see `CONTRIBUTING.md`). The year
   is the first year of publication and is not updated each year.

4. **Code taken from another project keeps its own header and licence
   unchanged**, gets its own SPDX line (for example `MIT`), its licence
   text goes in `third_party/`, and a line is added to `NOTICE`.

5. **When the code moves to the foundation**, only `NOTICE` changes
   (to "Copyright 2026 TwoGears EOOD and Rouh Foundation" or as the
   transfer says); no file needs to be touched.
