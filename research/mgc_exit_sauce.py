from __future__ import annotations
import csv, glob, json, os, sys
from collections import defaultdict
from mgc_15m_mid_slow_stoch_sweep import AdaptiveMACD2, VWMA, AggBar, Minute, pts, qkey, hkey, local_hour, TICK
from mgc_15m_signal_robustness import ParamStoch, find_entry, combo_name

COMBOS=[(25,4,14),(20,4,14),(20,4,20)]
WINDOWS={"19_03":{19,20,21,22,23,0,1,2,3},"20_02":{20,21,22,23,0,1,2},"22_02":{22,23,0,1,2},"00_02":{0,1,2}}
DEV={2023,2024};HOLD={2025,2026}
rows_by_combo=defaultdict(list)

def pnl(d,e,x): return x-e if d=="long" else e-x

def stop_only(minutes,ev,sd):
    d,e,i0,gap=ev["direction"],ev["entry"],ev["idx"],ev["gap"];stop=e-sd if d=="long" else e+sd
    for j in range(i0,len(minutes)):
        b=minutes[j];hit=b.l<=stop if d=="long" else b.h>=stop
        if not hit:continue
        if j==i0 and not gap:return {"amb":True,"pnl":None,"reason":"ENTRY_STOP_ORDER"}
        fill=(min(stop,b.o) if b.o<stop else stop) if d=="long" else (max(stop,b.o) if b.o>stop else stop)
        return {"amb":False,"pnl":pnl(d,e,fill),"reason":"STOP"}
    return {"amb":False,"pnl":pnl(d,e,minutes[-1].c),"reason":"HOUR_CLOSE"}

def asym(minutes,ev,sd,td):
    d,e,i0,gap=ev["direction"],ev["entry"],ev["idx"],ev["gap"];stop=e-sd if d=="long" else e+sd;target=e+td if d=="long" else e-td
    for j in range(i0,len(minutes)):
        b=minutes[j];hs=b.l<=stop if d=="long" else b.h>=stop;ht=b.h>=target if d=="long" else b.l<=target
        if hs and ht:return {"amb":True,"pnl":None,"reason":"BOTH"}
        if j==i0 and hs and not gap:return {"amb":True,"pnl":None,"reason":"ENTRY_STOP_ORDER"}
        if hs:
            fill=(min(stop,b.o) if b.o<stop else stop) if d=="long" else (max(stop,b.o) if b.o>stop else stop);return {"amb":False,"pnl":pnl(d,e,fill),"reason":"STOP"}
        if ht:return {"amb":False,"pnl":td,"reason":"TARGET"}
    return {"amb":False,"pnl":pnl(d,e,minutes[-1].c),"reason":"HOUR_CLOSE"}

def breakeven(minutes,ev,sd,activate):
    d,e,i0,gap=ev["direction"],ev["entry"],ev["idx"],ev["gap"];stop=e-sd if d=="long" else e+sd;armed=False
    for j in range(i0,len(minutes)):
        b=minutes[j];old=stop
        fav=(b.h-e) if d=="long" else (e-b.l);hit_old=b.l<=old if d=="long" else b.h>=old
        if not armed and fav>=activate:
            new=e;hit_new=b.l<=new if d=="long" else b.h>=new
            if hit_old or hit_new:return {"amb":True,"pnl":None,"reason":"ACTIVATION_ORDER"}
            armed=True;stop=new;continue
        if hit_old:
            if j==i0 and not gap:return {"amb":True,"pnl":None,"reason":"ENTRY_STOP_ORDER"}
            fill=(min(old,b.o) if b.o<old else old) if d=="long" else (max(old,b.o) if b.o>old else old);return {"amb":False,"pnl":pnl(d,e,fill),"reason":"BREAKEVEN" if armed else "STOP"}
    return {"amb":False,"pnl":pnl(d,e,minutes[-1].c),"reason":"HOUR_CLOSE"}

def delayed_trail(minutes,ev,sd,activate,trail):
    d,e,i0,gap=ev["direction"],ev["entry"],ev["idx"],ev["gap"];stop=e-sd if d=="long" else e+sd;best=e;armed=False
    for j in range(i0,len(minutes)):
        b=minutes[j];old=stop
        if d=="long":
            newbest=max(best,b.h);fav=newbest-e;newstop=max(old,newbest-trail) if (armed or fav>=activate) else old;hit_old=b.l<=old;hit_new=b.l<=newstop
        else:
            newbest=min(best,b.l);fav=e-newbest;newstop=min(old,newbest+trail) if (armed or fav>=activate) else old;hit_old=b.h>=old;hit_new=b.h>=newstop
        activating=(not armed and fav>=activate);raising=(newstop!=old)
        if hit_old:
            if j==i0 and not gap:return {"amb":True,"pnl":None,"reason":"ENTRY_STOP_ORDER"}
            fill=(min(old,b.o) if d=="long" and b.o<old else max(old,b.o) if d=="short" and b.o>old else old);return {"amb":False,"pnl":pnl(d,e,fill),"reason":"TRAIL" if armed else "STOP"}
        if (activating or raising) and hit_new:return {"amb":True,"pnl":None,"reason":"TRAIL_INTRABAR_ORDER"}
        if activating:armed=True
        best,stop=newbest,newstop
    return {"amb":False,"pnl":pnl(d,e,minutes[-1].c),"reason":"HOUR_CLOSE"}

def process_hour(minutes,ref):
    if not minutes or ref is None:return
    for combo in COMBOS:
        ev=find_entry(minutes,ref["high"],ref["low"],combo)
        if not ev:continue
        base={"year":minutes[0].ts.year,"hour":local_hour(minutes[0].ts),"direction":ev["direction"]}
        specs=[]
        for sd in [5,10,15,20]:specs.append((f"STOP_ONLY_{sd}",stop_only(minutes,ev,sd)))
        for sd,td in [(5,10),(5,15),(10,15),(10,20),(10,25),(15,20),(15,25),(15,30)]:specs.append((f"ASYM_S{sd}_T{td}",asym(minutes,ev,sd,td)))
        for a in [5,7.5,10]:specs.append((f"BE_S10_A{a}",breakeven(minutes,ev,10,a)))
        for a in [5,7.5,10]:
            for tr in [5,7.5,10]:specs.append((f"DTRAIL_S10_A{a}_T{tr}",delayed_trail(minutes,ev,10,a,tr)))
        name=combo_name(*combo)
        for spec,out in specs:rows_by_combo[(name,spec)].append({**base,**out})

def metrics(rows,years=None,hours=None):
    rr=[r for r in rows if (years is None or r["year"] in years) and (hours is None or r["hour"] in hours) and not r["amb"]];amb=sum(1 for r in rows if (years is None or r["year"] in years) and (hours is None or r["hour"] in hours) and r["amb"])
    n=len(rr);total=sum(r["pnl"] for r in rr);pos=sum(r["pnl"] for r in rr if r["pnl"]>0);neg=-sum(r["pnl"] for r in rr if r["pnl"]<0);wins=sum(r["pnl"]>0 for r in rr);losses=sum(r["pnl"]<0 for r in rr);hc=sum(r["reason"]=="HOUR_CLOSE" for r in rr)
    return {"n":n,"amb":amb,"wins":wins,"losses":losses,"avg":total/n if n else None,"points":total,"pf":pos/neg if neg else None,"hour_close_pct":hc/n if n else None}
def main(root):
    files=sorted(glob.glob(os.path.join(root,"data","ohlcv_MGC_*.csv")));macd=AdaptiveMACD2();stoch=ParamStoch();vws={10:VWMA(10),14:VWMA(14),20:VWMA(20)};cq=None;hkcur=None;hagg=None;mins=[];ref=None;prev=None
    for fp in files:
      with open(fp,newline="") as f:
       for r in csv.DictReader(f):
        ts=pts(r["timestamp"])
        if prev is not None and ts<=prev:continue
        prev=ts;o,h,l,c=map(float,(r["open"],r["high"],r["low"],r["close"]));v=float(r.get("volume") or 0);qk=qkey(ts);hk=hkey(ts)
        if cq is not None and qk!=cq.key:
            macd.commit(cq.close);stoch.commit(cq.high,cq.low,cq.close)
            for obj in vws.values():obj.commit(cq.close,cq.volume)
            cq=None
        if hkcur is not None and hk!=hkcur:
            process_hour(mins,ref);ref={"high":hagg.high,"low":hagg.low};hkcur=hk;hagg=None;mins=[]
        elif hkcur is None:hkcur=hk
        sig={"macd":macd.snapshot(),"stoch":stoch.snapshot(),"vwm":{L:x.snapshot() for L,x in vws.items()}};mins.append(Minute(ts,o,h,l,c,sig))
        if cq is None:cq=AggBar(qk,o,h,l,c,v)
        else:cq.add(o,h,l,c,v)
        if hagg is None:hagg=AggBar(hk,o,h,l,c,v)
        else:hagg.add(o,h,l,c,v)
    if hagg is not None:process_hour(mins,ref)
    report=[]
    for (combo,spec),rows in rows_by_combo.items():
      for wname,hours in WINDOWS.items():report.append({"combo":combo,"exit":spec,"window":wname,"dev":metrics(rows,DEV,hours),"holdout":metrics(rows,HOLD,hours),"full":metrics(rows,None,hours)})
    eligible=[x for x in report if x["dev"]["n"]>=40 and x["holdout"]["n"]>=20];rank=sorted(eligible,key=lambda x:(x["dev"]["avg"] or -999),reverse=True)
    stable=sorted(eligible,key=lambda x:min(x["dev"]["avg"] or -999,x["holdout"]["avg"] or -999),reverse=True)
    payload={"top_by_dev":rank[:30],"top_by_min_dev_holdout":stable[:30],"all":report};os.makedirs("backtest_output",exist_ok=True)
    with open("backtest_output/mgc_exit_sauce.json","w") as f:json.dump(payload,f,indent=2)
    print("EXIT_SAUCE_STABLE_START")
    for x in stable[:20]:print(json.dumps(x,separators=(",",":")))
    print("EXIT_SAUCE_STABLE_END")
if __name__=="__main__":main(sys.argv[1] if len(sys.argv)>1 else ".")
