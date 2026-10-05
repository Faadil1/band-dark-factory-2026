#!/usr/bin/env python3
import json
import os
import re
import subprocess
import sys
from pathlib import Path

BAND_BASE = "https://app.band.ai/api/v1/agent"
CTX_PATH = Path(os.environ.get("RUNNER_TEMP", "/tmp")) / "toy-claude-context.json"

def run(cmd, *, cwd=None, input_text=None, check=True, timeout=None):
    p = subprocess.run(cmd, cwd=cwd, input=input_text, text=True, capture_output=True, timeout=timeout)
    if check and p.returncode != 0:
        raise SystemExit(f"command failed: {' '.join(cmd)}\n{p.stdout}\n{p.stderr}")
    return p

def curl_json(method, url, api_key, payload=None):
    out = Path(os.environ["RUNNER_TEMP"]) / "band-claude-response.json"
    cmd = ["curl","--silent","--show-error","--user-agent","BAND-Dark-Factory-2026-Claude/1.0",
           "--output",str(out),"--write-out","%{http_code}","-X",method,
           "-H",f"X-API-Key: {api_key}","-H","Accept: application/json"]
    if payload is not None:
        cmd += ["-H","Content-Type: application/json","-d",json.dumps(payload)]
    cmd.append(url)
    p = run(cmd)
    code = p.stdout.strip()
    body = json.loads(out.read_text(encoding="utf-8") or "{}")
    if code not in {"200","201"}:
        raise SystemExit(f"BAND {method} {url} failed HTTP {code}: {body}")
    return body

def post_message(room_id, api_key, content, mentions):
    if len(content) > 15500:
        raise SystemExit(f"BAND message too large: {len(content)}")
    return curl_json("POST", f"{BAND_BASE}/chats/{room_id}/messages", api_key,
                     {"message":{"content":content,"mentions":mentions}})

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
            found[iid] = {"id":iid,"name":str(item.get("name") or handle),"handle":handle}
    missing = set(ids) - set(found)
    if missing:
        raise SystemExit(f"missing BAND participants: {sorted(missing)}")
    return found

def gh_comment(repo, pr, body):
    p = run(["gh","api","--method","POST","-H","Accept: application/vnd.github+json",
             f"repos/{repo}/issues/{pr}/comments","--input","-"], input_text=json.dumps({"body":body}))
    return json.loads(p.stdout)

def write_output(key, value):
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as f:
        f.write(f"{key}={value}\n")

def write_output_multiline(key, value):
    marker = "TOY_REPAIR_CONTEXT_EOF"
    if marker in value:
        value = value.replace(marker, "TOY_REPAIR_CONTEXT")
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as f:
        f.write(f"{key}<<{marker}\n{value}\n{marker}\n")

def rehearsal_identity():
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8"))
    pr = int(event["pull_request"]["number"])
    branch = str(event["pull_request"]["head"]["ref"])
    sha = str(event["pull_request"]["head"]["sha"])
    m = re.fullmatch(r"toy/rehearsal-(\d+)", branch)
    if not m:
        raise SystemExit(f"unexpected Toy rehearsal branch: {branch}")
    rehearsal = int(m.group(1))
    token = f"toy-r{rehearsal}-pr{pr}-{sha[:12]}"
    return pr, branch, sha, rehearsal, token

def specs_text():
    parts=[]
    for n in range(1,5):
        p=Path("toy-input")/f"stage-{n}.md"
        parts.append(f"\n\n===== TOY STAGE {n} SPEC =====\n"+p.read_text(encoding="utf-8"))
    return "".join(parts)

def load_ctx():
    return json.loads(CTX_PATH.read_text(encoding="utf-8"))

def save_ctx(ctx):
    CTX_PATH.write_text(json.dumps(ctx, indent=2), encoding="utf-8")

def participant_env():
    return {
        "coord_id": os.environ["BAND_COORDINATOR_AGENT_ID"].strip(),
        "coord_key": os.environ["BAND_COORDINATOR_API_KEY"].strip(),
        "impl_id": os.environ["BAND_IMPLEMENTER_AGENT_ID"].strip(),
        "impl_key": os.environ["BAND_IMPLEMENTER_API_KEY"].strip(),
        "review_id": os.environ["BAND_REVIEWER_AGENT_ID"].strip(),
        "review_key": os.environ["BAND_REVIEWER_API_KEY"].strip(),
    }

def terminal(repo, pr, ctx, status, *, revision=None, harness_exit=None, reason=None, attempt=None):
    fields=["TOY_REHEARSAL_TERMINAL",f"status={status}",f"run_token={ctx['token']}",
            f"branch={ctx['branch']}","runtime=CLAUDE_CODE_OAUTH"]
    if revision: fields.append(f"revision={revision}")
    if harness_exit is not None: fields.append(f"harness_exit={harness_exit}")
    if reason: fields.append(f"reason={reason}")
    if attempt is not None: fields.append(f"attempt={attempt}")
    gh_comment(repo, pr, " ".join(fields))

def cmd_prepare():
    repo=os.environ["GITHUB_REPOSITORY"]
    pr, branch, sha, rehearsal, token = rehearsal_identity()
    pe=participant_env()
    for k,v in pe.items():
        if not v: raise SystemExit(f"missing credential: {k}")
    # Fail if an implementation is already seeded.
    for n in range(1,5):
        if (Path("toy-result")/f"stage-{n}"/"Dockerfile").exists():
            raise SystemExit(f"preseeded implementation detected in stage-{n}")
    room = curl_json("POST", f"{BAND_BASE}/chats", pe["coord_key"], {"chat":{}})
    rd=room.get("data") or {}
    room_id=str(rd.get("id") or rd.get("chat_id") or rd.get("room_id") or "")
    if not room_id: raise SystemExit("no BAND room id")
    for pid in (pe["impl_id"],pe["review_id"]):
        curl_json("POST", f"{BAND_BASE}/chats/{room_id}/participants", pe["coord_key"],
                  {"participant":{"participant_id":pid}})
    parts=resolve_participants(room_id, pe["coord_key"], {pe["coord_id"],pe["impl_id"],pe["review_id"]})
    coord, impl, reviewer = parts[pe["coord_id"]],parts[pe["impl_id"]],parts[pe["review_id"]]
    task=(f"@{impl['handle']} TOY_FACTORY_REHEARSAL_{rehearsal} run_token={token}. "
          "Implement all four Toy stages in order under toy-result/stage-1 through stage-4. "
          "Each stage must be standalone and preserve inherited behavior. Build to the written requirements, "
          "not merely tests. Do not ask the human for steering. Reviewer will independently run the official "
          "isolated harness. Complete requirements follow:"+specs_text())
    msg=post_message(room_id, pe["coord_key"], task,
                     [{"id":impl["id"],"name":impl["name"],"handle":impl["handle"]}])
    ctx={"repo":repo,"pr":pr,"branch":branch,"initial_sha":sha,"rehearsal":rehearsal,"token":token,
         "room_id":room_id,"coord":coord,"impl":impl,"reviewer":reviewer}
    save_ctx(ctx)
    gh_comment(repo, pr, "\n".join([
        "TOY_REHEARSAL_CONTEXT",
        f"TOY_RUN_TOKEN={token}",
        f"TOY_REHEARSAL_BRANCH={branch}",
        f"TOY_ROOM_ID={room_id}",
        f"TOY_COORDINATOR_HANDOFF_ID={str((msg.get('data') or {}).get('id') or '')}",
        "TOY_IMPLEMENTER_RUNTIME=CLAUDE_CODE_OAUTH",
    ]))
    for k,v in {"run_token":token,"branch":branch,"initial_sha":sha,"room_id":room_id}.items():
        write_output(k,v)

def changed_paths():
    p=run(["git","status","--porcelain=v1"], check=True)
    paths=[]
    for raw in p.stdout.splitlines():
        if not raw.strip(): continue
        path=raw[3:]
        if " -> " in path: path=path.split(" -> ",1)[1]
        paths.append(path)
    return paths

def cmd_publish(attempt, expected_sha):
    ctx=load_ctx()
    pe=participant_env()
    paths=changed_paths()
    if not paths: raise SystemExit("Claude produced no file changes")
    allowed=re.compile(r"^toy-result/stage-[1-4]/.+")
    bad=[p for p in paths if not allowed.fullmatch(p)]
    if bad: raise SystemExit(f"Claude scope violation: {bad}")
    for n in range(1,5):
        stage=Path("toy-result")/f"stage-{n}"
        for required in ("Dockerfile","RUN.md"):
            if not (stage/required).is_file():
                raise SystemExit(f"stage-{n}/{required} missing")
        other=[p for p in stage.rglob("*") if p.is_file() and p.name not in {"Dockerfile","RUN.md"}]
        if not other: raise SystemExit(f"stage-{n} has no source file")
    run(["git","diff","--check"])
    run(["git","config","user.name","BAND Implementer (Claude Code)"])
    run(["git","config","user.email","band-implementer@users.noreply.github.com"])
    run(["git","add",*paths])
    run(["git","commit","-m",f"toy: Claude Implementer attempt {attempt} for {ctx['branch']}"])
    revision=run(["git","rev-parse","HEAD"]).stdout.strip()
    lease=f"refs/heads/{ctx['branch']}:{expected_sha}"
    run(["git","push",f"--force-with-lease={lease}","origin",f"HEAD:{ctx['branch']}"])
    parts=resolve_participants(ctx["room_id"],pe["coord_key"],{pe["coord_id"],pe["impl_id"],pe["review_id"]})
    coord,impl,reviewer=parts[pe["coord_id"]],parts[pe["impl_id"]],parts[pe["review_id"]]
    post_message(ctx["room_id"], pe["impl_key"],
        f"@{coord['handle']} @{reviewer['handle']} TOY_IMPLEMENTATION_READY run_token={ctx['token']} "
        f"revision={revision} attempt={attempt} runtime=Claude_Code. Implementation committed; independent review required.",
        [{"id":coord["id"],"name":coord["name"],"handle":coord["handle"]},
         {"id":reviewer["id"],"name":reviewer["name"],"handle":reviewer["handle"]}])
    post_message(ctx["room_id"], pe["coord_key"],
        f"@{reviewer['handle']} TOY_REVIEW_HANDOFF run_token={ctx['token']} revision={revision} attempt={attempt}. "
        "Independently verify exact committed candidate against all four specs using official isolated harness. "
        "Do not repair production code yourself.",
        [{"id":reviewer["id"],"name":reviewer["name"],"handle":reviewer["handle"]}])
    ctx[f"revision_{attempt}"]=revision
    save_ctx(ctx)
    write_output("revision",revision)

def cmd_review(attempt, revision):
    ctx=load_ctx()
    pe=participant_env()
    current=run(["git","rev-parse","HEAD"]).stdout.strip()
    if current != revision: raise SystemExit(f"review revision mismatch: {current} != {revision}")
    kickoff=Path(os.environ["KICKOFF"])
    out_dir=Path(os.environ["RUNNER_TEMP"])/f"toy-all-attempt-{attempt}"
    cmd=["python","-m","harness","run","--track","toy","--repo",str(Path.cwd()/"toy-result"),
         "--all","--mode","isolated","--out",str(out_dir)]
    p=run(cmd,cwd=kickoff,check=False,timeout=2400)
    artifact=Path("artifacts")/"toy-rehearsal"
    artifact.mkdir(parents=True,exist_ok=True)
    stdout_path=artifact/f"attempt-{attempt}-harness.stdout"
    stderr_path=artifact/f"attempt-{attempt}-harness.stderr"
    stdout_path.write_text(p.stdout,encoding="utf-8")
    stderr_path.write_text(p.stderr,encoding="utf-8")
    summary_path=out_dir/"summary.json"
    summary=json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.exists() else {}
    parts=resolve_participants(ctx["room_id"],pe["coord_key"],{pe["coord_id"],pe["impl_id"],pe["review_id"]})
    coord,impl,reviewer=parts[pe["coord_id"]],parts[pe["impl_id"]],parts[pe["review_id"]]
    short=json.dumps(summary,separators=(",",":"))[:3500]
    if p.returncode==0:
        verdict="ACCEPT"
        msg=(f"@{impl['handle']} @{coord['handle']} ACCEPT {revision} run_token={ctx['token']} attempt={attempt}. "
             f"Official isolated Toy harness exit=0 summary={short}.")
    else:
        verdict="REJECT"
        tail=(p.stdout+"\n"+p.stderr)[-5000:]
        msg=(f"@{impl['handle']} @{coord['handle']} REJECT {revision} run_token={ctx['token']} attempt={attempt}. "
             f"Official isolated Toy harness exit={p.returncode}. Reproduction tail:\n{tail}")
    review_msg=post_message(ctx["room_id"],pe["review_key"],msg,
        [{"id":impl["id"],"name":impl["name"],"handle":impl["handle"]},
         {"id":coord["id"],"name":coord["name"],"handle":coord["handle"]}])
    evidence={"status":verdict,"attempt":attempt,"room_id":ctx["room_id"],"pr":ctx["pr"],"branch":ctx["branch"],
              "run_token":ctx["token"],"revision":revision,"runtime":"CLAUDE_CODE_OAUTH",
              "review_message_id":str((review_msg.get("data") or {}).get("id") or ""),
              "harness_exit":p.returncode,"summary":summary,"human_steering_after_pr_open":False}
    (artifact/f"evidence-attempt-{attempt}.json").write_text(json.dumps(evidence,indent=2),encoding="utf-8")
    write_output("verdict",verdict)
    write_output("harness_exit",str(p.returncode))
    if verdict=="ACCEPT":
        terminal(ctx["repo"],ctx["pr"],ctx,"ACCEPT",revision=revision,harness_exit=0,attempt=attempt)
    elif attempt==1:
        tail=(p.stdout+"\n"+p.stderr)[-6500:]
        post_message(ctx["room_id"],pe["coord_key"],
            f"@{impl['handle']} TOY_REPAIR_REQUESTED run_token={ctx['token']} rejected_revision={revision}. "
            "Repair the rejected candidate from Reviewer evidence and return it for independent re-review. "
            "Do not ask the human for steering.",
            [{"id":impl["id"],"name":impl["name"],"handle":impl["handle"]}])
        repair_context = f"""Toy Factory autonomous repair attempt 2/2.
Run token: {ctx['token']}
Rejected revision: {revision}

Read all four specs in toy-input/stage-1.md through stage-4.md and inspect the current implementation.
The independent official isolated harness rejected attempt 1. Fix the implementation so every stage passes all inherited requirements.
Modify ONLY toy-result/stage-1/ through toy-result/stage-4/.
Do not commit or push.
Reviewer evidence tail:
{tail}
"""
        write_output_multiline("repair_context", repair_context)
    else:
        terminal(ctx["repo"],ctx["pr"],ctx,"REJECT",revision=revision,harness_exit=p.returncode,attempt=attempt)

def cmd_block(reason):
    if not CTX_PATH.exists():
        print("No context exists; nothing to terminalize")
        return
    ctx=load_ctx(); pe=participant_env()
    terminal(ctx["repo"],ctx["pr"],ctx,"BLOCKED",reason=reason)
    parts=resolve_participants(ctx["room_id"],pe["coord_key"],{pe["impl_id"],pe["review_id"]})
    mentions=[{"id":p["id"],"name":p["name"],"handle":p["handle"]} for p in parts.values()]
    post_message(ctx["room_id"],pe["coord_key"],
        f"TOY_REHEARSAL_TERMINAL status=BLOCKED reason={reason} run_token={ctx['token']} "
        "Fail closed; do not promote Track Lock.",mentions)

def main():
    if len(sys.argv)<2: raise SystemExit("usage: claude_pipeline.py prepare|publish|review|block ...")
    cmd=sys.argv[1]
    if cmd=="prepare": cmd_prepare()
    elif cmd=="publish": cmd_publish(int(sys.argv[2]),sys.argv[3])
    elif cmd=="review": cmd_review(int(sys.argv[2]),sys.argv[3])
    elif cmd=="block": cmd_block(sys.argv[2])
    else: raise SystemExit(f"unknown command: {cmd}")

if __name__=="__main__":
    main()
