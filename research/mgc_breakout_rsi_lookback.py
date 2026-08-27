import os, sys
from collections import deque
sys.path.insert(0, os.path.dirname(__file__))
import mgc_hourly_breakout_backtest as m

class RSIHistory(m.RSIWilder):
    def __init__(self,n=14):
        super().__init__(n); self.history=deque(maxlen=64)
    def commit(self,c):
        super().commit(c)
        if self.last is not None: self.history.append(self.last)
m.RSIWilder=RSIHistory

def strict(a,d):
    if not a:return False
    h=a['hists'];p=a['prev_hists']
    return (all(x<0 for x in h) and all(h[i]>p[i] for i in range(3))) if d=='long' else (all(x>0 for x in h) and all(h[i]<p[i] for i in range(3)))
def dir2(a,d):
    if not a:return False
    h=a['hists']; return (sum(x>0 for x in h)>=2) if d=='long' else (sum(x<0 for x in h)>=2)
def same2(a,d):
    if not a:return False
    h=a['hists'];p=a['prev_hists']
    return (sum(h[i]<0 and h[i]>p[i] for i in range(3))>=2) if d=='long' else (sum(h[i]>0 and h[i]<p[i] for i in range(3))>=2)
def recent_rsi(rsi,d,n):
    vals=list(rsi.history)[-n:]
    if not vals:return False
    return min(vals)<=20 if d=='long' else max(vals)>=80

def custom_strategies():
    out=[]
    for n in (1,2,4,8,16):
      for layer in ('h1','h1_m15_dir2','h1_m15_same2'):
       kind=f'{layer}_rsi_recent_{n}'
       for sess in (False,True):out.append(m.Strat('LOOKBACK_LIVE__'+kind.upper()+'__'+('PST19_04' if sess else 'ALL'),kind,sess,True))
    return out

def custom_filt(st,d,p,h1,m15,rsi):
    a=h1.live(p)
    if not strict(a,d):return False
    parts=st.kind.split('_recent_'); n=int(parts[1]); base=parts[0]
    if 'm15_dir2' in base and not dir2(m15.live(p),d):return False
    if 'm15_same2' in base and not same2(m15.live(p),d):return False
    return recent_rsi(rsi,d,n)

m.strategies=custom_strategies
m.filt=custom_filt
m.main(sys.argv[1] if len(sys.argv)>1 else '.')
