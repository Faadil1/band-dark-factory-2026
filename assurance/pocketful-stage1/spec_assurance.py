#!/usr/bin/env python3
import concurrent.futures
import json
import sys
import time
import urllib.error
import urllib.request

BASE=sys.argv[1].rstrip("/")
REPORT=sys.argv[2]
checks=[]

def record(name, ok, detail=""):
    checks.append({"name":name,"ok":bool(ok),"detail":str(detail)})
    if not ok:
        raise AssertionError(f"{name}: {detail}")

def call(method,path,body=None,token=None,key=None,expect=None):
    data=None if body is None else json.dumps(body,separators=(",",":")).encode()
    h={"Accept":"application/json"}
    if body is not None: h["Content-Type"]="application/json"
    if token: h["Authorization"]="Bearer "+token
    if key is not None: h["Idempotency-Key"]=key
    req=urllib.request.Request(BASE+path,data=data,method=method,headers=h)
    try:
        with urllib.request.urlopen(req,timeout=8) as r:
            raw=r.read()
            status=r.status
            ctype=r.headers.get("Content-Type","")
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

def err_code(obj):
    return obj.get("error",{}).get("code") if isinstance(obj,dict) else None

def reset(users=None,operators=None):
    if users is None:
        users=[
          {"id":"u_ada","email":"ada@example.com","password":"correct horse","display_name":"Ada","handle":"ada","balance":10000},
          {"id":"u_bob","email":"bob@example.com","password":"correct horse","display_name":"Bob","handle":"bob","balance":2500},
          {"id":"u_cy","email":"cy@example.com","password":"correct horse","display_name":"Cy","handle":"cy","balance":1000},
        ]
    body={"currency":"EUR","minor_units":2,"users":users,"payments":[],"requests":[]}
    if operators is not None: body["settlement_operator_ids"]=operators
    call("POST","/_test/reset",body,expect=204)

def login(email,password="correct horse"):
    s,o=call("POST","/auth/login",{"email":email,"password":password},expect=200)
    return o["token"]

def me(t):
    return call("GET","/me",token=t,expect=200)[1]

def assert_total(tokens,expected):
    total=sum(me(t)["balance"] for t in tokens)
    record("balance_conservation",total==expected,f"total={total}, expected={expected}")

def main():
    # 1. Seeded auth + baseline conservation.
    reset()
    ada,bob,cy=login("ada@example.com"),login("bob@example.com"),login("cy@example.com")
    record("seeded_login_and_me",me(ada)["handle"]=="ada" and me(bob)["balance"]==2500)
    assert_total([ada,bob,cy],13500)

    # 2. Payment defaults, Unicode round trip, private feed isolation, exact debit/credit.
    s,p=call("POST","/payments",{"to_handle":"bob","amount":123,"note":"café 🚀","visibility":"private"},ada,"pay-unicode",201)
    record("payment_unicode_roundtrip",p["note"]=="café 🚀" and p["amount"]==123)
    record("payment_exact_balances",me(ada)["balance"]==9877 and me(bob)["balance"]==2623)
    feed_cy=call("GET","/activity",token=cy,expect=200)[1]["payments"]
    record("private_payment_hidden_from_third_party",all(x["payment_id"]!=p["payment_id"] for x in feed_cy))

    # 3. Idempotency replay / conflict / failed-key reuse / cross-path scoping.
    s2,p2=call("POST","/payments",{"to_handle":"bob","amount":123,"note":"café 🚀","visibility":"private"},ada,"pay-unicode",200)
    record("payment_replay_same_json_value",p2==p)
    s3,e3=call("POST","/payments",{"to_handle":"bob","amount":124,"note":"café 🚀","visibility":"private"},ada,"pay-unicode",409)
    record("idempotency_different_body_conflict",err_code(e3)=="idempotency_key_reuse")
    sf,ef=call("POST","/payments",{"to_handle":"bob","amount":999999999},ada,"retry-after-fail",409)
    record("failed_key_not_claimed_first",err_code(ef)=="insufficient_funds")
    ss,ps=call("POST","/payments",{"to_handle":"bob","amount":1},ada,"retry-after-fail",201)
    record("failed_key_reusable",ps["amount"]==1)
    sr,rr=call("POST","/requests",{"payer_handle":"bob","amount":5},ada,"pay-unicode",201)
    record("same_key_different_path_independent",rr["status"]=="pending")

    # 4. Request may exceed balance; failed pay leaves pending; later funding enables pay; replay after paid returns original.
    reset()
    ada,bob,cy=login("ada@example.com"),login("bob@example.com"),login("cy@example.com")
    _,rq=call("POST","/requests",{"payer_handle":"cy","amount":2000,"note":"later"},ada,"rq-big",201)
    sp,ep=call("POST",f"/requests/{rq['request_id']}/pay",{},cy,"rq-pay",409)
    record("request_overbalance_created_and_pay_refused",err_code(ep)=="insufficient_funds")
    pending=call("GET","/requests?direction=incoming&status=pending",token=cy,expect=200)[1]["requests"]
    record("failed_pay_does_not_change_request",any(x["request_id"]==rq["request_id"] for x in pending))
    call("POST","/payments",{"to_handle":"cy","amount":1500},ada,"fund-cy",201)
    _,paid=call("POST",f"/requests/{rq['request_id']}/pay",{},cy,"rq-pay",201)
    before=me(cy)["balance"]
    _,paid_replay=call("POST",f"/requests/{rq['request_id']}/pay",{},cy,"rq-pay",200)
    record("request_pay_replay_after_paid_returns_original",paid_replay==paid and me(cy)["balance"]==before)

    # 5. Authority and idempotent terminal request transitions.
    reset(); ada,bob,cy=login("ada@example.com"),login("bob@example.com"),login("cy@example.com")
    _,rq=call("POST","/requests",{"payer_handle":"bob","amount":10},ada,"rq-auth",201)
    sx,ex=call("POST",f"/requests/{rq['request_id']}/decline",{},cy,expect=403)
    record("request_transition_authority",err_code(ex)=="forbidden")
    _,d1=call("POST",f"/requests/{rq['request_id']}/decline",{},bob,expect=200)
    _,d2=call("POST",f"/requests/{rq['request_id']}/decline",{},bob,expect=200)
    record("decline_twice_idempotent_without_key",d1["status"]=="declined" and d2==d1)

    # 6. Split rounding and zero share request.
    reset(); ada,bob,cy=login("ada@example.com"),login("bob@example.com"),login("cy@example.com")
    _,sp=call("POST","/splits",{"amount":1,"participant_handles":["ada","bob","cy"],"note":"tiny"},ada,"split-1",201)
    record("split_rounding_order",sp["shares"]==[{"handle":"ada","amount":1},{"handle":"bob","amount":0},{"handle":"cy","amount":0}])
    record("split_zero_share_requests_exist",len(sp["requests"])==2 and all(x["amount"]==0 for x in sp["requests"]))
    _,solo=call("POST","/splits",{"amount":5,"participant_handles":["ada"]},ada,"split-solo",201)
    record("split_only_caller_valid",solo["shares"]==[{"handle":"ada","amount":5}] and solo["requests"]==[])

    # 7. Export/import replacement preserves tokens, idempotency and exact state.
    reset(); ada,bob,cy=login("ada@example.com"),login("bob@example.com"),login("cy@example.com")
    _,orig=call("POST","/payments",{"to_handle":"bob","amount":77,"note":"persist"},ada,"persist-key",201)
    snapshot=call("GET","/_test/export",expect=200)[1]
    record("export_envelope",snapshot.get("track")=="pocketful" and snapshot.get("format_version")==1 and isinstance(snapshot.get("state"),dict))
    call("POST","/payments",{"to_handle":"bob","amount":55},ada,"after-export",201)
    call("POST","/_test/import",snapshot,expect=204)
    record("import_preserves_existing_token",me(ada)["balance"]==9923)
    _,replayed=call("POST","/payments",{"to_handle":"bob","amount":77,"note":"persist"},ada,"persist-key",200)
    record("import_preserves_idempotency_response",replayed==orig and me(ada)["balance"]==9923)
    bad=dict(snapshot); bad["track"]="wrong"
    sb,eb=call("POST","/_test/import",bad,expect=422)
    record("invalid_import_rejected_without_state_change",err_code(eb)=="validation_failed" and me(ada)["balance"]==9923)

    # 8. Settlement operator permission, aggregate affordability, atomic failure, replay.
    reset(operators=["u_ada"]); ada,bob,cy=login("ada@example.com"),login("bob@example.com"),login("cy@example.com")
    sn,en=call("POST","/settlements",{"transfers":[{"from_handle":"ada","to_handle":"bob","amount":1}]},bob,"sett-no",403)
    record("settlement_operator_required",err_code(en)=="forbidden")
    body={"transfers":[{"from_handle":"ada","to_handle":"bob","amount":100},{"from_handle":"bob","to_handle":"cy","amount":50}]}
    _,sett=call("POST","/settlements",body,ada,"sett-ok",201)
    balances=(me(ada)["balance"],me(bob)["balance"],me(cy)["balance"])
    record("settlement_atomic_net_effect",balances==(9900,2550,1050) and len(sett["payments"])==2)
    _,sett2=call("POST","/settlements",body,ada,"sett-ok",200)
    record("settlement_replay_exact_and_no_second_effect",sett2==sett and (me(ada)["balance"],me(bob)["balance"],me(cy)["balance"])==balances)
    before=(me(ada)["balance"],me(bob)["balance"],me(cy)["balance"])
    sf,ef=call("POST","/settlements",{"transfers":[{"from_handle":"cy","to_handle":"ada","amount":999999}]},ada,"sett-fail",409)
    after=(me(ada)["balance"],me(bob)["balance"],me(cy)["balance"])
    record("failed_settlement_moves_nothing",err_code(ef)=="insufficient_funds" and before==after)

    # 9. Concurrent unique-key payments: no negative wallet, exact conservation, no 5xx.
    users=[
      {"id":"u_ada","email":"ada@example.com","password":"correct horse","display_name":"Ada","handle":"ada","balance":1000},
      {"id":"u_bob","email":"bob@example.com","password":"correct horse","display_name":"Bob","handle":"bob","balance":0},
    ]
    reset(users=users); ada,bob=login("ada@example.com"),login("bob@example.com")
    def one(i):
        return call("POST","/payments",{"to_handle":"bob","amount":100},ada,f"conc-{i}")
    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as pool:
        results=list(pool.map(one,range(20)))
    statuses=[x[0] for x in results]
    record("concurrent_payment_no_5xx",all(s in (201,409) for s in statuses))
    record("concurrent_payment_exact_success_count",statuses.count(201)==10,f"statuses={statuses}")
    record("concurrent_payment_no_negative_and_conserved",me(ada)["balance"]==0 and me(bob)["balance"]==1000)

    # 10. Concurrent identical idempotent request: one 201, remaining 200, one economic effect.
    reset(); ada,bob,cy=login("ada@example.com"),login("bob@example.com"),login("cy@example.com")
    def idem(_):
        return call("POST","/payments",{"to_handle":"bob","amount":50},ada,"same-concurrent")
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
        results=list(pool.map(idem,range(12)))
    sts=[x[0] for x in results]; bodies=[x[1] for x in results]
    record("concurrent_idempotency_statuses",sts.count(201)==1 and sts.count(200)==11,f"statuses={sts}")
    record("concurrent_idempotency_same_response",all(x==bodies[0] for x in bodies))
    record("concurrent_idempotency_single_effect",me(ada)["balance"]==9950 and me(bob)["balance"]==2550)

    # 11. Signup handle derivation and collision.
    reset(); 
    _,su=call("POST","/auth/signup",{"email":"A.B+LONG-THING@example.com","password":"abcdefgh","display_name":"New"},expect=201)
    t=su["token"]; expected="a_b_long_thing"
    record("signup_handle_derivation",me(t)["handle"]==expected)
    sc,ec=call("POST","/auth/signup",{"email":"A?B+LONG-THING@other.com","password":"abcdefgh","display_name":"Other"},expect=409)
    record("derived_handle_collision",err_code(ec)=="handle_taken")

    result={"status":"PASS","checks":checks,"count":len(checks)}
    open(REPORT,"w",encoding="utf-8").write(json.dumps(result,indent=2))
    print(json.dumps(result,indent=2))

if __name__=="__main__":
    try:
        main()
    except Exception as e:
        result={"status":"FAIL","error":repr(e),"checks":checks,"count":len(checks)}
        open(REPORT,"w",encoding="utf-8").write(json.dumps(result,indent=2))
        print(json.dumps(result,indent=2))
        raise
