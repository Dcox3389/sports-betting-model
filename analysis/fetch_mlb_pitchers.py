im
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import DATA
os.chdir(DATA)
port json, urllib.request, concurrent.futures as cf

sched = json.load(open("mlb_sched_pp.json"))
ids = set()
for b in sched["dates"]:
    for g in b["games"]:
        for side in ("home", "away"):
            pp = g["teams"][side].get("probablePitcher")
            if pp:
                ids.add(pp["id"])
ids = sorted(ids)
print("pitchers to fetch:", len(ids))

URL = ("https://statsapi.mlb.com/api/v1/people/{}/stats"
       "?stats=gameLog&group=pitching&season=2026&gameType=R")

def grab(pid):
    for _ in range(3):
        try:
            with urllib.request.urlopen(URL.format(pid), timeout=30) as r:
                return pid, json.loads(r.read())
        except Exception:
            pass
    return pid, None

out = {}
with cf.ThreadPoolExecutor(max_workers=12) as ex:
    for i, (pid, data) in enumerate(ex.map(grab, ids), 1):
        out[pid] = data
        if i % 50 == 0:
            print("  ", i, "done")

json.dump(out, open("pitcher_logs.json", "w"))
ok = sum(1 for v in out.values() if v and v.get("stats"))
print(f"fetched {ok}/{len(ids)} with game-log data")
