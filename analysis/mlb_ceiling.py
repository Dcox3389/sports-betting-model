"""
How high can MLB game-outcome accuracy actually go?

Everything here deliberately CHEATS, to establish an upper bound:

  * oracle features  -- full-season (through Aug 3) team and pitcher quality,
                        i.e. information from AFTER each game was played
  * in-sample fit    -- logistic regression trained on the same 765 games it
                        is scored on, with no holdout at all

A model that sees the future and is fitted to the answer key cannot be beaten
by any honest model. Whatever it scores is the ceiling.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import DATA
os.chdir(DATA)

import json, math
import numpy as np
from collections import defaultdict

EVAL_START, EVAL_END = "2026-06-04", "2026-08-03"
HFA, K = 24.0, 4.0
IP_REGRESS = 60.0

def ip_to_float(s):
    if s is None: return 0.0
    w,_,f = str(s).partition(".")
    return int(w or 0) + {"0":0.0,"1":1/3,"2":2/3}.get(f,0.0)

# ---------- pitchers: FULL-SEASON FIP (oracle) ----------
logs = json.load(open("pitcher_logs.json"))
LG = dict(ip=0.0,hr=0,bb=0,hbp=0,k=0,er=0); tot = {}
for pid, blob in logs.items():
    if not blob or not blob.get("stats"): continue
    ip=hr=bb=hbp=k=er=0.0
    for sp in blob["stats"][0].get("splits", []):
        st=sp["stat"]; i_=ip_to_float(st.get("inningsPitched"))
        if i_<=0: continue
        ip+=i_; hr+=st.get("homeRuns",0); bb+=st.get("baseOnBalls",0)
        hbp+=st.get("hitBatsmen",0); k+=st.get("strikeOuts",0); er+=st.get("earnedRuns",0)
    tot[int(pid)]=(ip,hr,bb,hbp,k)
    LG["ip"]+=ip; LG["hr"]+=hr; LG["bb"]+=bb; LG["hbp"]+=hbp; LG["k"]+=k; LG["er"]+=er
lg_era = 9.0*LG["er"]/LG["ip"]
FIP_C = lg_era - (13*LG["hr"]+3*(LG["bb"]+LG["hbp"])-2*LG["k"])/LG["ip"]

def season_fip(pid):
    if pid not in tot: return lg_era
    ip,hr,bb,hbp,k = tot[pid]
    if ip<=0: return lg_era
    raw=(13*hr+3*(bb+hbp)-2*k)/ip + FIP_C
    return (raw*ip + lg_era*IP_REGRESS)/(ip+IP_REGRESS)

# ---------- games ----------
sched=json.load(open("mlb_sched_pp.json")); games=[]
for blk in sched["dates"]:
    for g in blk["games"]:
        if g["status"]["abstractGameState"]!="Final": continue
        h,a=g["teams"]["home"],g["teams"]["away"]
        if "score" not in h or "score" not in a or h["score"]==a["score"]: continue
        hp,ap=h.get("probablePitcher"),a.get("probablePitcher")
        games.append(dict(pk=g["gamePk"],date=g["officialDate"],dt=g["gameDate"],
            home=h["team"]["name"],away=a["team"]["name"],hs=h["score"],as_=a["score"],
            home_won=h["score"]>a["score"],hp=hp["id"] if hp else None,ap=ap["id"] if ap else None))
games.sort(key=lambda x:(x["dt"],x["pk"]))

# ---------- full-season (oracle) team quality ----------
W=defaultdict(int);L=defaultdict(int);RS=defaultdict(int);RA=defaultdict(int)
elo_f=defaultdict(lambda:1500.0)
for g in games:
    h,a=g["home"],g["away"]
    e=1/(1+10**(-((elo_f[h]+HFA)-elo_f[a])/400))
    d=K*math.log(abs(g["hs"]-g["as_"])+1)*((1.0 if g["home_won"] else 0.0)-e)
    elo_f[h]+=d; elo_f[a]-=d
    if g["home_won"]: W[h]+=1; L[a]+=1
    else: W[a]+=1; L[h]+=1
    RS[h]+=g["hs"]; RA[h]+=g["as_"]; RS[a]+=g["as_"]; RA[a]+=g["hs"]
wp={t:W[t]/(W[t]+L[t]) for t in W}
rdg={t:(RS[t]-RA[t])/(W[t]+L[t]) for t in W}
py={t:RS[t]**1.83/(RS[t]**1.83+RA[t]**1.83) for t in W}

ev=[g for g in games if EVAL_START<=g["date"]<=EVAL_END]
# match the exact 765-game sample used before (both teams >=20 games played)
gp=defaultdict(int); keep=[]
for g in games:
    if EVAL_START<=g["date"]<=EVAL_END and gp[g["home"]]>=20 and gp[g["away"]]>=20:
        keep.append(g)
    gp[g["home"]]+=1; gp[g["away"]]+=1
ev=keep
print(f"evaluation sample: {len(ev)} games\n")

X=[];y=[]
for g in ev:
    h,a=g["home"],g["away"]
    X.append([1.0,
              (elo_f[h]-elo_f[a])/100.0,
              wp[h]-wp[a],
              py[h]-py[a],
              rdg[h]-rdg[a],
              season_fip(g["ap"])-season_fip(g["hp"]),
              ])
    y.append(1.0 if g["home_won"] else 0.0)
X=np.array(X); y=np.array(y)
names=["intercept(HFA)","elo_diff/100","winpct_diff","pythag_diff","rundiff_diff","fip_diff(away-home)"]

# ---------- logistic regression, fitted IN-SAMPLE (Newton-Raphson) ----------
b=np.zeros(X.shape[1])
for _ in range(200):
    p=1/(1+np.exp(-X@b))
    Wd=p*(1-p)+1e-9
    grad=X.T@(y-p)
    H=(X*Wd[:,None]).T@X + 1e-6*np.eye(X.shape[1])
    step=np.linalg.solve(H,grad); b+=step
    if np.max(np.abs(step))<1e-9: break
p=1/(1+np.exp(-X@b))
acc=np.mean((p>=.5)==(y==1))
brier=np.mean((p-y)**2)

print("ORACLE + IN-SAMPLE logistic regression (cheats twice over)")
print(f"{'feature':<22}{'coef':>10}")
for nm,c in zip(names,b): print(f"  {nm:<20}{c:>10.4f}")
print(f"\n  in-sample accuracy : {acc:.2%}   ({int(((p>=.5)==(y==1)).sum())}/{len(y)})")
print(f"  in-sample Brier    : {brier:.4f}")
print(f"  fitted P(home) range: {p.min():.3f} .. {p.max():.3f}")

# ---------- theoretical ceiling implied by those probabilities ----------
theo=np.mean(np.maximum(p,1-p))
print(f"\n  If these fitted probabilities were the TRUE probabilities, the best")
print(f"  any predictor could ever average is  mean(max(p,1-p)) = {theo:.2%}")

# ---------- what would 80% even require? ----------
print(f"\n  games where the model is >=80% sure : {int((np.maximum(p,1-p)>=.80).sum())} of {len(y)}")
print(f"  games where the model is >=70% sure : {int((np.maximum(p,1-p)>=.70).sum())} of {len(y)}")
print(f"  games where the model is >=65% sure : {int((np.maximum(p,1-p)>=.65).sum())} of {len(y)}")

# ---------- selective prediction: cherry-pick only the surest games ----------
conf=np.maximum(p,1-p); hit=((p>=.5)==(y==1)).astype(int)
order=np.argsort(-conf)
print("\n  even if you only predict your most confident games:")
print(f"  {'top N%':<10}{'games':>7}{'accuracy':>11}")
for frac in (0.01,0.02,0.05,0.10,0.25,0.50,1.00):
    kk=max(1,int(len(y)*frac)); idx=order[:kk]
    print(f"  {frac:<10.0%}{kk:>7}{hit[idx].mean():>11.1%}")

# ---------- what DOES clear 80% ----------
print("\n" + "="*64)
print("QUESTIONS ABOUT THE SAME GAMES THAT *DO* CLEAR 80%")
print("="*64)
allg=[g for g in games if EVAL_START<=g["date"]<=EVAL_END]
n=len(allg)
m=[abs(g["hs"]-g["as_"]) for g in allg]
print(f"  'decided by fewer than 8 runs'        {sum(1 for x in m if x<8)/n:>7.1%}  (n={n})")
print(f"  'both teams score at least 1 run'     {sum(1 for g in allg if g['hs']>=1 and g['as_']>=1)/n:>7.1%}")
print(f"  'combined runs between 3 and 20'      {sum(1 for g in allg if 3<=g['hs']+g['as_']<=20)/n:>7.1%}")

# series winner: group consecutive same-matchup games
ser=defaultdict(list); prev={}
for g in allg:
    key=(g["home"],g["away"])
    ser[key].append(g)
groups=[]
for key,gs in ser.items():
    cur=[]
    for g in sorted(gs,key=lambda x:x["date"]):
        if cur and (np.datetime64(g["date"])-np.datetime64(cur[-1]["date"])).astype(int)>2:
            groups.append(cur); cur=[]
        cur.append(g)
    if cur: groups.append(cur)
gs3=[g for g in groups if len(g)>=3]
okc=0
for grp in gs3:
    h,a=grp[0]["home"],grp[0]["away"]
    fav = h if elo_f[h]+HFA>elo_f[a] else a
    hw=sum(1 for g in grp if g["home_won"]); aw=len(grp)-hw
    win = h if hw>aw else a
    okc += (fav==win)
print(f"  'better team wins the 3+ game SERIES' {okc/len(gs3):>7.1%}  (n={len(gs3)} series)")
swept=sum(1 for grp in gs3 if all(g['home_won'] for g in grp) or all(not g['home_won'] for g in grp))
print(f"  'series is NOT a sweep'               {1-swept/len(gs3):>7.1%}  (n={len(gs3)} series)")
