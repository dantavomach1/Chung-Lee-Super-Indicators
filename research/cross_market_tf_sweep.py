from __future__ import annotations
import csv,glob,json,math,os,sys
from collections import deque,defaultdict
from dataclasses import dataclass
from datetime import datetime,timezone,timedelta
from zoneinfo import ZoneInfo
sys.path.insert(0,"research")
from mgc_pullback_entry_sweep import AdaptiveMACD2,SlowStoch,VWMA

LA=ZoneInfo("America/Los_Angeles")
SPECS={
 "MGC":{"tick":0.1,"mult":10.0},
 "MNQ":{"tick":0.25,"mult":2.0},
 "MCL":{"tick":0.01,"mult":100.0},
}
THRESH=[70,75,80]
AGES=[2,4,6]
SESS={"ALL":None,"19_03":{19,20,21,22,23,0,1,2,3},"20_02":{20,21,22,23,0,1,2},"22_02":{22,23,0,1,2},"00_02":{0,1,2}}
PAIRS=[(5,5,"5_same"),(5,15,"5_to15"),(15,15,"15_same"),(15,60,"15_to60"),(60,60,"60_same"),(60,240,"60_to240")]
STOP_MODES=[("ATR",0.5),("ATR",1.0),("ATR",1.5),("ATR",2.0),("SIGNAL",0.0)]
TARGETS=["REF","VWMA200","NEAREST","CLOSE"]

@dataclass
class Bar:
 ts:datetime;o:float;h:float;l:float;c:float;v:float
@dataclass
class Agg:
 key:datetime;o:float;h:float;l:float;c:float;v:float
 def add(self,b):self.h=max(self.h,b.h);self.l=min(self.l,b.l);self.c=b.c;self.v+=b.v

class ATR:
 def __init__(self,n=14):self.n=n;self.prev=None;self.vals=deque(maxlen=n);self.value=None
 def commit(self,h,l,c):
  tr=h-l if self.prev is None else max(h-l,abs(h-self.prev),abs(l-self.prev));self.vals.append(tr)
  if len(self.vals)==self.n:self.value=sum(self.vals)/self.n
  self.prev=c

def ptime(s):
 s=s.replace("Z","").split("+")[0]
 s=s.split(".")[0]
 for f in ("%Y-%m-%dT%H:%M:%S","%Y-%m-%d %H:%M:%S"):
  try:return datetime.strptime(s,f)
  except:pass
 raise ValueError(s)

def keyn(ts,n):
 # UTC-aligned n-minute buckets
 epoch=datetime(1970,1,1);m=int((ts-epoch).total_seconds()//60);x=(m//n)*n
 return epoch+timedelta(minutes=x)
def lhour(ts):return ts.replace(tzinfo=timezone.utc).astimezone(LA).hour

def load_top(root,sym):
 fs=sorted(glob.glob(os.path.join(root,sym,f"{sym}_1min_*.csv")))
 if not fs:raise SystemExit(f"no {sym} files")
 seen=None
 for fp in fs:
  with open(fp,newline="") as f:
   for r in csv.DictReader(f):
    ts=ptime(r.get("datetime") or r.get("timestamp"));
    if seen is not None and ts<=seen:continue
    seen=ts
    yield Bar(ts,float(r["open"]),float(r["high"]),float(r["low"]),float(r["close"]),float(r.get("volume") or 0))
def load_deep(root):
 fs=sorted(glob.glob(os.path.join(root,"data","ohlcv_MGC_*.csv")))
 seen=None
 for fp in fs:
  with open(fp,newline="") as f:
   for r in csv.DictReader(f):
    ts=ptime(r["timestamp"])
    if seen is not None and ts<=seen:continue
    seen=ts
    yield Bar(ts,float(r["open"]),float(r["high"]),float(r["low"]),float(r["close"]),float(r.get("volume") or 0))

def bucket():
 return {"trades":[],"amb":0}
R=defaultdict(bucket)

def pf(vals):
 pos=sum(x for x in vals if x>0);neg=-sum(x for x in vals if x<0)
 return pos/neg if neg>0 else (999.0 if pos>0 else None)
def dd(vals):
 eq=peak=0.;mx=0.
 for x in vals:
  eq+=x;peak=max(peak,eq);mx=max(mx,peak-eq)
 return mx

def metrics(arr,tick,mult):
 if not arr:return None
 pn=[x["p"] for x in arr];rr=[x["r"] for x in arr];net=[x["p"]-2*tick for x in arr];nrr=[x["r"]-(2*tick/x["risk"] if x["risk"]>0 else 0) for x in arr]
 w=sum(x>0 for x in pn);l=sum(x<0 for x in pn);f=len(pn)-w-l
 return {"n":len(arr),"w":w,"l":l,"flat":f,"wr":w/len(arr),"pts":sum(pn),"avg_pts":sum(pn)/len(arr),"pf":pf(pn),"avgR":sum(rr)/len(rr),"pfR":pf(rr),"maxddR":dd(rr),"net2tick_pts":sum(net),"net2tick_avgR":sum(nrr)/len(nrr),"net2tick_pfR":pf(nrr),"dollars_1micro":sum(net)*mult}

def favorable(d,e,ref,vw):
 vals=[]
 if ref is not None:
  x=ref[1] if d=="short" else ref[0]
  if (d=="short" and x<e) or (d=="long" and x>e):vals.append(("REF",x))
 if vw is not None and ((d=="short" and vw<e) or (d=="long" and vw>e)):vals.append(("VWMA200",vw))
 return vals

def sim(mins,i0,d,e,stop,target,endidx,tick):
 for j in range(i0,endidx+1):
  b=mins[j];hs=b.l<=stop if d=="long" else b.h>=stop;ht=False
  if target is not None:ht=b.h>=target if d=="long" else b.l<=target
  if hs and ht:return None
  if hs:
   fill=min(stop,b.o) if d=="long" and b.o<stop else max(stop,b.o) if d=="short" and b.o>stop else stop
   return (fill-e if d=="long" else e-fill,"STOP")
  if ht:return (target-e if d=="long" else e-target,"TARGET")
 x=mins[endidx].c;return (x-e if d=="long" else e-x,"TIME")

def run_stream(rows,sym,sig_n,struct_n,label,dataset):
 tick=SPECS[sym]["tick"];mult=SPECS[sym]["mult"]
 macd=AdaptiveMACD2();st=SlowStoch();vw200=VWMA(200);atr=ATR(14)
 sigagg=None;sigstate=None;structkey=None;mins=[];ref=None;first=last=None;cnt=0
 def commitsig(a):
  nonlocal sigstate
  macd.commit(a.c);st.commit(a.h,a.l,a.c);vw200.commit(a.c,a.v);atr.commit(a.h,a.l,a.c)
  sigstate={"bar_key":a.key,"h":a.h,"l":a.l,"c":a.c,"macd":macd.snapshot(),"stoch":st.snapshot(),"vw":vw200.value,"atr":atr.value}
 def process(ms,refx):
  if not ms or refx is None:return
  # entries are armed by completed signal states visible in this structure bucket
  for thr in THRESH:
   for age in AGES:
    armed=None;lastid=None
    # each config gets one first qualifying trade in the structure bucket
    ev=None
    for i,(b,sig) in enumerate(ms):
     sid=sig.get("bar_key") if sig else None
     if sid is not None and sid!=lastid:
      lastid=sid;m=sig.get("macd");ss=sig.get("stoch")
      if m and ss:
       oks=[]
       if m.get("short") and m.get("short_age",999)<=age and ss["k"]>=thr and ss["k"]<ss["pk"]:oks.append("short")
       if m.get("long") and m.get("long_age",999)<=age and ss["k"]<=100-thr and ss["k"]>ss["pk"]:oks.append("long")
       if len(oks)==1:
        d=oks[0];armed={"d":d,"level":sig["l"]-tick if d=="short" else sig["h"]+tick,"sig":sig}
       elif len(oks)>1:armed=None
     if armed:
      d=armed["d"];lev=armed["level"]
      hit=(b.l<lev if d=="short" else b.h>lev)
      if hit:
       e=min(lev,b.o) if d=="short" else max(lev,b.o)
       fav=favorable(d,e,refx,armed["sig"].get("vw"))
       if any(k=="REF" for k,_ in fav):ev=(i,d,e,armed["sig"],fav);break
    if ev is None:continue
    i0,d,e,esig,fav=ev;entryhour=lhour(ms[i0][0].ts)
    for sname,hours in SESS.items():
     if hours is not None and entryhour not in hours:continue
     for smode,sv in STOP_MODES:
      if smode=="ATR":
       av=esig.get("atr");
       if av is None or av<=0:continue
       risk=av*sv;stop=e+risk if d=="short" else e-risk
      else:
       stop=esig["h"]+tick if d=="short" else esig["l"]-tick;risk=abs(stop-e)
       if risk<=0:continue
      for tk in TARGETS:
       target=None
       if tk=="REF":target=next((x for k,x in fav if k=="REF"),None)
       elif tk=="VWMA200":target=next((x for k,x in fav if k=="VWMA200"),None)
       elif tk=="NEAREST":
        xs=[x for _,x in fav];target=(max(xs) if d=="short" else min(xs)) if xs else None
       if tk!="CLOSE" and target is None:continue
       out=sim([x[0] for x in ms],i0,d,e,stop,target,len(ms)-1,tick)
       key=(dataset,sym,label,sig_n,struct_n,thr,age,sname,smode,sv,tk)
       if out is None:R[key]["amb"]+=1;continue
       p,reason=out
       R[key]["trades"].append({"p":p,"r":p/risk,"risk":risk,"d":d,"y":ms[i0][0].ts.year,"reason":reason})
 def flush_struct():
  nonlocal mins,ref
  if mins:
   process(mins,ref)
   ref=(max(x[0].h for x in mins),min(x[0].l for x in mins))
   mins=[]
 for b in rows:
  cnt+=1;first=first or b.ts;last=b.ts
  sk=keyn(b.ts,sig_n);bk=keyn(b.ts,struct_n)
  if sigagg is not None and sk!=sigagg.key:commitsig(sigagg);sigagg=None
  if structkey is not None and bk!=structkey:flush_struct();structkey=bk
  elif structkey is None:structkey=bk
  if sigagg is None:sigagg=Agg(sk,b.o,b.h,b.l,b.c,b.v)
  else:sigagg.add(b)
  mins.append((b,sigstate.copy() if sigstate else None))
 if sigagg is not None:commitsig(sigagg)
 flush_struct()
 return {"rows":cnt,"first":first.isoformat() if first else None,"last":last.isoformat() if last else None}

def summarize(dataset,sym,label,sig_n,struct_n):
 rows=[]
 for k,b in R.items():
  ds,sy,lab,sn,stn,thr,age,sess,smode,sv,tk=k
  if (ds,sy,lab,sn,stn)!=(dataset,sym,label,sig_n,struct_n):continue
  m=metrics(b["trades"],SPECS[sym]["tick"],SPECS[sym]["mult"])
  if not m:continue
  short=metrics([x for x in b["trades"] if x["d"]=="short"],SPECS[sym]["tick"],SPECS[sym]["mult"])
  long=metrics([x for x in b["trades"] if x["d"]=="long"],SPECS[sym]["tick"],SPECS[sym]["mult"])
  byy={}
  for y in sorted(set(x["y"] for x in b["trades"])):byy[str(y)]=metrics([x for x in b["trades"] if x["y"]==y],SPECS[sym]["tick"],SPECS[sym]["mult"])
  rows.append({"thr":thr,"age":age,"session":sess,"stop":f"{smode}{sv:g}" if smode=="ATR" else "SIGNAL","target":tk,"amb":b["amb"],**m,"short":short,"long":long,"by_year":byy})
 return rows

def main(toproot,deeproot):
 meta={}
 # common-window TopstepX transfer tests
 for sym in ("MGC","MNQ","MCL"):
  for sn,stn,label in PAIRS:
   x=run_stream(load_top(toproot,sym),sym,sn,stn,label,"COMMON2026");meta[("COMMON2026",sym,label)]=x
   print("DONE",sym,label,x,file=sys.stderr)
 # deep gold ladder only
 for sn,stn,label in PAIRS:
  x=run_stream(load_deep(deeproot),"MGC",sn,stn,label,"MGC_DEEP");meta[("MGC_DEEP","MGC",label)]=x
  print("DONE MGC_DEEP",label,x,file=sys.stderr)
 allout=[]
 for (ds,sym,label),mta in meta.items():
  sn,stn=next((a,b) for a,b,l in PAIRS if l==label)
  rr=summarize(ds,sym,label,sn,stn)
  # broad robust candidates; rank net-of-2-tick avgR, require enough trades
  floor=80 if ds=="MGC_DEEP" else 15
  cand=[x for x in rr if x["n"]>=floor and x["net2tick_pfR"] is not None]
  cand.sort(key=lambda x:(x["net2tick_avgR"],x["net2tick_pfR"]),reverse=True)
  print("TOP",ds,sym,label,json.dumps(cand[:5],separators=(",",":")))
  # short-only top
  sc=[x for x in rr if x.get("short") and x["short"]["n"]>=max(10,floor//2) and x["short"]["net2tick_pfR"] is not None]
  sc.sort(key=lambda x:(x["short"]["net2tick_avgR"],x["short"]["net2tick_pfR"]),reverse=True)
  print("TOPSHORT",ds,sym,label,json.dumps(sc[:5],separators=(",",":")))
  allout.append({"dataset":ds,"symbol":sym,"label":label,"meta":mta,"results":rr})
 os.makedirs("backtest_output",exist_ok=True)
 with open("backtest_output/cross_market_tf_sweep.json","w") as f:json.dump({"runs":allout},f)

if __name__=="__main__":main(sys.argv[1],sys.argv[2])
