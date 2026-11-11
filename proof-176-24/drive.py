"""Types into a real terminal program as a person would (pexpect, a real pseudo-terminal of 110 x 50),
and keeps the whole transcript. Script lines: `<pattern> => <what to type>`; what to type may be
<enter>, <ctrl-c>, or <emailed-code>, which waits for the code rouh.land emailed: the job reads it
from the inbox and pushes it to the branch proof/176-24-code as code.txt. Task 176, step 176-24."""
import os, subprocess, sys, time
import pexpect

script, transcript, *cmd = sys.argv[1:]
steps = [tuple(x.split(" => ", 1)) for x in open(script).read().splitlines() if " => " in x and not x.startswith("#")]
started = int(time.time())


def emailed_code() -> str:
    for _ in range(180):
        r = subprocess.run(["git", "fetch", "-q", "origin", "+refs/heads/proof/176-24-code:refs/remotes/origin/code"],
                           capture_output=True)
        if r.returncode == 0:
            when = int(subprocess.run(["git", "log", "-1", "--format=%ct", "origin/code"], capture_output=True, text=True).stdout or 0)
            if when >= started:
                return subprocess.run(["git", "show", "origin/code:code.txt"], capture_output=True, text=True).stdout.strip()
        time.sleep(10)
    raise SystemExit("no emailed code came in 30 minutes")


log = open(transcript, "w")
env = {**os.environ, "TERM": "xterm-256color", "COLORTERM": "truecolor"}
c = pexpect.spawn(cmd[0], cmd[1:], env=env, encoding="utf-8", timeout=900, dimensions=(50, 110))
c.logfile_read = log
for want, send in steps:
    c.expect(want)
    if send == "<ctrl-c>":
        c.sendintr()
    elif send == "<emailed-code>":
        c.sendline(emailed_code())
    else:
        c.sendline("" if send == "<enter>" else send)
c.expect(pexpect.EOF, timeout=1800)
c.close()
print(f"exit {c.exitstatus}")
sys.exit(c.exitstatus or 0)
