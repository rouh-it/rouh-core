#!/bin/bash
#
# Scan every layer of an image for anything that must not be published: keys, tokens, passwords,
# private keys, and names or addresses of the maker's own machines and people (task 98, step 98-23:
# rouh-base is to be made public only after this passes, and making it public is the owner's yes).
#
#   deploy/container/scan-image.sh OUT-FOLDER IMAGE [IMAGE ...]
#
# For each image and each platform it has: `docker save`, then every layer unpacked on its own -
# so a file a later layer deletes is still seen - and scanned by gitleaks (its default rules, every
# kind of key and token it knows) and by a list of the maker's own private names and addresses
# (SCAN_PRIVATE_NAMES, below). A file in the base's Python, Node or Debian packages that matches a key rule is
# listed as found, and judged by a person: a library's test key is not a leak, and the report says
# which package each is in.
#
# SCAN_DROP_IMAGES=1 removes each image once it is scanned (a CI runner's small disk).
#
# Writes OUT-FOLDER/report.md and report.json, and exits 1 when anything was found that is not a
# known library test value (ALLOWED below).
set -uo pipefail
out="${1:?scan-image.sh OUT IMAGE...}"; shift
mkdir -p "$out"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

GITLEAKS_VERSION=8.30.0
if ! command -v gitleaks >/dev/null; then
  arch="$(uname -m | sed 's/x86_64/x64/; s/aarch64/arm64/')"
  curl -fsSL "https://github.com/gitleaks/gitleaks/releases/download/v${GITLEAKS_VERSION}/gitleaks_${GITLEAKS_VERSION}_linux_${arch}.tar.gz" \
    | tar -xz -C "$work" gitleaks
  PATH="$work:$PATH"
fi

# The maker's own machines, addresses, people and accounts that must never be in an image. The list
# itself is private, so it is not here: it is one extended regular expression (grep -E) in the
# environment, SCAN_PRIVATE_NAMES, which the workflow fills from the Actions secret of the same name.
# With SCAN_REQUIRE_PRIVATE=1 (the workflow) a missing list fails the scan rather than skip it.
PRIVATE="${SCAN_PRIVATE_NAMES:-}"
if [ -z "$PRIVATE" ]; then
  if [ "${SCAN_REQUIRE_PRIVATE:-}" = 1 ]; then
    echo "scan-image.sh: SCAN_PRIVATE_NAMES is empty: the private-names list is the Actions secret of that name" >&2
    exit 2
  fi
  echo "scan-image.sh: no SCAN_PRIVATE_NAMES given, so only keys and tokens are looked for" >&2
fi
# Paths whose matches are libraries' own test data or documentation, judged once by a person.
ALLOWED='^(usr/lib/python3[0-9.]*|usr/local/lib/python3[0-9.]*|opt/venv/lib/python3[0-9.]*/site-packages|usr/local/lib/node_modules|usr/share/doc|usr/lib/node_modules|usr/share/ca-certificates|etc/ssl|usr/share/perl[0-9.]*|usr/lib/[a-z0-9_]+-linux-gnu|var/lib/dpkg|usr/share/(common-licenses|man|locale|i18n))/|^etc/chromium\.d/apikeys$'
# etc/chromium.d/apikeys is Debian's own: the Google API keys Google assigned to Debian for
# Chromium, shipped in Debian's public chromium package (dpkg -S says so), not anything of ours.

echo '[]' > "$work/all.json"
for image in "$@"; do
  for platform in linux/amd64 linux/arm64; do
    name="$(echo "$image" | tr '/:@' '___')-${platform#linux/}"
    if ! docker pull -q --platform "$platform" "$image" >/dev/null 2>&1; then
      here="$(docker image inspect "$image" --format '{{.Os}}/{{.Architecture}}' 2>/dev/null || true)"
      if [ "$here" != "$platform" ]; then
        echo "skip  $image ($platform): no such platform"
        continue
      fi
    fi
    dir="$work/$name"; mkdir -p "$dir/layers"
    docker save --platform "$platform" "$image" -o "$dir/image.tar" 2>/dev/null || docker save "$image" -o "$dir/image.tar"
    tar -xf "$dir/image.tar" -C "$dir"
    layers=$(python3 - "$dir" <<'PY'
import json, os, sys
d = sys.argv[1]
idx = json.load(open(os.path.join(d, "index.json")))
def blob(digest): return os.path.join(d, "blobs", *digest.split(":"))
def walk(desc):
    m = json.load(open(blob(desc["digest"])))
    if "manifests" in m:
        for x in m["manifests"]:
            p = x.get("platform") or {}
            if p.get("architecture") in ("amd64", "arm64") and p.get("os") == "linux" or "platform" not in x:
                yield from walk(x)
    elif "layers" in m:
        for layer in m["layers"]:
            yield blob(layer["digest"])
seen = []
for desc in idx["manifests"]:
    for b in walk(desc):
        if b not in seen:
            seen.append(b)
print("\n".join(seen))
PY
)
    n=0
    for layer in $layers; do
      n=$((n + 1))
      ld="$dir/layers/$n"; mkdir -p "$ld"
      tar -xf "$layer" -C "$ld" 2>/dev/null || true
      gitleaks dir "$ld" --no-banner --exit-code 0 --report-format json --report-path "$dir/leaks-$n.json" >/dev/null 2>&1 || true
      : > "$dir/private-$n.txt"
      [ -z "$PRIVATE" ] || grep -rnIoE "$PRIVATE" "$ld" 2>/dev/null | sed "s|^$ld/||" | head -200 > "$dir/private-$n.txt" || true
      python3 - "$work/all.json" "$dir/leaks-$n.json" "$dir/private-$n.txt" "$image" "$platform" "$n" "$ld" "$ALLOWED" <<'PY'
import json, re, sys
allp, leaks_f, priv_f, image, platform, n, root, allowed = sys.argv[1:]
rows = json.load(open(allp))
try:
    leaks = json.load(open(leaks_f))
except Exception:
    leaks = []
for l in leaks:
    path = l.get("File", "").replace(root + "/", "")
    rows.append({"image": image, "platform": platform, "layer": int(n), "kind": "key", "rule": l.get("RuleID"),
                 "path": path, "line": l.get("StartLine"), "library": bool(re.match(allowed, path))})
for line in open(priv_f).read().splitlines():
    path, _, rest = line.partition(":")
    rows.append({"image": image, "platform": platform, "layer": int(n), "kind": "private", "rule": rest.split(":", 1)[-1][:60],
                 "path": path, "line": rest.split(":", 1)[0], "library": bool(re.match(allowed, path))})
json.dump(rows, open(allp, "w"))
PY
      rm -rf "$ld"
    done
    echo "done  $image ($platform): $n layers"
    rm -rf "$dir"
    # Room for the next: a runner's disk holds one platform of one image at a time.
    [ -n "${SCAN_DROP_IMAGES:-}" ] && { docker image rm -f "$image" >/dev/null 2>&1; docker system prune -af >/dev/null 2>&1; }
  done
done

python3 - "$work/all.json" "$out" "$@" <<'PY'
import collections, json, os, sys
rows = json.load(open(sys.argv[1]))
out, images = sys.argv[2], sys.argv[3:]
json.dump(rows, open(os.path.join(out, "report.json"), "w"), indent=1)
bad = [r for r in rows if not r["library"]]
lib = [r for r in rows if r["library"]]
lines = ["# Secrets scan of the published images", "",
         "Every layer of " + ", ".join(f"`{i}`" for i in images) + ", each platform, unpacked one by one: gitleaks' rules for keys and tokens, and the makers' own private names and addresses.", ""]
if not bad:
    lines.append(f"**Clean.** Nothing outside libraries' own files. {len(lib)} match{'es' if len(lib) != 1 else ''} inside libraries' own files (their test data and documentation), listed below to be judged.")
else:
    lines.append(f"**{len(bad)} found outside libraries' own files:**")
    for r in bad[:200]:
        lines.append(f"- {r['image']} {r['platform']} layer {r['layer']}: `{r['path']}`:{r['line']} ({r['kind']}: {r['rule']})")
if lib:
    lines += ["", "Inside libraries' own files, by rule:"]
    for (kind, rule), n in collections.Counter((r["kind"], r["rule"]) for r in lib).most_common(40):
        where = sorted({r["path"].split("/site-packages/")[-1].split("/")[0] if "/site-packages/" in r["path"] else r["path"].split("/")[2] if r["path"].count("/") > 2 else r["path"] for r in lib if (r["kind"], r["rule"]) == (kind, rule)})[:8]
        lines.append(f"- {kind} {rule}: {n}, in {', '.join(where)}")
open(os.path.join(out, "report.md"), "w").write("\n".join(lines) + "\n")
print("\n".join(lines[:60]))
sys.exit(1 if bad else 0)
PY
