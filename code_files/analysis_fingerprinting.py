#analysis_fingerprinting.py-> wpp s8

import argparse
import sqlite3
import csv
import os
from collections import defaultdict

import tldextract

#canvas apis used for drawing (potential fingerprinting signals)
CANVAS_DRAW = {"CanvasRenderingContext2D.fillText", "CanvasRenderingContext2D.strokeText",
               "CanvasRenderingContext2D.fillRect", "CanvasRenderingContext2D.arc",
               "CanvasRenderingContext2D.fill", "CanvasRenderingContext2D.stroke"}

#canvas apis used to extract image data
CANVAS_EXTRACT = {"HTMLCanvasElement.toDataURL", "HTMLCanvasElement.toBlob",
                  "CanvasRenderingContext2D.getImageData"}

#audio api used for generation
AUDIO_GEN = {"AudioContext.createOscillator", "AudioContext.createDynamicsCompressor",
             "AudioContext.createBuffer", "AudioContext.createAnalyser",
             "OfflineAudioContext.startRendering"}

#audio apis used for extracting features
AUDIO_EXTRACT = {"AudioBuffer.getChannelData", "AnalyserNode.getFloatFrequencyData",
                 "AnalyserNode.getByteFrequencyData", "AnalyserNode.getFloatTimeDomainData"}

#get registered domain
def get_rd(url):
    ext = tldextract.extract(url or "")
    return f"{ext.domain}.{ext.suffix}" if ext.suffix else ext.domain or url

def analyze(db_path):
    os.makedirs("results", exist_ok=True) #output folder

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    #load visited sites
    cur.execute("SELECT visit_id, site_url FROM site_visits")
    visits = {r["visit_id"]: r["site_url"] for r in cur.fetchall()}
    total = len(visits)

    #JS API calls log
    cur.execute("SELECT visit_id, script_url, symbol FROM javascript")
    js_rows = cur.fetchall()
    conn.close()

    print(f"[*] {len(js_rows):,} JS API calls across {total} sites")

    #group JS symbols by (site visit, script domain)
    script_syms = defaultdict(set)
    for row in js_rows:
        vid = row["visit_id"]
        rd = get_rd(row["script_url"] or "")
        sym = row["symbol"] or ""
        script_syms[(vid, rd)].add(sym)

    canvas_sites = set()
    canvas_scripts = defaultdict(set)
    audio_sites = set()
    audio_scripts = defaultdict(set)

    #detect fingerprinting patterns
    for (vid, rd), syms in script_syms.items():
        if syms & CANVAS_DRAW and syms & CANVAS_EXTRACT:
            canvas_sites.add(vid)
            canvas_scripts[rd].add(vid)

        if syms & AUDIO_GEN and syms & AUDIO_EXTRACT:
            audio_sites.add(vid)
            audio_scripts[rd].add(vid)

    #print summary
    def show(label, sites, scripts):
        n = len(sites)
        pct = 100 * n / total if total else 0
        print(f"\n{label} Fingerprinting")
        print(f"  Sites: {n}/{total} ({pct:.1f}%)")

        top = sorted(scripts.items(), key=lambda x: -len(x[1]))[:10]
        for d, v in top:
            print(f"    {d:<45} {len(v):>3} sites")

    show("Canvas", canvas_sites, canvas_scripts)
    show("Audio", audio_sites, audio_scripts)

    #save per-domain results
    def save_csv(path, scripts, visits):
        with open(path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["script_domain", "n_sites", "site_urls"])
            for d, vids in sorted(scripts.items(), key=lambda x: -len(x[1])):
                w.writerow([d, len(vids), "; ".join(visits.get(v, "") for v in vids)])

    save_csv("results/fingerprinting_canvas.csv", canvas_scripts, visits)
    save_csv("results/fingerprinting_audio.csv", audio_scripts, visits)

    #save per-site flags
    with open("results/fingerprinting_per_site.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["visit_id", "site_url", "canvas_fp", "audio_fp"])
        for vid, url in visits.items():
            w.writerow([vid, url, int(vid in canvas_sites), int(vid in audio_sites)])

    #final report
    summary = f"""
Fingerprinting Analysis
=======================
Total sites: {total}

Canvas fingerprinting:  {len(canvas_sites)}/{total} ({100*len(canvas_sites)/total:.1f}%)
Audio fingerprinting:   {len(audio_sites)}/{total} ({100*len(audio_sites)/total:.1f}%)

Top Canvas FP scripts:
""" + "".join(
        f"  {d:<45} {len(v):>3} sites\n"
        for d, v in sorted(canvas_scripts.items(), key=lambda x: -len(x[1]))[:10]
    )

    with open("results/fingerprinting_summary.txt", "w") as f:
        f.write(summary)

    print(summary)
    print("[+] Done. Results in results/")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="crawl_output/crawl-data.sqlite")
    args = parser.parse_args()
    analyze(args.db)