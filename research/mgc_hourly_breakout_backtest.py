from __future__ import annotations
import csv, glob, json, math, os, sys
from collections import deque, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

TICK=0.1; STOP=10.0; TARGET=10.0; LA=ZoneInfo('America/Los_Angeles')
MACD_CFG=[(15,5,21,8,'fast'),(15,65,270,105,'slow'),(15,21,144,34,'mid')]

def corr_r2(closes):
    n=len(closes)
    if n<2:return None
    mx=(n-1)/2; my=sum(closes)/n
    sxx=sum((i-mx)**2 for i in range(n)); syy=sum((y-my)**2 for y in closes)
    if sxx<=0 or syy<=0:corr=0.0
    else:
        sxy=sum((i-mx)*(y-my) for i,y in enumerate(closes)); corr=sxy/math.sqrt(sxx*syy); corr=max(-1,min(1,corr))
    return .5*corr*corr+.5

class AdaptiveMACDTriple:
    def __init__(self):
        self.close_hist=deque(maxlen=15); self.prev_close=None; self._prior_hists=[None]*3; self.state=[]
        for length,fast,slow,signal,name in MACD_CFG:
            self.state.append({'a1':2/(fast+1),'a2':2/(slow+1),'alpha':2/(signal+1),'m1':0.0,'m2':0.0,'ema':None,'hist':None})
    def _eval(self,st,close,r2):
        if self.prev_close is None or r2 is None:return None,None,None
        a1,a2=st['a1'],st['a2']; K=r2*((1-a1)*(1-a2))+(1-r2)*((1-a1)/(1-a2))
        macd=(close-self.prev_close)*(a1-a2)+(-a2-a1+2)*st['m1']-K*st['m2']
        ema=macd if st['ema'] is None else st['alpha']*macd+(1-st['alpha'])*st['ema']
        return macd,ema,macd-ema
    @staticmethod
    def classify(h,p):
        return {'hists':h,'prev_hists':p,
          'long_all3':all(x<0 for x in h) and all(h[i]>p[i] for i in range(3)),
          'short_all3':all(x>0 for x in h) and all(h[i]<p[i] for i in range(3))}
    def live(self,close):
        if self.prev_close is None:return None
        vals=(list(self.close_hist)[-14:])+[close]
        if len(vals)<15:return None
        r2=corr_r2(vals); h=[]; p=[]
        for st in self.state:
            _,_,x=self._eval(st,close,r2); h.append(x); p.append(st['hist'])
        if any(x is None for x in h+p):return None
        return self.classify(h,p)
    def confirmed(self):
        h=[st['hist'] for st in self.state]; p=self._prior_hists
        if any(x is None for x in h+p):return None
        return self.classify(h,p)
    def commit(self,close):
        old=[st['hist'] for st in self.state]; vals=(list(self.close_hist)[-14:])+[close]; r2=corr_r2(vals) if len(vals)>=15 else None
        for st in self.state:
            m,e,h=self._eval(st,close,r2)
            if m is not None: st['m2'],st['m1']=st['m1'],m; st['ema']=e; st['hist']=h
        self._prior_hists=old; self.prev_close=close; self.close_hist.append(close)

class RSIWilder:
    def __init__(self,n=14):
        self.n=n; self.prev=None; self.g=[]; self.l=[]; self.ag=None; self.al=None; self.last=None
    @staticmethod
    def calc(ag,al):
        if ag is None or al is None:return None
        if al==0:return 100.0 if ag>0 else 50.0
        return 100-100/(1+ag/al)
    def live(self,c):
        if self.prev is None:return None
        ch=c-self.prev; g=max(ch,0); l=max(-ch,0)
        if self.ag is not None:return self.calc((self.ag*(self.n-1)+g)/self.n,(self.al*(self.n-1)+l)/self.n)
        if len(self.g)+1>=self.n:return self.calc(sum((self.g+[g])[-self.n:])/self.n,sum((self.l+[l])[-self.n:])/self.n)
        return None
    def confirmed(self):return self.last
    def commit(self,c):
        if self.prev is None:self.prev=c;return
        ch=c-self.prev; g=max(ch,0); l=max(-ch,0)
        if self.ag is None:
            self.g.append(g);self.l.append(l)
            if len(self.g)>=self.n:self.ag=sum(self.g[-self.n:])/self.n;self.al=sum(self.l[-self.n:])/self.n;self.last=self.calc(self.ag,self.al)
        else:self.ag=(self.ag*(self.n-1)+g)/self.n;self.al=(self.al*(self.n-1)+l)/self.n;self.last=self.calc(self.ag,self.al)
        self.prev=c

@dataclass
class AggBar:
    key:datetime; open:float; high:float; low:float; close:float; volume:float=0
    def add(self,o,h,l,c,v):self.high=max(self.high,h);self.low=min(self.low,l);self.close=c;self.volume+=v
@dataclass
class Trade:
    direction:str; entry:float; stop:float; target:float; entry_time:datetime; ref_hour:datetime
@dataclass
class Strat:
    name:str; kind:str; session:bool; live_filter:bool; include4:bool=False; pos:Trade|None=None; ref_high:float|None=None; ref_low:float|None=None; ref_hour:datetime|None=None; bl:bool=False; bs:bool=False; trades:list=field(default_factory=list); amb_trigger:int=0; dq_l:int=0; dq_s:int=0; elig_l:int=0; elig_s:int=0
    def setref(self,b):self.ref_high=b.high;self.ref_low=b.low;self.ref_hour=b.key;self.bl=False;self.bs=False

def in_session(ts,include4=False):
    h=ts.replace(tzinfo=timezone.utc).astimezone(LA).hour
    return h>=19 or (h<=4 if include4 else h<4)
def lhour(ts):return ts.replace(tzinfo=timezone.utc).astimezone(LA).hour
def hkey(ts):return ts.replace(minute=0,second=0,microsecond=0)
def qkey(ts):return ts.replace(minute=(ts.minute//15)*15,second=0,microsecond=0)
def pts(s):return datetime.strptime(s.split('.')[0],'%Y-%m-%d %H:%M:%S')

def strategies():
    out=[]
    for mode in ('confirmed','live'):
      for key,label in [('raw','RAW'),('h1','H1_MACD'),('h1_m15','H1_M15_MACD'),('full','H1_M15_MACD_RSI20_80')]:
       for sess in (False,True):out.append(Strat(f'{mode.upper()}__{label}__'+('PST19_04' if sess else 'ALL'),key,sess,mode=='live'))
    out.append(Strat('LIVE__H1_M15_MACD_RSI20_80__PST19_04_INCLUSIVE4','full',True,True,True));return out

def filt(st,d,p,h1,m15,rsi):
    if st.kind=='raw':return True
    a=h1.live(p) if st.live_filter else h1.confirmed(); w='long_all3' if d=='long' else 'short_all3'
    if not a or not a[w]:return False
    if st.kind=='h1':return True
    b=m15.live(p) if st.live_filter else m15.confirmed()
    if not b or not b[w]:return False
    if st.kind=='h1_m15':return True
    r=rsi.live(p) if st.live_filter else rsi.confirmed()
    return r is not None and (r<=20 if d=='long' else r>=80)

def rec(st,tr,res,xt=None,xp=None,reason=None):
    st.trades.append({'direction':tr.direction,'entry_time':tr.entry_time.isoformat(),'entry':tr.entry,'ref_hour':tr.ref_hour.isoformat() if tr.ref_hour else None,'result':res,'exit_time':xt.isoformat() if xt else None,'exit_price':xp,'reason':reason,'local_hour':lhour(tr.entry_time),'year':tr.entry_time.year,'duration_min':int((xt-tr.entry_time).total_seconds()//60) if xt else None})

def manage(st,ts,o,h,l):
    tr=st.pos
    if tr is None:return False
    ht=h>=tr.target if tr.direction=='long' else l<=tr.target; hs=l<=tr.stop if tr.direction=='long' else h>=tr.stop
    if ht and hs:rec(st,tr,'AMBIGUOUS',ts,None,'both stop and target in same 1m bar');st.pos=None;return True
    if ht:rec(st,tr,'WIN',ts,tr.target,'target');st.pos=None;return True
    if hs:rec(st,tr,'LOSS',ts,tr.stop,'stop');st.pos=None;return True
    return False

def enter(st,ts,o,h,l,h1,m15,rsi):
    if st.pos is not None or st.ref_high is None:return
    if st.session and not in_session(ts,st.include4):
        if h>st.ref_high:st.bl=True
        if l<st.ref_low:st.bs=True
        return
    lc=(not st.bl) and h>st.ref_high; sc=(not st.bs) and l<st.ref_low
    if not(lc or sc):return
    lt=round(st.ref_high+TICK,10); stt=round(st.ref_low-TICK,10); le=max(lt,o) if lc else None; se=min(stt,o) if sc else None
    lo=filt(st,'long',le,h1,m15,rsi) if lc else False; so=filt(st,'short',se,h1,m15,rsi) if sc else False
    if lc:
        if lo:st.elig_l+=1
        else:st.dq_l+=1
        st.bl=True
    if sc:
        if so:st.elig_s+=1
        else:st.dq_s+=1
        st.bs=True
    if lo and so:
        if o>=lt:so=False
        elif o<=stt:lo=False
        else:st.amb_trigger+=1;return
    if not(lo or so):return
    d='long' if lo else 'short'; e=le if lo else se; stop=e-STOP if d=='long' else e+STOP; target=e+TARGET if d=='long' else e-TARGET; tr=Trade(d,e,stop,target,ts,st.ref_hour)
    ht=h>=target if d=='long' else l<=target; hs=l<=stop if d=='long' else h>=stop; gap=(d=='long' and o>=lt) or (d=='short' and o<=stt)
    if ht and hs:rec(st,tr,'AMBIGUOUS',ts,None,'both stop and target in entry 1m bar');return
    if ht:rec(st,tr,'WIN',ts,target,'target in entry 1m bar');return
    if hs:
        if gap:rec(st,tr,'LOSS',ts,stop,'stop after gap entry at minute open')
        else:rec(st,tr,'AMBIGUOUS',ts,None,'stop in entry 1m bar may precede breakout')
        return
    st.pos=tr

def wilson(w,n,z=1.95996398454):
    if not n:return [None,None]
    p=w/n; den=1+z*z/n; c=(p+z*z/(2*n))/den; hh=z*math.sqrt((p*(1-p)+z*z/(4*n))/n)/den;return [c-hh,c+hh]
def summarize(st):
    W=[x for x in st.trades if x['result']=='WIN'];L=[x for x in st.trades if x['result']=='LOSS'];A=[x for x in st.trades if x['result']=='AMBIGUOUS'];n=len(W)+len(L); seq=[1 if x['result']=='WIN' else -1 for x in st.trades if x['result'] in ('WIN','LOSS')]
    eq=pk=dd=cw=cl=mw=ml=0
    for x in seq:
        eq+=x;pk=max(pk,eq);dd=max(dd,pk-eq)
        if x>0:cw+=1;cl=0;mw=max(mw,cw)
        else:cl+=1;cw=0;ml=max(ml,cl)
    dur=[x['duration_min'] for x in st.trades if x['result'] in ('WIN','LOSS') and x['duration_min'] is not None]
    def breakdown(field):
        d=defaultdict(lambda:[0,0,0])
        for x in st.trades:
            i=0 if x['result']=='WIN' else 1 if x['result']=='LOSS' else 2;d[str(x[field])][i]+=1
        return {k:{'wins':v[0],'losses':v[1],'ambiguous':v[2],'definite':v[0]+v[1],'win_rate':v[0]/(v[0]+v[1]) if v[0]+v[1] else None} for k,v in sorted(d.items(),key=lambda kv:int(kv[0]) if kv[0].isdigit() else kv[0])}
    pot=n+len(A)+st.amb_trigger
    return {'strategy':st.name,'wins':len(W),'losses':len(L),'definite_trades':n,'ambiguous_outcomes':len(A),'ambiguous_triggers':st.amb_trigger,'win_rate_definite':len(W)/n if n else None,'win_rate_95ci':wilson(len(W),n),'ambiguity_winrate_bounds':[len(W)/pot if pot else None,(len(W)+len(A)+st.amb_trigger)/pot if pot else None],'expectancy_R_per_definite_trade':(len(W)-len(L))/n if n else None,'profit_factor_R':len(W)/len(L) if L else None,'net_R_definite':len(W)-len(L),'max_drawdown_R_definite':dd,'max_consecutive_wins':mw,'max_consecutive_losses':ml,'avg_duration_min':sum(dur)/len(dur) if dur else None,'median_duration_min':sorted(dur)[len(dur)//2] if dur else None,'eligible_long_signals':st.elig_l,'eligible_short_signals':st.elig_s,'disqualified_long_breaks':st.dq_l,'disqualified_short_breaks':st.dq_s,'by_year':breakdown('year'),'by_local_entry_hour':breakdown('local_hour'),'by_direction':breakdown('direction')}

def main(root):
    files=sorted(glob.glob(os.path.join(root,'data','ohlcv_MGC_*.csv')))
    if not files:raise SystemExit('no MGC 1m files')
    h1=AdaptiveMACDTriple();m15=AdaptiveMACDTriple();rsi=RSIWilder(14);ss=strategies();ch=cq=None;first=last=prev=None;rows=0
    for fp in files:
      with open(fp,newline='') as f:
       for r in csv.DictReader(f):
        ts=pts(r['timestamp'])
        if prev is not None and ts<=prev:continue
        prev=ts;rows+=1;first=first or ts;last=ts;o=float(r['open']);h=float(r['high']);l=float(r['low']);c=float(r['close']);v=float(r.get('volume') or 0);hk=hkey(ts);qk=qkey(ts)
        if cq is not None and qk!=cq.key:m15.commit(cq.close);rsi.commit(cq.close);cq=None
        if ch is not None and hk!=ch.key:
            h1.commit(ch.close)
            for s in ss:s.setref(ch)
            ch=None
        if cq is None:cq=AggBar(qk,o,h,l,c,v)
        else:cq.add(o,h,l,c,v)
        if ch is None:ch=AggBar(hk,o,h,l,c,v)
        else:ch.add(o,h,l,c,v)
        for s in ss:
            if s.pos is not None:
                manage(s,ts,o,h,l)
                if s.ref_high is not None and h>s.ref_high:s.bl=True
                if s.ref_low is not None and l<s.ref_low:s.bs=True
                continue
            enter(s,ts,o,h,l,h1,m15,rsi)
    for s in ss:
        if s.pos is not None:rec(s,s.pos,'AMBIGUOUS',last,None,'dataset ended open');s.pos=None
    sums=[summarize(s) for s in ss]
    meta={'instrument':'MGC continuous liquid-contract series','source_repo':'domzack/mgc-ohlcv-data','source_provider_claim':'Databento','minute_rows':rows,'first_timestamp_utc_assumed':first.isoformat(),'last_timestamp_utc_assumed':last.isoformat(),'tick':TICK,'stop_points':STOP,'target_points':TARGET,'rsi':'15m Wilder RSI(14), long <=20, short >=80','waning':'ALL THREE histograms: long each <0 and rising; short each >0 and falling','macd_configs':MACD_CFG,'session':'America/Los_Angeles DST-aware, 19:00 <= local time < 04:00','execution':'1m OHLC, breakout one tick beyond prior completed hourly high/low; unresolved intraminute sequencing classified ambiguous'}
    os.makedirs('backtest_output',exist_ok=True);json.dump({'meta':meta,'summaries':sums},open('backtest_output/results.json','w'),indent=2)
    cols=['strategy','wins','losses','definite_trades','ambiguous_outcomes','ambiguous_triggers','win_rate_definite','expectancy_R_per_definite_trade','profit_factor_R','net_R_definite','max_drawdown_R_definite','max_consecutive_losses','avg_duration_min','eligible_long_signals','eligible_short_signals']
    with open('backtest_output/summary.csv','w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=cols);w.writeheader();[w.writerow({k:s.get(k) for k in cols}) for s in sums]
    print('BACKTEST_META='+json.dumps(meta,separators=(',',':')));print('BACKTEST_SUMMARY_START')
    for s in sums:print(json.dumps({k:s[k] for k in ['strategy','wins','losses','definite_trades','ambiguous_outcomes','ambiguous_triggers','win_rate_definite','win_rate_95ci','expectancy_R_per_definite_trade','profit_factor_R','net_R_definite','max_drawdown_R_definite','max_consecutive_losses','avg_duration_min','eligible_long_signals','eligible_short_signals']},separators=(',',':')))
    print('BACKTEST_SUMMARY_END')
if __name__=='__main__':main(sys.argv[1] if len(sys.argv)>1 else '.')
