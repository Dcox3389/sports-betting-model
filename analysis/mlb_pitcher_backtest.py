"""
MLB backtest v3 -- clean starting-pitcher experiment.

Fixes the v2 confound: the pitcher adjustment had leaked into the Elo UPDATE,
so the "no pitcher" baseline was no longer the v1 baseline. Here three Elo
tracks run fully independently over the same games:

  elo_pure : ratings updated with no pitcher information at all  (= v1 baseline)
  elo_dev  : starter expressed as deviation from that team's own rotation
  elo_raw  : starter expressed as raw regressed FIP vs league mean

Both pitcher specs are tested because it is not obvious a priori which is
right: `dev` avoids double-counting rotation quality already inside team Elo,
`raw` assumes team Elo is driven mostly by offence/bullpen.

Discordant picks are tested with McNemar's exact test.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import DATA
os.chdir(DATA)

import json, math, csv
from collections import defaultdict

EVAL_START, EVAL_END = "2026-06-04", "2026-08-03"
HFA, K = 24.0, 4.0
IP_REGRESS, EXP_IP, ELO_PER_RUN, DAMP = 60.0, 5.5, 72.0, 0.9

def ip_to_float(s):
    if s is None: return 0.0
    w, _, f = str(s).partition(".")
    return int(w or 0) + {"0": 0.0, "1": 1/3, "2": 2/3}.get(f, 0.0)

logs = json.load(open("pitcher_logs.json"))
pg = defaultdict(list); LG = dict(ip=0.0, hr=0, bb=0, hbp=0, k=0, er=0)
for pid, blob in logs.items():
    if not blob or not blob.get("stats"): continue
    for sp in blob["stats"][0].get("splits", []):
        st = sp["stat"]; ip = ip_to_float(st.get("inningsPitched"))
        if ip <= 0: continue
        pg[int(pid)].append((sp["date"], ip, st.get("homeRuns",0), st.get("baseOnBalls",0),
                             st.get("hitBatsmen",0), st.get("strikeOuts",0), st.get("earnedRuns",0)))
        LG["ip"]+=ip; LG["hr"]+=st.get("homeRuns",0); LG["bb"]+=st.get("baseOnBalls",0)
        LG["hbp"]+=st.get("hitBatsmen",0); LG["k"]+=st.get("strikeOuts",0); LG["er"]+=st.get("earnedRuns",0)
for p in pg: pg[p].sort()

lg_era = 9.0*LG["er"]/LG["ip"]
FIP_C = lg_era - (13*LG["hr"] + 3*(LG["bb"]+LG["hbp"]) - 2*LG["k"])/LG["ip"]

cum = {}
for pid, rows in pg.items():
    run=[]; ip=hr=bb=hbp=k=0.0
    for d,i_,h_,b_,hb_,k_,_ in rows:
        run.append((d,ip,hr,bb,hbp,k)); ip+=i_; hr+=h_; bb+=b_; hbp+=hb_; k+=k_
    cum[pid]=run

def fip_before(pid, date):
    rows = cum.get(pid)
    if not rows: return lg_era, 0.0
    ip=hr=bb=hbp=k=0.0
    for d,i_,h_,b_,hb_,k_ in rows:
        if d >= date: break
        ip,hr,bb,hbp,k = i_,h_,b_,hb_,k_
    if ip <= 0: return lg_era, 0.0
    raw = (13*hr + 3*(bb+hbp) - 2*k)/ip + FIP_C
    return (raw*ip + lg_era*IP_REGRESS)/(ip+IP_REGRESS), ip

sched = json.load(open("mlb_sched_pp.json"))
games=[]
for blk in sched["dates"]:
    for g in blk["games"]:
        if g["status"]["abstractGameState"]!="Final": continue
        h,a = g["teams"]["home"], g["teams"]["away"]
        if "score" not in h or "score" not in a or h["score"]==a["score"]: continue
        hp,ap = h.get("probablePitcher"), a.get("probablePitcher")
        games.append(dict(pk=g["gamePk"],date=g["officialDate"],dt=g["gameDate"],
            home=h["team"]["name"],away=a["team"]["name"],hs=h["score"],as_=a["score"],
            home_won=h["score"]>a["score"], hp=hp["id"] if hp else None, ap=ap["id"] if ap else None,
            hpn=hp["fullName"] if hp else "?", apn=ap["fullName"] if ap else "?"))
games.sort(key=lambda x:(x["dt"],x["pk"]))

TRACKS = ["pure","dev","raw"]
elo = {t: defaultdict(lambda:1500.0) for t in TRACKS}
W=defaultdict(int); L=defaultdict(int); RS=defaultdict(int); RA=defaultdict(int); GP=defaultdict(int)
rot=defaultdict(list)

def ep(rh,ra,adj=0.0): return 1.0/(1.0+10**(-((rh+HFA+adj)-ra)/400.0))
def log5(pa,pb):
    n=pa-pa*pb; d=pa+pb-2*pa*pb; return n/d if d else .5
def pythag(rs,ra,e=1.83): return .5 if rs<=0 and ra<=0 else rs**e/(rs**e+ra**e)
def rot_base(t): return sum(rot[t][-40:])/len(rot[t][-40:]) if len(rot[t])>=5 else lg_era

MODELS=["elo_pure","ensemble_v1","elo_dev","elo_raw","ensemble_v3"]
res={m:dict(n=0,correct=0,brier=0.0,logloss=0.0) for m in MODELS}
buck={m:defaultdict(lambda:[0,0]) for m in MODELS}
rows_out=[]

for g in games:
    h,a = g["home"], g["away"]
    fh,_ = fip_before(g["hp"], g["date"]) if g["hp"] else (lg_era,0)
    fa,_ = fip_before(g["ap"], g["date"]) if g["ap"] else (lg_era,0)

    dev = ((rot_base(h)-fh) - (rot_base(a)-fa))/9.0*EXP_IP
    raw = (fa-fh)/9.0*EXP_IP
    adj_dev = ELO_PER_RUN*dev*DAMP
    adj_raw = ELO_PER_RUN*raw*DAMP

    if EVAL_START <= g["date"] <= EVAL_END and GP[h]>=20 and GP[a]>=20:
        p_pure = ep(elo["pure"][h], elo["pure"][a])
        p_dev  = ep(elo["dev"][h],  elo["dev"][a],  adj_dev)
        p_raw  = ep(elo["raw"][h],  elo["raw"][a],  adj_raw)
        wp_h = W[h]/(W[h]+L[h]) if W[h]+L[h] else .5
        wp_a = W[a]/(W[a]+L[a]) if W[a]+L[a] else .5
        p_rec = min(max(log5(wp_h,wp_a)+.035,.02),.98)
        p_pyt = min(max(log5(pythag(RS[h],RA[h]),pythag(RS[a],RA[a]))+.035,.02),.98)
        p_v1 = .50*p_pure + .25*p_pyt + .25*p_rec
        p_v3 = .50*p_raw  + .25*p_pyt + .25*p_rec

        preds={"elo_pure":p_pure,"ensemble_v1":p_v1,"elo_dev":p_dev,
               "elo_raw":p_raw,"ensemble_v3":p_v3}
        for m,p in preds.items():
            pick=p>=.5; ok=(pick==g["home_won"]); r=res[m]
            r["n"]+=1; r["correct"]+=ok
            y=1.0 if g["home_won"] else 0.0
            r["brier"]+=(p-y)**2
            pc=min(max(p,1e-9),1-1e-9); r["logloss"]-= y*math.log(pc)+(1-y)*math.log(1-pc)
            conf=p if pick else 1-p
            b=round(min(conf,.799)//.05*.05+.025,3)
            buck[m][b][0]+=1; buck[m][b][1]+=ok

        rows_out.append(dict(date=g["date"],away=a,home=h,score=f"{g['as_']}-{g['hs']}",
            actual="HOME" if g["home_won"] else "AWAY", sp_away=g["apn"], sp_home=g["hpn"],
            fip_away=round(fa,2), fip_home=round(fh,2), sp_elo_adj=round(adj_raw,1),
            p_home_v1=round(p_v1,4), p_home_v3=round(p_v3,4),
            pick_v1="HOME" if p_v1>=.5 else "AWAY", pick_v3="HOME" if p_v3>=.5 else "AWAY",
            hit_v1=int((p_v1>=.5)==g["home_won"]), hit_v3=int((p_v3>=.5)==g["home_won"])))

    y = 1.0 if g["home_won"] else 0.0
    mov = math.log(abs(g["hs"]-g["as_"])+1)
    for t,adj in (("pure",0.0),("dev",adj_dev),("raw",adj_raw)):
        d = K*mov*(y - ep(elo[t][h], elo[t][a], adj))
        elo[t][h]+=d; elo[t][a]-=d
    if g["home_won"]: W[h]+=1; L[a]+=1
    else: W[a]+=1; L[h]+=1
    RS[h]+=g["hs"]; RA[h]+=g["as_"]; RS[a]+=g["as_"]; RA[a]+=g["hs"]; GP[h]+=1; GP[a]+=1
    if g["hp"]: rot[h].append(fh)
    if g["ap"]: rot[a].append(fa)

n=res["elo_pure"]["n"]
print(f"league starters: {LG['ip']:.0f} IP, ERA {lg_era:.2f}, FIP const {FIP_C:.3f}")
print(f"\nevaluated games ({EVAL_START}..{EVAL_END}): {n}\n")
print(f"{'model':<14}{'games':>7}{'correct':>9}{'acc':>9}{'brier':>9}{'logloss':>10}")
for m in MODELS:
    r=res[m]
    print(f"{m:<14}{r['n']:>7}{r['correct']:>9}{r['correct']/r['n']:>8.1%}"
          f"{r['brier']/r['n']:>9.4f}{r['logloss']/r['n']:>10.4f}")

def mcnemar(rows,k1,k2):
    b=sum(1 for r in rows if r[k1]==1 and r[k2]==0)
    c=sum(1 for r in rows if r[k1]==0 and r[k2]==1)
    nn=b+c
    if nn==0: return b,c,1.0
    lo=min(b,c)
    p=2*sum(math.comb(nn,i) for i in range(lo+1))/2**nn
    return b,c,min(p,1.0)

b,c,p = mcnemar(rows_out,"hit_v3","hit_v1")
print(f"\nstarter term changed the pick in {b+c} of {n} games: "
      f"{b} newly right, {c} newly wrong (net {b-c:+d}), McNemar exact p = {p:.3f}")

print("\nensemble_v3 calibration:")
print(f"{'bucket':<10}{'n':>6}{'predicted':>11}{'actual':>9}")
for bk in sorted(buck["ensemble_v3"]):
    cn,kk = buck["ensemble_v3"][bk]
    if cn>=10: print(f"{bk:<10.3f}{cn:>6}{bk:>11.1%}{kk/cn:>9.1%}")

with open("mlb_backtest_v3.csv","w",newline="",encoding="utf-8") as f:
    wr=csv.DictWriter(f,fieldnames=list(rows_out[0].keys())); wr.writeheader(); wr.writerows(rows_out)
print(f"\nwrote mlb_backtest_v3.csv ({len(rows_out)} rows)")

# does the starter matter more when the FIP gap is large?
print("\naccuracy by size of starter mismatch (regressed FIP gap):")
print(f"{'gap':<14}{'n':>6}{'v1':>8}{'v3':>8}")
for lo,hi,lbl in [(0,.5,'0.0-0.5'),(.5,1.0,'0.5-1.0'),(1.0,1.5,'1.0-1.5'),(1.5,9,'1.5+')]:
    sub=[r for r in rows_out if lo<=abs(r["fip_home"]-r["fip_away"])<hi]
    if len(sub)>=15:
        print(f"{lbl:<14}{len(sub):>6}{sum(r['hit_v1'] for r in sub)/len(sub):>8.1%}"
              f"{sum(r['hit_v3'] for r in sub)/len(sub):>8.1%}")
