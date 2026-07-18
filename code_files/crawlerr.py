#crawlerr.py -> wpp s3

import csv
import time
from pathlib import Path
from selenium.webdriver import Firefox
from openwpm.command_sequence import CommandSequence
from openwpm.commands.types import BaseCommand
from openwpm.config import BrowserParams, BrowserParamsInternal, ManagerParams, ManagerParamsInternal
from openwpm.socket_interface import ClientSocket
from openwpm.storage.sql_provider import SQLiteStorageProvider
from openwpm.task_manager import TaskManager

#configs
INPUT_CSV = "top-1m.csv"
OUTPUT_DIR = Path("crawl_output")
DB_PATH = OUTPUT_DIR / "crawl-data.sqlite"
DWELL_TIME = 25 #seconds to stay on each page
MAX_INTERNAL = 5 #max internal links to follow
NUM_BROWSERS = 1
OUTPUT_DIR.mkdir(exist_ok=True)

#cookie banner command
class AcceptCookieBannerCommand(BaseCommand):
    #JS script to click common "accept cookies" buttons
    SCRIPT = """
    (function() {
        const selectors = [
            'button[id*="accept"]', 'button[class*="accept"]',
            'button[id*="agree"]', 'button[class*="agree"]',
            'button[id*="consent"]', 'button[class*="consent"]',
            'a[id*="accept"]', 'a[class*="accept"]',
            '#onetrust-accept-btn-handler',
            '.cc-accept', '.accept-cookies',
            '[data-testid="accept-button"]',
        ];
        for (const sel of selectors) {
            try {
                const el = document.querySelector(sel);
                if (el) { el.click(); return 'clicked: ' + sel; }
            } catch(e) {}
        }
        return 'no banner found';
    })();
    """

    def __init__(self):
        self.logger = None

    def __repr__(self):
        return "AcceptCookieBannerCommand"

    def execute(
        self,
        webdriver: Firefox,
        browser_params: BrowserParamsInternal,
        manager_params: ManagerParamsInternal,
        extension_socket: ClientSocket,
    ) -> None:
        try:
            result = webdriver.execute_script(self.SCRIPT)
            print(f"    Cookie banner: {result}")
        except Exception as e:
            print(f"    Cookie banner error: {e}")

#load sites
def load_sites(csv_path: str) -> list:
    sites = []
    with open(csv_path, newline="") as f:
        reader = csv.reader(f)
        for i, row in enumerate(reader):
            if i >= 100: #limit to first 100 sites
                break
            domain = row[1].strip().lower() if len(row) >= 2 else row[0].strip().lower()
            if not domain.startswith("http"):
                domain = "https://" + domain #ensure valid URL
            sites.append(domain)
    return sites

#main
def main():
    sites = load_sites(INPUT_CSV)
    print(f"[*] Loaded {len(sites)} sites from {INPUT_CSV}")

    manager_params = ManagerParams(num_browsers=NUM_BROWSERS)
    manager_params.data_directory = OUTPUT_DIR
    manager_params.log_path = OUTPUT_DIR / "openwpm.log"

    browser_params_list = []
    for _ in range(NUM_BROWSERS):
        bp = BrowserParams(display_mode="headless") #run browser headless
        bp.http_instrument = True
        bp.cookie_instrument = True
        bp.js_instrument = True
        bp.navigation_instrument = True
        bp.save_content = False
        browser_params_list.append(bp)

    storage = SQLiteStorageProvider(db_path=DB_PATH)

    with TaskManager(
        manager_params_temp=manager_params,
        browser_params_temp=browser_params_list,
        structured_storage_provider=storage,
        unstructured_storage_provider=None,
    ) as manager:

        for idx, site_url in enumerate(sites):
            print(f"[{idx+1}/{len(sites)}] Crawling: {site_url}")

            #fresh isolated profile per site
            cs = CommandSequence(site_url, site_rank=idx + 1, reset=True)

            #1.visit homepage and dwell
            cs.get(sleep=DWELL_TIME)

            #2.try to accept cookie banner
            cs.append_command(AcceptCookieBannerCommand(), timeout=10)

            #3.follow internal links and dwell
            cs.browse(num_links=MAX_INTERNAL, sleep=DWELL_TIME)

            manager.execute_command_sequence(cs)

    print(f"[+] Crawl complete. Database: {DB_PATH}")

if __name__ == "__main__":
    main()