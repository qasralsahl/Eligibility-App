import asyncio
from playwright.async_api import (
    async_playwright,
    TimeoutError as PlaywrightTimeoutError,
)


def log(msg: str):
    print(f"[LOG] {msg}")


def error(msg: str):
    print(f"[ERROR] {msg}")


class NextCareEligibilityChecker:
    def __init__(self, username: str, password: str, headless: bool = True):
        self.username = username
        self.password = password
        self.headless = headless
        self.browser = None
        self.page = None

    async def _launch_browser(self):
        log("Launching Chromium browser in headless mode.")
        playwright = await async_playwright().start()
        self.browser = await playwright.chromium.launch(headless=self.headless)
        self.page = await self.browser.new_page()

    async def _login(self):
        url = "https://pulse-uae.nextcarehealth.com/Login2.aspx?ReturnUrl=%2F"
        try:
            log(f"Navigating to URL: {url}")
            await self.page.goto(url)

            log("Filling username field.")
            await self.page.locator('//*[@id="txtUserName"]').fill(self.username)

            log("Filling password field.")
            await self.page.locator('//*[@id="txtPassword"]').fill(self.password)

            log("Clicking login button.")
            await self.page.locator('//*[@id="btnLogin"]').click()

            log("Waiting for login to complete (networkidle).")
            await self.page.wait_for_load_state("networkidle")
        except Exception as e:
            error(f"Login step failed: {e}")
            raise

    async def _check_eligibility(self, eid: str):
        try:

            log("Navigating to Eligibility Checking page.")
            await self.page.locator('//*[@id="441240"]/a').click()
            await self.page.wait_for_load_state("networkidle")

            log("Clicking Other ID tab.")
            await self.page.locator('//*[@id="ulEligibilityTabs"]/div/label[3]').click()

            log(f"Entering Emirates ID: {eid}")
            await self.page.locator('//*[@id="txtIDTypeValue"]').fill(eid)

            log("Selecting Out Patient from dropdown.")
            await self.page.locator(
                '//*[@id="ctl00_ContentPlaceHolderBody_cmbType_chosen"]/a'
            ).click()
            await self.page.locator(
                '//*[@id="ctl00_ContentPlaceHolderBody_cmbType_chosen"]/div/ul/li[2]'
            ).click()

            log("Clicking Check Eligibility button.")
            await self.page.locator(
                '//*[@id="btnCheckEligibilityorSearchbyPolicy"]'
            ).click()
            await self.page.wait_for_load_state("networkidle")

            log("Fetching eligibility result.")
            result = await self.page.locator(
                '//*[@id="lblResultMessage1"]/b[1]'
            ).text_content()
            status = result.strip() if result else "Unknown"

            log(f"Member Status: {status}")
            return {"status": "success", "Is_Eligible": status}
        except Exception as e:
            error(f"Eligibility check failed: {e}")
            raise

    async def _save_artifacts(self, eid: str):
        try:
            log("Taking screenshot of the result page.")
            await self.page.screenshot(path=f"NextCare_{eid}.png")

            log("Exporting page as PDF.")
            await self.page.pdf(path=f"NextCare_{eid}.pdf", print_background=True)

            log(f"Saved screenshot and PDF for {eid}")
        except Exception as e:
            error(f"Failed to save screenshot or PDF: {e}")
            raise

    async def run_async(self, eid: str):
        try:
            await self._launch_browser()
            await self._login()
            result = await self._check_eligibility(eid)
            await self._save_artifacts(eid)
            # import pdb; pdb.set_trace()
            return result
        finally:
            if self.browser:
                log("Closing browser.")
                await self.browser.close()

    # def run(self, eid: str):
    #     """Sync wrapper so you can call from FastAPI without awaiting everywhere"""
    #     return asyncio.run(self.run_async(eid))
