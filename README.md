# Web Privacy Measurement Study with OpenWPM

A large-scale web privacy measurement study built on top of [OpenWPM](https://github.com/openwpm/OpenWPM), an instrumented browser automation framework for studying tracking, cookies, and fingerprinting at scale. This project crawls the Tranco top 100 websites, collects fine-grained instrumentation data (HTTP traffic, cookies, JavaScript API calls), and analyzes it to characterize third-party tracking, tracking cookies, browser fingerprinting, and the structure of the underlying tracker ecosystem.

## Overview

This repository contains:

- A custom OpenWPM-based crawler that visits a site's homepage plus up to five internal pages, attempts to dismiss cookie consent banners, and isolates each site's browsing state in its own browser profile.
- A dataset exploration module for understanding the OpenWPM SQLite schema (`site_visits`, `crawl_history`, `http_requests`, `http_responses`, `http_redirects`, `javascript`, `javascript_cookies`).
- Analysis pipelines for:
  - **Tracking cookie detection** — prevalence of well-known tracking cookies (first vs. third-party, HTTP- vs. JS-set)
  - **Tracking request detection** — using EasyList, EasyPrivacy, and a regional filter list (EasyList Germany) via `adblockparser`
  - **Tracker ecosystem analysis** — a bipartite site–tracker graph, Jaccard co-occurrence clustering, and site×tracker presence matrix
  - **Fingerprinting detection** — Canvas and AudioContext fingerprinting behavior via JS instrumentation
- A manual inspection case study run against a dedicated test page to validate and stress-test the automated detection pipeline, including detection of first-party proxying and CNAME cloaking.

## Motivation

Modern websites embed a large number of third-party scripts and resources for analytics, advertising, and personalization — many of which track users across sites using cookies, fingerprinting, and other identification techniques. This project builds an end-to-end measurement pipeline to empirically quantify how prevalent these techniques are across popular websites, which actors dominate the tracking ecosystem, and where filter-list-based detection approaches fall short.

## What is OpenWPM?

[OpenWPM](https://github.com/openwpm/OpenWPM) is an open-source web privacy measurement platform developed at Princeton University, built around a manager–worker architecture (`TaskManager`, `BrowserManager`, `StorageController`) and an instrumented Firefox WebExtension that hooks HTTP traffic, cookie changes, navigation events, and JavaScript API calls (Canvas, AudioContext, RTCPeerConnection, `navigator`, `screen`, `localStorage`) at the prototype level. All instrumented data is streamed to a normalized SQLite database keyed on `visit_id`, enabling reproducible, join-based cross-dimensional analysis. It's widely used in empirical web privacy research because of its controlled, stateless, per-domain-isolated crawling model and its documented, extensible API.

## Requirements

- Python 3.10 or 3.11 (required by OpenWPM; note this is stricter than the environment's system Python)
- macOS or Linux (Windows users: run via Docker or a VM)
- [OpenWPM](https://github.com/openwpm/OpenWPM) (clone and follow their install instructions)
- `adblockparser` for filter-list-based tracker detection
- `tldextract` for registrable-domain extraction (first vs. third-party classification)
- Additional Python dependencies listed in `requirements.txt`

## Setup

1. Clone and install OpenWPM:
```bash
   git clone https://github.com/openwpm/OpenWPM.git
   cd OpenWPM
   conda env create -f environment.yaml
   conda activate openwpm
   ./install.sh
```
2. **macOS note:** OpenWPM spawns Firefox worker processes via `fork()`, which conflicts with the macOS Objective-C runtime's thread-safety model. This must be set in the shell *before* invoking Python (setting it via `os.environ` inside the script is too late, since the fork happens during `TaskManager` init):
```bash
   export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
   python crawler/crawl.py
```

**Environment used for development:**

| Parameter | Value |
|---|---|
| OS | macOS (Apple Silicon, macOS 15.6.1) |
| Python | 3.14.2 (Homebrew), with conda env + venv for OpenWPM's Python 3.10/3.11 requirement |
| OpenWPM version | v0.33.0-3-ga088fd37 |
| Firefox | 149.0 (managed by OpenWPM) |
| Virtualization | Native macOS (no Docker/VM) |

## Running the Crawler

```bash
export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES   # macOS only
python crawler/crawl.py --input crawler/sites.csv --output data/crawl-data.sqlite
```

Crawler behavior:
- Visits each site's homepage, then up to 5 internal pages discovered via same-origin links (`browse(num_links=5, sleep=25)`).
- Attempts to interact with cookie consent banners via a custom `AcceptCookieBannerCommand` (matches common selectors/ARIA labels and "Accept all" / "I agree" text).
- Dwells on each page for 25 seconds to allow tracking/fingerprinting scripts to execute.
- Uses a **fresh, isolated browser profile per site** (`reset=True` — no persisted cookies/localStorage/cache across sites), but **reuses the same profile across a site's internal pages** to preserve session continuity.
- Records HTTP requests/responses, cookies (HTTP- and JS-set), and JavaScript API call instrumentation for every visit.

Crawl target: **Tranco top 100**.

### Crawl Results

| Metric | Value |
|---|---|
| Total sites attempted | 100 |
| Sites with HTTP data collected | 100 (100%) |
| Sites completing full browse sequence | 46 |
| Sites with browse timeout (homepage data still captured) | 39 |
| Sites with only 1 request (DNS/infra domains) | 15 |
| Total HTTP requests recorded | 30,906 |
| Total JavaScript API calls recorded | 198,475 |
| Total cookies recorded | 16,271 |
| Crawl duration | ~7 hours |

All 100 sites produced at least one recorded HTTP request. The 15 single-request sites are DNS/CDN infrastructure domains (e.g. `akadns.net`, `akamaiedge.net`, `cloudfront.net`) that appear in Tranco due to DNS query volume but aren't navigable sites. The 39 browse timeouts occurred on content-heavy pages (Amazon, YouTube, Wikipedia) exceeding the 60s `BrowseCommand` timeout — homepage data was fully committed in all such cases; only internal-page coverage is incomplete for those sites.

**Known limitations:** imperfect cookie-banner click detection, sequential single-browser crawling (increases total wall-clock time), a 60s internal-page timeout that's short for content-heavy sites, and a point-in-time snapshot (April 3–4, 2026) that may not generalize over time.

## Dataset Schema

| Table | Rows | Description |
|---|---|---|
| `site_visits` | 100 | One row per site visit; maps `visit_id` to `site_url` |
| `http_requests` | 30,906 | Outgoing HTTP/HTTPS requests |
| `http_responses` | 28,007 | HTTP responses with status codes and headers |
| `http_redirects` | 3,197 | Redirect chains |
| `javascript_cookies` | 16,271 | All cookies observed (HTTP- and JS-set) |
| `javascript` | 198,475 | JavaScript API call events |
| `navigations` | 1,906 | Browser navigation events |
| `incomplete_visits` | 111 | Visits interrupted before completion |

`visit_id` is the primary join key linking `javascript`, `http_requests`, and other tables back to a specific `site_visits` entry. `http_responses` links to `http_requests` via a shared `request_id` (scoped within `visit_id`). Note: OpenWPM v0.33's `is_third_party_to_top_window` column is `NULL`, so first-/third-party status is computed manually by comparing registrable domains (via `tldextract`) between `url` and `top_level_url`.

## Analysis Pipeline

### 1. Tracking Cookie Analysis
Measures prevalence of three well-known tracking cookies — `_ga` (Google Analytics), `IDE` (DoubleClick/Google Ad Manager), and `_fbp` (Facebook Pixel) — across the 100 sites, by first-/third-party context and HTTP- vs. JS-set origin.

| Cookie | Sites | % of sites | Context | Set via |
|---|---|---|---|---|
| `_ga` | 22 | 22.0% | Always 1P (value read by Google's servers) | Always JS |
| `IDE` | 23 | 23.0% | Almost always 3P (doubleclick.net) | Always HTTP |
| `_fbp` | 12 | 12.0% | Always 1P (value exfiltrated to Meta) | Always JS |

### 2. Tracking Request Analysis
Matches `http_requests` against **EasyList + EasyPrivacy**, then adds **EasyList Germany** as a regional supplement, via `adblockparser`.

| Metric | EasyList + EasyPrivacy | + EasyList Germany |
|---|---|---|
| Sites with any tracking | 68/100 (68.0%) | 68/100 (68.0%) |
| Sites with first-party tracking | 55/100 (55.0%) | 55/100 (55.0%) |
| Sites with third-party tracking | 56/100 (56.0%) | 56/100 (56.0%) |
| Median / mean tracking domains per site | 2.0 / 9.02 | 2.0 / 9.02 |

Adding the regional list produced **no measurable change** — expected for a globally dominated Tranco top-100 list, where tracking infrastructure is already covered by the global lists. Top tracking domains: `google.com` (34 sites), `doubleclick.net` (30), `googletagmanager.com` (29), `bing.com` (22), `facebook.com` (19), plus several real-time bidding platforms (Index Exchange, Rubicon/Magnite, PubMatic, AppNexus).

### 3. Tracker Ecosystem Analysis
Builds a bipartite site–tracker graph (100 sites × 299 unique tracker domains) and computes pairwise Jaccard co-occurrence between the top 30 trackers by site reach.

- **Concentration:** the top 3 trackers (Google's stack) reach 34%, 30%, and 29% of sites respectively; no single tracker crosses 50%.
- **Long tail:** 209 of 299 tracker domains (69.9%) appear on at most 2 sites.
- **Clusters:** two clear co-occurrence clusters emerge — Google's integrated analytics/ads family, and a real-time-bidding cluster (Index Exchange, Rubicon, PubMatic, AppNexus, Demdex) reflecting shared publisher ad-stack integrations.

### 4. Fingerprinting Analysis
Detects Canvas fingerprinting (drawing API + extraction API from the same script/visit) and Audio fingerprinting (generation API + extraction API) via the `javascript` table.

| Type | Sites affected | Fraction |
|---|---|---|
| Canvas fingerprinting | 14 | 14.0% |
| Audio fingerprinting | 3 | 3.0% |

Canvas fingerprinting was largely attributable to **bot-detection/security infrastructure** (Akamai challenge scripts on Adobe/Apple/Microsoft/Samsung, AWS WAF on Amazon, PerimeterX on LinkedIn), not advertising scripts — and **none** of these were flagged by EasyList/EasyPrivacy, since filter lists target ad/analytics infrastructure rather than first-party security code. Audio fingerprinting was concentrated entirely on `mail.ru`.

### 5. Test Case & Manual Inspection
Ran the full pipeline against `https://salim.webprivacylab.com/`: 37 total HTTP requests, **19 flagged** as tracking by the automated pipeline (Facebook Pixel ×4 IDs, GTM ×2 containers, Scorecard Research/comScore, NYT analytics, Iterate HQ, a first-party serverside GA proxy), and **15 additional suspicious-but-unflagged requests** identified via manual review — including a self-hosted Facebook Pixel script (`fb_direct.js`), a CNAME-cloaked tracking proxy (`fb_proxy.js` on an unlisted subdomain), cross-subdomain tracker hosting, and a first-party Conversions API endpoint representing fully invisible server-to-server tracking. These findings illustrate concrete evasion techniques — first-party self-hosting, CNAME cloaking, subdomain hosting, and server-side tracking — that structurally evade URL/domain-based filter list detection.

## Limitations

- Filter-list-based detection misses first-party self-hosted trackers, CNAME-cloaked domains, and server-to-server (Conversions API-style) tracking that never generates a browser-visible request.
- A 25-second per-page dwell time may not capture tracking triggered by longer sessions or specific user interactions.
- Sequential single-browser crawling and a 60s internal-page timeout led to incomplete internal-page coverage on 39 content-heavy sites (homepage data unaffected).
- Results reflect a single crawl snapshot (April 2026) and may not generalize across time or geography.

## Acknowledgments

- [OpenWPM](https://github.com/openwpm/OpenWPM) —> the underlying instrumentation framework
- [EasyList / EasyPrivacy / EasyList Germany](https://easylist.to/) —> filter lists used for tracker detection
- [Tranco](https://tranco-list.eu/) —> site ranking list used to select crawl targets
