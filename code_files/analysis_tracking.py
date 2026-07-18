#analysis_tracking.py-> wpp s6

import argparse
import sqlite3
import os
import csv
import statistics
from collections import defaultdict

import requests as http_requests
import tldextract
import adblockparser

#optional regional filter list source
REGIONAL_LIST = [("EasyList Germany", "https://easylist.to/easylistgermany/easylistgermany.txt")]

#main filter lists used for tracking detection
FILTER_LISTS = {
    "easylist": "https://easylist.to/easylist/easylist.txt",
    "easyprivacy": "https://easylist.to/easylist/easyprivacy.txt",
}

CACHE_DIR = ".filter_cache"

#download + cache filter list
def download_list(name: str, url: str) -> list:
    os.makedirs(CACHE_DIR, exist_ok=True)
    cache = os.path.join(CACHE_DIR, f"{name}.txt")

    #use cached version if available
    if os.path.exists(cache):
        print(f"  [cache] {name}")
        with open(cache, encoding="utf-8", errors="replace") as f:
            return f.readlines()

    #otherwise download
    print(f"  [download] {name} ...")
    resp = http_requests.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
    resp.raise_for_status()

    with open(cache, "w", encoding="utf-8") as f:
        f.write(resp.text)

    return resp.text.splitlines(keepends=True)

#download regional filter list (fallback logic)
def download_regional() -> tuple:
    os.makedirs(CACHE_DIR, exist_ok=True)
    cache = os.path.join(CACHE_DIR, "regional.txt")
    name_cache = os.path.join(CACHE_DIR, "regional_name.txt")

    #use cached regional list if exists
    if os.path.exists(cache):
        friendly = open(name_cache).read() if os.path.exists(name_cache) else "regional"
        print(f"  [cache] {friendly}")
        with open(cache, encoding="utf-8", errors="replace") as f:
            return friendly, f.readlines()

    #try downloading available list
    for friendly, url in REGIONAL_LIST:
        try:
            print(f"  [trying] {friendly} ...")
            resp = http_requests.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
            resp.raise_for_status()

            with open(cache, "w", encoding="utf-8") as f:
                f.write(resp.text)
            with open(name_cache, "w") as f:
                f.write(friendly)

            print(f"  [ok] Downloaded {friendly}")
            return friendly, resp.text.splitlines(keepends=True)

        except Exception as e:
            print(f"  [skip] {friendly}: {e}")

#build adblock rules from selected lists
def build_rules(names: list, regional_lines: list = None) -> adblockparser.AdblockRules:
    lines = []

    for n in names:
        if n == "regional":
            lines.extend(regional_lines)
        else:
            lines.extend(download_list(n, FILTER_LISTS[n]))

    return adblockparser.AdblockRules(lines, use_re2=False)

#get registrable domain
def get_rd(url: str) -> str:
    ext = tldextract.extract(url)
    return f"{ext.domain}.{ext.suffix}" if ext.suffix else ext.domain

def analyze(db_path: str):
    os.makedirs("results", exist_ok=True)

    print("Building base rules...")
    rules_base = build_rules(["easylist", "easyprivacy"])

    print("Downloading regional list...")
    regional_name, regional_lines = download_regional()

    print("Building extended rules...")
    rules_ext = build_rules(["easylist", "easyprivacy", "regional"], regional_lines=regional_lines)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    #load site visits
    cur.execute("SELECT visit_id, site_url FROM site_visits")
    visits = {r["visit_id"]: r["site_url"] for r in cur.fetchall()}
    total = len(visits)

    #load all http requests
    cur.execute("SELECT visit_id, url, top_level_url FROM http_requests")
    reqs = cur.fetchall()
    conn.close()

    print(f"Sites: {total}, Requests: {len(reqs):,}")

    #tracking stats containers (base vs extended rules)
    site_track_b = defaultdict(set)
    site_1st_b = defaultdict(set)
    site_3rd_b = defaultdict(set)

    site_track_e = defaultdict(set)
    site_1st_e = defaultdict(set)
    site_3rd_e = defaultdict(set)

    dom_b = defaultdict(set)
    dom_e = defaultdict(set)

    print("Classifying...")
    for i, row in enumerate(reqs):
        if i % 10000 == 0:
            print(f"  {i:,}/{len(reqs):,}")

        url = row["url"]
        vid = row["visit_id"]
        top = row["top_level_url"] or visits.get(vid, "")

        third = get_rd(url) != get_rd(top)
        rd = get_rd(url)

        #base rules classification
        if rules_base.should_block(url, {"third-party": third}):
            site_track_b[vid].add(rd)
            dom_b[rd].add(vid)
            (site_3rd_b if third else site_1st_b)[vid].add(rd)

        #extended rules classification
        if rules_ext.should_block(url, {"third-party": third}):
            site_track_e[vid].add(rd)
            dom_e[rd].add(vid)
            (site_3rd_e if third else site_1st_e)[vid].add(rd)

    #report helper
    def report(track, first, third, doms, label):
        n_any = sum(1 for v in visits if track[v])
        n_first = sum(1 for v in visits if first[v])
        n_third = sum(1 for v in visits if third[v])

        sizes = [len(track[v]) for v in visits]
        med = statistics.median(sizes)
        mean = statistics.mean(sizes)

        top = sorted(doms.items(), key=lambda x: -len(x[1]))[:15]

        print(f"\n{'='*60}\n{label}\n{'='*60}")
        print(f"  Any tracking:        {n_any}/{total} ({100*n_any/total:.1f}%)")
        print(f"  First-party:         {n_first}/{total} ({100*n_first/total:.1f}%)")
        print(f"  Third-party:         {n_third}/{total} ({100*n_third/total:.1f}%)")
        print(f"  Median domains/site: {med:.1f}")
        print(f"  Mean domains/site:   {mean:.2f}")

        print("  Top 15 domains:")
        for d, v in top:
            print(f"    {d:<45} {len(v):>3} sites")

        return {
            "label": label,
            "n_any": n_any,
            "n_first": n_first,
            "n_third": n_third,
            "median": med,
            "mean": mean,
            "top": top
        }

    r_b = report(site_track_b, site_1st_b, site_3rd_b, dom_b, "EasyList + EasyPrivacy")
    r_e = report(site_track_e, site_1st_e, site_3rd_e, dom_e,
                 f"EasyList + EasyPrivacy + {regional_name}")

    #per-site csv output
    with open("results/per_site_tracking.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["visit_id", "site_url",
                    "n_base", "n_1st_b", "n_3rd_b",
                    "n_ext", "n_1st_e", "n_3rd_e"])

        for vid, url in visits.items():
            w.writerow([
                vid, url,
                len(site_track_b[vid]), len(site_1st_b[vid]), len(site_3rd_b[vid]),
                len(site_track_e[vid]), len(site_1st_e[vid]), len(site_3rd_e[vid])
            ])

    #domain comparison csv
    all_doms = set(dom_b) | set(dom_e)
    with open("results/tracking_domains.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["domain", "sites_base", "sites_ext"])

        for d in sorted(all_doms, key=lambda x: -len(dom_e.get(x, set()))):
            w.writerow([d, len(dom_b.get(d, set())), len(dom_e.get(d, set()))])

    #summary file
    with open("results/tracking_summary.txt", "w") as f:
        for r in [r_b, r_e]:
            f.write(f"\n{'='*60}\n{r['label']}\n{'='*60}\n")
            f.write(f"Any:    {r['n_any']}/{total} ({100*r['n_any']/total:.1f}%)\n")
            f.write(f"1st:    {r['n_first']}/{total} ({100*r['n_first']/total:.1f}%)\n")
            f.write(f"3rd:    {r['n_third']}/{total} ({100*r['n_third']/total:.1f}%)\n")
            f.write(f"Median: {r['median']:.1f}  Mean: {r['mean']:.2f}\n\nTop domains:\n")

            for d, v in r["top"]:
                f.write(f"  {d:<45} {len(v):>3}\n")

    print(f"\n[+] Done. Regional list used: {regional_name}")
    print("[+] Results in results/")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="crawl_output/crawl-data.sqlite")
    args = parser.parse_args()
    analyze(args.db)