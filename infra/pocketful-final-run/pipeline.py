#!/usr/bin/env python3
import json, os, re, shutil, subprocess, sys, time
from pathlib import Path

BAND_BASE="https://app.band.ai/api/v1/agent"
ROOT=Path(os.environ.get("GITHUB_WORKSPACE",".")).resolve()
RESULT=ROOT/"submission-final-runtime"/"result"
TEMPLATES=ROOT/"submission-final"/"templates"
CTX=Path(os.environ.get("RUNNER_TEMP","/tmp"))/"pocketful-final-run-context.json"
ART=ROOT/"artifacts"/"pocketful-final-run"

def run(cmd,cwd=None,input_text=None,check=True,timeout=None):
    p=subprocess.run(cmd,cwd=cwd,input=input_text,text=True,capture_output=True,timeout=timeout)
    if check and p.returncode!=0:
        raise SystemExit(f"command failed: {' '.join(map(str,cmd))}\n{p.stdout}\n{p.stderr}")
    return p

def curl_json(method,url,key,payload=None):
    out=Path(os.environ["RUNNER_TEMP"])/"band-final-response.json"
    cmd=["curl","--silent","--show-error","--user-agent","BAND-Dark-Factory-Final/1.0",
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

def pe():
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
    missing=set(ids)-set(found)
    if missing: raise SystemExit(f"missing BAND participants: {missing}")
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
    marker="FINAL_REPAIR_EOF"
    with open(os.environ["GITHUB_OUTPUT"],"a",encoding="utf-8") as f:
        f.write(f"{k}<<{marker}\n{v}\n{marker}\n")

def identity():
    ev=json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
    pr=int(ev["pull_request"]["number"])
    branch=str(ev["pull_request"]["head"]["ref"])
    sha=str(ev["pull_request"]["head"]["sha"])
    m=re.fullmatch(r"submission/pocketful-final-run-(\d+)",branch)
    if not m: raise SystemExit(f"unexpected branch {branch}")
    run_no=int(m.group(1))
    token=f"pocketful-final-r{run_no}-pr{pr}-{sha[:12]}"
    return pr,branch,sha,run_no,token

def load(): return json.loads(CTX.read_text())
def save(x): CTX.write_text(json.dumps(x,indent=2))

def git(*args,check=True):
    return run(["git","-C",str(RESULT),*args],check=check)

def spec_text(stage):
    chunks=[]
    for n in range(1,stage+1):
        label="BASE STAGE 1 SPEC" if n==1 else f"STAGE {n} ADDITIONS"
        chunks.append(f"===== {label} =====\n"+(ROOT/f"pocketful-input/stage-{n}.md").read_text())
    return "\n\n".join(chunks)

def mention(x):
    return {"id":x["id"],"name":x["name"],"handle":x["handle"]}

def send_chunks(room,key,target,header,body):
    text=header+"\n\n"+body
    chunks=[]
    while text:
        chunks.append(text[:14000]); text=text[14000:]
    ids=[]
    for i,ch in enumerate(chunks,1):
        prefix="" if i==1 else f"CONTINUED {i}/{len(chunks)}\n"
        r=post(room,key,prefix+ch,[mention(target)])
        ids.append(str((r.get("data") or {}).get("id") or ""))
    return ids

def cmd_prepare():
    repo=os.environ["GITHUB_REPOSITORY"]; pr,branch,sha,run_no,token=identity()
    if RESULT.exists(): raise SystemExit("fresh result repository path already exists")
    RESULT.mkdir(parents=True)
    (RESULT/"mandates").mkdir()
    shutil.copy2(TEMPLATES/"README.md",RESULT/"README.md")
    shutil.copy2(TEMPLATES/"FACTORY.md",RESULT/"FACTORY.md")
    for name in ("coordinator.md","implementer.md","reviewer.md"):
        shutil.copy2(TEMPLATES/"mandates"/name,RESULT/"mandates"/name)
    git("init","-b","main")
    git("config","user.name","BAND Factory Bootstrap")
    git("config","user.email","band-factory@users.noreply.github.com")
    git("add",".")
    git("commit","-m","Initialize fresh submission result repository")
    initial=git("rev-parse","HEAD").stdout.strip()

    env=pe()
    room=curl_json("POST",f"{BAND_BASE}/chats",env["coord_key"],{"chat":{}})
    rd=room.get("data") or {}; room_id=str(rd.get("id") or rd.get("chat_id") or rd.get("room_id") or "")
    if not room_id: raise SystemExit("no BAND room id")
    for pid in (env["impl_id"],env["review_id"]):
        curl_json("POST",f"{BAND_BASE}/chats/{room_id}/participants",env["coord_key"],{"participant":{"participant_id":pid}})
    parts=resolve(room_id,env["coord_key"],{env["coord_id"],env["impl_id"],env["review_id"]})
    coord,impl,reviewer=parts[env["coord_id"]],parts[env["impl_id"]],parts[env["review_id"]]
    intro=(f"@{impl['handle']} @{reviewer['handle']} FINAL_DARK_FACTORY_RUN run_token={token}. "
           f"One fresh BAND room and one fresh git result repository have been created at {RESULT}. "
           "This run will build four stages sequentially. The human supplied only the initial run trigger. "
           "There must be no human steering, approval, clarification or retry request between stage dispatches. "
           "Each stage will extend the prior accepted stage, be committed in this fresh repository, and receive "
           "independent review before the next stage starts. Do not read or copy any earlier product implementation.")
    post(room_id,env["coord_key"],intro,[mention(impl),mention(reviewer)])
    ctx={"repo":repo,"pr":pr,"branch":branch,"trigger_sha":sha,"run_no":run_no,"token":token,
         "room_id":room_id,"coord":coord,"impl":impl,"reviewer":reviewer,
         "initial_result_revision":initial,"started_at_epoch":time.time(),"stages":{}}
    save(ctx)
    gh_comment(repo,pr,"\n".join(["POCKETFUL_FINAL_RUN_CONTEXT",f"RUN_TOKEN={token}",f"ROOM_ID={room_id}",
                                   f"FRESH_RESULT_INITIAL_REVISION={initial}",
                                   "RESULT_REPOSITORY=FRESH_EPHEMERAL_GIT_REPOSITORY",
                                   "HUMAN_STEERING_AFTER_PR_OPEN=FORBIDDEN"]))
    for k,v in {"run_token":token,"room_id":room_id,"result_path":str(RESULT),"initial_revision":initial}.items(): output(k,v)

def cmd_begin(stage):
    ctx=load(); env=pe()
    if stage<1 or stage>4: raise SystemExit("stage out of range")
    dst=RESULT/f"stage-{stage}"
    if dst.exists(): raise SystemExit(f"stage-{stage} already exists")
    if stage==1:
        dst.mkdir()
    else:
        src=RESULT/f"stage-{stage-1}"
        if not src.is_dir(): raise SystemExit(f"accepted stage-{stage-1} missing")
        shutil.copytree(src,dst)
        git("config","user.name","BAND Coordinator")
        git("config","user.email","band-coordinator@users.noreply.github.com")
        git("add",f"stage-{stage}")
        git("commit","-m",f"Seed Stage {stage} from accepted Stage {stage-1}")
    base=git("rev-parse","HEAD").stdout.strip()
    ctx["stages"][str(stage)]={"base_revision":base,"started_at_epoch":time.time(),"status":"ACTIVE","attempts":[]}
    save(ctx)
    parts=resolve(ctx["room_id"],env["coord_key"],{env["coord_id"],env["impl_id"],env["review_id"]})
    impl=parts[env["impl_id"]]
    header=(f"@{impl['handle']} FINAL_STAGE_{stage}_IMPLEMENTATION run_token={ctx['token']} "
            f"result_repo={RESULT} target=stage-{stage} base_revision={base}. "
            f"Implement Stage {stage} completely from the supplied cumulative requirements. "
            "Modify only the target stage folder. Build to the written requirements, not merely shipped checks. "
            "Do not inspect prior solutions outside this fresh result repository. Do not commit or push. "
            "Do not ask the human for steering.")
    ids=send_chunks(ctx["room_id"],env["coord_key"],impl,header,spec_text(stage))
    ctx=load(); ctx["stages"][str(stage)]["implementer_handoff_ids"]=ids; save(ctx)
    output("base_revision",base); output("result_path",str(RESULT))

def changed_paths():
    p=git("status","--porcelain=v1","--untracked-files=all")
    out=[]
    for raw in p.stdout.splitlines():
        if not raw.strip(): continue
        path=raw[3:]
        if " -> " in path: path=path.split(" -> ",1)[1]
        out.append(path)
    return out

def cmd_publish(stage,attempt,expected):
    ctx=load(); env=pe()
    head=git("rev-parse","HEAD").stdout.strip()
    if head!=expected: raise SystemExit(f"result revision drift {head} != {expected}")
    paths=changed_paths()
    if not paths: raise SystemExit("Implementer produced no file changes")
    allowed=re.compile(rf"^stage-{stage}/.+")
    bad=[p for p in paths if not allowed.fullmatch(p)]
    if bad: raise SystemExit(f"Implementer scope violation: {bad}")
    folder=RESULT/f"stage-{stage}"
    for req in ("Dockerfile","RUN.md"):
        if not (folder/req).is_file(): raise SystemExit(f"stage-{stage}/{req} missing")
    others=[p for p in folder.rglob("*") if p.is_file() and p.name not in {"Dockerfile","RUN.md"}]
    if not others: raise SystemExit(f"stage-{stage} has no source file")
    git("config","user.name","BAND Implementer (Claude Code)")
    git("config","user.email","band-implementer@users.noreply.github.com")
    git("add",*paths)
    git("diff","--cached","--check")
    git("commit","-m",f"Implement Stage {stage} attempt {attempt}")
    revision=git("rev-parse","HEAD").stdout.strip()
    parts=resolve(ctx["room_id"],env["coord_key"],{env["coord_id"],env["impl_id"],env["review_id"]})
    coord,impl,reviewer=parts[env["coord_id"]],parts[env["impl_id"]],parts[env["review_id"]]
    post(ctx["room_id"],env["impl_key"],
         f"@{coord['handle']} @{reviewer['handle']} IMPLEMENTATION_READY stage={stage} attempt={attempt} "
         f"run_token={ctx['token']} revision={revision}. Independent review required.",
         [mention(coord),mention(reviewer)])
    header=(f"@{reviewer['handle']} FINAL_STAGE_{stage}_REVIEW_HANDOFF run_token={ctx['token']} "
            f"revision={revision} attempt={attempt}. Independently verify this exact committed candidate against "
            "the complete cumulative requirements below. Do not modify production code. A shipped harness pass is "
            "evidence, not permission to ignore written requirements.")
    ids=send_chunks(ctx["room_id"],env["coord_key"],reviewer,header,spec_text(stage))
    st=ctx["stages"][str(stage)]; st["attempts"].append({"attempt":attempt,"revision":revision,"review_handoff_ids":ids})
    save(ctx); output("revision",revision)

def cmd_review(stage,attempt,revision):
    ctx=load(); env=pe()
    if git("rev-parse","HEAD").stdout.strip()!=revision: raise SystemExit("review revision mismatch")
    kickoff=Path(os.environ["KICKOFF"])
    out=ART/f"stage-{stage}-attempt-{attempt}"
    out.mkdir(parents=True,exist_ok=True)
    cmd=["python","-m","harness","run","--track","pocketful","--repo",str(RESULT),
         "--stage",str(stage),"--mode","isolated","--out",str(out/"official")]
    p=run(cmd,cwd=kickoff,check=False,timeout=3600)
    (out/"stdout.txt").write_text(p.stdout); (out/"stderr.txt").write_text(p.stderr)
    report=out/"official"/"report.json"
    summary=json.loads(report.read_text()) if report.exists() else {}
    parts=resolve(ctx["room_id"],env["coord_key"],{env["coord_id"],env["impl_id"],env["review_id"]})
    coord,impl=parts[env["coord_id"]],parts[env["impl_id"]]
    short=json.dumps(summary,separators=(",",":"))[:3500]
    if p.returncode==0:
        verdict="ACCEPT"
        msg=(f"@{impl['handle']} @{coord['handle']} ACCEPT {revision} stage={stage} attempt={attempt} "
             f"run_token={ctx['token']} official_isolated_harness_exit=0 report={short}")
    else:
        verdict="REJECT"
        tail=(p.stdout+"\n"+p.stderr)[-6500:]
        msg=(f"@{impl['handle']} @{coord['handle']} REJECT {revision} stage={stage} attempt={attempt} "
             f"run_token={ctx['token']} official_isolated_harness_exit={p.returncode}. Reproduction tail:\n{tail}")
    post(ctx["room_id"],env["review_key"],msg,[mention(impl),mention(coord)])
    ctx=load(); st=ctx["stages"][str(stage)]
    for a in st["attempts"]:
        if a["attempt"]==attempt and a["revision"]==revision:
            a.update({"verdict":verdict,"harness_exit":p.returncode,"report":summary})
    if verdict=="ACCEPT":
        st["status"]="ACCEPT"; st["accepted_revision"]=revision; st["accepted_attempt"]=attempt
        st["completed_at_epoch"]=time.time()
    elif attempt==2:
        st["status"]="REJECT"; st["completed_at_epoch"]=time.time()
    save(ctx)
    output("verdict",verdict); output("harness_exit",str(p.returncode))
    if verdict=="REJECT" and attempt==1:
        post(ctx["room_id"],env["coord_key"],
             f"@{impl['handle']} REPAIR_REQUESTED stage={stage} rejected_revision={revision} "
             f"run_token={ctx['token']}. Repair only the current stage from Reviewer evidence and return a new "
             "committed revision for independent re-review. Do not ask the human for steering.",[mention(impl)])
        tail=(p.stdout+"\n"+p.stderr)[-7500:]
        specs=", ".join(f"pocketful-input/stage-{n}.md" for n in range(1,stage+1))
        repair=f"""Autonomous final-run repair for Stage {stage}, attempt 2/2.
Run token: {ctx['token']}
Fresh result repository: {RESULT}
Rejected revision: {revision}

Read the authoritative cumulative specifications: {specs}.
Inspect only {RESULT}/stage-{stage} and repair the Reviewer-observed failure.
Modify ONLY submission-final-runtime/result/stage-{stage}/.
Do not read or copy earlier solutions outside the fresh result repository.
Do not commit or push. Do not ask the human for steering.

Reviewer evidence tail:
{tail}
"""
        output_multi("repair_context",repair)

def cmd_gate(stage):
    ctx=load(); st=ctx["stages"].get(str(stage),{})
    if st.get("status")!="ACCEPT":
        raise SystemExit(f"Stage {stage} not accepted: {st.get('status')}")
    post(ctx["room_id"],pe()["coord_key"],
         f"STAGE_{stage}_PROMOTED_WITHIN_FINAL_RUN run_token={ctx['token']} "
         f"revision={st['accepted_revision']} attempt={st['accepted_attempt']}. Proceeding autonomously.",
         [])
    output("accepted_revision",st["accepted_revision"])

def cmd_finalize():
    ctx=load(); env=pe()
    for n in range(1,5):
        if ctx["stages"].get(str(n),{}).get("status")!="ACCEPT":
            raise SystemExit(f"cannot finalize: stage {n} not accepted")
    if changed_paths(): raise SystemExit(f"fresh result repository dirty before finalize: {changed_paths()}")
    elapsed=round(time.time()-ctx["started_at_epoch"],3)
    metrics={
      "run_token":ctx["token"],"room_id":ctx["room_id"],"elapsed_seconds":elapsed,
      "human_steering_after_trigger":False,
      "provider_spend_visibility":"NOT_EXPOSED_BY_SUBSCRIPTION_RUNTIME",
      "stages":{n:{"accepted_revision":ctx["stages"][n]["accepted_revision"],
                    "accepted_attempt":ctx["stages"][n]["accepted_attempt"],
                    "elapsed_seconds":round(ctx["stages"][n]["completed_at_epoch"]-ctx["stages"][n]["started_at_epoch"],3)}
                for n in ctx["stages"]}
    }
    (RESULT/"RUN-METRICS.json").write_text(json.dumps(metrics,indent=2)+"\n")
    git("config","user.name","BAND Coordinator")
    git("config","user.email","band-coordinator@users.noreply.github.com")
    git("add","RUN-METRICS.json")
    git("commit","-m","Record final dark-factory run metrics")
    final_head=git("rev-parse","HEAD").stdout.strip()

    # Fail closed if anything except the protected full-room download is missing.
    kickoff=Path(os.environ["KICKOFF"])
    code=("import sys; sys.path.insert(0,sys.argv[1]); "
          "from harness.check import check_repo; "
          "p=check_repo(sys.argv[2],'pocketful'); print('\\n'.join(p)); "
          "assert len(p)==1 and 'room.json is missing' in p[0], p")
    pre=run(["python","-c",code,str(kickoff),str(RESULT)],check=False)
    ART.mkdir(parents=True,exist_ok=True)
    (ART/"pre-room-check.stdout").write_text(pre.stdout)
    (ART/"pre-room-check.stderr").write_text(pre.stderr)
    if pre.returncode!=0: raise SystemExit(f"pre-room submission check failed\n{pre.stdout}\n{pre.stderr}")

    final_out=ART/"final-official-stage4"
    p=run(["python","-m","harness","run","--track","pocketful","--repo",str(RESULT),
           "--stage","4","--mode","isolated","--out",str(final_out)],cwd=kickoff,check=False,timeout=3600)
    (ART/"final-stage4.stdout").write_text(p.stdout); (ART/"final-stage4.stderr").write_text(p.stderr)
    if p.returncode!=0: raise SystemExit("final Stage 4 harness failed after metrics commit")

    parts=resolve(ctx["room_id"],env["coord_key"],{env["coord_id"],env["impl_id"],env["review_id"]})
    impl,reviewer=parts[env["impl_id"]],parts[env["review_id"]]
    post(ctx["room_id"],env["coord_key"],
         f"@{impl['handle']} @{reviewer['handle']} FINAL_RUN_PRODUCT_COMPLETE run_token={ctx['token']} "
         f"fresh_result_revision={final_head}. All four stages were independently accepted with no human steering. "
         "The product run is complete. Submission remains blocked until the human downloads this full BAND session "
         "and saves it unchanged as room.json in this fresh result repository.",[mention(impl),mention(reviewer)])

    ctx["final_result_revision_before_room_json"]=final_head
    ctx["completed_at_epoch"]=time.time(); ctx["elapsed_seconds"]=elapsed
    ctx["status"]="PRODUCT_COMPLETE_AWAITING_AUTHENTIC_ROOM_JSON"; save(ctx)
    shutil.copy2(CTX,ART/"context.json")
    run(["git","-C",str(RESULT),"bundle","create",str(ART/"fresh-result-before-room.bundle"),"--all"])
    run(["tar","-C",str(RESULT),"--exclude=.git","-czf",str(ART/"fresh-result-files-before-room.tar.gz"),"."])
    (ART/"git-log.txt").write_text(git("log","--reverse","--format=%H %an %s").stdout)
    gh_comment(ctx["repo"],ctx["pr"],"\n".join([
      "POCKETFUL_FINAL_RUN_TERMINAL status=PRODUCT_COMPLETE_AWAITING_AUTHENTIC_ROOM_JSON",
      f"RUN_TOKEN={ctx['token']}",f"ROOM_ID={ctx['room_id']}",
      f"FRESH_RESULT_REVISION={final_head}","HUMAN_STEERING_AFTER_PR_OPEN=false",
      "NEXT_PROTECTED_ACTION=Band_console_Download_full_session_then_save_as_room.json"]))
    output("room_id",ctx["room_id"]); output("final_result_revision",final_head)

def main():
    if len(sys.argv)<2: raise SystemExit("usage: prepare|begin|publish|review|gate|finalize")
    cmd=sys.argv[1]
    if cmd=="prepare": cmd_prepare()
    elif cmd=="begin": cmd_begin(int(sys.argv[2]))
    elif cmd=="publish": cmd_publish(int(sys.argv[2]),int(sys.argv[3]),sys.argv[4])
    elif cmd=="review": cmd_review(int(sys.argv[2]),int(sys.argv[3]),sys.argv[4])
    elif cmd=="gate": cmd_gate(int(sys.argv[2]))
    elif cmd=="finalize": cmd_finalize()
    else: raise SystemExit(cmd)

if __name__=="__main__":
    main()
