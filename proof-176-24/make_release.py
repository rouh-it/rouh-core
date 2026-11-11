"""A test release with the edge part: the live release from rouh.land with this commit's stack file,
allow-list and the proof's own guard image, signed with a throwaway key that only this runner's
updater is told to trust (its mac_release.PUBLIC_KEYS, patched here). Never published anywhere.
    make_release.py GUARD_IMAGE CORE_DIR OUT.json"""
import base64, hashlib, json, re, subprocess, sys, tempfile, urllib.request
from pathlib import Path

guard, core, out = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3])
req = urllib.request.Request("https://rouh.land/mac/release/stable.json", headers={"User-Agent": "rouh-proof-176-24"})
live = json.loads(json.load(urllib.request.urlopen(req))["payload"])
compose = (core / "deploy/stack/compose.yml").read_text()
policy = (core / "guard/policy/stack-policy.json").read_text()
r = dict(live)
r.update(version=live["version"] + 1, images={**live["images"], "guard": guard}, compose=compose, policy=policy,
         compose_sha256=hashlib.sha256(compose.encode()).hexdigest(), policy_sha256=hashlib.sha256(policy.encode()).hexdigest(),
         changes=["proof 176-24: the edge part, and the stack check that holds it"])
r.pop("check_sha256", None)
payload = json.dumps(r, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
with tempfile.TemporaryDirectory() as t:
    k = Path(t, "k.pem")
    subprocess.run(["openssl", "genpkey", "-algorithm", "ed25519", "-out", str(k)], check=True)
    Path(t, "m").write_bytes(payload.encode())
    sig = subprocess.run(["openssl", "pkeyutl", "-sign", "-inkey", str(k), "-rawin", "-in", str(Path(t, "m"))],
                         capture_output=True, check=True).stdout
    pub = subprocess.run(["openssl", "pkey", "-in", str(k), "-pubout", "-outform", "DER"], capture_output=True, check=True).stdout
raw = base64.b64encode(pub[-32:]).decode()
out.write_text(json.dumps({"format": 1, "key": "proof-176-24", "payload": payload, "signature": base64.b64encode(sig).decode()}))
mr = core / "deploy/container/mac_release.py"
text = mr.read_text()
text, n = re.subn(r'PUBLIC_KEYS = \{KEY_ID: "([^"]+)"\}', lambda m: f'PUBLIC_KEYS = {{KEY_ID: "{m.group(1)}", "proof-176-24": "{raw}"}}', text)
assert n == 1, "PUBLIC_KEYS not found"
mr.write_text(text)
print(f"test release {r['version']}, guard {guard}, key proof-176-24 {raw}")
