#analysis_testpage.py-> wpp s9

import argparse
import sqlite3
import os
from pathlib import Path
from collections import defaultdict

import tldextract
import adblockparser

#cookies commonly used for tracking
TARGET_COOKIES = {"_ga","IDE","_fbp","__utma","__utmz","fr","_gcl_au","NID","DSID"}

#canvas fingerprinting signals
CANVAS_DRAW = {"CanvasRenderingContext2D.fillText","CanvasRenderingContext2D.strokeText",
               "CanvasRenderingContext2D.fillRect","CanvasRenderingContext2D.arc"}
CANVAS_EXTRACT = {"HTMLCanvasElement.toDataURL","CanvasRenderingContext2D.getImageData"}

#audio fingerprinting signals
AUDIO_GEN = {"AudioContext.createOscillator","AudioContext.createDynamicsCompressor"}
AUDIO_EXTRACT = {"AudioBuffer.getChannelData","AnalyserNode.getFloatFrequencyData"}

#heuristic keywords for suspicious tracking endpoints
SUSPICIOUS_KW = ["pixel","beacon","track","analytics","collect","telemetry",
                  "stat","metrics","event","log","ping","impression","convert"]

#get registered domain
def get_rd(url):
    ext = tldextract.extract(url or "")
    return f"{ext.domain}.{ext.suffix}" if ext.suffix else ext.domain or url

#load adblock filter rules
def load_rules():
    lines = []
    for name in ["easylist","easyprivacy"]:
        p = Path(f".filter_cache/{name}.txt")
        if p.exists():
            lines.extend(p.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True))
    return adblockparser.AdblockRules(lines, use_re2=False) if lines else None

def analyze(db_path):
    os.makedirs("results", exist_ok=True)
    rules = load_rules()

    if not rules:
        print("WARNING: No filter rules cached. Run analysis_tracking.py first for full detection.")

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    #load all visited sites
    cur.execute("SELECT visit_id, site_url FROM site_visits")
    visits = {r["visit_id"]: r["site_url"] for r in cur.fetchall()}
    if not visits:
        print("No visits found.")
        return

    #pick first site for deep inspection
    vid = list(visits.keys())[0]
    site_url = visits[vid]
    print(f"\nAnalyzing: {site_url}  (visit_id={vid})")

    #load HTTP requests for that site
    cur.execute("""
        SELECT url, top_level_url, resource_type
        FROM http_requests WHERE visit_id=?""", (vid,))
    http_reqs = cur.fetchall()

    #load cookies for that site
    cur.execute("""
        SELECT name, value, host, is_http_only, is_secure, same_site
        FROM javascript_cookies WHERE visit_id=?""", (vid,))
    cookies = cur.fetchall()

    #load JS API calls
    cur.execute("SELECT script_url, symbol FROM javascript WHERE visit_id=?", (vid,))
    js_calls = cur.fetchall()
    conn.close()

    #classify requests
    flagged = []
    suspicious = []
    clean = []

    for row in http_reqs:
        url = row["url"]
        top = row["top_level_url"] or site_url
        third = get_rd(url) != get_rd(top)
        blocked = rules.should_block(url, {"third-party": third}) if rules else False

        entry = {
            "url": url,
            "type": row["resource_type"],
            "third": third,
            "flagged": blocked
        }

        if blocked:
            flagged.append(entry)
        else:
            url_l = url.lower()
            reason = None

            #heuristic detection for tracking endpoints
            if any(k in url_l for k in SUSPICIOUS_KW):
                reason = "URL contains tracking keyword"
            elif third and row["resource_type"] in ("xmlhttprequest","image","ping","beacon"):
                reason = f"Third-party {row['resource_type']}"

            if reason:
                entry["reason"] = reason
                suspicious.append(entry)
            else:
                clean.append(entry)

    #fingerprinting detection via JS API usage patterns
    script_syms = defaultdict(set)
    for row in js_calls:
        script_syms[get_rd(row["script_url"] or "")].add(row["symbol"] or "")

    canvas_fp = any(s & CANVAS_DRAW and s & CANVAS_EXTRACT for s in script_syms.values())
    audio_fp = any(s & AUDIO_GEN and s & AUDIO_EXTRACT for s in script_syms.values())

    #tracking cookies
    found_cookies = [r for r in cookies if r["name"] in TARGET_COOKIES]

    #summary output
    print(f"\nTotal HTTP requests:   {len(http_reqs)}")
    print(f"Filter-list flagged:   {len(flagged)}")
    print(f"Suspicious (unflagged):{len(suspicious)}")
    print(f"Canvas fingerprinting: {canvas_fp}")
    print(f"Audio fingerprinting:  {audio_fp}")
    print(f"Tracking cookies:      {len(found_cookies)}")

    print(f"\n--- Flagged requests ({len(flagged)}) ---")
    for r in flagged:
        print(f"  [{'3rd' if r['third'] else '1st'}] {r['url'][:90]}")

    print(f"\n--- Suspicious unflagged ({len(suspicious)}) ---")
    for r in suspicious:
        print(f"  [{'3rd' if r['third'] else '1st'}] {r['url'][:90]}")
        print(f"       Reason: {r['reason']}")

    print(f"\n--- Tracking cookies ({len(found_cookies)}) ---")
    for c in found_cookies:
        print(f"  {c['name']} | host={c['host']} | http_only={c['is_http_only']}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("-db", default="crawl_output/crawl-data.sqlite")
    args = parser.parse_args()
    analyze(args.db)