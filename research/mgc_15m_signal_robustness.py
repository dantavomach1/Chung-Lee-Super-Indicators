from __future__ import annotations
import csv, glob, json, os, sys
from collections import deque, defaultdict
from mgc_15m_mid_slow_stoch_sweep import AdaptiveMACD2, VWMA, AggBar, Minute, pts, qkey, hkey, local_hour, simulate_fixed, TICK
THRESHOLDS=[20,25,30]; LOOKBACKS=[1,2,4,6,8]; VWMA_LENGTHS=[0,10,14,20]; DIST=10
class ParamStoch:
    def __init__(self,length=14,smooth_k=3,smooth_d=3):
        self.length=length;self.sk=smooth_k;self.sd=smooth_d;self.highs=deque(maxlen=length);self.lows=deque(maxlen=length);self.raw=deque(maxlen=smooth_k);self.ks=deque(maxlen=smooth_d);self.k=self.d=self.pk=self.pd=None;self.hist=deque(maxlen=16)
    def commit(self,h,l,c):
        self.highs.append(h);self.lows.append(l);self.pk,self.pd=self.k,self.d
        if len(self.highs)>=self.length:
            hh,ll=max(self.highs),min(self.lows);rk=50.0 if hh==ll else 100*(c-ll)/(hh-ll);self.raw.append(rk)
            if len(self.raw)>=self.sk:self.k=sum(self.raw)/len(self.raw);self.ks.append(self.k);self.d=sum(self.ks)/len(self.ks) if len(self.ks)>=self.sd else None
        self.hist.append((self.k,self.d))
    def snapshot(self):
        if None in (self.k,self.d,self.pk,self.pd):return None
        return {"k":self.k,"d":self.d,"pk":self.pk,"pd":self.pd,"hist":[x for x in self.hist if x[0] is not None and x[1] is not None]}
def combo_name(t,n,L):return f"T{t}_N{n}_VWMA{L if L else 'OFF'}"
def filt(combo,d,sig):
    t,n,L=combo;m=sig.get("macd") if sig else None;st=sig.get("stoch") if sig else None
    if not m or not m.get(d) or not st:return False
    recent=st["hist"][-n:]
    if d=="long":
        if not(st["k"]>st["pk"]):return False
        if not any(k<=t or dd<=t for k,dd in recent):return False
    else:
        hi=100-t
        if not(st["k"]<st["pk"]):return False
        if not any(k>=hi or dd>=hi for k,dd in recent):return False
    if L:
        vw=sig["vwm"].get(L)
        if not vw:return False
        if d=="long" and not(vw["close"]>vw["vwma"]):return False
        if d=="short" and not(vw["close"]<vw["vwma"]):return False
    return True
def find_entry(minutes,rh,rl,combo):
    bl=bs=False
    for i,b in enumerate(minutes):
        lc=(not bl) and b.h>rh;sc=(not bs) and b.l<rl
        if not(lc or sc):continue
        tl=rh+TICK;ts=rl-TICK;lo=filt(combo,"long",b.signal) if lc else False;so=filt(combo,"short",b.signal) if sc else False
        if lc:bl=True
        if sc:bs=True
        if lo and so:return None
        if lo:return {"idx":i,"direction":"long","entry":max(tl,b.o),"trigger":tl,"gap":b.o>=tl}
        if so:return {"idx":i,"direction":"short","entry":min(ts,b.o),"trigger":ts,"gap":b.o<=ts}
    return None
trades=defaultdict(list)
def process_hour(minutes,ref):
    if not minutes or ref is None:return
    hour=local_hour(minutes[0].ts)
    for t in THRESHOLDS:
      for n in LOOKBACKS:
       for L in VWMA_LENGTHS:
        combo=(t,n,L);ev=find_entry(minutes,ref["high"],ref["low"],combo)
        if not ev:continue
        out=simulate_fixed(minutes,ev,DIST);trades[combo_name(t,n,L)].append({"year":minutes[0].ts.year,"hour":hour,"direction":ev["direction"],"ambiguous":out["ambiguous"],"pnl":out["pnl"],"reason":out["reason"]})
def metrics(rows,years=None,hours=None):
    rr=[r for r in rows if (years is None or r["year"] in years) and (hours is None or r["hour"] in hours) and not r["ambiguous"]];amb=sum(1 for r in rows if (years is None or r["year"] in years) and (hours is None or r["hour"] in hours) and r["ambiguous"])
    if not rr:return {"n":0,"amb":amb,"wins":0,"losses":0,"avg":None,"points":0,"pf":None}
    wins=sum(r["pnl"]>1e-9 for r in rr);losses=sum(r["pnl"]<-1e-9 for r in rr);pos=sum(r["pnl"] for r in rr if r["pnl"]>0);neg=-sum(r["pnl"] for r in rr if r["pnl"]<0)
    return {"n":len(rr),"amb":amb,"wins":wins,"losses":losses,"avg":sum(r["pnl"] for r in rr)/len(rr),"points":sum(r["pnl"] for r in rr),"pf":pos/neg if neg>0 else None}
def main(root):
    files=sorted(glob.glob(os.path.join(root,"data","ohlcv_MGC_*.csv")));macd=AdaptiveMACD2();stoch=ParamStoch();vws={L:VWMA(L) for L in [10,14,20]};cq=None;hkcur=None;hagg=None;mins=[];ref=None;prev=None
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
        sig={"macd":macd.snapshot(),"stoch":stoch.snapshot(),"vwm":{L:o.snapshot() for L,o in vws.items()}};mins.append(Minute(ts,o,h,l,c,sig))
        if cq is None:cq=AggBar(qk,o,h,l,c,v)
        else:cq.add(o,h,l,c,v)
        if hagg is None:hagg=AggBar(hk,o,h,l,c,v)
        else:hagg.add(o,h,l,c,v)
    if hagg is not None:process_hour(mins,ref)
    dev={2023,2024};hold={2025,2026};ov={19,20,21,22,23,0,1,2,3};report=[]
    for name,rows in trades.items():
        p=name.replace("T","",1).split("_");t=int(p[0]);n=int(p[1][1:]);vp=p[2].replace("VWMA","");L=0 if vp=="OFF" else int(vp)
        report.append({"name":name,"threshold":t,"lookback":n,"vwma":L,"dev":metrics(rows,dev,ov),"holdout":metrics(rows,hold,ov),"full":metrics(rows,None,ov),"all_hours":metrics(rows,None,None)})
    eligible=[x for x in report if x["dev"]["n"]>=50 and x["holdout"]["n"]>=30];ranked=sorted(eligible,key=lambda x:x["dev"]["avg"] if x["dev"]["avg"] is not None else -1e9,reverse=True);base=next(x for x in report if x["threshold"]==25 and x["lookback"]==4 and x["vwma"]==14);base_rows=trades[base["name"]]
    year_hour={str(y):{str(h):metrics(base_rows,{y},{h}) for h in [19,20,21,22,23,0,1,2,3]} for y in [2023,2024,2025,2026]}
    windows={"19_03":[19,20,21,22,23,0,1,2,3],"20_02":[20,21,22,23,0,1,2],"22_02":[22,23,0,1,2],"00_02":[0,1,2],"00_03":[0,1,2,3]};base_windows={k:{"dev":metrics(base_rows,dev,set(v)),"holdout":metrics(base_rows,hold,set(v)),"full":metrics(base_rows,None,set(v))} for k,v in windows.items()}
    payload={"ranking_by_DEV_2023_2024":ranked,"base_T25_N4_VWMA14":base,"base_year_hour":year_hour,"base_windows":base_windows};os.makedirs("backtest_output",exist_ok=True)
    with open("backtest_output/mgc_15m_signal_robustness.json","w") as f:json.dump(payload,f,indent=2)
    print("ROBUST_TOP_DEV_START")
    for x in ranked[:15]:print(json.dumps(x,separators=(",",":")))
    print("ROBUST_TOP_DEV_END");print("BASE="+json.dumps(base,separators=(",",":")));print("BASE_WINDOWS="+json.dumps(base_windows,separators=(",",":")));print("BASE_YEAR_HOUR="+json.dumps(year_hour,separators=(",",":")))
if __name__=="__main__":main(sys.argv[1] if len(sys.argv)>1 else ".")
