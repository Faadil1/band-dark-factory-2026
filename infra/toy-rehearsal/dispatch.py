#!/usr/bin/env python3
import json
import os
import re
import subprocess
import time
from pathlib import Path

BAND_BASE = "https://app.band.ai/api/v1/agent"
CODEX_BOT = "chatgpt-codex-connector[bot]"


def run(cmd, *, input_text=None, check=True, env=None):
    p = subprocess.run(cmd, input=input_text, text=True, capture_output=True, env=env)
    if check and p.returncode != 0:
        raise SystemExit(f"command failed: {' '.join(cmd)}\n{p.stdout}\n{p.stderr}")
    return p


def curl_json(method, url, api_key, payload=None):
    out = Path(os.environ["RUNNER_TEMP"]) / "band-response.json"
    cmd = [
        "curl", "--silent", "--show-error",
        "--user-agent", "BAND-Dark-Factory-2026-Toy-Rehearsal/1.1",
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


def gh_comment(repo, pr, body, *, token=None):
    payload = json.dumps({"body": body})
    env = None
    if token is not None:
        env = os.environ.copy()
        env["GH_TOKEN"] = token
    p = run([
        "gh", "api", "--method", "POST",
        "-H", "Accept: application/vnd.github+json",
        f"repos/{repo}/issues/{pr}/comments",
        "--input", "-"
    ], input_text=payload, env=env)
    return json.loads(p.stdout)


def validate_codex_user_token(repo, token):
    if not token:
        raise SystemExit("CODEX_GITHUB_USER_TOKEN is required for user-authored @codex dispatch")
    env = os.environ.copy()
    env["GH_TOKEN"] = token
    p = run(["gh", "api", "user"], env=env)
    login = str(json.loads(p.stdout).get("login") or "")
    expected = repo.split("/", 1)[0]
    if login != expected:
        raise SystemExit(
            f"CODEX_GITHUB_USER_TOKEN authenticates as {login!r}; expected repository owner {expected!r}"
        )
    return login


def gh_comments(repo, pr):
    p = run([
        "gh", "api",
        "-H", "Accept: application/vnd.github+json",
        f"repos/{repo}/issues/{pr}/comments?per_page=100",
    ])
    return json.loads(p.stdout)


def codex_patch_reply(repo, pr, *, after_comment_id):
    for item in gh_comments(repo, pr):
        if int(item.get("id") or 0) <= int(after_comment_id):
            continue
        if str((item.get("user") or {}).get("login") or "") != CODEX_BOT:
            continue
        body = str(item.get("body") or "")
        if "TOY_IMPL_PATCH_B64_BEGIN" in body and "TOY_IMPL_PATCH_B64_END" in body:
            return item
    return None


def wait_for_codex(repo, pr, *, after_comment_id, timeout_seconds, poll_seconds):
    deadline = time.monotonic() + timeout_seconds
    while True:
        reply = codex_patch_reply(repo, pr, after_comment_id=after_comment_id)
        if reply is not None:
            return reply
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return None
        time.sleep(min(poll_seconds, max(1, int(remaining))))


def rehearsal_identity(event):
    pr = event["pull_request"]["number"]
    branch = str(event["pull_request"]["head"]["ref"])
    head_sha = str(event["pull_request"]["head"]["sha"])
    m = re.fullmatch(r"toy/rehearsal-(\d+)", branch)
    if not m:
        raise SystemExit(f"unexpected Toy rehearsal branch: {branch}")
    rehearsal = int(m.group(1))
    token = f"toy-r{rehearsal}-pr{pr}-{head_sha[:12]}"
    return pr, branch, rehearsal, token


def codex_prompt(token, branch, rehearsal, *, retry=False):
    retry_note = (
        "\nThis is the single bounded transport retry (attempt 2/2). "
        "If a patch for this same run token is already present in this PR, do not emit another patch.\n"
        if retry else ""
    )
    return f"""@codex Act as the Implementer seat for Toy Factory Rehearsal {rehearsal}.

TOY_RUN_TOKEN={token}
TOY_REHEARSAL_BRANCH={branch}
{retry_note}
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

Return the run token and single-line base64 payload exactly like this, with no code fence:
TOY_RUN_TOKEN={token}
TOY_IMPL_PATCH_B64_BEGIN
<base64 payload>
TOY_IMPL_PATCH_B64_END
"""


def main():
    repo = os.environ["GITHUB_REPOSITORY"]
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
    pr, branch, rehearsal, token = rehearsal_identity(event)
    kickoff = Path(os.environ["KICKOFF"])
    codex_user_token = os.environ.get("CODEX_GITHUB_USER_TOKEN", "").strip()
    codex_user_login = validate_codex_user_token(repo, codex_user_token)

    first_window = int(os.getenv("CODEX_FIRST_WINDOW_SECONDS", "480"))
    retry_window = int(os.getenv("CODEX_RETRY_WINDOW_SECONDS", "720"))
    poll_seconds = int(os.getenv("CODEX_POLL_SECONDS", "60"))

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
    coord = participants[coord_id]
    impl = participants[impl_id]
    reviewer = participants[review_id]

    specs = []
    for n in range(1, 5):
        text = (kickoff / "toy" / "spec" / f"stage-{n}.md").read_text(encoding="utf-8")
        specs.append(f"\n\n===== TOY STAGE {n} SPEC =====\n{text}")

    task = (
        f"@{impl['handle']} TOY_FACTORY_REHEARSAL_{rehearsal} run_token={token}. "
        "Build the shared-counter service one stage at a time. "
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
        (
            "TOY_REHEARSAL_CONTEXT\n"
            f"TOY_RUN_TOKEN={token}\n"
            f"TOY_REHEARSAL_BRANCH={branch}\n"
            f"TOY_ROOM_ID={room_id}\n"
            f"TOY_COORDINATOR_HANDOFF_ID={msg_id}\n"
        ),
    )

    first_prompt = gh_comment(
        repo, pr, codex_prompt(token, branch, rehearsal), token=codex_user_token
    )
    reply = wait_for_codex(
        repo,
        pr,
        after_comment_id=first_prompt["id"],
        timeout_seconds=first_window,
        poll_seconds=poll_seconds,
    )
    if reply is not None:
        print(json.dumps({
            "status": "CODEX_RESPONSE_OBSERVED",
            "room_id": room_id,
            "pr": pr,
            "branch": branch,
            "run_token": token,
            "attempts": 1,
            "codex_dispatch_login": codex_user_login,
            "codex_comment_id": reply["id"],
        }))
        return

    retry_prompt = gh_comment(
        repo, pr, codex_prompt(token, branch, rehearsal, retry=True), token=codex_user_token
    )
    reply = wait_for_codex(
        repo,
        pr,
        after_comment_id=first_prompt["id"],
        timeout_seconds=retry_window,
        poll_seconds=poll_seconds,
    )
    if reply is not None:
        print(json.dumps({
            "status": "CODEX_RESPONSE_OBSERVED_AFTER_RETRY",
            "room_id": room_id,
            "pr": pr,
            "branch": branch,
            "run_token": token,
            "attempts": 2,
            "codex_dispatch_login": codex_user_login,
            "retry_comment_id": retry_prompt["id"],
            "codex_comment_id": reply["id"],
        }))
        return

    blocker = (
        "TOY_REHEARSAL_TERMINAL "
        f"status=BLOCKED reason=CODEX_TRANSPORT_TIMEOUT run_token={token} "
        f"branch={branch} attempts=2 first_window_seconds={first_window} "
        f"retry_window_seconds={retry_window}"
    )
    gh_comment(repo, pr, blocker)
    post_message(
        room_id,
        coord_key,
        (
            f"@{impl['handle']} @{reviewer['handle']} {blocker}. "
            "No Toy implementation patch was observed from the GitHub Codex transport. "
            "Fail closed; do not ask the human for steering and do not promote Track Lock."
        ),
        [
            {"id": impl["id"], "name": impl["name"], "handle": impl["handle"]},
            {"id": reviewer["id"], "name": reviewer["name"], "handle": reviewer["handle"]},
        ],
    )
    raise SystemExit("Codex transport timed out after the single bounded retry")


if __name__ == "__main__":
    main()
