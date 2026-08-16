"""Fetch everything, then build the screen. `python run_all.py --skip-fetch` reuses cached data."""
import sys, time

def main():
    skip = "--skip-fetch" in sys.argv
    if not skip:
        t0 = time.time()
        import fetch_mlb, fetch_espn, fetch_tennis
        print("=== MLB ==="); fetch_mlb.main()
        print("\n=== ESPN ==="); fetch_espn.main()
        print("\n=== TENNIS ==="); fetch_tennis.main()
        print(f"\nfetch took {time.time()-t0:.0f}s")
    else:
        print("(skipping fetch, using cached data/)")
    print("\n=== SCREEN ===")
    import screen
    screen.main()

if __name__ == "__main__":
    main()
