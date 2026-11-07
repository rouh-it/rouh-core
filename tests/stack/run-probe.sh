#!/bin/bash
#
# What the stack test's one run does (tests/stack/smoke.py, RUN_BRIEF), as a run of the one
# program in the worker, with the environment a run is given: it fetches a page through the key
# proxy, and asks Rouh's MCP server for runs (rouh/worker_mcp.py) for a note to the owner and for
# the list of its tools. Each answer is left in /tmp for the checks to read.
out=/tmp/stack-run
env | grep -iE '^(https?_proxy|no_proxy|one_run|rouh_worker_key_file)=' | sed 's/=.*//' | sort > "$out-env"
curl -sS --max-time 20 -o /dev/null -w '%{http_code}' https://example.com > "$out-internet" 2>&1
mcp() {                             # mcp ID METHOD PARAMS-JSON
  { printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"stack-test","version":"1"}}}' \
      '{"jsonrpc":"2.0","method":"notifications/initialized"}' \
      "{\"jsonrpc\":\"2.0\",\"id\":$1,\"method\":\"$2\",\"params\":$3}"; sleep 10; } \
    | timeout 30 python3 -I /code/rouh/worker_mcp.py
}
mcp 2 tools/call '{"name":"notify_owner","arguments":{"subject":"Stack test","body":"A note from a run in the worker"}}' > "$out-notify" 2>&1
mcp 3 tools/list '{}' > "$out-tools" 2>&1
# The workspace's own commands, as a run uses them (bin/rouh, bin/rouh-task): a task made in this
# checkout, its status set, both through Rouh with the worker's key.
owner="$(python3 -c 'import json; m=json.load(open("_migration-map.json")); print(next(o["id"] for o in m["objects"] if o.get("type") == "project"))' 2>/dev/null)"
rouh objecttree create "Made by a run" --type task --owner "$owner" > "$out-tree" 2>&1
number="$(grep -oE 'at [^ ]*/([0-9]+)\.' "$out-tree" | grep -oE '[0-9]+' | tail -1)"
{ rouh-task status "$number" in-progress && rouh-task show "$number"; } > "$out-task" 2>&1
