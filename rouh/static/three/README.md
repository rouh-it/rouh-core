# three.js r170, vendored

The 3D orb (`rouh/static/app/orb3d.js`) draws with three.js r170, the same
version as the orb's reference viewer (workspace task 178, step 178-02).
It is served from here like every other front-end file, never from a CDN.

Only the parts the orb uses are here: the library itself, `OrbitControls`, and
the bloom passes with the shaders and passes they need.
`LICENSE.txt` is three.js's own MIT licence.

One change from upstream: an add-on's relative imports (`'./Pass.js'`) are
written as bare names (`'three/addons/postprocessing/Pass.js'`).
Every file is served under a hash of its own content (`rouh/web/assets.py`), so
there is no folder they share for a relative path to resolve against; the page's
import map resolves the bare names to each file's own address instead.
