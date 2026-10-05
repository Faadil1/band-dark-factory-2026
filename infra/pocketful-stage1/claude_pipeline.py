#!/usr/bin/env python3
import json, os, re, subprocess, sys
from pathlib import Path

BAND_BASE="https://app.band.ai/api/v1/agent"
CTX=Path(os.environ.get("RUNNER_TEMP","/tmp"))/"pocketful-stage1-context.json"

def run(cmd, cwd=None, input_text=None, check=True, timeout=None):
    p=subprocess.run(cmd,cwd=cwd,input=input_text,text=True,capture_output=True,timeout=timeout)
    if check and p.returncode!=0:
        raise SystemExit(f"command failed: {' '.join(cmd)}\n{p.stdout}\n{p.stderr}")
    return p

def curl_json(method,url,key,payload=None):
    out=Path(os.environ["RUNNER_TEMP"])/"band-pocketful-response.json"
    cmd=["curl","--silent","--show-error","--user-agent","BAND-Dark-Factory-Pocketful/1.0",
         "--output",str(out),"--write-out","%{http_code}","-X",method,
         "-H",f"X-API-Key: {key}","-H","Accept: application/json"]
    if payload is not None:
        cmd += ["-H","Content-Type: application/json","-d",json.dumps(payload)]
    cmd.append(url)
    p=run(cmd); code=p.stdout.strip()
    body=json.loads(out.read_text(encoding="utf-8") or "{}")
    if code not in {"200","201"}:
        raise SystemExit(f"BAND {method} failed HTTP {code}: {body}")
    return body

def participants_env():
    return {
      "coord_id":os.environ["BAND_COORDINATOR_AGENT_ID"].strip(),
      "coord_key":os.environ["BAND_COORDINATOR_API_KEY"].strip(),
      "impl_id":os.environ["BAND_IMPLEMENTER_AGENT_ID"].strip(),
      "impl_key":os.environ["BAND_IMPLEMENTER_API_KEY"].strip(),
      "review_id":os.environ["BAND_REVIEWER_AGENT_ID"].strip(),
      "review_key":os.environ["BAND_REVIEWER_API_KEY"].strip(),
    }

def resolve(room,key,ids):
    payload=curl_json("GET",f"{BAND_BASE}/chats/{room}/participants",key)
    data=payload.get("data") or []
    if isinstance(data,dict): data=data.get("participants") or data.get("items") or []
    found={}
    for x in data:
        iid=str(x.get("id") or x.get("participant_id") or "")
        if iid in ids:
            found[iid]={"id":iid,"name":str(x.get("name") or x.get("handle") or iid),
                        "handle":str(x.get("handle") or "").lstrip("@")}
    if set(ids)-set(found): raise SystemExit(f"missing BAND participants: {set(ids)-set(found)}")
    return found

def post(room,key,content,mentions):
    if len(content)>15500: raise SystemExit(f"BAND message too large: {len(content)}")
    return curl_json("POST",f"{BAND_BASE}/chats/{room}/messages",key,
                     {"message":{"content":content,"mentions":mentions}})

def gh_comment(repo,pr,body):
    p=run(["gh","api","--method","POST","-H","Accept: application/vnd.github+json",
           f"repos/{repo}/issues/{pr}/comments","--input","-"],input_text=json.dumps({"body":body}))
    return json.loads(p.stdout)

def output(k,v):
    with open(os.environ["GITHUB_OUTPUT"],"a",encoding="utf-8") as f: f.write(f"{k}={v}\n")

def output_multi(k,v):
    marker="POCKETFUL_REPAIR_EOF"
    with open(os.environ["GITHUB_OUTPUT"],"a",encoding="utf-8") as f:
        f.write(f"{k}<<{marker}\n{v}\n{marker}\n")

def identity():
    ev=json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
    pr=int(ev["pull_request"]["number"]); branch=str(ev["pull_request"]["head"]["ref"]); sha=str(ev["pull_request"]["head"]["sha"])
    m=re.fullmatch(r"pocketful/stage-1-run-(\d+)",branch)
    if not m: raise SystemExit(f"unexpected branch {branch}")
    run_no=int(m.group(1)); token=f"pocketful-s1-r{run_no}-pr{pr}-{sha[:12]}"
    return pr,branch,sha,run_no,token

def load(): return json.loads(CTX.read_text())
def save(x): CTX.write_text(json.dumps(x,indent=2))

def terminal(ctx,status,revision=None,harness_exit=None,reason=None,attempt=None):
    fields=["POCKETFUL_STAGE_1_TERMINAL",f"status={status}",f"run_token={ctx['token']}",
            f"branch={ctx['branch']}","runtime=CLAUDE_CODE_OAUTH"]
    if revision: fields.append(f"revision={revision}")
    if harness_exit is not None: fields.append(f"harness_exit={harness_exit}")
    if reason: fields.append(f"reason={reason}")
    if attempt is not None: fields.append(f"attempt={attempt}")
    gh_comment(ctx["repo"],ctx["pr"]," ".join(fields))

def cmd_prepare():
    repo=os.environ["GITHUB_REPOSITORY"]; pr,branch,sha,run_no,token=identity(); pe=participants_env()
    if (Path("pocketful-result")/"stage-1"/"Dockerfile").exists():
        raise SystemExit("preseeded Pocketful implementation detected")
    room=curl_json("POST",f"{BAND_BASE}/chats",pe["coord_key"],{"chat":{}})
    rd=room.get("data") or {}; room_id=str(rd.get("id") or rd.get("chat_id") or rd.get("room_id") or "")
    if not room_id: raise SystemExit("no BAND room id")
    for pid in (pe["impl_id"],pe["review_id"]):
        curl_json("POST",f"{BAND_BASE}/chats/{room_id}/participants",pe["coord_key"],{"participant":{"participant_id":pid}})
    parts=resolve(room_id,pe["coord_key"],{pe["coord_id"],pe["impl_id"],pe["review_id"]})
    coord,impl,reviewer=parts[pe["coord_id"]],parts[pe["impl_id"]],parts[pe["review_id"]]
    spec=Path("pocketful-input/stage-1.md").read_text()
    intro=(f"@{impl['handle']} POCKETFUL_STAGE_1 run_token={token}. This is the first real-track run. "
           "Implement exactly Stage 1 under pocketful-result/stage-1. Do not overshoot into later stages. "
           "Build to the complete written specification, not merely public tests. Do not ask the human for steering. "
           "Reviewer independently runs the pinned official isolated harness. Complete requirements follow:\n\n")
    # BAND has a message-size limit; split authoritative spec into ordered self-contained chunks.
    chunks=[]
    text=intro+spec
    while text:
        chunks.append(text[:14500]); text=text[14500:]
    msg_ids=[]
    for i,ch in enumerate(chunks,1):
        prefix="" if i==1 else f"POCKETFUL_STAGE_1_SPEC_CONTINUED {i}/{len(chunks)} run_token={token}\n"
        m=post(room_id,pe["coord_key"],prefix+ch,[{"id":impl["id"],"name":impl["name"],"handle":impl["handle"]}])
        msg_ids.append(str((m.get("data") or {}).get("id") or ""))
    ctx={"repo":repo,"pr":pr,"branch":branch,"initial_sha":sha,"run_no":run_no,"token":token,"room_id":room_id,
         "coord":coord,"impl":impl,"reviewer":reviewer,"handoff_ids":msg_ids}
    save(ctx)
    gh_comment(repo,pr,"\n".join(["POCKETFUL_STAGE_1_CONTEXT",f"RUN_TOKEN={token}",f"BRANCH={branch}",
                                   f"ROOM_ID={room_id}",f"COORDINATOR_HANDOFF_IDS={','.join(msg_ids)}",
                                   "IMPLEMENTER_RUNTIME=CLAUDE_CODE_OAUTH"]))
    for k,v in {"run_token":token,"branch":branch,"initial_sha":sha,"room_id":room_id}.items(): output(k,v)

def changed_paths():
    p=run(["git","status","--porcelain=v1","--untracked-files=all"])
    out=[]
    for raw in p.stdout.splitlines():
        if not raw.strip(): continue
        path=raw[3:]
        if " -> " in path: path=path.split(" -> ",1)[1]
        out.append(path)
    return out

def cmd_publish(attempt,expected_sha):
    ctx=load(); pe=participants_env(); paths=changed_paths()
    if not paths: raise SystemExit("Claude produced no file changes")
    bad=[p for p in paths if not re.fullmatch(r"pocketful-result/stage-1/.+",p)]
    if bad: raise SystemExit(f"Claude scope violation: {bad}")
    stage=Path("pocketful-result/stage-1")
    for req in ("Dockerfile","RUN.md"):
        if not (stage/req).is_file(): raise SystemExit(f"stage-1/{req} missing")
    others=[p for p in stage.rglob("*") if p.is_file() and p.name not in {"Dockerfile","RUN.md"}]
    if not others: raise SystemExit("stage-1 has no source file")
    run(["git","diff","--check"]); run(["git","config","user.name","BAND Implementer (Claude Code)"])
    run(["git","config","user.email","band-implementer@users.noreply.github.com"]); run(["git","add",*paths])
    run(["git","commit","-m",f"pocketful: Stage 1 Claude attempt {attempt}"])
    revision=run(["git","rev-parse","HEAD"]).stdout.strip()
    run(["git","push",f"--force-with-lease=refs/heads/{ctx['branch']}:{expected_sha}","origin",f"HEAD:{ctx['branch']}"])
    parts=resolve(ctx["room_id"],pe["coord_key"],{pe["coord_id"],pe["impl_id"],pe["review_id"]})
    coord,impl,reviewer=parts[pe["coord_id"]],parts[pe["impl_id"]],parts[pe["review_id"]]
    post(ctx["room_id"],pe["impl_key"],
         f"@{coord['handle']} @{reviewer['handle']} POCKETFUL_IMPLEMENTATION_READY run_token={ctx['token']} revision={revision} attempt={attempt} runtime=Claude_Code. Independent review required.",
         [{"id":coord["id"],"name":coord["name"],"handle":coord["handle"]},{"id":reviewer["id"],"name":reviewer["name"],"handle":reviewer["handle"]}])
    post(ctx["room_id"],pe["coord_key"],
         f"@{reviewer['handle']} POCKETFUL_REVIEW_HANDOFF run_token={ctx['token']} revision={revision} attempt={attempt}. Independently verify exact Stage 1 candidate against the complete spec using pinned official isolated harness. Do not repair production code yourself.",
         [{"id":reviewer["id"],"name":reviewer["name"],"handle":reviewer["handle"]}])
    ctx[f"revision_{attempt}"]=revision; save(ctx); output("revision",revision)

def cmd_review(attempt,revision):
    ctx=load(); pe=participants_env()
    current=run(["git","rev-parse","HEAD"]).stdout.strip()
    if current!=revision: raise SystemExit(f"review revision mismatch {current} != {revision}")
    kickoff=Path(os.environ["KICKOFF"]); out=Path(os.environ["RUNNER_TEMP"])/f"pocketful-stage1-attempt-{attempt}"
    cmd=["python","-m","harness","run","--track","pocketful","--repo",str(Path.cwd()/"pocketful-result"),
         "--stage","1","--mode","isolated","--out",str(out)]
    p=run(cmd,cwd=kickoff,check=False,timeout=3000)
    art=Path("artifacts/pocketful-stage-1"); art.mkdir(parents=True,exist_ok=True)
    (art/f"attempt-{attempt}.stdout").write_text(p.stdout); (art/f"attempt-{attempt}.stderr").write_text(p.stderr)
    report=out/"report.json"
    summary=json.loads(report.read_text()) if report.exists() else {}
    parts=resolve(ctx["room_id"],pe["coord_key"],{pe["coord_id"],pe["impl_id"],pe["review_id"]})
    coord,impl,reviewer=parts[pe["coord_id"]],parts[pe["impl_id"]],parts[pe["review_id"]]
    short=json.dumps(summary,separators=(",",":"))[:3500]
    if p.returncode==0:
        verdict="ACCEPT"
        msg=f"@{impl['handle']} @{coord['handle']} ACCEPT {revision} run_token={ctx['token']} attempt={attempt}. Official isolated Pocketful Stage 1 harness exit=0 report={short}."
    else:
        verdict="REJECT"; tail=(p.stdout+"\n"+p.stderr)[-6000:]
        msg=f"@{impl['handle']} @{coord['handle']} REJECT {revision} run_token={ctx['token']} attempt={attempt}. Official isolated Pocketful Stage 1 harness exit={p.returncode}. Reproduction tail:\n{tail}"
    rm=post(ctx["room_id"],pe["review_key"],msg,[{"id":impl["id"],"name":impl["name"],"handle":impl["handle"]},{"id":coord["id"],"name":coord["name"],"handle":coord["handle"]}])
    evidence={"status":verdict,"attempt":attempt,"room_id":ctx["room_id"],"run_token":ctx["token"],"revision":revision,
              "harness_exit":p.returncode,"report":summary,"review_message_id":str((rm.get("data") or {}).get("id") or ""),
              "human_steering_after_pr_open":False}
    (art/f"evidence-attempt-{attempt}.json").write_text(json.dumps(evidence,indent=2))
    output("verdict",verdict); output("harness_exit",str(p.returncode))
    if verdict=="ACCEPT":
        terminal(ctx,"ACCEPT",revision=revision,harness_exit=0,attempt=attempt)
    elif attempt==1:
        tail=(p.stdout+"\n"+p.stderr)[-7000:]
        post(ctx["room_id"],pe["coord_key"],
             f"@{impl['handle']} POCKETFUL_REPAIR_REQUESTED run_token={ctx['token']} rejected_revision={revision}. Repair only Stage 1 from Reviewer evidence and return for independent re-review. Do not ask the human for steering.",
             [{"id":impl["id"],"name":impl["name"],"handle":impl["handle"]}])
        repair=f"""Pocketful Stage 1 autonomous repair attempt 2/2.
Run token: {ctx['token']}
Rejected revision: {revision}

Read the full authoritative pocketful-input/stage-1.md and inspect the current Stage 1 implementation.
Repair the Reviewer-observed failures without adding future-stage behavior.
Modify ONLY pocketful-result/stage-1/.
Do not commit or push. Do not ask the human for steering.
Reviewer evidence tail:
{tail}
"""
        output_multi("repair_context",repair)
    else:
        terminal(ctx,"REJECT",revision=revision,harness_exit=p.returncode,attempt=attempt)

def cmd_block(reason):
    if not CTX.exists(): return
    ctx=load(); terminal(ctx,"BLOCKED",reason=reason)

def main():
    if len(sys.argv)<2: raise SystemExit("usage: prepare|publish|review|block")
    c=sys.argv[1]
    if c=="prepare": cmd_prepare()
    elif c=="publish": cmd_publish(int(sys.argv[2]),sys.argv[3])
    elif c=="review": cmd_review(int(sys.argv[2]),sys.argv[3])
    elif c=="block": cmd_block(sys.argv[2])
    else: raise SystemExit(c)
if __name__=="__main__": main()
