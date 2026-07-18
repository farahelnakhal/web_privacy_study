#analysis_cookies.py -> wpp 5

import argparse
import sqlite3
import csv
import os
from collections import defaultdict

import tldextract

#target cookies to track
TARGET_COOKIES = {
    "_ga": "Google Analytics client identifier",
    "IDE": "DoubleClick/Google Ad Manager user identifier",
    "_fbp": "Facebook Pixel browser identifier",
}

#get registered domain (sub.example.com -> example.com)
def get_registered_domain(host: str) -> str:
    ext = tldextract.extract(host.lstrip("."))
    return f"{ext.domain}.{ext.suffix}" if ext.suffix else ext.domain

def analyze(db_path: str):
    os.makedirs("results", exist_ok=True) #ensure output dir exists
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    #map visit_id -> site_url
    cur.execute("SELECT visit_id, site_url FROM site_visits")
    visits = {row["visit_id"]: row["site_url"] for row in cur.fetchall()}
    total_sites = len(visits)
    print(f"Total site visits: {total_sites}")

    #fetch all cookies from DB
    cur.execute("""
        SELECT visit_id, name, value, host, is_http_only, is_host_only, is_secure, same_site
        FROM javascript_cookies
    """)
    all_cookies = cur.fetchall()
    conn.close()

    #init result structure
    results = {name: {"sites": set(), "first_party": 0, "third_party": 0,
                      "via_http": 0, "via_js": 0}
               for name in TARGET_COOKIES}

    #process each cookie
    for row in all_cookies:
        name = row["name"]
        if name not in TARGET_COOKIES:
            continue #skip nontarget cookies

        vid = row["visit_id"]
        site_url = visits.get(vid, "")
        cookie_host = row["host"]

        #compare domains to determine 1st vs 3rd party
        site_rd = get_registered_domain(site_url)
        cookie_rd = get_registered_domain(cookie_host)

        results[name]["sites"].add(vid) #track unique sites

        if cookie_rd == site_rd or cookie_rd == "":
            results[name]["first_party"] += 1
        else:
            results[name]["third_party"] += 1

        #is_http_only=1 -> set via HTTP, else via JS
        if row["is_http_only"]:
            results[name]["via_http"] += 1
        else:
            results[name]["via_js"] += 1

    #print summary table
    print(f"\n{'Cookie':<12} {'Sites':>6} {'%':>7} {'1st':>5} {'3rd':>5} {'HTTP':>6} {'JS':>5}")
    print("-" * 50)

    rows_out = []
    for name, data in results.items():
        n = len(data["sites"])
        pct = 100 * n / total_sites if total_sites else 0
        print(f"{name:<12} {n:>6} {pct:>6.1f}% {data['first_party']:>5} {data['third_party']:>5} {data['via_http']:>6} {data['via_js']:>5}")
        
        #store row for csv
        rows_out.append({
            "cookie_name": name,
            "description": TARGET_COOKIES[name],
            "sites_found": n,
            "pct_sites": round(pct, 1),
            "first_party": data["first_party"],
            "third_party": data["third_party"],
            "via_http": data["via_http"],
            "via_js": data["via_js"],
        })

    #write results to csv
    with open("results/cookie_results.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=rows_out[0].keys())
        w.writeheader()
        w.writerows(rows_out)
    print("\nSaved: results/cookie_results.csv")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("-db", default="crawl_output/crawl-data.sqlite") #input DB path
    args = parser.parse_args()
    analyze(args.db)