#!/usr/bin/env python3
import json
import os
import subprocess
from pathlib import Path

BAND_BASE = "https://app.band.ai/api/v1/agent"


def run(cmd, *, input_text=None, check=True):
    p = subprocess.run(cmd, input=input_text, text=True, capture_output=True)
    if check and p.returncode != 0:
        raise SystemExit(f"command failed: {' '.join(cmd)}\n{p.stdout}\n{p.stderr}")
    return p


def curl_json(method, url, api_key, payload=None):
    out = Path(os.environ["RUNNER_TEMP"]) / "band-response.json"
    cmd = [
        "curl", "--silent", "--show-error",
        "--user-agent", "BAND-Dark-Factory-2026-Toy-Rehearsal/1.0",
        "--output", str(out), "--write-out", "%{http_code}",
        "-X", method,
        "-H", f"X-API-Key: {api_key}",
        "-H", "Accept: application/json",
    ]
    if payload is not None:
        cmd += ["-H", "Content-Type: application/json", "-d", json.dumps(payload)]
    cmd.append(url)
    p = run(cmd)
    code = p.stdout.strip()
    body = json.loads(out.read_text(encoding="utf-8") or "{}")
    if code not in {"200", "201"}:
        raise SystemExit(f"BAND {method} {url} failed HTTP {code}: {body}")
    return body


def resolve_participants(room_id, coordinator_key, ids):
    payload = curl_json("GET", f"{BAND_BASE}/chats/{room_id}/participants", coordinator_key)
    data = payload.get("data") or []
    if isinstance(data, dict):
        data = data.get("participants") or data.get("items") or []
    found = {}
    for item in data:
        iid = str(item.get("id") or item.get("participant_id") or "")
        if iid in ids:
            handle = str(item.get("handle") or "").lstrip("@")
            if not handle:
                raise SystemExit(f"missing handle for participant {iid}")
            found[iid] = {
                "id": iid,
                "name": str(item.get("name") or handle),
                "handle": handle,
            }
    missing = set(ids) - set(found)
    if missing:
        raise SystemExit(f"room missing participants: {sorted(missing)}")
    return found


def post_message(room_id, sender_key, content, mentions):
    payload = {"message": {"content": content, "mentions": mentions}}
    return curl_json("POST", f"{BAND_BASE}/chats/{room_id}/messages", sender_key, payload)


def gh_comment(repo, pr, body):
    payload = json.dumps({"body": body})
    run([
        "gh", "api", "--method", "POST",
        "-H", "Accept: application/vnd.github+json",
        f"repos/{repo}/issues/{pr}/comments",
        "--input", "-"
    ], input_text=payload)


def main():
    repo = os.environ["GITHUB_REPOSITORY"]
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
    pr = event["pull_request"]["number"]
    kickoff = Path(os.environ["KICKOFF"])

    coord_id = os.environ["BAND_COORDINATOR_AGENT_ID"].strip()
    coord_key = os.environ["BAND_COORDINATOR_API_KEY"].strip()
    impl_id = os.environ["BAND_IMPLEMENTER_AGENT_ID"].strip()
    review_id = os.environ["BAND_REVIEWER_AGENT_ID"].strip()

    room = curl_json("POST", f"{BAND_BASE}/chats", coord_key, {"chat": {}})
    room_data = room.get("data") or {}
    room_id = str(room_data.get("id") or room_data.get("chat_id") or room_data.get("room_id") or "")
    if not room_id:
        raise SystemExit(f"no room id in response: {room}")

    for participant_id in (impl_id, review_id):
        curl_json(
            "POST",
            f"{BAND_BASE}/chats/{room_id}/participants",
            coord_key,
            {"participant": {"participant_id": participant_id}},
        )

    participants = resolve_participants(room_id, coord_key, {coord_id, impl_id, review_id})
    impl = participants[impl_id]

    specs = []
    for n in range(1, 5):
        text = (kickoff / "toy" / "spec" / f"stage-{n}.md").read_text(encoding="utf-8")
        specs.append(f"\n\n===== TOY STAGE {n} SPEC =====\n{text}")

    task = (
        f"@{impl['handle']} TOY_FACTORY_REHEARSAL_1. Build the shared-counter service one stage at a time. "
        "The result repository is the current GitHub branch under toy-result/. Stage 1 goes in "
        "toy-result/stage-1/; when complete, copy it forward to stage-2 and extend it, then stage-3 and stage-4. "
        "Each stage must contain source, Dockerfile and RUN.md and preserve all inherited behavior. "
        "Do not modify FACTORY.md, mandates/, state/, workflows, evidence outside toy-result/stage-*/ or toy-input/. "
        "The Reviewer will independently run the official isolated harness. Do not ask the human for steering. "
        "Complete requirements follow:"
        + "".join(specs)
    )
    if len(task) > 15000:
        raise SystemExit(f"task message unexpectedly large: {len(task)}")

    msg = post_message(
        room_id,
        coord_key,
        task,
        [{"id": impl["id"], "name": impl["name"], "handle": impl["handle"]}],
    )
    msg_id = str((msg.get("data") or {}).get("id") or "")

    gh_comment(
        repo,
        pr,
        f"TOY_REHEARSAL_CONTEXT\nTOY_ROOM_ID={room_id}\nTOY_COORDINATOR_HANDOFF_ID={msg_id}\n",
    )

    codex_prompt = """@codex Act as the Implementer seat for Toy Factory Rehearsal 1.

Read the four official practice specs committed at:
- toy-input/stage-1.md
- toy-input/stage-2.md
- toy-input/stage-3.md
- toy-input/stage-4.md

Implement them sequentially under:
- toy-result/stage-1/
- toy-result/stage-2/
- toy-result/stage-3/
- toy-result/stage-4/

Stage N must remain a complete standalone service satisfying every earlier stage. Each stage needs source files, Dockerfile, and RUN.md. Build to the written specs, not to tests. Do not touch any path outside toy-result/stage-1/ through toy-result/stage-4/.

Do not commit or push. At the end run:
git diff --binary -- toy-result/stage-1 toy-result/stage-2 toy-result/stage-3 toy-result/stage-4 | base64 -w0

Return the single-line base64 payload between exactly these markers, with no code fence:
TOY_IMPL_PATCH_B64_BEGIN
<base64 payload>
TOY_IMPL_PATCH_B64_END
"""
    gh_comment(repo, pr, codex_prompt)
    print(json.dumps({"status": "DISPATCHED", "room_id": room_id, "pr": pr}))


if __name__ == "__main__":
    main()
