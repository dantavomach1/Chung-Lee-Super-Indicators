import os, sys, re
sys.path.insert(0, os.path.dirname(__file__))
import mgc_hourly_breakout_backtest as m

def strict(a,d):
    if not a:return False
    h=a['hists'];p=a['prev_hists']
    return (all(x<0 for x in h) and all(h[i]>p[i] for i in range(3))) if d=='long' else (all(x>0 for x in h) and all(h[i]<p[i] for i in range(3)))
def dir2(a,d):
    if not a:return False
    h=a['hists'];return sum(x>0 for x in h)>=2 if d=='long' else sum(x<0 for x in h)>=2
def same2(a,d):
    if not a:return False
    h=a['hists'];p=a['prev_hists']
    return sum(h[i]<0 and h[i]>p[i] for i in range(3))>=2 if d=='long' else sum(h[i]>0 and h[i]<p[i] for i in range(3))>=2

def custom_strategies():
    out=[]
    for low in (20,25,30,35,40,45):
      high=100-low
      for layer in ('h1','h1_m15_dir2','h1_m15_same2'):
       kind=f'{layer}_rsi_{low}_{high}'
       for sess in (False,True):out.append(m.Strat('THRESH_LIVE__'+kind.upper()+'__'+('PST19_04' if sess else 'ALL'),kind,sess,True))
    return out

def custom_filt(st,d,p,h1,m15,rsi):
    if not strict(h1.live(p),d):return False
    if '_m15_dir2_' in st.kind and not dir2(m15.live(p),d):return False
    if '_m15_same2_' in st.kind and not same2(m15.live(p),d):return False
    mm=re.search(r'_rsi_(\d+)_(\d+)$',st.kind); low=int(mm.group(1)); high=int(mm.group(2)); r=rsi.live(p)
    return r is not None and (r<=low if d=='long' else r>=high)

m.strategies=custom_strategies
m.filt=custom_filt
m.main(sys.argv[1] if len(sys.argv)>1 else '.')
