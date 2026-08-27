from __future__ import annotations
import csv, glob, json, os, sys
from collections import defaultdict
sys.path.insert(0,"research")
from mgc_pullback_entry_sweep import (
    pts,qkey,hkey,lhour,AdaptiveMACD2,SlowStoch,VWMA,Agg,Min,RefHour,
    favorable_ref_target,simulate,poc_proxy
)

TICK=0.1
THRESHOLDS=[65,70,75,80,85]
AGES=[2,4,6,8]
STOPS=[5.0,7.5,10.0,12.5,15.0]
SESSIONS={"19_03":{19,20,21,22,23,0,1,2,3},"20_02":{20,21,22,23,0,1,2},"22_02":{22,23,0,1,2}}
R=defaultdict(lambda:{"n":0,"amb":0,"pos":0.0,"neg":0.0,"sum":0.0,"wins":0,"losses":0,"flat":0,"by_year":defaultdict(lambda:[0,0,0,0.0])})

def turn(sig,d,thr,age):
    m=(sig or {}).get("macd");s=(sig or {}).get("stoch")
    if not m or not s or not m.get(d) or m.get(d+"_age",999)>age:return False
    if d=="short":return s["k"]>=thr and s["k"]<s["pk"]
    return s["k"]<=100-thr and s["k"]>s["pk"]

def entry(minutes,ref,thr,age):
    armed=None;last=None
    for i,b in enumerate(minutes):
        sid=(b.sig or {}).get("signal_bar_key")
        if sid is not None and sid!=last:
            last=sid
            oks=[]
            for d in ("long","short"):
                if turn(b.sig,d,thr,age) and favorable_ref_target(d,b.o,ref) is not None:
                    oks.append(d)
            if len(oks)==1:
                d=oks[0]
                armed={"d":d,"level":b.sig["signal_bar_high"]+TICK if d=="long" else b.sig["signal_bar_low"]-TICK,"sig":b.sig}
            elif len(oks)>1:
                armed=None
        if armed:
            d=armed["d"];lev=armed["level"]
            if d=="long" and b.h>lev:return {"i":i,"d":d,"entry":max(lev,b.o),"sig":armed["sig"],"kind":"break15"}
            if d=="short" and b.l<lev:return {"i":i,"d":d,"entry":min(lev,b.o),"sig":armed["sig"],"kind":"break15"}
    return None

def add(key,ev,out):
    b=R[key]
    if out["amb"]:b["amb"]+=1;return
    p=out["pnl"];b["n"]+=1;b["sum"]+=p
    if p>1e-9:b["wins"]+=1;b["pos"]+=p;cls=0
    elif p<-1e-9:b["losses"]+=1;b["neg"]+=-p;cls=1
    else:b["flat"]+=1;cls=2
    y=ev["ts"].year;b["by_year"][y][cls]+=1;b["by_year"][y][3]+=p

def process(minutes,ref):
    if not minutes or ref is None:return
    hr=lhour(minutes[0].ts)
    for thr in THRESHOLDS:
      for age in AGES:
        ev=entry(minutes,ref,thr,age)
        if not ev:continue
        ev["ts"]=minutes[ev["i"]].ts
        target=favorable_ref_target(ev["d"],ev["entry"],ref)
        if target is None:continue
        for sess,hours in SESSIONS.items():
          if hr not in hours:continue
          for stop in STOPS:
            out=simulate(minutes,ev,stop,target);add((thr,age,sess,stop),ev,out)

def comp(b):
    n=b["n"];pf=b["pos"]/b["neg"] if b["neg"] else None
    dev=sum(v[3] for y,v in b["by_year"].items() if int(y)<=2024)
    hold=sum(v[3] for y,v in b["by_year"].items() if int(y)>=2025)
    nd=sum(sum(v[:3]) for y,v in b["by_year"].items() if int(y)<=2024)
    nh=sum(sum(v[:3]) for y,v in b["by_year"].items() if int(y)>=2025)
    return {"n":n,"amb":b["amb"],"wins":b["wins"],"losses":b["losses"],"flat":b["flat"],"avg":b["sum"]/n if n else None,
            "points":b["sum"],"pf":pf,"dev_points":dev,"hold_points":hold,"dev_n":nd,"hold_n":nh,
            "by_year":{str(k):v for k,v in b["by_year"].items()}}

def main(root):
    files=sorted(glob.glob(os.path.join(root,"data","ohlcv_MGC_*.csv")))
    macd=AdaptiveMACD2();st=SlowStoch();vw14=VWMA(14);vw200=VWMA(200)
    qb=None;hk=None;mins=[];ref=None;sig=None;prev=None;rows=0
    def cq(q):
        nonlocal sig
        macd.commit(q.c);st.commit(q.h,q.l,q.c);vw14.commit(q.c,q.v);vw200.commit(q.c,q.v)
        sig={"macd":macd.snapshot(),"stoch":st.snapshot(),"vwma14":vw14.value,"vwma200":vw200.value,
             "signal_bar_key":q.key.isoformat(),"signal_bar_high":q.h,"signal_bar_low":q.l,"signal_bar_close":q.c}
    for fp in files:
      with open(fp,newline="") as f:
       for r in csv.DictReader(f):
        ts=pts(r["timestamp"])
        if prev is not None and ts<=prev:continue
        prev=ts;rows+=1;o=float(r["open"]);h=float(r["high"]);l=float(r["low"]);c=float(r["close"]);v=float(r.get("volume") or 0)
        qk=qkey(ts);hh=hkey(ts)
        if qb is not None and qk!=qb.key:cq(qb);qb=None
        if hk is not None and hh!=hk:
            process(mins,ref)
            ref=RefHour(hk,max(x.h for x in mins),min(x.l for x in mins),poc_proxy(mins))
            mins=[];hk=hh
        elif hk is None:hk=hh
        if qb is None:qb=Agg(qk,o,h,l,c,v)
        else:qb.add(o,h,l,c,v)
        mins.append(Min(ts,o,h,l,c,v,sig.copy() if sig else None))
    if qb:cq(qb)
    if mins:process(mins,ref)
    out=[]
    for k,b in R.items():
        thr,age,sess,stop=k;x=comp(b)
        out.append({"threshold":thr,"age":age,"session":sess,"stop":stop,**x})
    stable=[x for x in out if x["n"]>=40 and x["dev_points"]>0 and x["hold_points"]>0]
    stable.sort(key=lambda x:x["avg"],reverse=True)
    print("ROBUST_PULLBACK_META="+json.dumps({"rows":rows,"thresholds":THRESHOLDS,"ages":AGES,"stops":STOPS,
          "entry":"completed 15m stoch turns from extreme while middle+slow histograms are same-side waning; then 1 tick break of signal 15m candle in trade direction",
          "target":"previous completed hour opposite boundary","split":"2023-24 development vs 2025-26 holdout"},separators=(",",":")))
    print("ROBUST_STABLE_START")
    for x in stable[:30]:print(json.dumps(x,separators=(",",":")))
    print("ROBUST_STABLE_END")
    print("THRESHOLD_SPOTLIGHT_START")
    for thr in THRESHOLDS:
        b=R.get((thr,4,"20_02",10.0))
        if b:print(json.dumps({"threshold":thr,"age":4,"session":"20_02","stop":10.0,**comp(b)},separators=(",",":")))
    print("THRESHOLD_SPOTLIGHT_END")
    os.makedirs("backtest_output",exist_ok=True)
    json.dump({"rows":out},open("backtest_output/mgc_pullback_robustness.json","w"))

if __name__=="__main__":main(sys.argv[1])
