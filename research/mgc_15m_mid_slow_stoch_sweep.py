from __future__ import annotations
import csv, glob, json, math, os, sys
from collections import deque, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

TICK = 0.1
LA = ZoneInfo("America/Los_Angeles")
MACD_CFG = [(15, 21, 144, 34, "mid"),(15, 65, 270, 105, "slow")]
DISTANCES = list(range(5, 51, 5))

def pts(s): return datetime.strptime(s.split(".")[0], "%Y-%m-%d %H:%M:%S")
def hkey(ts): return ts.replace(minute=0, second=0, microsecond=0)
def qkey(ts): return ts.replace(minute=(ts.minute // 15) * 15, second=0, microsecond=0)
def local_hour(ts): return ts.replace(tzinfo=timezone.utc).astimezone(LA).hour
def corr_r2(closes):
    n=len(closes)
    if n<2:return None
    mx=(n-1)/2; my=sum(closes)/n
    sxx=sum((i-mx)**2 for i in range(n)); syy=sum((y-my)**2 for y in closes)
    if sxx<=0 or syy<=0:corr=0.0
    else:
        sxy=sum((i-mx)*(y-my) for i,y in enumerate(closes)); corr=max(-1.0,min(1.0,sxy/math.sqrt(sxx*syy)))
    return 0.5*corr*corr+0.5

class AdaptiveMACD2:
    def __init__(self):
        self.close_hist=deque(maxlen=15); self.prev_close=None; self.prior_hists=[None,None]; self.states=[]
        for period,fast,slow,signal,name in MACD_CFG:
            self.states.append({"name":name,"a1":2/(fast+1),"a2":2/(slow+1),"alpha":2/(signal+1),"m1":0.0,"m2":0.0,"ema":None,"hist":None})
    def _eval(self,st,close,r2):
        if self.prev_close is None or r2 is None:return None,None,None
        a1,a2=st["a1"],st["a2"]; K=r2*((1-a1)*(1-a2))+(1-r2)*((1-a1)/(1-a2))
        macd=(close-self.prev_close)*(a1-a2)+(-a2-a1+2)*st["m1"]-K*st["m2"]
        ema=macd if st["ema"] is None else st["alpha"]*macd+(1-st["alpha"])*st["ema"]
        return macd,ema,macd-ema
    def commit(self,close):
        old=[st["hist"] for st in self.states]; vals=list(self.close_hist)[-14:]+[close]; r2=corr_r2(vals) if len(vals)>=15 else None
        for st in self.states:
            m,e,h=self._eval(st,close,r2)
            if m is not None: st["m2"],st["m1"]=st["m1"],m; st["ema"],st["hist"]=e,h
        self.prior_hists=old; self.prev_close=close; self.close_hist.append(close)
    def snapshot(self):
        h=[st["hist"] for st in self.states]; p=self.prior_hists
        if any(x is None for x in h+p):return None
        return {"mid":h[0],"slow":h[1],"mid_prev":p[0],"slow_prev":p[1],
                "long":h[0]<0 and h[1]<0 and h[0]>p[0] and h[1]>p[1],
                "short":h[0]>0 and h[1]>0 and h[0]<p[0] and h[1]<p[1]}

class SlowStoch:
    def __init__(self,length=14,smooth_k=3,smooth_d=3):
        self.length=length; self.smooth_k=smooth_k; self.smooth_d=smooth_d
        self.highs=deque(maxlen=length); self.lows=deque(maxlen=length); self.rawks=deque(maxlen=smooth_k); self.slowks=deque(maxlen=smooth_d)
        self.k=self.d=self.prev_k=self.prev_d=None; self.recent=deque(maxlen=5)
    def commit(self,high,low,close):
        self.highs.append(high); self.lows.append(low); self.prev_k,self.prev_d=self.k,self.d
        if len(self.highs)<self.length:self.recent.append((self.k,self.d));return
        hh,ll=max(self.highs),min(self.lows); raw=50.0 if hh==ll else 100.0*(close-ll)/(hh-ll); self.rawks.append(raw)
        if len(self.rawks)<self.smooth_k:self.recent.append((self.k,self.d));return
        k=sum(self.rawks)/len(self.rawks); self.slowks.append(k); self.k=k; self.d=sum(self.slowks)/len(self.slowks) if len(self.slowks)>=self.smooth_d else None; self.recent.append((self.k,self.d))
    def snapshot(self):
        if None in (self.k,self.d,self.prev_k,self.prev_d):return None
        vals=[(k,d) for k,d in self.recent if k is not None and d is not None]; recent4=vals[-4:]
        return {"k":self.k,"d":self.d,"pk":self.prev_k,"pd":self.prev_d,
                "low_extreme":self.k<=25 and self.d<=25,"high_extreme":self.k>=75 and self.d>=75,
                "cross_up_extreme":self.prev_k<=self.prev_d and self.k>self.d and min(self.prev_k,self.prev_d)<=25,
                "cross_dn_extreme":self.prev_k>=self.prev_d and self.k<self.d and max(self.prev_k,self.prev_d)>=75,
                "recent_low4":any(k<=25 or d<=25 for k,d in recent4),"recent_high4":any(k>=75 or d>=75 for k,d in recent4),
                "rising":self.k>self.prev_k,"falling":self.k<self.prev_k,
                "bull_dir":self.k>self.d and self.k>self.prev_k,"bear_dir":self.k<self.d and self.k<self.prev_k}

class VWMA:
    def __init__(self,length=14):self.length=length;self.rows=deque(maxlen=length);self.value=None;self.close=None
    def commit(self,close,volume):
        self.rows.append((close,volume));self.close=close
        if len(self.rows)<self.length:self.value=None;return
        sv=sum(v for _,v in self.rows);self.value=sum(c*v for c,v in self.rows)/sv if sv else sum(c for c,_ in self.rows)/len(self.rows)
    def snapshot(self):return None if self.value is None or self.close is None else {"vwma":self.value,"close":self.close}

@dataclass
class AggBar:
    key:datetime;open:float;high:float;low:float;close:float;volume:float
    def add(self,o,h,l,c,v):self.high=max(self.high,h);self.low=min(self.low,l);self.close=c;self.volume+=v
@dataclass
class Minute:
    ts:datetime;o:float;h:float;l:float;c:float;signal:dict|None

FILTERS=["MACD","MACD_VWMA","MACD_STOCH_EXTREME","MACD_STOCH_EXTREME_VWMA","MACD_STOCH_CROSS","MACD_STOCH_CROSS_VWMA","MACD_STOCH_RECENT4","MACD_STOCH_RECENT4_VWMA","MACD_STOCH_DIRECTION","MACD_STOCH_DIRECTION_VWMA"]

def filter_ok(name,direction,sig):
    if not sig or not sig.get("macd") or not sig["macd"].get(direction):return False
    st=sig.get("stoch");vw=sig.get("vwma")
    if "_VWMA" in name:
        if not vw:return False
        if direction=="long" and not(vw["close"]>vw["vwma"]):return False
        if direction=="short" and not(vw["close"]<vw["vwma"]):return False
    if "STOCH_EXTREME" in name:return bool(st) and (st["low_extreme"] if direction=="long" else st["high_extreme"])
    if "STOCH_CROSS" in name:return bool(st) and (st["cross_up_extreme"] if direction=="long" else st["cross_dn_extreme"])
    if "STOCH_RECENT4" in name:return bool(st) and ((st["recent_low4"] and st["rising"]) if direction=="long" else (st["recent_high4"] and st["falling"]))
    if "STOCH_DIRECTION" in name:return bool(st) and (st["bull_dir"] if direction=="long" else st["bear_dir"])
    return True

def find_entry(minutes,ref_high,ref_low,filter_name):
    bl=bs=False
    for i,b in enumerate(minutes):
        lc=(not bl) and b.h>ref_high;sc=(not bs) and b.l<ref_low
        if not(lc or sc):continue
        tl=ref_high+TICK;ts=ref_low-TICK;lo=filter_ok(filter_name,"long",b.signal) if lc else False;so=filter_ok(filter_name,"short",b.signal) if sc else False
        if lc:bl=True
        if sc:bs=True
        if lo and so:return None
        if lo:return {"idx":i,"direction":"long","entry":max(tl,b.o),"trigger":tl,"gap":b.o>=tl}
        if so:return {"idx":i,"direction":"short","entry":min(ts,b.o),"trigger":ts,"gap":b.o<=ts}
    return None

def realized_pnl(direction,entry,exit_price):return exit_price-entry if direction=="long" else entry-exit_price

def simulate_fixed(minutes,ev,dist):
    d,e,i0,gap=ev["direction"],ev["entry"],ev["idx"],ev["gap"];stop=e-dist if d=="long" else e+dist;target=e+dist if d=="long" else e-dist
    for j in range(i0,len(minutes)):
        b=minutes[j]
        if d=="long":
            ht=b.h>=target;hs=b.l<=stop
            if j==i0:
                if ht and hs:return {"ambiguous":True,"reason":"ENTRY_BOTH","pnl":None,"exit_i":j}
                if hs and not gap:return {"ambiguous":True,"reason":"ENTRY_STOP_ORDER","pnl":None,"exit_i":j}
                if ht:return {"ambiguous":False,"reason":"TARGET","pnl":dist,"exit_i":j}
                if hs:return {"ambiguous":False,"reason":"STOP","pnl":-dist,"exit_i":j}
            else:
                if ht and hs:return {"ambiguous":True,"reason":"BOTH","pnl":None,"exit_i":j}
                if hs:
                    fill=min(stop,b.o) if b.o<stop else stop;return {"ambiguous":False,"reason":"STOP","pnl":realized_pnl(d,e,fill),"exit_i":j}
                if ht:return {"ambiguous":False,"reason":"TARGET","pnl":dist,"exit_i":j}
        else:
            ht=b.l<=target;hs=b.h>=stop
            if j==i0:
                if ht and hs:return {"ambiguous":True,"reason":"ENTRY_BOTH","pnl":None,"exit_i":j}
                if hs and not gap:return {"ambiguous":True,"reason":"ENTRY_STOP_ORDER","pnl":None,"exit_i":j}
                if ht:return {"ambiguous":False,"reason":"TARGET","pnl":dist,"exit_i":j}
                if hs:return {"ambiguous":False,"reason":"STOP","pnl":-dist,"exit_i":j}
            else:
                if ht and hs:return {"ambiguous":True,"reason":"BOTH","pnl":None,"exit_i":j}
                if hs:
                    fill=max(stop,b.o) if b.o>stop else stop;return {"ambiguous":False,"reason":"STOP","pnl":realized_pnl(d,e,fill),"exit_i":j}
                if ht:return {"ambiguous":False,"reason":"TARGET","pnl":dist,"exit_i":j}
    return {"ambiguous":False,"reason":"HOUR_CLOSE","pnl":realized_pnl(d,e,minutes[-1].c),"exit_i":len(minutes)-1}

def simulate_trail(minutes,ev,dist):
    d,e,i0,gap=ev["direction"],ev["entry"],ev["idx"],ev["gap"];best=e;stop=e-dist if d=="long" else e+dist
    for j in range(i0,len(minutes)):
        b=minutes[j];old=stop
        if d=="long":
            nb=max(best,b.h);ns=max(old,nb-dist)
            if j==i0:
                if b.l<=old and not gap:return {"ambiguous":True,"reason":"ENTRY_TRAIL_ORDER","pnl":None,"exit_i":j}
                if b.l<=old:return {"ambiguous":False,"reason":"TRAIL","pnl":realized_pnl(d,e,old),"exit_i":j}
                if ns>old and b.l<=ns:return {"ambiguous":True,"reason":"INTRABAR_TRAIL_ORDER","pnl":None,"exit_i":j}
            else:
                if b.l<=old:
                    fill=min(old,b.o) if b.o<old else old;return {"ambiguous":False,"reason":"TRAIL","pnl":realized_pnl(d,e,fill),"exit_i":j}
                if ns>old and b.l<=ns:return {"ambiguous":True,"reason":"INTRABAR_TRAIL_ORDER","pnl":None,"exit_i":j}
            best,stop=nb,ns
        else:
            nb=min(best,b.l);ns=min(old,nb+dist)
            if j==i0:
                if b.h>=old and not gap:return {"ambiguous":True,"reason":"ENTRY_TRAIL_ORDER","pnl":None,"exit_i":j}
                if b.h>=old:return {"ambiguous":False,"reason":"TRAIL","pnl":realized_pnl(d,e,old),"exit_i":j}
                if ns<old and b.h>=ns:return {"ambiguous":True,"reason":"INTRABAR_TRAIL_ORDER","pnl":None,"exit_i":j}
            else:
                if b.h>=old:
                    fill=max(old,b.o) if b.o>old else old;return {"ambiguous":False,"reason":"TRAIL","pnl":realized_pnl(d,e,fill),"exit_i":j}
                if ns<old and b.h>=ns:return {"ambiguous":True,"reason":"INTRABAR_TRAIL_ORDER","pnl":None,"exit_i":j}
            best,stop=nb,ns
    return {"ambiguous":False,"reason":"HOUR_CLOSE","pnl":realized_pnl(d,e,minutes[-1].c),"exit_i":len(minutes)-1}

def mfe_mae(minutes,ev):
    d,e,i0=ev["direction"],ev["entry"],ev["idx"];hs=[b.h for b in minutes[i0:]];ls=[b.l for b in minutes[i0:]]
    return (max(hs)-e,e-min(ls)) if d=="long" else (e-min(ls),max(hs)-e)

def new_bucket():return {"trades":0,"ambiguous":0,"wins":0,"losses":0,"flat":0,"sum_pnl":0.0,"pos_pnl":0.0,"neg_pnl":0.0,"target":0,"stop":0,"trail":0,"hour_close":0,"sum_hold":0,"pnls":[],"by_year":defaultdict(lambda:[0,0,0,0.0]),"by_hour":defaultdict(lambda:[0,0,0,0.0]),"by_dir":defaultdict(lambda:[0,0,0,0.0])}
results=defaultdict(new_bucket);candidate_stats=defaultdict(lambda:{"count":0,"mfe":[],"mae":[],"close_pnl":[]})

def add_result(key,meta,out,hold):
    b=results[key]
    if out["ambiguous"]:b["ambiguous"]+=1;return
    pnl=out["pnl"];b["trades"]+=1;b["sum_pnl"]+=pnl;b["sum_hold"]+=hold;b["pnls"].append(pnl)
    if pnl>1e-9:b["wins"]+=1;b["pos_pnl"]+=pnl;cls=0
    elif pnl<-1e-9:b["losses"]+=1;b["neg_pnl"]+=-pnl;cls=1
    else:b["flat"]+=1;cls=2
    reason=out["reason"]
    if reason=="TARGET":b["target"]+=1
    elif reason=="STOP":b["stop"]+=1
    elif reason=="TRAIL":b["trail"]+=1
    elif reason=="HOUR_CLOSE":b["hour_close"]+=1
    for dct,field in ((b["by_year"],meta["year"]),(b["by_hour"],meta["hour"]),(b["by_dir"],meta["direction"])):
        arr=dct[field];arr[cls]+=1;arr[3]+=pnl

def process_hour(minutes,ref):
    if not minutes or ref is None:return
    rh,rl=ref["high"],ref["low"];year=minutes[0].ts.year;hour=local_hour(minutes[0].ts);overnight=hour>=19 or hour<4
    for fname in FILTERS:
        ev=find_entry(minutes,rh,rl,fname)
        if not ev:continue
        mfe,mae=mfe_mae(minutes,ev);cp=realized_pnl(ev["direction"],ev["entry"],minutes[-1].c);cs=candidate_stats[fname];cs["count"]+=1;cs["mfe"].append(mfe);cs["mae"].append(mae);cs["close_pnl"].append(cp)
        meta={"year":year,"hour":hour,"direction":ev["direction"]};sessions=["ALL"]+(["PST19_04"] if overnight else [])
        for sess in sessions:
            for dist in DISTANCES:
                out=simulate_fixed(minutes,ev,dist);add_result((fname,sess,"FIXED",dist),meta,out,out["exit_i"]-ev["idx"]+1)
                out=simulate_trail(minutes,ev,dist);add_result((fname,sess,"TRAIL",dist),meta,out,out["exit_i"]-ev["idx"]+1)

def percentile(vals,q):
    if not vals:return None
    a=sorted(vals)
    if len(a)==1:return a[0]
    x=(len(a)-1)*q;lo,hi=int(math.floor(x)),int(math.ceil(x))
    return a[lo] if lo==hi else a[lo]+(a[hi]-a[lo])*(x-lo)
def max_drawdown(pnls):
    eq=peak=dd=0.0
    for x in pnls:eq+=x;peak=max(peak,eq);dd=max(dd,peak-eq)
    return dd

def summarize_bucket(key,b):
    fname,sess,ex,dist=key;n=b["trades"];den=b["wins"]+b["losses"];pf=b["pos_pnl"]/b["neg_pnl"] if b["neg_pnl"]>0 else (None if b["pos_pnl"]==0 else float("inf"))
    return {"filter":fname,"session":sess,"exit":ex,"distance":dist,"definite_trades":n,"ambiguous":b["ambiguous"],"wins":b["wins"],"losses":b["losses"],"flat":b["flat"],"win_rate":b["wins"]/den if den else None,"avg_points":b["sum_pnl"]/n if n else None,"total_points":b["sum_pnl"],"avg_R":b["sum_pnl"]/n/dist if n else None,"profit_factor":pf,"max_drawdown_points":max_drawdown(b["pnls"]),"target_exits":b["target"],"stop_exits":b["stop"],"trail_exits":b["trail"],"hour_close_exits":b["hour_close"],"hour_close_pct":b["hour_close"]/n if n else None,"avg_hold_minutes":b["sum_hold"]/n if n else None,"by_year":{str(k):{"wins":v[0],"losses":v[1],"flat":v[2],"points":v[3]} for k,v in sorted(b["by_year"].items())},"by_hour":{str(k):{"wins":v[0],"losses":v[1],"flat":v[2],"points":v[3]} for k,v in sorted(b["by_hour"].items())},"by_direction":{str(k):{"wins":v[0],"losses":v[1],"flat":v[2],"points":v[3]} for k,v in sorted(b["by_dir"].items())}}

def main(root):
    files=sorted(glob.glob(os.path.join(root,"data","ohlcv_MGC_*.csv")))
    if not files:raise SystemExit("No MGC one-minute files found")
    macd=AdaptiveMACD2();stoch=SlowStoch();vwma=VWMA(14);cur_q=None;cur_h_key=None;cur_h_agg=None;cur_minutes=[];ref=None;prev_ts=None;rows=0;first=last=None
    def snapshot():return {"macd":macd.snapshot(),"stoch":stoch.snapshot(),"vwma":vwma.snapshot()}
    for fp in files:
      with open(fp,newline="") as f:
       for r in csv.DictReader(f):
        ts=pts(r["timestamp"])
        if prev_ts is not None and ts<=prev_ts:continue
        prev_ts=ts;rows+=1;first=first or ts;last=ts;o,h,l,c=map(float,(r["open"],r["high"],r["low"],r["close"]));v=float(r.get("volume") or 0);qk=qkey(ts);hk=hkey(ts)
        if cur_q is not None and qk!=cur_q.key:
            macd.commit(cur_q.close);stoch.commit(cur_q.high,cur_q.low,cur_q.close);vwma.commit(cur_q.close,cur_q.volume);cur_q=None
        if cur_h_key is not None and hk!=cur_h_key:
            process_hour(cur_minutes,ref);ref={"high":cur_h_agg.high,"low":cur_h_agg.low,"key":cur_h_key};cur_h_key=hk;cur_h_agg=None;cur_minutes=[]
        elif cur_h_key is None:cur_h_key=hk
        sig=snapshot();cur_minutes.append(Minute(ts,o,h,l,c,sig))
        if cur_q is None:cur_q=AggBar(qk,o,h,l,c,v)
        else:cur_q.add(o,h,l,c,v)
        if cur_h_agg is None:cur_h_agg=AggBar(hk,o,h,l,c,v)
        else:cur_h_agg.add(o,h,l,c,v)
    if cur_h_agg is not None:process_hour(cur_minutes,ref)
    summaries=[summarize_bucket(k,b) for k,b in results.items()];summaries.sort(key=lambda x:(x["filter"],x["session"],x["exit"],x["distance"]))
    cstats={}
    for k,v in candidate_stats.items():cstats[k]={"candidate_hours":v["count"],"mfe_p25":percentile(v["mfe"],.25),"mfe_median":percentile(v["mfe"],.5),"mfe_p75":percentile(v["mfe"],.75),"mae_p25":percentile(v["mae"],.25),"mae_median":percentile(v["mae"],.5),"mae_p75":percentile(v["mae"],.75),"hour_close_pnl_median":percentile(v["close_pnl"],.5)}
    eligible=[s for s in summaries if s["definite_trades"]>=30];top_exp=sorted(eligible,key=lambda s:s["avg_points"] if s["avg_points"] is not None else -1e99,reverse=True)[:30];top_pf=sorted([s for s in eligible if s["profit_factor"] is not None and math.isfinite(s["profit_factor"])],key=lambda s:s["profit_factor"],reverse=True)[:30]
    meta={"instrument":"MGC continuous liquid-contract series","source_repo":"domzack/mgc-ohlcv-data","minute_rows":rows,"first_timestamp_utc_assumed":first.isoformat() if first else None,"last_timestamp_utc_assumed":last.isoformat() if last else None,"breakout":"one tick beyond previous completed hourly high/low; max one trade per hour per filter","indicator_timeframe":"15m ONLY; only completed 15m bars are used and held static until the next 15m close","macd":"adaptive medium (21,144,34,R2=15) + slow (65,270,105,R2=15); both must share sign and wane","stochastic":"standard Slow Stochastic 14,3,3 with 25/75 zones","vwma":"15m VWMA(14); when enabled long requires last completed 15m close > VWMA, short < VWMA","fixed_exits":"equal stop/target distances 5..50 by 5; unresolved trade exits at hour close","trailing_exits":"initial stop and immediate trailing distance 5..50 by 5, no profit target; unresolved trade exits at hour close","ambiguity":"1m OHLC cases where intraminute ordering changes the result are excluded and counted","session":"ALL and DST-aware America/Los_Angeles 19:00-03:59 entry hours","filter_definitions":{"MACD":"MACD only baseline","STOCH_EXTREME":"both slow %K and %D currently <=25 for long or >=75 for short","STOCH_CROSS":"%K/%D directional cross with prior oscillator touching the 25/75 extreme","STOCH_RECENT4":"an extreme occurred within the last four completed 15m bars and %K is now turning in trade direction","STOCH_DIRECTION":"exploratory: %K vs %D and %K slope agree with trade, no extreme requirement"}}
    outdir="backtest_output";os.makedirs(outdir,exist_ok=True);payload={"meta":meta,"candidate_stats":cstats,"summaries":summaries,"top_expectancy_min30":top_exp,"top_pf_min30":top_pf}
    with open(os.path.join(outdir,"mgc_15m_mid_slow_stoch_sweep.json"),"w") as f:json.dump(payload,f,indent=2)
    cols=["filter","session","exit","distance","definite_trades","ambiguous","wins","losses","flat","win_rate","avg_points","total_points","avg_R","profit_factor","max_drawdown_points","target_exits","stop_exits","trail_exits","hour_close_exits","hour_close_pct","avg_hold_minutes"]
    with open(os.path.join(outdir,"mgc_15m_mid_slow_stoch_sweep.csv"),"w",newline="") as f:
        w=csv.DictWriter(f,fieldnames=cols);w.writeheader()
        for s in summaries:w.writerow({k:s.get(k) for k in cols})
    print("SWEEP_META="+json.dumps(meta,separators=(",",":")));print("CANDIDATE_STATS="+json.dumps(cstats,separators=(",",":")))
    print("TOP_EXPECTANCY_MIN30_START")
    for s in top_exp[:20]:print(json.dumps({k:s[k] for k in cols},separators=(",",":")))
    print("TOP_EXPECTANCY_MIN30_END");print("TOP_PF_MIN30_START")
    for s in top_pf[:15]:print(json.dumps({k:s[k] for k in cols},separators=(",",":")))
    print("TOP_PF_MIN30_END");print("EXACT_FILTER_SPOTLIGHT_START")
    for s in summaries:
        if s["filter"]=="MACD_STOCH_EXTREME_VWMA" and s["session"] in ("ALL","PST19_04"):print(json.dumps({k:s[k] for k in cols},separators=(",",":")))
    print("EXACT_FILTER_SPOTLIGHT_END")
if __name__=="__main__":main(sys.argv[1] if len(sys.argv)>1 else ".")
