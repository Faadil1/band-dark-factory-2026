#!/usr/bin/env python3
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

BAND_BASE = "https://app.band.ai/api/v1/agent"
CTX_PATH = Path(os.environ.get("RUNNER_TEMP", "/tmp")) / "pocketful-stage1-context.json"
SPEC_PATH = Path("pocketful-input/stage-1.md")
RESULT_ROOT = Path("pocketful-result")
STAGE_DIR = RESULT_ROOT / "stage-1"

def run(cmd, *, cwd=None, input_text=None, check=True, timeout=None):
    p = subprocess.run(cmd, cwd=cwd, input=input_text, text=True, capture_output=True, timeout=timeout)
    if check and p.returncode != 0:
        raise SystemExit(f"command failed: {' '.join(cmd)}\n{p.stdout}\n{p.stderr}")
    return p

def curl_json(method, url, api_key, payload=None):
    out = Path(os.environ["RUNNER_TEMP"]) / "band-pocketful-response.json"
    cmd = ["curl","--silent","--show-error","--user-agent","BAND-Dark-Factory-2026-Pocketful/1.0",
           "--output",str(out),"--write-out","%{http_code}","-X",method,
           "-H",f"X-API-Key: {api_key}","-H","Accept: application/json"]
    if payload is not None:
        cmd += ["-H","Content-Type: application/json","-d",json.dumps(payload)]
    cmd.append(url)
    p=run(cmd)
    code=p.stdout.strip()
    body=json.loads(out.read_text(encoding="utf-8") or "{}")
    if code not in {"200","201"}:
        raise SystemExit(f"BAND {method} {url} failed HTTP {code}: {body}")
    return body

def post_message(room_id, api_key, content, mentions):
    if len(content) > 15500:
        raise SystemExit(f"BAND message too large: {len(content)}")
    return curl_json("POST",f"{BAND_BASE}/chats/{room_id}/messages",api_key,
                     {"message":{"content":content,"mentions":mentions}})

def resolve_participants(room_id, api_key, ids):
    payload=curl_json("GET",f"{BAND_BASE}/chats/{room_id}/participants",api_key)
    data=payload.get("data") or []
    if isinstance(data,dict):
        data=data.get("participants") or data.get("items") or []
    found={}
    for item in data:
        iid=str(item.get("id") or item.get("participant_id") or "")
        if iid in ids:
            handle=str(item.get("handle") or "").lstrip("@")
            if not handle:
                raise SystemExit(f"missing handle for {iid}")
            found[iid]={"id":iid,"name":str(item.get("name") or handle),"handle":handle}
    missing=set(ids)-set(found)
    if missing:
        raise SystemExit(f"missing BAND participants: {sorted(missing)}")
    return found

def gh_comment(repo, pr, body):
    p=run(["gh","api","--method","POST","-H","Accept: application/vnd.github+json",
           f"repos/{repo}/issues/{pr}/comments","--input","-"],input_text=json.dumps({"body":body}))
    return json.loads(p.stdout)

def write_output(key,value):
    with open(os.environ["GITHUB_OUTPUT"],"a",encoding="utf-8") as f:
        f.write(f"{key}={value}\n")

def write_output_multiline(key,value):
    marker="POCKETFUL_REPAIR_CONTEXT_EOF"
    if marker in value:
        value=value.replace(marker,"POCKETFUL_REPAIR_CONTEXT")
    with open(os.environ["GITHUB_OUTPUT"],"a",encoding="utf-8") as f:
        f.write(f"{key}<<{marker}\n{value}\n{marker}\n")

def identity():
    event=json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8"))
    pr=int(event["pull_request"]["number"])
    branch=str(event["pull_request"]["head"]["ref"])
    sha=str(event["pull_request"]["head"]["sha"])
    m=re.fullmatch(r"pocketful/stage-1-run-(\d+)",branch)
    if not m:
        raise SystemExit(f"unexpected Pocketful Stage 1 branch: {branch}")
    run_no=int(m.group(1))
    token=f"pocketful-s1-r{run_no}-pr{pr}-{sha[:12]}"
    return pr,branch,sha,run_no,token

def participant_env():
    return {
        "coord_id":os.environ["BAND_COORDINATOR_AGENT_ID"].strip(),
        "coord_key":os.environ["BAND_COORDINATOR_API_KEY"].strip(),
        "impl_id":os.environ["BAND_IMPLEMENTER_AGENT_ID"].strip(),
        "impl_key":os.environ["BAND_IMPLEMENTER_API_KEY"].strip(),
        "review_id":os.environ["BAND_REVIEWER_AGENT_ID"].strip(),
        "review_key":os.environ["BAND_REVIEWER_API_KEY"].strip(),
    }

def save_ctx(ctx):
    CTX_PATH.write_text(json.dumps(ctx,indent=2),encoding="utf-8")

def load_ctx():
    return json.loads(CTX_PATH.read_text(encoding="utf-8"))

def terminal(repo,pr,ctx,status,*,revision=None,harness_exit=None,reason=None,attempt=None):
    fields=["POCKETFUL_STAGE_TERMINAL",f"status={status}",f"run_token={ctx['token']}",
            f"branch={ctx['branch']}","stage=1","runtime=CLAUDE_CODE_OAUTH"]
    if revision: fields.append(f"revision={revision}")
    if harness_exit is not None: fields.append(f"harness_exit={harness_exit}")
    if reason: fields.append(f"reason={reason}")
    if attempt is not None: fields.append(f"attempt={attempt}")
    gh_comment(repo,pr," ".join(fields))

def chunks(text,limit=10500):
    out=[]; buf=""
    for line in text.splitlines(keepends=True):
        if len(line)>limit:
            if buf: out.append(buf); buf=""
            for i in range(0,len(line),limit): out.append(line[i:i+limit])
        elif len(buf)+len(line)>limit:
            out.append(buf); buf=line
        else:
            buf+=line
    if buf: out.append(buf)
    return out

def cmd_prepare():
    repo=os.environ["GITHUB_REPOSITORY"]
    pr,branch,sha,run_no,token=identity()
    pe=participant_env()
    if not SPEC_PATH.is_file():
        raise SystemExit("Pocketful Stage 1 spec missing")
    if (STAGE_DIR/"Dockerfile").exists():
        raise SystemExit("preseeded Pocketful Stage 1 implementation detected")
    spec=SPEC_PATH.read_text(encoding="utf-8")
    spec_sha=hashlib.sha256(spec.encode()).hexdigest()
    room=curl_json("POST",f"{BAND_BASE}/chats",pe["coord_key"],{"chat":{}})
    rd=room.get("data") or {}
    room_id=str(rd.get("id") or rd.get("chat_id") or rd.get("room_id") or "")
    if not room_id: raise SystemExit("no BAND room id")
    for pid in (pe["impl_id"],pe["review_id"]):
        curl_json("POST",f"{BAND_BASE}/chats/{room_id}/participants",pe["coord_key"],
                  {"participant":{"participant_id":pid}})
    parts=resolve_participants(room_id,pe["coord_key"],{pe["coord_id"],pe["impl_id"],pe["review_id"]})
    coord,impl,reviewer=parts[pe["coord_id"]],parts[pe["impl_id"]],parts[pe["review_id"]]
    mentions=[
      {"id":impl["id"],"name":impl["name"],"handle":impl["handle"]},
      {"id":reviewer["id"],"name":reviewer["name"],"handle":reviewer["handle"]},
    ]
    spec_parts=chunks(spec)
    ids=[]
    head=(f"@{impl['handle']} @{reviewer['handle']} POCKETFUL_STAGE_1 run_token={token}. "
          f"This is the single Stage 1 task. Complete spec SHA256={spec_sha}; it follows in {len(spec_parts)} "
          "autonomous Coordinator messages that together form one task. Implementer must build only "
          "pocketful-result/stage-1/. Reviewer must independently verify the exact committed candidate against "
          "the complete spec and the official isolated harness. Build to the written requirements, not merely "
          "the public tests. Do not ask the human for steering.")
    ids.append(str((post_message(room_id,pe["coord_key"],head,mentions).get("data") or {}).get("id") or ""))
    for i,part in enumerate(spec_parts,1):
        body=(f"@{impl['handle']} @{reviewer['handle']} POCKETFUL_STAGE_1_SPEC "
              f"run_token={token} chunk={i}/{len(spec_parts)} spec_sha256={spec_sha}\n{part}")
        ids.append(str((post_message(room_id,pe["coord_key"],body,mentions).get("data") or {}).get("id") or ""))
    ctx={"repo":repo,"pr":pr,"branch":branch,"initial_sha":sha,"run_no":run_no,"token":token,
         "room_id":room_id,"spec_sha256":spec_sha,"coord":coord,"impl":impl,"reviewer":reviewer,
         "coordinator_message_ids":ids}
    save_ctx(ctx)
    gh_comment(repo,pr,"\n".join([
      "POCKETFUL_STAGE_CONTEXT",
      f"POCKETFUL_RUN_TOKEN={token}",
      f"POCKETFUL_BRANCH={branch}",
      "POCKETFUL_STAGE=1",
      f"POCKETFUL_ROOM_ID={room_id}",
      f"POCKETFUL_SPEC_SHA256={spec_sha}",
      f"POCKETFUL_COORDINATOR_MESSAGE_IDS={','.join(ids)}",
      "POCKETFUL_IMPLEMENTER_RUNTIME=CLAUDE_CODE_OAUTH",
    ]))
    for k,v in {"run_token":token,"branch":branch,"initial_sha":sha,"room_id":room_id,"spec_sha256":spec_sha}.items():
        write_output(k,v)

def changed_paths():
    p=run(["git","status","--porcelain=v1","--untracked-files=all"])
    paths=[]
    for raw in p.stdout.splitlines():
        if not raw.strip(): continue
        path=raw[3:]
        if " -> " in path: path=path.split(" -> ",1)[1]
        paths.append(path)
    return paths

def cmd_publish(attempt,expected_sha):
    ctx=load_ctx(); pe=participant_env()
    paths=changed_paths()
    if not paths: raise SystemExit("Claude produced no file changes")
    allowed=re.compile(r"^pocketful-result/stage-1/.+")
    bad=[p for p in paths if not allowed.fullmatch(p)]
    if bad: raise SystemExit(f"Claude scope violation: {bad}")
    for required in ("Dockerfile","RUN.md"):
        if not (STAGE_DIR/required).is_file():
            raise SystemExit(f"stage-1/{required} missing")
    source=[p for p in STAGE_DIR.rglob("*") if p.is_file() and p.name not in {"Dockerfile","RUN.md"}]
    if not source: raise SystemExit("stage-1 has no source file")
    run(["git","diff","--check"])
    run(["git","config","user.name","BAND Implementer (Claude Code)"])
    run(["git","config","user.email","band-implementer@users.noreply.github.com"])
    run(["git","add",*paths])
    run(["git","commit","-m",f"pocketful: Stage 1 Claude attempt {attempt} for {ctx['branch']}"])
    revision=run(["git","rev-parse","HEAD"]).stdout.strip()
    lease=f"refs/heads/{ctx['branch']}:{expected_sha}"
    run(["git","push",f"--force-with-lease={lease}","origin",f"HEAD:{ctx['branch']}"])
    parts=resolve_participants(ctx["room_id"],pe["coord_key"],{pe["coord_id"],pe["impl_id"],pe["review_id"]})
    coord,impl,reviewer=parts[pe["coord_id"]],parts[pe["impl_id"]],parts[pe["review_id"]]
    post_message(ctx["room_id"],pe["impl_key"],
        f"@{coord['handle']} @{reviewer['handle']} POCKETFUL_IMPLEMENTATION_READY run_token={ctx['token']} "
        f"stage=1 revision={revision} attempt={attempt} runtime=Claude_Code. Implementation committed; independent review required.",
        [{"id":coord["id"],"name":coord["name"],"handle":coord["handle"]},
         {"id":reviewer["id"],"name":reviewer["name"],"handle":reviewer["handle"]}])
    post_message(ctx["room_id"],pe["coord_key"],
        f"@{reviewer['handle']} POCKETFUL_REVIEW_HANDOFF run_token={ctx['token']} stage=1 revision={revision} "
        f"attempt={attempt} spec_sha256={ctx['spec_sha256']}. Independently verify exact committed candidate "
        "against the complete Stage 1 spec. Use official isolated harness with --repo pocketful-result --stage 1. "
        "Reject overshoot as well as conformance failure. Do not repair production code yourself.",
        [{"id":reviewer["id"],"name":reviewer["name"],"handle":reviewer["handle"]}])
    ctx[f"revision_{attempt}"]=revision; save_ctx(ctx); write_output("revision",revision)

def cmd_review(attempt,revision):
    ctx=load_ctx(); pe=participant_env()
    current=run(["git","rev-parse","HEAD"]).stdout.strip()
    if current!=revision: raise SystemExit(f"review revision mismatch: {current} != {revision}")
    kickoff=Path(os.environ["KICKOFF"])
    out_dir=Path(os.environ["RUNNER_TEMP"])/f"pocketful-stage1-attempt-{attempt}"
    cmd=["python","-m","harness","run","--track","pocketful","--repo",str(Path.cwd()/RESULT_ROOT),
         "--stage","1","--mode","isolated","--out",str(out_dir)]
    p=run(cmd,cwd=kickoff,check=False,timeout=2700)
    artifact=Path("artifacts")/"pocketful-stage-1"; artifact.mkdir(parents=True,exist_ok=True)
    (artifact/f"attempt-{attempt}-harness.stdout").write_text(p.stdout,encoding="utf-8")
    (artifact/f"attempt-{attempt}-harness.stderr").write_text(p.stderr,encoding="utf-8")
    report_path=out_dir/"report.json"
    report=json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else {}
    accepted=(p.returncode==0 and report.get("state")=="completed" and
              str(report.get("claimed_stage") or "")=="1" and not report.get("overshoot"))
    parts=resolve_participants(ctx["room_id"],pe["coord_key"],{pe["coord_id"],pe["impl_id"],pe["review_id"]})
    coord,impl,reviewer=parts[pe["coord_id"]],parts[pe["impl_id"]],parts[pe["review_id"]]
    short=json.dumps(report,separators=(",",":"))[-5000:]
    if accepted:
        verdict="ACCEPT"
        msg=(f"@{impl['handle']} @{coord['handle']} ACCEPT {revision} run_token={ctx['token']} stage=1 "
             f"attempt={attempt}. Official isolated Pocketful harness exit=0; claimed_stage=1; overshoot=null. "
             f"report_tail={short}")
    else:
        verdict="REJECT"
        tail=(p.stdout+"\n"+p.stderr)[-7000:]
        msg=(f"@{impl['handle']} @{coord['handle']} REJECT {revision} run_token={ctx['token']} stage=1 "
             f"attempt={attempt}. harness_exit={p.returncode} claimed_stage={report.get('claimed_stage')} "
             f"overshoot={report.get('overshoot')}. Reproduction tail:\n{tail}")
    review_msg=post_message(ctx["room_id"],pe["review_key"],msg,
        [{"id":impl["id"],"name":impl["name"],"handle":impl["handle"]},
         {"id":coord["id"],"name":coord["name"],"handle":coord["handle"]}])
    evidence={"status":verdict,"stage":1,"attempt":attempt,"room_id":ctx["room_id"],"pr":ctx["pr"],
              "branch":ctx["branch"],"run_token":ctx["token"],"spec_sha256":ctx["spec_sha256"],
              "revision":revision,"runtime":"CLAUDE_CODE_OAUTH",
              "review_message_id":str((review_msg.get("data") or {}).get("id") or ""),
              "harness_exit":p.returncode,"claimed_stage":report.get("claimed_stage"),
              "overshoot":report.get("overshoot"),"report":report,"human_steering_after_pr_open":False}
    (artifact/f"evidence-attempt-{attempt}.json").write_text(json.dumps(evidence,indent=2),encoding="utf-8")
    write_output("verdict",verdict); write_output("harness_exit",str(p.returncode))
    if verdict=="ACCEPT":
        terminal(ctx["repo"],ctx["pr"],ctx,"ACCEPT",revision=revision,harness_exit=0,attempt=attempt)
    elif attempt==1:
        tail=(p.stdout+"\n"+p.stderr)[-9000:]
        post_message(ctx["room_id"],pe["coord_key"],
            f"@{impl['handle']} POCKETFUL_REPAIR_REQUESTED run_token={ctx['token']} stage=1 "
            f"rejected_revision={revision}. Repair from Reviewer evidence and return a new exact revision for "
            "independent re-review. Do not ask the human for steering.",
            [{"id":impl["id"],"name":impl["name"],"handle":impl["handle"]}])
        repair=f"""Pocketful Stage 1 autonomous repair attempt 2/2.
Run token: {ctx['token']}
Rejected revision: {revision}
Spec SHA256: {ctx['spec_sha256']}

Read pocketful-input/stage-1.md and inspect the current implementation.
Repair every violation identified by the independent official isolated harness.
Modify ONLY pocketful-result/stage-1/.
Do not commit or push. Do not ask the human for clarification.
Reviewer evidence tail:
{tail}
"""
        write_output_multiline("repair_context",repair)
    else:
        terminal(ctx["repo"],ctx["pr"],ctx,"REJECT",revision=revision,harness_exit=p.returncode,attempt=attempt)

def cmd_block(reason):
    if not CTX_PATH.exists():
        print("No context exists; nothing to terminalize"); return
    ctx=load_ctx(); pe=participant_env()
    terminal(ctx["repo"],ctx["pr"],ctx,"BLOCKED",reason=reason)
    parts=resolve_participants(ctx["room_id"],pe["coord_key"],{pe["impl_id"],pe["review_id"]})
    mentions=[{"id":p["id"],"name":p["name"],"handle":p["handle"]} for p in parts.values()]
    post_message(ctx["room_id"],pe["coord_key"],
        f"POCKETFUL_STAGE_TERMINAL status=BLOCKED stage=1 reason={reason} run_token={ctx['token']} "
        "Fail closed; do not promote the real-track slice.",mentions)

def main():
    if len(sys.argv)<2: raise SystemExit("usage: stage1_pipeline.py prepare|publish|review|block ...")
    cmd=sys.argv[1]
    if cmd=="prepare": cmd_prepare()
    elif cmd=="publish": cmd_publish(int(sys.argv[2]),sys.argv[3])
    elif cmd=="review": cmd_review(int(sys.argv[2]),sys.argv[3])
    elif cmd=="block": cmd_block(sys.argv[2])
    else: raise SystemExit(f"unknown command: {cmd}")

if __name__=="__main__":
    main()
