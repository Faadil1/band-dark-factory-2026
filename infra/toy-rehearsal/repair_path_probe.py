#!/usr/bin/env python3
"""Development-only negative-path proof bootstrap.

Creates a fresh BAND room and the context expected by claude_pipeline.py.
This does not alter or make claims about the accepted Rehearsal 8 revision.
"""
import importlib.util
import json
import os
from pathlib import Path

PIPE = Path("infra/toy-rehearsal/claude_pipeline.py")
spec = importlib.util.spec_from_file_location("toy_claude_pipeline", PIPE)
cp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cp)

event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8"))
pr = int(event["pull_request"]["number"])
branch = str(event["pull_request"]["head"]["ref"])
sha = str(event["pull_request"]["head"]["sha"])
repo = os.environ["GITHUB_REPOSITORY"]
token = f"toy-repair-proof-pr{pr}-{sha[:12]}"
pe = cp.participant_env()

room = cp.curl_json("POST", f"{cp.BAND_BASE}/chats", pe["coord_key"], {"chat": {}})
data = room.get("data") or {}
room_id = str(data.get("id") or data.get("chat_id") or data.get("room_id") or "")
if not room_id:
    raise SystemExit("no BAND room id")

for pid in (pe["impl_id"], pe["review_id"]):
    cp.curl_json(
        "POST",
        f"{cp.BAND_BASE}/chats/{room_id}/participants",
        pe["coord_key"],
        {"participant": {"participant_id": pid}},
    )

parts = cp.resolve_participants(
    room_id, pe["coord_key"], {pe["coord_id"], pe["impl_id"], pe["review_id"]}
)
coord, impl, reviewer = parts[pe["coord_id"]], parts[pe["impl_id"]], parts[pe["review_id"]]
ctx = {
    "repo": repo,
    "pr": pr,
    "branch": branch,
    "initial_sha": sha,
    "rehearsal": "repair-path-proof",
    "token": token,
    "room_id": room_id,
    "coord": coord,
    "impl": impl,
    "reviewer": reviewer,
}
cp.save_ctx(ctx)

content = (
    f"@{impl['handle']} @{reviewer['handle']} DEVELOPMENT_NEGATIVE_PATH_PROOF "
    f"run_token={token}. Evidence class=SIMULATED_DEFECT_TECHNICAL_PROOF. "
    "The accepted Rehearsal 8 product revision remains unchanged. This bounded test will inject "
    "one deterministic regression into a disposable proof branch, require Reviewer REJECT, then "
    "route that rejection to the Implementer for one autonomous repair and independent re-review. "
    "Do not represent the injected defect as product behavior and do not ask the human for steering."
)
cp.post_message(
    room_id,
    pe["coord_key"],
    content,
    [
        {"id": impl["id"], "name": impl["name"], "handle": impl["handle"]},
        {"id": reviewer["id"], "name": reviewer["name"], "handle": reviewer["handle"]},
    ],
)
cp.gh_comment(
    repo,
    pr,
    "\n".join(
        [
            "TOY_REPAIR_PATH_PROOF_CONTEXT",
            f"RUN_TOKEN={token}",
            f"ROOM_ID={room_id}",
            f"BRANCH={branch}",
            "EVIDENCE_CLASS=SIMULATED_DEFECT_TECHNICAL_PROOF",
            "SOURCE_ACCEPTED_REVISION=7679ba2f5d1937ebeed4b1e04449918ac8a7ecc8",
        ]
    ),
)
for key, value in {"run_token": token, "room_id": room_id, "branch": branch}.items():
    cp.write_output(key, value)
