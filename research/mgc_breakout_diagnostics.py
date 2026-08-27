import os, sys
sys.path.insert(0, os.path.dirname(__file__))
import mgc_hourly_breakout_backtest as m


def condition(a, direction, mode):
    if not a:
        return False
    h=a['hists']; p=a['prev_hists']
    if direction=='long':
        strict=all(x<0 for x in h) and all(h[i]>p[i] for i in range(3))
        same2=sum(h[i]<0 and h[i]>p[i] for i in range(3))>=2
        dir3=all(x>0 for x in h)
        dir2=sum(x>0 for x in h)>=2
    else:
        strict=all(x>0 for x in h) and all(h[i]<p[i] for i in range(3))
        same2=sum(h[i]>0 and h[i]<p[i] for i in range(3))>=2
        dir3=all(x<0 for x in h)
        dir2=sum(x<0 for x in h)>=2
    return {'strict':strict,'same2':same2,'dir3':dir3,'dir2':dir2}[mode]


def custom_strategies():
    kinds=[
      'h1_strict_rsi',
      'h1_strict_m15_same2',
      'h1_strict_m15_same2_rsi',
      'h1_strict_m15_dir3',
      'h1_strict_m15_dir3_rsi',
      'h1_strict_m15_dir2',
      'h1_strict_m15_dir2_rsi',
      'h1_2_m15_same2_rsi',
    ]
    out=[]
    for kind in kinds:
        for sess in (False,True):
            out.append(m.Strat('DIAG_LIVE__'+kind.upper()+'__'+('PST19_04' if sess else 'ALL'),kind,sess,True))
    return out


def custom_filt(st,d,p,h1,m15,rsi):
    a=h1.live(p)
    h1mode='same2' if st.kind.startswith('h1_2_') else 'strict'
    if not condition(a,d,h1mode):
        return False
    if st.kind=='h1_strict_rsi':
        r=rsi.live(p)
        return r is not None and (r<=20 if d=='long' else r>=80)
    b=m15.live(p)
    if '_m15_same2' in st.kind:
        ok=condition(b,d,'same2')
    elif '_m15_dir3' in st.kind:
        ok=condition(b,d,'dir3')
    elif '_m15_dir2' in st.kind:
        ok=condition(b,d,'dir2')
    else:
        ok=False
    if not ok:
        return False
    if st.kind.endswith('_rsi'):
        r=rsi.live(p)
        return r is not None and (r<=20 if d=='long' else r>=80)
    return True

m.strategies=custom_strategies
m.filt=custom_filt
m.main(sys.argv[1] if len(sys.argv)>1 else '.')
