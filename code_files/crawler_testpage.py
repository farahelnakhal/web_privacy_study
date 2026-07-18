#crawler_testpage.py-> wpp s9

from pathlib import Path

from selenium.webdriver import Firefox

from openwpm.command_sequence import CommandSequence
from openwpm.commands.types import BaseCommand
from openwpm.config import BrowserParams, BrowserParamsInternal, ManagerParams, ManagerParamsInternal
from openwpm.socket_interface import ClientSocket
from openwpm.storage.sql_provider import SQLiteStorageProvider
from openwpm.task_manager import TaskManager

#test page url
TEST_URL = "https://salim.webprivacylab.com/"

#output configuration
OUTPUT_DIR = Path("crawl_output_testpage")
DB_PATH = OUTPUT_DIR / "crawl-data.sqlite"
DWELL_TIME = 30 #time spent on page

OUTPUT_DIR.mkdir(exist_ok=True)

#cookie banner auto-click command
class AcceptCookieBannerCommand(BaseCommand):
    SCRIPT = """
    (function() {
        const selectors = [
            'button[id*="accept"]', 'button[class*="accept"]',
            'button[id*="agree"]', 'button[class*="agree"]',
            'button[id*="consent"]', 'button[class*="consent"]',
            '#onetrust-accept-btn-handler',
            '.cc-accept', '.accept-cookies',
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

    def __repr__(self):
        return "AcceptCookieBannerCommand"

    #run script inside browser context
    def execute(self, webdriver: Firefox, browser_params: BrowserParamsInternal,
                manager_params: ManagerParamsInternal, extension_socket: ClientSocket) -> None:
        try:
            print(f"    Cookie banner: {webdriver.execute_script(self.SCRIPT)}")
        except Exception as e:
            print(f"    Cookie banner error: {e}")

#manager configuration
manager_params = ManagerParams(num_browsers=1)
manager_params.data_directory = OUTPUT_DIR
manager_params.log_path = OUTPUT_DIR / "openwpm.log"

#browser configuration (headless crawl)
browser_params = [BrowserParams(display_mode="headless")]
for bp in browser_params:
    bp.http_instrument = True
    bp.cookie_instrument = True
    bp.js_instrument = True
    bp.navigation_instrument = True
    bp.save_content = False

#sqlite storage backend
storage = SQLiteStorageProvider(db_path=DB_PATH)

#run single-page crawl
with TaskManager(
    manager_params_temp=manager_params,
    browser_params_temp=browser_params,
    structured_storage_provider=storage,
    unstructured_storage_provider=None,
) as manager:

    cs = CommandSequence(TEST_URL, site_rank=1, reset=True)

    #load page and wait
    cs.get(sleep=DWELL_TIME)

    #attempt cookie acceptance
    cs.append_command(AcceptCookieBannerCommand(), timeout=10)

    manager.execute_command_sequence(cs)

print(f"[+] Test page crawl complete. DB: {DB_PATH}")