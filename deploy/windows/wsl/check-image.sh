#!/usr/bin/env bash
# Checks a built .wsl file on Linux with Docker (task 186, step 186-04): what can be proved of Rouh's
# own WSL Linux without Windows, since GitHub's Windows machines cannot run WSL2.
#
#     deploy/windows/wsl/check-image.sh FILE.wsl [--static-only] [--out DIR]
#
# 1. The file itself: a gzip'd tar whose SHA-256 is its .sha256; wsl.conf with systemd on, no
#    Windows drives mounted, no Windows programs runnable; the narrow sudo rule and nothing wider;
#    no container leftovers; the person's account rouh (uid 1000, in docker's group, no password).
# 2. Booted as WSL boots it: the root file system imported as an image and started with systemd as
#    its first process, Docker Engine coming up inside under systemd, on the host's network (so
#    127.0.0.1:8420 is reached from outside, as WSL's localhost forwarding gives it to Windows).
# 3. Rouh in it, as Rouh for Windows does it, through rouh-wsl: first-start (the live
#    https://rouh.land/install.sh, the signed release, the updater at the signed commit, the first
#    start), state, link (the setup address answers from outside), the nightly timer, update, a
#    reboot of the Linux, then uninstall-keep and first-start again (Bring back your Rouh).
# Every step's words go to DIR/check.log, and DIR/result.json says which passed.
set -euo pipefail
wsl="$1"; shift
static_only=0 out="$PWD/wsl-check"
while [ $# -gt 0 ]; do
  case "$1" in
    --static-only) static_only=1; shift ;;
    --out) out="$2"; shift 2 ;;
    *) echo "unknown option $1" >&2; exit 2 ;;
  esac
done
mkdir -p "$out"
log="$out/check.log"; : > "$log"
results=()
pass() { echo "PASS $1" | tee -a "$log"; results+=("\"$1\": true"); }
fail() { echo "FAIL $1: $2" | tee -a "$log"; results+=("\"$1\": false"); FAILED=1; }
FAILED=0
finish() {
  { printf '{\n'; local IFS=$',\n'; printf ' %s\n' "${results[*]}"; printf '}\n'; } > "$out/result.json"
  [ "$FAILED" = 0 ] && echo "every check passed" | tee -a "$log" || echo "some checks failed" | tee -a "$log"
  exit "$FAILED"
}
trap finish EXIT

# ---- 1. the file ---------------------------------------------------------------------------------
if [ -f "$wsl.sha256" ] && (cd "$(dirname "$wsl")" && sha256sum -c "$(basename "$wsl").sha256" >/dev/null); then pass file.sha256
else fail file.sha256 "the file does not match its .sha256"; fi
root="$out/root"; rm -rf "$root"; mkdir -p "$root"
gzip -t "$wsl" && pass file.gzip || fail file.gzip "not gzip"
names="$(tar -tzf "$wsl")"
pre=""; head -n 1 <<<"$names" | grep -q '^\./' && pre="./"
names="$(sed 's#^\./##' <<<"$names")"
# Only the files the static checks read, unpacked as the runner's user (no device files needed).
tar -xzf "$wsl" -C "$root" ${pre}etc/wsl.conf ${pre}etc/wsl-distribution.conf ${pre}etc/sudoers.d/rouh ${pre}etc/passwd \
  ${pre}etc/group ${pre}etc/shadow ${pre}etc/rouh-wsl-release ${pre}usr/local/bin/rouh-wsl 2>>"$log" || true
grep -qx '.dockerenv' <<<"$names" && fail file.no-container-leftovers "/.dockerenv is in it" || pass file.no-container-leftovers
missing=0
for f in usr/bin/dockerd usr/bin/docker usr/libexec/docker/cli-plugins/docker-compose usr/lib/systemd/systemd usr/bin/python3 usr/bin/git usr/bin/curl usr/bin/openssl usr/bin/sudo; do
  grep -qx "$f" <<<"$names" || { fail "file.has-$(basename "$f")" "$f is missing"; missing=1; }
done
[ "$missing" = 0 ] && pass file.has-docker-systemd-python-git
conf="$root/etc/wsl.conf"
want() { python3 - "$conf" "$1" "$2" "$3" <<'PY'
import configparser, sys
c = configparser.ConfigParser(); c.read(sys.argv[1])
sys.exit(0 if c.get(sys.argv[2], sys.argv[3], fallback=None) == sys.argv[4] else 1)
PY
}
want boot systemd true && pass wslconf.systemd || fail wslconf.systemd "systemd is not on"
want user default rouh && pass wslconf.user || fail wslconf.user "the default user is not rouh"
want automount enabled false && want automount mountFsTab false && pass wslconf.no-windows-drives || fail wslconf.no-windows-drives "Windows drives would be mounted"
want interop enabled false && want interop appendWindowsPath false && pass wslconf.no-interop || fail wslconf.no-interop "Windows programs could be started from inside"
grep -q '^rouh:x:1000:1000:' "$root/etc/passwd" && pass account.rouh-1000 || fail account.rouh-1000 "no rouh with uid 1000"
grep -Eq '^docker:x:[0-9]+:(.*,)?rouh(,|$)' "$root/etc/group" && pass account.in-docker-group || fail account.in-docker-group "rouh is not in docker's group"
if [ -r "$root/etc/shadow" ]; then
  awk -F: '$1=="rouh"||$1=="root" {print $2}' "$root/etc/shadow" | grep -qv '^!' && fail account.no-passwords "a password is set" || pass account.no-passwords
fi
s="$root/etc/sudoers.d/rouh"
if grep -Eq 'NOPASSWD: *ALL|ALL *= *\(ALL(:ALL)?\) *(NOPASSWD: *)?ALL' "$s" || grep -q '^%sudo\|^rouh.*ALL$' "$s"; then fail sudo.narrow "the sudo rule is wider than the rouh command's commands"
else pass sudo.narrow; fi
python3 -m py_compile "$root/usr/local/bin/rouh-wsl" && pass helper.compiles || fail helper.compiles "rouh-wsl does not compile"
cat "$root/etc/rouh-wsl-release" >> "$log" 2>/dev/null || true
[ "$static_only" = 1 ] && exit 0

# ---- 2. booted with systemd, Docker inside ------------------------------------------------------
img="rouh-wsl-check:$(basename "$wsl" .wsl)"
docker import "$wsl" "$img" >>"$log"
docker rm -f rouh-wsl-check >/dev/null 2>&1 || true
docker volume rm -f rouh-wsl-check-docker rouh-wsl-check-containerd >/dev/null 2>&1 || true
# Docker's and containerd's stores on volumes of their own, as they are on WSL's own ext4 disk: on
# the check container's overlay root, an image layer's whiteouts cannot be made (overlay in overlay).
docker run -d --name rouh-wsl-check --hostname rouh --privileged --cgroupns=private --network host \
  --tmpfs /run --tmpfs /run/lock --tmpfs /tmp:exec -v rouh-wsl-check-docker:/var/lib/docker -v rouh-wsl-check-containerd:/var/lib/containerd \
  "$img" /usr/lib/systemd/systemd >>"$log"
in_root() { docker exec rouh-wsl-check "$@"; }
as_rouh() { docker exec -u rouh -w /home/rouh -e HOME=/home/rouh rouh-wsl-check "$@"; }
for _ in $(seq 60); do
  st="$(in_root systemctl is-system-running 2>/dev/null || true)"
  case "$st" in running|degraded) break ;; esac
  sleep 2
done
echo "systemd: $st" >> "$log"; in_root systemctl --failed --no-legend >> "$log" 2>&1 || true
case "$st" in running|degraded) pass boot.systemd ;; *) fail boot.systemd "systemd says $st" ;; esac
for _ in $(seq 60); do in_root systemctl is-active -q docker && break; sleep 2; done
in_root systemctl is-active -q docker && pass boot.docker-under-systemd || fail boot.docker-under-systemd "docker.service is not active"
as_rouh docker info --format '{{.ServerVersion}} {{.Driver}} cgroup v{{.CgroupVersion}}' >>"$log" 2>&1 && pass boot.docker-for-rouh || fail boot.docker-for-rouh "rouh cannot reach Docker"
as_rouh sudo -n true >/dev/null 2>&1 && fail sudo.no-general "rouh has general sudo" || pass sudo.no-general
as_rouh sudo -n /usr/bin/docker compose version >>"$log" 2>&1 && pass sudo.compose-version || fail sudo.compose-version "the one sudo install.sh needs is refused"

# ---- 3. Rouh, through rouh-wsl -------------------------------------------------------------------
state() { as_rouh rouh-wsl state 2>>"$log" | tail -n 1; }
field() { python3 -c 'import json,sys; v=json.loads(sys.argv[1]).get(sys.argv[2]); print(str(v).lower())' "$1" "$2"; }
s="$(state)"; echo "state before: $s" >> "$log"
[ "$(field "$s" installed)" = false ] && pass helper.state-before || fail helper.state-before "$s"
if as_rouh rouh-wsl first-start >>"$log" 2>&1; then pass rouh.first-start; else fail rouh.first-start "first-start failed; the end of check.log says why"; fi
s="$(state)"; echo "state after: $s" >> "$log"
[ "$(field "$s" running)" = true ] && pass rouh.running || fail rouh.running "$s"
[ "$(field "$s" owner)" = false ] && pass rouh.no-owner-yet || fail rouh.no-owner-yet "$s"
curl -fsS --max-time 10 http://127.0.0.1:8420/healthz >>"$log" 2>&1 && pass rouh.reached-from-outside || fail rouh.reached-from-outside "127.0.0.1:8420 does not answer"
link="$(as_rouh rouh-wsl link 2>>"$log" | tail -n 1)"
# The address takes its code and sends the browser on to the first run (303); followed, as a browser does.
code="$(curl -sL -c "$out/cookies" -o "$out/setup.html" -w '%{http_code}' --max-time 20 "$link" || true)"
echo "link answered $code" >> "$log"
[[ "$link" == http://127.0.0.1:8420/setup\?code=* ]] && [ "$code" = 200 ] && pass rouh.setup-link-opens || fail rouh.setup-link-opens "the setup address answered $code"
in_root systemctl is-enabled -q rouh-update.timer && pass rouh.nightly-timer || fail rouh.nightly-timer "rouh-update.timer is not enabled"
as_rouh rouh-wsl update >>"$log" 2>&1 && pass rouh.update || fail rouh.update "rouh update failed"
as_rouh rouh status >>"$log" 2>&1 || true
# A restart of the Linux, as a restart of Windows or wsl --shutdown gives it.
docker restart -t 60 rouh-wsl-check >>"$log"
for _ in $(seq 90); do s="$(state || true)"; [ "$(field "$s" running 2>/dev/null)" = true ] && break; sleep 5; done
[ "$(field "$s" running)" = true ] && pass rouh.after-restart || fail rouh.after-restart "Rouh did not come back by itself: $s"
# As Linux's own proof (176-25): Rouh stopped, its database alone up, so nothing changes under the count.
as_rouh sh -c 'c="docker compose -p rouh -f $HOME/rouh/stack/stack.json"; $c stop && $c start postgres' >>"$log" 2>&1 || true
as_rouh rouh fingerprint > "$out/fingerprint-before.json" 2>>"$log" || true
as_rouh rouh-wsl uninstall-keep >>"$log" 2>&1 && as_rouh test -d /home/rouh/rouh-kept && pass rouh.uninstall-keep || fail rouh.uninstall-keep "no checked copy in ~/rouh-kept"
# Brought back and not started yet, so the fingerprint is of exactly what came back; then started.
docker exec -u rouh -w /home/rouh -e HOME=/home/rouh -e ROUH_STOP_AFTER_BRING_BACK=1 rouh-wsl-check rouh-wsl first-start >>"$log" 2>&1 \
  && pass rouh.bring-back || fail rouh.bring-back "first-start after Keep did not bring it back"
as_rouh rouh fingerprint > "$out/fingerprint-after.json" 2>>"$log" || true
as_rouh rouh update >>"$log" 2>&1 || true
s="$(state)"; [ "$(field "$s" running)" = true ] && pass rouh.running-after-bring-back || fail rouh.running-after-bring-back "$s"
# The same Rouh: what Linux's own proof compares (task 176, step 176-25), key by key.
python3 - "$out/fingerprint-before.json" "$out/fingerprint-after.json" >> "$log" 2>&1 <<'PY' && pass rouh.same-after-bring-back || fail rouh.same-after-bring-back "the fingerprint differs; check.log names what"
import json, sys
a, b = (json.load(open(p)) for p in sys.argv[1:3])
def flat(d, pre=""):
    out = {}
    for k, v in (d.items() if isinstance(d, dict) else []):
        out.update(flat(v, f"{pre}{k}.") if isinstance(v, dict) else {f"{pre}{k}": v})
    return out
fa, fb = flat(a), flat(b)
diff = sorted(k for k in set(fa) | set(fb) if fa.get(k) != fb.get(k))
for k in diff:
    print(f"fingerprint {k}: before {str(fa.get(k))[:120]!r}, after {str(fb.get(k))[:120]!r}")
print(f"fingerprint: {len(fa)} values, {len(diff)} differ")
sys.exit(1 if diff or not fa else 0)
PY
docker logs rouh-wsl-check > "$out/systemd.log" 2>&1 || true
docker rm -f rouh-wsl-check >/dev/null 2>&1 || true
docker volume rm -f rouh-wsl-check-docker rouh-wsl-check-containerd >/dev/null 2>&1 || true
