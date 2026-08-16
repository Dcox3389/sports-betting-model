"""Pull MLB schedules + probable pitchers from the MLB StatsAPI."""
import json, os, urllib.request
from config import DATA, MLB_SEASONS

BASE = ("https://statsapi.mlb.com/api/v1/schedule?sportId=1"
        "&startDate={}&endDate={}&gameType=R&hydrate=linescore,team,probablePitcher")


def get(url, timeout=90):
    for _ in range(3):
        try:
            with urllib.request.urlopen(url, timeout=timeout) as r:
                return json.loads(r.read())
        except Exception:
            pass
    return None


def main():
    games = []
    raw_dates = []          # raw blob kept for the scripts in analysis/
    for start, end in MLB_SEASONS:
        data = get(BASE.format(start, end))
        if not data:
            print(f"  mlb {start}..{end}: FAILED")
            continue
        raw_dates.extend(data.get("dates", []))
        n = 0
        for blk in data.get("dates", []):
            for g in blk["games"]:
                if g["status"]["abstractGameState"] != "Final":
                    continue
                h, a = g["teams"]["home"], g["teams"]["away"]
                if "score" not in h or "score" not in a or h["score"] == a["score"]:
                    continue
                hp, ap = h.get("probablePitcher"), a.get("probablePitcher")
                games.append(dict(
                    lg="mlb", date=g["officialDate"], home=h["team"]["name"],
                    away=a["team"]["name"], hs=h["score"], as_=a["score"],
                    draw=False,
                    hp=hp["id"] if hp else None, ap=ap["id"] if ap else None,
                    hpn=hp["fullName"] if hp else None,
                    apn=ap["fullName"] if ap else None))
                n += 1
        print(f"  mlb {start}..{end}: {n} final games")

    games.sort(key=lambda x: x["date"])
    with open(os.path.join(DATA, "mlb_games.json"), "w") as f:
        json.dump(games, f)
    with open(os.path.join(DATA, "mlb_sched_pp.json"), "w") as f:
        json.dump({"dates": raw_dates}, f)
    print(f"mlb total: {len(games)} games")
    return games


if __name__ == "__main__":
    main()
