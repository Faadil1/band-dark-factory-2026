#!/usr/bin/env python3
import base64
import json
import os
import re
import subprocess
from pathlib import Path

BAND_BASE = "https://app.band.ai/api/v1/agent"


def run(cmd, *, cwd=None, input_text=None, check=True, timeout=None):
    p = subprocess.run(
        cmd, cwd=cwd, input=input_text, text=True,
        capture_output=True, timeout=timeout
    )
    if check and p.returncode != 0:
        raise SystemExit(f"command failed: {' '.join(cmd)}\n{p.stdout}\n{p.stderr}")
    return p


def curl_json(method, url, api_key, payload=None):
    out = Path(os.environ["RUNNER_TEMP"]) / "band-review-response.json"
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


def resolve_participants(room_id, api_key, ids):
    payload = curl_json("GET", f"{BAND_BASE}/chats/{room_id}/participants", api_key)
    data = payload.get("data") or []
    if isinstance(data, dict):
        data = data.get("participants") or data.get("items") or []
    found = {}
    for item in data:
        iid = str(item.get("id") or item.get("participant_id") or "")
        if iid in ids:
            handle = str(item.get("handle") or "").lstrip("@")
            if not handle:
                raise SystemExit(f"missing handle for {iid}")
            found[iid] = {
                "id": iid,
                "name": str(item.get("name") or handle),
                "handle": handle,
            }
    missing = set(ids) - set(found)
    if missing:
        raise SystemExit(f"missing BAND participants: {sorted(missing)}")
    return found


def post_message(room_id, sender_key, content, mentions):
    if len(content) > 15500:
        raise SystemExit(f"BAND message too large: {len(content)}")
    return curl_json(
        "POST",
        f"{BAND_BASE}/chats/{room_id}/messages",
        sender_key,
        {"message": {"content": content, "mentions": mentions}},
    )


def get_pr(repo, pr):
    p = run(["gh", "api", f"repos/{repo}/pulls/{pr}"])
    return json.loads(p.stdout)


def get_room_id(repo, pr):
    p = run(["gh", "api", "--paginate", f"repos/{repo}/issues/{pr}/comments"])
    comments = json.loads(p.stdout)
    for item in reversed(comments):
        body = str(item.get("body") or "")
        m = re.search(r"(?m)^TOY_ROOM_ID=([0-9a-fA-F-]+)$", body)
        if m:
            return m.group(1)
    raise SystemExit("TOY_ROOM_ID marker not found on PR")


def extract_patch(body):
    m = re.search(
        r"TOY_IMPL_PATCH_B64_BEGIN\s*([A-Za-z0-9+/=\r\n]+?)\s*TOY_IMPL_PATCH_B64_END",
        body,
        flags=re.S,
    )
    if not m:
        raise SystemExit("Toy patch markers not found")
    payload = re.sub(r"\s+", "", m.group(1))
    return base64.b64decode(payload, validate=True)


def validate_patch(patch_text):
    paths = set()
    for line in patch_text.splitlines():
        if line.startswith("+++ b/"):
            paths.add(line[6:])
        elif line.startswith("--- a/"):
            paths.add(line[6:])
    if not paths:
        raise SystemExit("Patch contains no repository paths")
    allowed = re.compile(r"^toy-result/stage-[1-4]/[^/].*")
    bad = [p for p in paths if not allowed.match(p) or "/.git" in p or p.endswith("/.git")]
    if bad:
        raise SystemExit(f"Toy patch scope mismatch: {bad}")
    return sorted(paths)


def specs_text(kickoff):
    parts = []
    for n in range(1, 5):
        body = (kickoff / "toy" / "spec" / f"stage-{n}.md").read_text(encoding="utf-8")
        parts.append(f"\n\n===== TOY STAGE {n} SPEC =====\n{body}")
    return "".join(parts)


def main():
    repo = os.environ["GITHUB_REPOSITORY"]
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8"))
    pr = int(event["issue"]["number"])
    body = event["comment"]["body"]
    kickoff = Path(os.environ["KICKOFF"])
    workspace = Path(os.environ["GITHUB_WORKSPACE"])

    pr_data = get_pr(repo, pr)
    if pr_data["head"]["repo"]["full_name"] != repo:
        raise SystemExit("Refusing Toy relay for fork PR")
    if pr_data["head"]["ref"] != "toy/rehearsal-1":
        raise SystemExit(f"Unexpected Toy branch: {pr_data['head']['ref']}")

    room_id = get_room_id(repo, pr)
    patch = extract_patch(body)
    patch_path = Path(os.environ["RUNNER_TEMP"]) / "toy-impl.patch"
    patch_path.write_bytes(patch)
    paths = validate_patch(patch.decode("utf-8"))

    run(["git", "apply", "--check", str(patch_path)], cwd=workspace)
    run(["git", "apply", str(patch_path)], cwd=workspace)
    run(["git", "diff", "--check"], cwd=workspace)

    for n in range(1, 5):
        stage = workspace / "toy-result" / f"stage-{n}"
        for required in ("Dockerfile", "RUN.md"):
            if not (stage / required).is_file():
                raise SystemExit(f"stage-{n}/{required} missing after Codex patch")

    changed = run(["git", "diff", "--name-only"], cwd=workspace).stdout.splitlines()
    if set(changed) != set(paths):
        raise SystemExit(f"Changed paths differ from patch paths: {changed} vs {paths}")

    run(["git", "config", "user.name", "BAND Implementer"], cwd=workspace)
    run(["git", "config", "user.email", "band-implementer@users.noreply.github.com"], cwd=workspace)
    run(["git", "add", *paths], cwd=workspace)
    run(["git", "commit", "-m", "toy: implement four-stage shared counter"], cwd=workspace)
    revision = run(["git", "rev-parse", "HEAD"], cwd=workspace).stdout.strip()
    run(["git", "push", "origin", "HEAD:toy/rehearsal-1"], cwd=workspace)

    coord_id = os.environ["BAND_COORDINATOR_AGENT_ID"].strip()
    coord_key = os.environ["BAND_COORDINATOR_API_KEY"].strip()
    impl_id = os.environ["BAND_IMPLEMENTER_AGENT_ID"].strip()
    impl_key = os.environ["BAND_IMPLEMENTER_API_KEY"].strip()
    review_id = os.environ["BAND_REVIEWER_AGENT_ID"].strip()
    review_key = os.environ["BAND_REVIEWER_API_KEY"].strip()
    participants = resolve_participants(room_id, coord_key, {coord_id, impl_id, review_id})
    coord, impl, reviewer = participants[coord_id], participants[impl_id], participants[review_id]

    specs = specs_text(kickoff)
    impl_handoff = (
        f"@{coord['handle']} @{reviewer['handle']} TOY_IMPLEMENTATION_READY revision={revision}. "
        "I implemented all four Toy stages under toy-result/stage-1 through stage-4. "
        "Independent check command: python -m harness run --track toy --repo <workspace>/toy-result "
        "--all --mode isolated. Complete requirements follow:" + specs
    )
    post_message(
        room_id,
        impl_key,
        impl_handoff,
        [
            {"id": coord["id"], "name": coord["name"], "handle": coord["handle"]},
            {"id": reviewer["id"], "name": reviewer["name"], "handle": reviewer["handle"]},
        ],
    )

    review_handoff = (
        f"@{reviewer['handle']} TOY_REVIEW_HANDOFF revision={revision}. Independently verify the exact committed "
        "candidate against all four complete Toy specs. Run the official isolated harness over toy-result with "
        "--all. Do not fix production code yourself. Return ACCEPT or REJECT with revision, command, results and "
        "residual unknowns. Complete requirements follow:" + specs
    )
    post_message(
        room_id,
        coord_key,
        review_handoff,
        [{"id": reviewer["id"], "name": reviewer["name"], "handle": reviewer["handle"]}],
    )

    out_dir = Path(os.environ["RUNNER_TEMP"]) / "toy-all"
    cmd = [
        "python", "-m", "harness", "run",
        "--track", "toy",
        "--repo", str(workspace / "toy-result"),
        "--all",
        "--mode", "isolated",
        "--out", str(out_dir),
    ]
    p = run(cmd, cwd=kickoff, check=False, timeout=2400)
    (Path(os.environ["RUNNER_TEMP"]) / "toy-harness.stdout").write_text(p.stdout, encoding="utf-8")
    (Path(os.environ["RUNNER_TEMP"]) / "toy-harness.stderr").write_text(p.stderr, encoding="utf-8")

    summary_path = out_dir / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.exists() else {}
    short = json.dumps(summary, separators=(",", ":"))[:4500]

    if p.returncode == 0:
        verdict = (
            f"@{impl['handle']} @{coord['handle']} ACCEPT {revision}. "
            "Reviewer command: python -m harness run --track toy --repo toy-result --all --mode isolated. "
            f"exit=0 summary={short}. Residual unknown: room.json and offline harness check still require "
            "the final full-session export."
        )
        status = "ACCEPT"
    else:
        tail = (p.stdout + "\n" + p.stderr)[-5000:]
        verdict = (
            f"@{impl['handle']} @{coord['handle']} REJECT {revision}. "
            "Reviewer command: python -m harness run --track toy --repo toy-result --all --mode isolated. "
            f"exit={p.returncode}. Reproduction tail follows:\n{tail}"
        )
        status = "REJECT"

    review_msg = post_message(
        room_id,
        review_key,
        verdict,
        [
            {"id": impl["id"], "name": impl["name"], "handle": impl["handle"]},
            {"id": coord["id"], "name": coord["name"], "handle": coord["handle"]},
        ],
    )
    review_msg_id = str((review_msg.get("data") or {}).get("id") or "")

    evidence_dir = workspace / "artifacts" / "toy-rehearsal"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    evidence = {
        "status": status,
        "room_id": room_id,
        "pr": pr,
        "revision": revision,
        "codex_comment_id": event["comment"]["id"],
        "review_message_id": review_msg_id,
        "harness_exit": p.returncode,
        "summary": summary,
        "human_steering_after_pr_open": False,
    }
    (evidence_dir / "evidence.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")

    print(json.dumps(evidence, indent=2))
    if p.returncode != 0:
        raise SystemExit(p.returncode)


if __name__ == "__main__":
    main()
