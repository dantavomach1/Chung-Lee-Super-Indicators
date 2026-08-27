from __future__ import annotations
import csv, glob, json, math, os, sys
from collections import deque, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

TICK = 0.1
LA = ZoneInfo("America/Los_Angeles")
MACD_CFG = [(15,21,144,34,"mid"), (15,65,270,105,"slow")]
STOPS = [5.0,7.5,10.0,12.5,15.0,20.0]
SESSIONS = {
    "ALL": None,
    "19_03": {19,20,21,22,23,0,1,2,3},
    "20_02": {20,21,22,23,0,1,2},
    "22_02": {22,23,0,1,2},
    "00_02": {0,1,2},
}
ENTRY_VARIANTS = [
    "BREAKOUT_MACD",
    "TURN75_A4",
    "TURN80_A4",
    "CROSS75_A4",
    "EXIT75_A4",
    "TURN75_ANY",
    "BREAK15_TURN75_A4",
    "BREAK15_CROSS75_A4",
    "VWMA14_REJECT_TURN75_A4",
]
TARGETS = ["HOUR_CLOSE", "REF_BOUNDARY", "VWMA200", "POC_PROXY", "NEAREST_STRUCT"]

def pts(s): return datetime.strptime(s.split(".")[0], "%Y-%m-%d %H:%M:%S")
def qkey(ts): return ts.replace(minute=(ts.minute//15)*15, second=0, microsecond=0)
def hkey(ts): return ts.replace(minute=0, second=0, microsecond=0)
def lhour(ts): return ts.replace(tzinfo=timezone.utc).astimezone(LA).hour

def corr_r2(closes):
    n=len(closes)
    if n<2: return None
    mx=(n-1)/2; my=sum(closes)/n
    sxx=sum((i-mx)**2 for i in range(n)); syy=sum((y-my)**2 for y in closes)
    if sxx<=0 or syy<=0: corr=0.0
    else:
        sxy=sum((i-mx)*(y-my) for i,y in enumerate(closes))
        corr=max(-1.0,min(1.0,sxy/math.sqrt(sxx*syy)))
    return .5*corr*corr+.5

class AdaptiveMACD2:
    def __init__(self):
        self.close_hist=deque(maxlen=15); self.prev_close=None
        self.prior_hists=[None,None]; self.states=[]
        self.short_age=0; self.long_age=0
        for period,fast,slow,signal,name in MACD_CFG:
            self.states.append({
                "name":name, "a1":2/(fast+1), "a2":2/(slow+1),
                "alpha":2/(signal+1), "m1":0.0, "m2":0.0,
                "ema":None, "hist":None
            })
    def _eval(self,st,close,r2):
        if self.prev_close is None or r2 is None: return None,None,None
        a1,a2=st["a1"],st["a2"]
        K=r2*((1-a1)*(1-a2))+(1-r2)*((1-a1)/(1-a2))
        macd=(close-self.prev_close)*(a1-a2)+(-a2-a1+2)*st["m1"]-K*st["m2"]
        ema=macd if st["ema"] is None else st["alpha"]*macd+(1-st["alpha"])*st["ema"]
        return macd,ema,macd-ema
    def commit(self,close):
        old=[st["hist"] for st in self.states]
        vals=list(self.close_hist)[-14:]+[close]
        r2=corr_r2(vals) if len(vals)>=15 else None
        for st in self.states:
            m,e,h=self._eval(st,close,r2)
            if m is not None:
                st["m2"],st["m1"]=st["m1"],m
                st["ema"],st["hist"]=e,h
        self.prior_hists=old
        self.prev_close=close
        self.close_hist.append(close)
        snap=self._raw_snapshot()
        if snap:
            self.long_age = self.long_age+1 if snap["long"] else 0
            self.short_age = self.short_age+1 if snap["short"] else 0
    def _raw_snapshot(self):
        h=[st["hist"] for st in self.states]; p=self.prior_hists
        if any(x is None for x in h+p): return None
        return {
            "mid":h[0],"slow":h[1],"mid_prev":p[0],"slow_prev":p[1],
            "long":h[0]<0 and h[1]<0 and h[0]>p[0] and h[1]>p[1],
            "short":h[0]>0 and h[1]>0 and h[0]<p[0] and h[1]<p[1],
        }
    def snapshot(self):
        s=self._raw_snapshot()
        if not s:return None
        s["long_age"]=self.long_age; s["short_age"]=self.short_age
        return s

class SlowStoch:
    def __init__(self,length=14,smooth_k=3,smooth_d=3):
        self.length=length; self.smooth_k=smooth_k; self.smooth_d=smooth_d
        self.highs=deque(maxlen=length); self.lows=deque(maxlen=length)
        self.rawks=deque(maxlen=smooth_k); self.slowks=deque(maxlen=smooth_d)
        self.k=self.d=self.pk=self.pd=None
    def commit(self,high,low,close):
        self.highs.append(high); self.lows.append(low); self.pk,self.pd=self.k,self.d
        if len(self.highs)<self.length:return
        hh,ll=max(self.highs),min(self.lows)
        raw=50.0 if hh==ll else 100*(close-ll)/(hh-ll)
        self.rawks.append(raw)
        if len(self.rawks)<self.smooth_k:return
        self.k=sum(self.rawks)/len(self.rawks)
        self.slowks.append(self.k)
        if len(self.slowks)>=self.smooth_d:self.d=sum(self.slowks)/len(self.slowks)
    def snapshot(self):
        if None in (self.k,self.d,self.pk,self.pd):return None
        return {"k":self.k,"d":self.d,"pk":self.pk,"pd":self.pd}

class VWMA:
    def __init__(self,n):
        self.n=n; self.rows=deque(maxlen=n); self.value=None
    def commit(self,close,vol):
        self.rows.append((close,vol))
        if len(self.rows)<self.n:self.value=None;return
        sv=sum(v for _,v in self.rows)
        self.value=sum(c*v for c,v in self.rows)/sv if sv else sum(c for c,_ in self.rows)/len(self.rows)

@dataclass
class Agg:
    key:datetime; o:float; h:float; l:float; c:float; v:float
    def add(self,o,h,l,c,v):
        self.h=max(self.h,h);self.l=min(self.l,l);self.c=c;self.v+=v

@dataclass
class Min:
    ts:datetime; o:float; h:float; l:float; c:float; v:float; sig:dict|None

@dataclass
class RefHour:
    key:datetime; high:float; low:float; poc:float|None

def poc_proxy(minutes,bin_size=0.5):
    d=defaultdict(float)
    for b in minutes:
        p=(b.h+b.l+b.c)/3
        k=round(p/bin_size)*bin_size
        d[k]+=b.v
    return max(d.items(), key=lambda kv:kv[1])[0] if d else None

def macd_ok(sig,d,age_max=None):
    m=(sig or {}).get("macd")
    if not m or not m.get(d):return False
    if age_max is not None and m.get(d+"_age",999)>age_max:return False
    return True

def stoch_turn(sig,d,thr):
    s=(sig or {}).get("stoch")
    if not s:return False
    if d=="short": return s["k"]>=thr and s["k"]<s["pk"]
    return s["k"]<=100-thr and s["k"]>s["pk"]

def stoch_cross(sig,d,thr=75):
    s=(sig or {}).get("stoch")
    if not s:return False
    if d=="short":
        return s["pk"]>=s["pd"] and s["k"]<s["d"] and max(s["pk"],s["pd"],s["k"],s["d"])>=thr
    return s["pk"]<=s["pd"] and s["k"]>s["d"] and min(s["pk"],s["pd"],s["k"],s["d"])<=100-thr

def stoch_exit(sig,d,thr=75):
    s=(sig or {}).get("stoch")
    if not s:return False
    if d=="short": return s["pk"]>=thr and s["k"]<thr and s["k"]<s["pk"]
    return s["pk"]<=100-thr and s["k"]>100-thr and s["k"]>s["pk"]

def direct_signal_ok(sig,d,variant):
    if variant=="TURN75_A4": return macd_ok(sig,d,4) and stoch_turn(sig,d,75)
    if variant=="TURN80_A4": return macd_ok(sig,d,4) and stoch_turn(sig,d,80)
    if variant=="CROSS75_A4": return macd_ok(sig,d,4) and stoch_cross(sig,d,75)
    if variant=="EXIT75_A4": return macd_ok(sig,d,4) and stoch_exit(sig,d,75)
    if variant=="TURN75_ANY": return macd_ok(sig,d,None) and stoch_turn(sig,d,75)
    return False

def favorable_ref_target(d,entry,ref):
    if d=="short" and ref.low<entry:return ref.low
    if d=="long" and ref.high>entry:return ref.high
    return None

def favorable_vwma200(d,entry,sig):
    x=(sig or {}).get("vwma200")
    if x is None:return None
    if d=="short" and x<entry:return x
    if d=="long" and x>entry:return x
    return None

def favorable_poc(d,entry,ref):
    x=ref.poc
    if x is None:return None
    if d=="short" and x<entry:return x
    if d=="long" and x>entry:return x
    return None

def choose_target(kind,d,entry,ref,sig):
    if kind=="HOUR_CLOSE":return None
    rb=favorable_ref_target(d,entry,ref)
    vw=favorable_vwma200(d,entry,sig)
    pc=favorable_poc(d,entry,ref)
    if kind=="REF_BOUNDARY":return rb
    if kind=="VWMA200":return vw
    if kind=="POC_PROXY":return pc
    vals=[x for x in (rb,vw,pc) if x is not None]
    if not vals:return None
    return max(vals) if d=="short" else min(vals)

def entry_for_variant(minutes,ref,variant):
    if not minutes:return None
    if variant=="BREAKOUT_MACD":
        bl=bs=False
        for i,b in enumerate(minutes):
            lc=(not bl) and b.h>ref.high
            sc=(not bs) and b.l<ref.low
            if lc:bl=True
            if sc:bs=True
            lo=lc and macd_ok(b.sig,"long",None)
            so=sc and macd_ok(b.sig,"short",None)
            if lo and so:return None
            if lo:
                trig=ref.high+TICK
                return {"i":i,"d":"long","entry":max(trig,b.o),"sig":b.sig,"kind":"boundary"}
            if so:
                trig=ref.low-TICK
                return {"i":i,"d":"short","entry":min(trig,b.o),"sig":b.sig,"kind":"boundary"}
        return None

    if variant in ("TURN75_A4","TURN80_A4","CROSS75_A4","EXIT75_A4","TURN75_ANY"):
        last_sig_id=None
        for i,b in enumerate(minutes):
            sid=(b.sig or {}).get("signal_bar_key")
            if sid is None or sid==last_sig_id:continue
            last_sig_id=sid
            for d in ("long","short"):
                if direct_signal_ok(b.sig,d,variant):
                    e=b.o
                    if favorable_ref_target(d,e,ref) is None:continue
                    return {"i":i,"d":d,"entry":e,"sig":b.sig,"kind":"15m_direct"}
        return None

    if variant in ("BREAK15_TURN75_A4","BREAK15_CROSS75_A4"):
        armed=None; last_sig_id=None
        for i,b in enumerate(minutes):
            sid=(b.sig or {}).get("signal_bar_key")
            if sid is not None and sid!=last_sig_id:
                last_sig_id=sid
                for d in ("long","short"):
                    ok = (macd_ok(b.sig,d,4) and
                          (stoch_turn(b.sig,d,75) if "TURN" in variant else stoch_cross(b.sig,d,75)))
                    if ok and favorable_ref_target(d,b.o,ref) is not None:
                        armed={
                            "d":d,
                            "level":(b.sig["signal_bar_high"]+TICK if d=="long" else b.sig["signal_bar_low"]-TICK),
                            "sig":b.sig,
                        }
                        break
            if armed:
                d=armed["d"];lev=armed["level"]
                if d=="long" and b.h>lev:
                    return {"i":i,"d":d,"entry":max(lev,b.o),"sig":armed["sig"],"kind":"break15"}
                if d=="short" and b.l<lev:
                    return {"i":i,"d":d,"entry":min(lev,b.o),"sig":armed["sig"],"kind":"break15"}
        return None

    if variant=="VWMA14_REJECT_TURN75_A4":
        armed=None; last_sig_id=None; prev_close=None
        for i,b in enumerate(minutes):
            sid=(b.sig or {}).get("signal_bar_key")
            if sid is not None and sid!=last_sig_id:
                last_sig_id=sid
                for d in ("long","short"):
                    if macd_ok(b.sig,d,4) and stoch_turn(b.sig,d,75) and favorable_ref_target(d,b.o,ref) is not None:
                        armed={"d":d,"sig":b.sig}
                        break
            if armed and prev_close is not None:
                vw=(b.sig or {}).get("vwma14")
                if vw is not None:
                    d=armed["d"]
                    crossed=(d=="short" and prev_close>=vw and b.c<vw) or (d=="long" and prev_close<=vw and b.c>vw)
                    if crossed and i+1<len(minutes):
                        nb=minutes[i+1]
                        return {"i":i+1,"d":d,"entry":nb.o,"sig":armed["sig"],"kind":"vwma_reject"}
            prev_close=b.c
        return None
    return None

def simulate(minutes,ev,stop_dist,target):
    d,e,i0=ev["d"],ev["entry"],ev["i"]
    stop=e-stop_dist if d=="long" else e+stop_dist
    for j in range(i0,len(minutes)):
        b=minutes[j]
        hs=(b.l<=stop if d=="long" else b.h>=stop)
        ht=(target is not None and (b.h>=target if d=="long" else b.l<=target))
        if j==i0 and hs:
            if ev["kind"] in ("boundary","break15") and not ((d=="long" and b.o>=e) or (d=="short" and b.o<=e)):
                return {"amb":True}
        if hs and ht:return {"amb":True}
        if hs:
            fill=min(stop,b.o) if d=="long" and b.o<stop else max(stop,b.o) if d=="short" and b.o>stop else stop
            pnl=fill-e if d=="long" else e-fill
            return {"amb":False,"pnl":pnl,"reason":"STOP","j":j}
        if ht:
            pnl=target-e if d=="long" else e-target
            return {"amb":False,"pnl":pnl,"reason":"TARGET","j":j}
    x=minutes[-1].c
    pnl=x-e if d=="long" else e-x
    return {"amb":False,"pnl":pnl,"reason":"HOUR_CLOSE","j":len(minutes)-1}

def mfe_mae(minutes,ev):
    arr=minutes[ev["i"]:]
    e=ev["entry"];d=ev["d"]
    if d=="long":return max(b.h for b in arr)-e, e-min(b.l for b in arr)
    return e-min(b.l for b in arr), max(b.h for b in arr)-e

def bucket():
    return {"n":0,"amb":0,"win":0,"loss":0,"flat":0,"sum":0.0,"pos":0.0,"neg":0.0,
            "stop":0,"target":0,"close":0,"mfe":[],"mae":[],"by_year":defaultdict(lambda:[0,0,0,0.0]),
            "by_dir":defaultdict(lambda:[0,0,0,0.0]),"by_hour":defaultdict(lambda:[0,0,0,0.0])}

RES=defaultdict(bucket)
ENTRY_STATS=defaultdict(lambda:{"n":0,"mfe":[],"mae":[],"entry_to_ref":[]})

def add(key,ev,out,mfe,mae):
    b=RES[key]
    if out["amb"]:b["amb"]+=1;return
    p=out["pnl"];b["n"]+=1;b["sum"]+=p;b["mfe"].append(mfe);b["mae"].append(mae)
    if p>1e-9:b["win"]+=1;b["pos"]+=p;cls=0
    elif p<-1e-9:b["loss"]+=1;b["neg"]+=-p;cls=1
    else:b["flat"]+=1;cls=2
    b["stop"]+=out["reason"]=="STOP";b["target"]+=out["reason"]=="TARGET";b["close"]+=out["reason"]=="HOUR_CLOSE"
    y=ev["ts"].year;h=lhour(ev["ts"]);d=ev["d"]
    for k in (b["by_year"][y],b["by_dir"][d],b["by_hour"][h]):
        k[cls]+=1;k[3]+=p

def process_hour(minutes,ref):
    if not minutes or ref is None:return
    hour=lhour(minutes[0].ts)
    for variant in ENTRY_VARIANTS:
        ev=entry_for_variant(minutes,ref,variant)
        if not ev:continue
        ev["ts"]=minutes[ev["i"]].ts
        mfe,mae=mfe_mae(minutes,ev)
        es=ENTRY_STATS[variant];es["n"]+=1;es["mfe"].append(mfe);es["mae"].append(mae)
        rt=favorable_ref_target(ev["d"],ev["entry"],ref)
        if rt is not None:es["entry_to_ref"].append(abs(ev["entry"]-rt))
        for sname,hours in SESSIONS.items():
            if hours is not None and hour not in hours:continue
            for sd in STOPS:
                for tk in TARGETS:
                    target=choose_target(tk,ev["d"],ev["entry"],ref,ev["sig"])
                    out=simulate(minutes,ev,sd,target)
                    add((variant,sname,sd,tk),ev,out,mfe,mae)

def quant(a,q):
    if not a:return None
    a=sorted(a);x=(len(a)-1)*q;i=int(x);f=x-i
    return a[i] if i+1>=len(a) else a[i]*(1-f)+a[i+1]*f

def compact(b):
    n=b["n"];pf=b["pos"]/b["neg"] if b["neg"] else None
    return {"n":n,"amb":b["amb"],"wins":b["win"],"losses":b["loss"],"flat":b["flat"],
            "avg":b["sum"]/n if n else None,"points":b["sum"],"pf":pf,
            "stop_pct":b["stop"]/n if n else None,"target_pct":b["target"]/n if n else None,
            "hour_close_pct":b["close"]/n if n else None,
            "mfe_med":quant(b["mfe"],.5),"mae_med":quant(b["mae"],.5)}

def main(root):
    files=sorted(glob.glob(os.path.join(root,"data","ohlcv_MGC_*.csv")))
    if not files:raise SystemExit("no MGC minute files")
    macd=AdaptiveMACD2(); st=SlowStoch(); vw14=VWMA(14);vw200=VWMA(200)
    qb=None; hk=None; hour_minutes=[]; ref=None; sig=None
    prevts=None;rows=0;first=last=None

    def commit_q(q):
        nonlocal sig
        macd.commit(q.c);st.commit(q.h,q.l,q.c);vw14.commit(q.c,q.v);vw200.commit(q.c,q.v)
        sig={"macd":macd.snapshot(),"stoch":st.snapshot(),"vwma14":vw14.value,"vwma200":vw200.value,
             "signal_bar_key":q.key.isoformat(),"signal_bar_high":q.h,"signal_bar_low":q.l,"signal_bar_close":q.c}

    for fp in files:
        with open(fp,newline="") as f:
            for r in csv.DictReader(f):
                ts=pts(r["timestamp"])
                if prevts is not None and ts<=prevts:continue
                prevts=ts;rows+=1;first=first or ts;last=ts
                o=float(r["open"]);h=float(r["high"]);l=float(r["low"]);c=float(r["close"]);v=float(r.get("volume") or 0)
                qk=qkey(ts);hh=hkey(ts)
                if qb is not None and qk!=qb.key:
                    commit_q(qb);qb=None
                if hk is not None and hh!=hk:
                    process_hour(hour_minutes,ref)
                    ref=RefHour(hk,max(x.h for x in hour_minutes),min(x.l for x in hour_minutes),poc_proxy(hour_minutes))
                    hour_minutes=[];hk=hh
                elif hk is None:hk=hh
                if qb is None:qb=Agg(qk,o,h,l,c,v)
                else:qb.add(o,h,l,c,v)
                hour_minutes.append(Min(ts,o,h,l,c,v,sig.copy() if sig else None))
    if qb is not None:commit_q(qb)
    if hour_minutes:process_hour(hour_minutes,ref)

    meta={"rows":rows,"first":first.isoformat(),"last":last.isoformat(),
          "indicator_tf":"15m completed/static only",
          "macd":"middle + slow adaptive histograms only; same-side and waning",
          "stoch":"Slow Stochastic 14,3,3; timing variants around 75/25 and 80/20",
          "targets":TARGETS,"stops":STOPS,
          "poc":"exploratory prior-hour proxy: each 1m bar volume assigned to rounded 0.5-point HLC3 bin"}
    print("PULLBACK_META="+json.dumps(meta,separators=(",",":")))

    eq={}
    for k,v in ENTRY_STATS.items():
        eq[k]={"n":v["n"],"mfe_med":quant(v["mfe"],.5),"mae_med":quant(v["mae"],.5),
               "mfe_p75":quant(v["mfe"],.75),"mae_p75":quant(v["mae"],.75),
               "median_room_to_ref":quant(v["entry_to_ref"],.5)}
    print("ENTRY_QUALITY="+json.dumps(eq,separators=(",",":")))

    rowsout=[]
    for key,b in RES.items():
        var,sess,sd,tk=key;c=compact(b)
        if c["n"]<25:continue
        row={"entry":var,"session":sess,"stop":sd,"target":tk,**c}
        rowsout.append(row)
    rowsout.sort(key=lambda x:(x["avg"] if x["avg"] is not None else -999),reverse=True)
    print("TOP_AVG_MIN25_START")
    for x in rowsout[:35]:print(json.dumps(x,separators=(",",":")))
    print("TOP_AVG_MIN25_END")
    rowsout.sort(key=lambda x:(x["pf"] if x["pf"] is not None else -999),reverse=True)
    print("TOP_PF_MIN25_START")
    for x in rowsout[:25]:print(json.dumps(x,separators=(",",":")))
    print("TOP_PF_MIN25_END")

    print("SPOTLIGHT_START")
    for var in ENTRY_VARIANTS:
        for sess in ("19_03","20_02","22_02","00_02"):
            for tk in ("HOUR_CLOSE","REF_BOUNDARY","VWMA200","NEAREST_STRUCT"):
                b=RES.get((var,sess,10.0,tk))
                if not b:continue
                c=compact(b)
                if c["n"]<8:continue
                rec={"entry":var,"session":sess,"stop":10.0,"target":tk,**c,
                     "by_year":{str(k):v for k,v in b["by_year"].items()},
                     "by_dir":{str(k):v for k,v in b["by_dir"].items()}}
                print(json.dumps(rec,separators=(",",":")))
    print("SPOTLIGHT_END")

    os.makedirs("backtest_output",exist_ok=True)
    with open("backtest_output/mgc_pullback_entry_sweep.json","w") as f:
        json.dump({"meta":meta,"entry_quality":eq,
                   "results":[{"entry":k[0],"session":k[1],"stop":k[2],"target":k[3],**compact(v),
                               "by_year":{str(y):z for y,z in v["by_year"].items()},
                               "by_dir":{str(y):z for y,z in v["by_dir"].items()},
                               "by_hour":{str(y):z for y,z in v["by_hour"].items()}}
                              for k,v in RES.items()]},f)

if __name__=="__main__":
    main(sys.argv[1])
