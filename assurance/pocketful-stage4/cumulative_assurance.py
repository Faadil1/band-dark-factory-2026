#!/usr/bin/env python3
import concurrent.futures
import datetime as dt
import json
import sys
import urllib.error
import urllib.parse
import urllib.request

BASE4=sys.argv[1].rstrip("/")
BASE3=sys.argv[2].rstrip("/")
REPORT=sys.argv[3]
checks=[]

def add(name, ok, detail=""):
    checks.append({"name":name,"ok":bool(ok),"detail":str(detail)})
    if not ok:
        raise AssertionError(f"{name}: {detail}")

def call(base,method,path,body=None,token=None,key=None,expect=None):
    data=None if body is None else json.dumps(body,separators=(",",":")).encode()
    h={"Accept":"application/json"}
    if body is not None: h["Content-Type"]="application/json"
    if token: h["Authorization"]="Bearer "+token
    if key is not None: h["Idempotency-Key"]=key
    req=urllib.request.Request(base+path,data=data,method=method,headers=h)
    try:
        with urllib.request.urlopen(req,timeout=8) as r:
            raw=r.read(); status=r.status; ctype=r.headers.get("Content-Type","")
    except urllib.error.HTTPError as e:
        status=e.code; raw=e.read(); ctype=e.headers.get("Content-Type","")
    obj=None
    if raw:
        try: obj=json.loads(raw)
        except Exception: obj=raw.decode(errors="replace")
    if expect is not None and status!=expect:
        raise AssertionError(f"{method} {path}: expected {expect}, got {status}: {obj}")
    if raw and isinstance(obj,(dict,list)) and "application/json" not in ctype:
        raise AssertionError(f"{method} {path}: JSON body without JSON content-type: {ctype}")
    return status,obj

def c4(method,path,body=None,token=None,key=None,expect=None):
    return call(BASE4,method,path,body,token,key,expect)

def c3(method,path,body=None,token=None,key=None,expect=None):
    return call(BASE3,method,path,body,token,key,expect)

def err(obj):
    return obj.get("error",{}).get("code") if isinstance(obj,dict) else None

def iso(seconds=0):
    return (dt.datetime.now(dt.timezone.utc)+dt.timedelta(seconds=seconds)).replace(microsecond=0).isoformat()

def q(v):
    return urllib.parse.quote(v,safe="")

def users(a=1000,b=0,c=0):
    return [
      {"id":"u_ada","email":"ada@example.com","password":"correct horse","display_name":"Ada","handle":"ada","balance":a},
      {"id":"u_bob","email":"bob@example.com","password":"correct horse","display_name":"Bob","handle":"bob","balance":b},
      {"id":"u_cy","email":"cy@example.com","password":"correct horse","display_name":"Cy","handle":"cy","balance":c},
    ]

def reset4(a=1000,b=0,c=0,operators=None,extra=None):
    body={"currency":"EUR","minor_units":2,"users":users(a,b,c),"payments":[],"requests":[]}
    if operators is not None: body["settlement_operator_ids"]=operators
    if extra: body.update(extra)
    c4("POST","/_test/reset",body,expect=204)

def reset3(a=1000,b=0,c=0,operators=None,extra=None):
    body={"currency":"EUR","minor_units":2,"users":users(a,b,c),"payments":[],"requests":[]}
    if operators is not None: body["settlement_operator_ids"]=operators
    if extra: body.update(extra)
    c3("POST","/_test/reset",body,expect=204)

def login4(email):
    return c4("POST","/auth/login",{"email":email,"password":"correct horse"},expect=200)[1]["token"]

def login3(email):
    return c3("POST","/auth/login",{"email":email,"password":"correct horse"},expect=200)[1]["token"]

def me4(t,path="/me"):
    return c4("GET",path,token=t,expect=200)[1]

def scenario(name,fn):
    before=len(checks)
    try:
        fn()
        if len(checks)==before:
            add(name,True,"scenario completed")
    except Exception as e:
        checks.append({"name":name,"ok":False,"detail":repr(e)})

def s2_holds_and_captures():
    reset4()
    ada,bob,cy=login4("ada@example.com"),login4("bob@example.com"),login4("cy@example.com")
    _,a=c4("POST","/authorizations",{"to_handle":"bob","amount":600,"note":"reserve","visibility":"private"},ada,"auth-1",201)
    m=me4(ada)
    add("s2_hold_changes_available_not_total",m["total"]==1000 and m["balance"]==1000 and m["held"]==600 and m["available"]==400,m)
    _,e=c4("POST","/payments",{"to_handle":"cy","amount":500},ada,"blocked-by-hold",409)
    add("s2_held_funds_cannot_fund_payment",err(e)=="insufficient_funds",e)
    aid=a["authorization_id"]
    _,p1=c4("POST",f"/authorizations/{aid}/capture",{"amount":200,"final":False},bob,"cap-1",201)
    auths=c4("GET","/authorizations?direction=outgoing",token=ada,expect=200)[1]["authorizations"]
    cur=next(x for x in auths if x["authorization_id"]==aid)
    m=me4(ada)
    add("s2_partial_capture_keeps_remainder_held",cur["status"]=="open" and cur["captured_amount"]==200 and cur["remaining_amount"]==400 and m["total"]==800 and m["held"]==400 and m["available"]==400,{"auth":cur,"me":m})
    _,p2=c4("POST",f"/authorizations/{aid}/capture",{"amount":100},bob,"cap-2",201)
    auths=c4("GET","/authorizations?direction=outgoing",token=ada,expect=200)[1]["authorizations"]
    cur=next(x for x in auths if x["authorization_id"]==aid)
    m=me4(ada)
    add("s2_final_capture_releases_uncaptured_remainder",cur["status"]=="captured" and cur["captured_amount"]==300 and cur["remaining_amount"]==0 and m["total"]==700 and m["held"]==0 and m["available"]==700,{"auth":cur,"me":m})
    add("s2_capture_payments_link_authorization",p1["authorization_id"]==aid and p2["authorization_id"]==aid)

def s2_authority_expiry_and_failed_reset_atomicity():
    reset4()
    ada,bob,cy=login4("ada@example.com"),login4("bob@example.com"),login4("cy@example.com")
    _,a=c4("POST","/authorizations",{"to_handle":"bob","amount":100},ada,"auth-rights",201)
    aid=a["authorization_id"]
    _,e=c4("POST",f"/authorizations/{aid}/capture",{"amount":10},cy,"bad-cap",403)
    add("s2_only_receiver_captures",err(e)=="forbidden",e)
    _,e=c4("POST",f"/authorizations/{aid}/void",{},bob,expect=403)
    add("s2_only_payer_voids",err(e)=="forbidden",e)
    _,v=c4("POST",f"/authorizations/{aid}/void",{},ada,expect=200)
    add("s2_void_releases_hold",v["status"]=="voided" and me4(ada)["held"]==0)
    past=iso(-60)
    body={"currency":"EUR","minor_units":2,"users":users(),"payments":[],"requests":[],
          "authorizations":[{"id":"a_seed","from_user_id":"u_ada","to_user_id":"u_bob","amount":200,"status":"open","expires_at":past}]}
    c4("POST","/_test/reset",body,expect=204)
    ada=login4("ada@example.com")
    auths=c4("GET","/authorizations",token=ada,expect=200)[1]["authorizations"]
    add("s2_past_seed_hold_reads_expired",auths[0]["status"]=="expired" and me4(ada)["held"]==0,auths)
    old=me4(ada)
    bad={"currency":"EUR","minor_units":2,"users":users(100,0,0),"payments":[],"requests":[],
         "authorizations":[{"id":"bad","from_user_id":"u_ada","to_user_id":"u_bob","amount":200,"status":"open","expires_at":iso(3600)}]}
    _,e=c4("POST","/_test/reset",bad,expect=422)
    add("s2_invalid_seed_hold_reset_is_atomic",err(e)=="validation_failed" and me4(ada)==old,e)

def s3_temporal_correction_snapshot_and_privacy():
    t1=iso(-3600); before=iso(-7200); future=iso(3600)
    body={"currency":"EUR","minor_units":2,"users":users(900,100,0),
          "payments":[{"id":"p_seed","from_user_id":"u_ada","to_user_id":"u_bob","amount":100,"created_at":t1}],
          "requests":[]}
    c4("POST","/_test/reset",body,expect=204)
    ada,bob,cy=login4("ada@example.com"),login4("bob@example.com"),login4("cy@example.com")
    add("s3_as_of_before_payment_returns_opening",me4(ada,f"/me?as_of={q(before)}")["balance"]==1000)
    add("s3_as_of_exact_payment_inclusive",me4(ada,f"/me?as_of={q(t1)}")["balance"]==900)
    st0=c4("GET",f"/statement?from={q(before)}&to={q(future)}&limit=1&offset=0",token=ada,expect=200)[1]
    snap=st0["snapshot"]
    add("s3_statement_full_window_balances_and_entry",st0["opening_balance"]==1000 and st0["closing_balance"]==900 and st0["entries"][0]["delta"]==-100,st0)
    _,rev=c4("POST","/payments/p_seed/corrections",{"expected_revision":1,"amount":200,"effective_at":t1,"reason":"corrected"},ada,"corr-1",201)
    add("s3_correction_moves_current_balance",me4(ada)["balance"]==800 and me4(bob)["balance"]==200)
    rs=c4("GET","/payments/p_seed/revisions",token=ada,expect=200)[1]["revisions"]
    add("s3_revision_history_is_immutable_and_ordered",len(rs)==2 and rs[0]["amount"]==100 and rs[1]["amount"]==200 and rs[0]["reason"]=="",rs)
    _,e=c4("GET","/payments/p_seed/revisions",token=cy,expect=404)
    add("s3_third_party_cannot_read_revisions",err(e)=="not_found",e)
    oldview=me4(ada,f"/me?as_of={q(t1)}&known_at={q(t1)}")
    newview=me4(ada,f"/me?as_of={q(t1)}&known_at={q(future)}")
    add("s3_known_at_separates_recorded_from_effective_time",oldview["balance"]==900 and newview["balance"]==800,{"old":oldview,"new":newview})
    frozen=c4("GET",f"/statement?snapshot={q(snap)}&limit=50&offset=0",token=ada,expect=200)[1]
    add("s3_statement_snapshot_survives_correction",frozen["entries"][0]["payment"]["amount"]==100 and frozen["closing_balance"]==900,frozen)
    _,e=c4("GET",f"/statement?snapshot={q(snap)}&from={q(before)}",token=ada,expect=422)
    add("s3_snapshot_rejects_temporal_parameters",err(e)=="validation_failed",e)
    _,e=c4("GET",f"/statement?snapshot={q(snap)}",token=bob,expect=404)
    add("s3_snapshot_is_user_scoped",err(e)=="not_found",e)

def s3_historical_overdraft_and_linked_immutability():
    t1=iso(-7200); t2=iso(-3600)
    body={"currency":"EUR","minor_units":2,"users":users(500,100,500),
          "payments":[
            {"id":"p_old","from_user_id":"u_ada","to_user_id":"u_bob","amount":100,"created_at":t1},
            {"id":"p_fund","from_user_id":"u_cy","to_user_id":"u_ada","amount":500,"created_at":t2}],
          "requests":[]}
    c4("POST","/_test/reset",body,expect=204)
    ada=login4("ada@example.com")
    _,e=c4("POST","/payments/p_old/corrections",{"expected_revision":1,"amount":200,"effective_at":t1,"reason":"retro"},ada,"hist-over",409)
    add("s3_historical_overdraft_blocks_retroactive_negative_balance",err(e)=="historical_overdraft",e)
    add("s3_failed_correction_preserves_current_balance",me4(ada)["balance"]==500)
    reset4(1000,1000,1000,operators=["u_ada"])
    ada,bob=login4("ada@example.com"),login4("bob@example.com")
    _,sett=c4("POST","/settlements",{"transfers":[{"from_handle":"ada","to_handle":"bob","amount":50}]},ada,"sett-linked",201)
    pid=sett["payments"][0]["payment_id"]
    _,e=c4("POST",f"/payments/{pid}/corrections",{"expected_revision":1,"amount":40,"effective_at":sett["payments"][0]["created_at"],"reason":"single"},ada,"single-sett",422)
    add("s3_single_correction_rejects_settlement_member",err(e)=="linked_payment_immutable",e)

def s4_refunds_and_available_funds():
    reset4()
    ada,bob,cy=login4("ada@example.com"),login4("bob@example.com"),login4("cy@example.com")
    _,p=c4("POST","/payments",{"to_handle":"bob","amount":100,"note":"orig","visibility":"private"},ada,"pay-r",201)
    pid=p["payment_id"]
    _,e=c4("POST",f"/payments/{pid}/refunds",{"amount":1},ada,"bad-refunder",403)
    add("s4_only_original_receiver_can_refund",err(e)=="forbidden",e)
    _,r=c4("POST",f"/payments/{pid}/refunds",{"amount":40},bob,"refund-1",201)
    rid=r["payment_id"]
    add("s4_refund_is_opposite_linked_payment",r["from_handle"]=="bob" and r["to_handle"]=="ada" and r["refund_of"]==pid and r["note"]=="orig" and r["visibility"]=="private",r)
    bal=(me4(ada)["balance"],me4(bob)["balance"])
    _,rr=c4("POST",f"/payments/{pid}/refunds",{"amount":40},bob,"refund-1",200)
    add("s4_refund_replay_has_one_economic_effect",rr==r and (me4(ada)["balance"],me4(bob)["balance"])==bal)
    _,e=c4("POST",f"/payments/{pid}/refunds",{"amount":70},bob,"refund-too-much",422)
    add("s4_cumulative_refunds_cannot_exceed_current_amount",err(e)=="refund_exceeds_payment",e)
    _,e=c4("POST",f"/payments/{rid}/refunds",{"amount":1},ada,"refund-refund",422)
    add("s4_refund_of_refund_forbidden",err(e)=="invalid_refund_target",e)
    _,e=c4("POST",f"/payments/{pid}/corrections",{"expected_revision":1,"amount":30,"effective_at":p["created_at"],"reason":"too low"},ada,"corr-below-refund",422)
    add("s4_correction_cannot_drop_below_refunded_amount",err(e)=="refund_exceeds_payment",e)
    _,e=c4("POST",f"/payments/{rid}/corrections",{"expected_revision":1,"amount":30,"effective_at":r["created_at"],"reason":"no"},bob,"corr-refund",422)
    add("s4_refund_payment_is_immutable",err(e)=="linked_payment_immutable",e)

    reset4()
    ada,bob,cy=login4("ada@example.com"),login4("bob@example.com"),login4("cy@example.com")
    _,p=c4("POST","/payments",{"to_handle":"bob","amount":100},ada,"pay-hold-refund",201)
    _,a=c4("POST","/authorizations",{"to_handle":"cy","amount":80},bob,"bob-hold",201)
    _,e=c4("POST",f"/payments/{p['payment_id']}/refunds",{"amount":50},bob,"refund-held",409)
    add("s4_refund_debits_available_not_total",err(e)=="insufficient_funds" and me4(bob)["total"]==100 and me4(bob)["available"]==20,e)

def s4_batch_corrections_atomicity_replay_and_snapshot():
    reset4(1000,1000,1000,operators=["u_ada"])
    ada,bob,cy=login4("ada@example.com"),login4("bob@example.com"),login4("cy@example.com")
    body={"transfers":[{"from_handle":"ada","to_handle":"bob","amount":100},{"from_handle":"bob","to_handle":"cy","amount":50}]}
    _,sett=c4("POST","/settlements",body,ada,"sett-batch",201)
    ps=sett["payments"]; p1,p2=ps[0]["payment_id"],ps[1]["payment_id"]; eff=ps[0]["created_at"]
    snap=c4("GET","/statement?limit=50&offset=0",token=ada,expect=200)[1]["snapshot"]
    one={"corrections":[{"payment_id":p1,"expected_revision":1,"amount":0,"effective_at":eff,"reason":"reverse"}]}
    _,e=c4("POST","/correction-batches",one,ada,"batch-incomplete",422)
    add("s4_batch_requires_complete_settlement",err(e)=="incomplete_settlement",e)
    add("s4_rejected_batch_is_atomic",(me4(ada)["balance"],me4(bob)["balance"],me4(cy)["balance"])==(900,1050,1050))
    full={"corrections":[
      {"payment_id":p1,"expected_revision":1,"amount":0,"effective_at":eff,"reason":"reverse"},
      {"payment_id":p2,"expected_revision":1,"amount":0,"effective_at":eff,"reason":"reverse"}]}
    _,e=c4("POST","/correction-batches",full,bob,"batch-no-operator",403)
    add("s4_batch_requires_settlement_operator",err(e)=="forbidden",e)
    _,batch=c4("POST","/correction-batches",full,ada,"batch-ok",201)
    revs=batch["revisions"]
    add("s4_batch_revisions_share_recorded_at_and_batch_id",len(revs)==2 and len({x["recorded_at"] for x in revs})==1 and all(x["correction_batch_id"]==batch["correction_batch_id"] for x in revs),batch)
    add("s4_batch_combined_effect_is_atomic",(me4(ada)["balance"],me4(bob)["balance"],me4(cy)["balance"])==(1000,1000,1000))
    after=(me4(ada)["balance"],me4(bob)["balance"],me4(cy)["balance"])
    _,replay=c4("POST","/correction-batches",full,ada,"batch-ok",200)
    add("s4_batch_replay_exact_no_second_effect",replay==batch and (me4(ada)["balance"],me4(bob)["balance"],me4(cy)["balance"])==after)
    _,sett_replay=c4("POST","/settlements",body,ada,"sett-batch",200)
    add("s4_original_settlement_receipt_immutable_after_batch",sett_replay==sett,sett_replay)
    frozen=c4("GET",f"/statement?snapshot={q(snap)}&limit=50&offset=0",token=ada,expect=200)[1]
    add("s4_pre_batch_statement_snapshot_remains_frozen",any(e["payment"]["payment_id"]==p1 and e["payment"]["amount"]==100 for e in frozen["entries"]),frozen)

def s4_concurrent_expected_revision():
    reset4(1000,0,0)
    ada=login4("ada@example.com")
    _,p=c4("POST","/payments",{"to_handle":"bob","amount":100},ada,"conc-base",201)
    pid=p["payment_id"]; eff=p["created_at"]
    def one(args):
        key,amount=args
        return c4("POST",f"/payments/{pid}/corrections",{"expected_revision":1,"amount":amount,"effective_at":eff,"reason":key},ada,key)
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        out=list(pool.map(one,[("conc-c1",110),("conc-c2",120)]))
    sts=[x[0] for x in out]
    add("s4_concurrent_corrections_same_expected_revision_only_one_succeeds",sorted(sts)==[201,409],out)
    rs=c4("GET",f"/payments/{pid}/revisions",token=ada,expect=200)[1]["revisions"]
    add("s4_concurrent_correction_appends_exactly_one_revision",len(rs)==2,rs)

def s3_to_s4_import_preserves_tokens_corrections_and_snapshot():
    reset3(1000,0,0)
    ada3=login3("ada@example.com")
    _,p=c3("POST","/payments",{"to_handle":"bob","amount":100},ada3,"xpay",201)
    _,r=c3("POST",f"/payments/{p['payment_id']}/corrections",{"expected_revision":1,"amount":120,"effective_at":p["created_at"],"reason":"x"},ada3,"xcorr",201)
    st=c3("GET","/statement?limit=50&offset=0",token=ada3,expect=200)[1]
    snap=st["snapshot"]
    exported=c3("GET","/_test/export",expect=200)[1]
    c4("POST","/_test/import",exported,expect=204)
    m=me4(ada3)
    add("migration_stage3_to_stage4_preserves_login_token_and_corrected_balance",m["balance"]==880,m)
    rs=c4("GET",f"/payments/{p['payment_id']}/revisions",token=ada3,expect=200)[1]["revisions"]
    add("migration_stage3_to_stage4_preserves_revision_history",len(rs)==2 and rs[-1]["amount"]==120,rs)
    frozen=c4("GET",f"/statement?snapshot={q(snap)}&limit=50&offset=0",token=ada3,expect=200)[1]
    add("migration_stage3_to_stage4_preserves_statement_snapshot",frozen["snapshot"]==snap and frozen["entries"]==st["entries"],frozen)

def main():
    for name,fn in [
      ("s2_holds_and_captures",s2_holds_and_captures),
      ("s2_authority_expiry_and_failed_reset_atomicity",s2_authority_expiry_and_failed_reset_atomicity),
      ("s3_temporal_correction_snapshot_and_privacy",s3_temporal_correction_snapshot_and_privacy),
      ("s3_historical_overdraft_and_linked_immutability",s3_historical_overdraft_and_linked_immutability),
      ("s4_refunds_and_available_funds",s4_refunds_and_available_funds),
      ("s4_batch_corrections_atomicity_replay_and_snapshot",s4_batch_corrections_atomicity_replay_and_snapshot),
      ("s4_concurrent_expected_revision",s4_concurrent_expected_revision),
      ("s3_to_s4_import_preserves_tokens_corrections_and_snapshot",s3_to_s4_import_preserves_tokens_corrections_and_snapshot),
    ]:
        scenario(name,fn)
    failed=[x for x in checks if not x["ok"]]
    result={"status":"PASS" if not failed else "FAIL","count":len(checks),"failed":len(failed),"checks":checks}
    open(REPORT,"w",encoding="utf-8").write(json.dumps(result,indent=2))
    print(json.dumps(result,indent=2))
    if failed:
        raise SystemExit(1)

if __name__=="__main__":
    main()
