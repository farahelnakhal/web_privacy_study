#analysis_ecosystem.py-> wpp s7

import argparse
import sqlite3
import os
from collections import defaultdict
from pathlib import Path

import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
import tldextract
import adblockparser

#get registered domain from url
def get_rd(url):
    ext = tldextract.extract(url)
    return f"{ext.domain}.{ext.suffix}" if ext.suffix else ext.domain or url

#load EasyList + EasyPrivacy rules from cache
def load_rules():
    lines = []
    for name in ["easylist", "easyprivacy"]:
        p = Path(f".filter_cache/{name}.txt")
        if p.exists():
            lines.extend(p.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True))
    if not lines:
        raise FileNotFoundError("Run analysis_tracking.py first to populate .filter_cache/")
    return adblockparser.AdblockRules(lines, use_re2=False)

def analyze(db_path):
    os.makedirs("results", exist_ok=True) #ensure output dir

    print("[1/6] Loading filter rules...")
    rules = load_rules()

    print("[2/6] Loading requests from DB...")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT visit_id, site_url FROM site_visits")
    visits = {r["visit_id"]: r["site_url"] for r in cur.fetchall()} #map visit_id -> site
    cur.execute("SELECT visit_id, url, top_level_url FROM http_requests")
    reqs = cur.fetchall()
    conn.close()
    print(f"    {len(visits)} sites, {len(reqs):,} requests")

    print("[3/6] Classifying tracking requests...")
    site_trackers = defaultdict(set) #site -> tracker domains
    domain_sites = defaultdict(set)  #tracker -> sites
    for i, row in enumerate(reqs):
        if i % 10000 == 0:
            print(f"    {i:,}/{len(reqs):,}")
        url = row["url"]
        vid = row["visit_id"]
        top = row["top_level_url"] or visits.get(vid, "")
        third = get_rd(url) != get_rd(top) #check 3rd-party
        rd = get_rd(url)
        if rules.should_block(url, {"third-party": third}):
            site_trackers[vid].add(rd)
            domain_sites[rd].add(vid)

    #get top N trackers by site coverage
    TOP_N = 30
    top_trackers = sorted(domain_sites.items(), key=lambda x: -len(x[1]))[:TOP_N]
    tracker_list = [t[0] for t in top_trackers]
    site_list = list(visits.keys())
    site_urls = [visits[v] for v in site_list]
    n_sites = len(site_list)
    n_t = len(tracker_list)
    print(f"    Unique tracker domains: {len(domain_sites)}, using top {n_t}")

    print("[4/6] Building binary matrix...")
    #matrix[i,j] = 1 if site i contains tracker j
    matrix = np.zeros((n_sites, n_t), dtype=np.int8)
    for i, vid in enumerate(site_list):
        for j, t in enumerate(tracker_list):
            if t in site_trackers[vid]:
                matrix[i, j] = 1

    print("[5/6] Generating plots...")

    #plt1: site x tracker heatmap
    order = np.argsort(-matrix.sum(axis=1)) #sort sites by #trackers
    short_sites = [site_urls[i].replace("https://","").rstrip("/")[:28] for i in order]
    short_tracks = [t[:22] for t in tracker_list]

    fig, ax = plt.subplots(figsize=(14, max(8, n_sites * 0.22)))
    sns.heatmap(matrix[order], ax=ax, cmap="Blues", cbar=False,
                linewidths=0.3, linecolor="gray",
                xticklabels=short_tracks, yticklabels=short_sites)
    ax.set_title("Site x Tracker Presence Matrix (Top 30 Trackers)")
    ax.set_xlabel("Tracker domain")
    ax.set_ylabel("Site (sorted by # trackers)")
    plt.xticks(rotation=45, ha="right", fontsize=7)
    plt.yticks(fontsize=7)
    plt.tight_layout()
    plt.savefig("results/ecosystem_clusters.png", dpi=150)
    plt.close()
    print("    Saved: results/ecosystem_clusters.png")

    #plt2: tracker concentration (sites per tracker)
    counts = sorted([(t, len(domain_sites[t])) for t in tracker_list], key=lambda x: -x[1])
    fig2, ax2 = plt.subplots(figsize=(12, 6))
    ax2.barh([c[0][:35] for c in counts[::-1]], [c[1] for c in counts[::-1]], color="steelblue")
    ax2.set_xlabel("Number of sites")
    ax2.set_title("Top Tracking Domains by Site Reach")
    ax2.axvline(n_sites * 0.5, color="red", linestyle="--", alpha=0.6, label="50% of sites")
    ax2.legend()
    plt.tight_layout()
    plt.savefig("results/tracker_concentration.png", dpi=150)
    plt.close()
    print("    Saved: results/tracker_concentration.png")

    #plt3: jaccard co-occurrence between trackers
    #cooc[i,j] = intersection / union
    m = matrix.astype(np.float32)
    both = m.T @ m #sites with both trackers
    col_sum = m.sum(axis=0) #sites per tracker
    either = col_sum[:, None] + col_sum[None, :] - both
    cooc = np.where(either > 0, both / either, 0.0)

    fig3, ax3 = plt.subplots(figsize=(12, 10))
    sns.heatmap(cooc, ax=ax3, cmap="YlOrRd", vmin=0, vmax=1,
                xticklabels=short_tracks, yticklabels=short_tracks)
    ax3.set_title("Tracker Co-occurrence (Jaccard Similarity)")
    plt.xticks(rotation=45, ha="right", fontsize=7)
    plt.yticks(fontsize=7)
    plt.tight_layout()
    plt.savefig("results/tracker_cooccurrence.png", dpi=150)
    plt.close()
    print("    Saved: results/tracker_cooccurrence.png")

    print("[6/6] Writing report...")
    n_any = int((matrix.sum(axis=1) > 0).sum()) #sites with ≥1 tracker
    long_tail = sum(1 for v in domain_sites.values() if len(v) <= 2) #rare trackers

    report = f"""
Tracker Ecosystem Analysis
==========================
Total sites:                    {n_sites}
Sites with any tracker:         {n_any} ({100*n_any/n_sites:.1f}%)
Unique tracker domains:         {len(domain_sites)}
Long-tail trackers (<=2 sites): {long_tail} ({100*long_tail/len(domain_sites):.1f}%)

Top 10 trackers:
"""
    for t, cnt in counts[:10]:
        report += f"  {t:<45} {cnt:>3} sites ({100*cnt/n_sites:.0f}%)\n"

    #save report to file
    with open("results/ecosystem_report.txt", "w") as f:
        f.write(report)
    print(report)
    print("[+] Ecosystem analysis complete. Results in results/")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="crawl_output/crawl-data.sqlite") #input DB
    args = parser.parse_args()
    analyze(args.db)