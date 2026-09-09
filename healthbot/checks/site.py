#!/usr/bin/env python3

"""
Searches for a product, adds it to cart and loads checkout — outside-in,
through a real browser.

Ported from Selenium + geckodriver (pinned to a 2021 release that cannot
drive a current Firefox) to Playwright, which bundles its browsers:
`playwright install chromium` replaces the geckodriver download and the
distro Firefox entirely. Auto-waiting replaces the WebDriverWait
scaffolding, and a failure now leaves evidence — screenshot, page HTML and a
replayable trace under logs/ — instead of a bare False.
"""

# Standard imports
from datetime import UTC, datetime
from os import makedirs, path

# Third party imports
from playwright.sync_api import TimeoutError as PlaywrightTimeout
from playwright.sync_api import sync_playwright

# Local imports
from healthbot.api.logs import logger
from healthbot.settings import get_settings

DEFAULT_SEARCH_TERM = "blue shirt"
STEP_TIMEOUT_MS = 15_000


def validate_checkout(base_url: str, search_term: str = None, evidence_dir: str = None) -> bool:
    # A browser that fails to launch must report checkout as down, not
    # silently skip the check — "cannot tell" pages.
    try:
        return _validate_checkout(
            base_url,
            search_term or DEFAULT_SEARCH_TERM,
            evidence_dir or get_settings().log_dir,
        )
    except Exception as err:
        logger.exception(f"checkout validation could not run: {err!r}")
        return False


def _validate_checkout(base_url: str, search_term: str, evidence_dir: str) -> bool:
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context()
        context.tracing.start(screenshots=True, snapshots=True)
        page = context.new_page()
        page.set_default_timeout(STEP_TIMEOUT_MS)

        try:
            page.goto(base_url)

            search = page.locator("#search")
            search.fill(search_term)
            search.press("Enter")

            page.locator("h1.page-title").wait_for()
            grid = page.locator("div.products-grid")
            grid.locator(".product-item-photo").first.click()

            for attribute in ("color", "size"):
                swatch = page.locator(f"div.swatch-attribute.{attribute}")
                if swatch.count() > 0:
                    swatch.first.click()

            page.locator(".add-to-cart-title").first.click()

            # A/B test: either the recommended-products modal or the classic
            # cart modal appears
            try:
                page.locator(".recommended-products-modal-content").wait_for()
                page.locator("a.popup-button.primary").click()
            except PlaywrightTimeout:
                page.locator(".modal-inner-wrap").wait_for()
                page.locator("button.to-checkout").click()

            page.wait_for_url("**/checkout**")
            checkout_pass = "Checkout" in page.title()

            if not checkout_pass:
                _save_evidence(page, context, evidence_dir, "title-mismatch")
            return checkout_pass

        except Exception as err:
            logger.error(f"checkout journey failed: {err!r}")
            _save_evidence(page, context, evidence_dir, "failure")
            return False

        finally:
            context.close()
            browser.close()


def _save_evidence(page, context, evidence_dir: str, label: str) -> None:
    """
    When it fails you should learn more than that it failed: screenshot,
    page source and a trace replayable with `playwright show-trace`.
    """
    try:
        makedirs(evidence_dir, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        prefix = path.join(evidence_dir, f"checkout-{label}-{stamp}")
        page.screenshot(path=f"{prefix}.png", full_page=True)
        with open(f"{prefix}.html", "w") as fp:
            fp.write(page.content())
        context.tracing.stop(path=f"{prefix}-trace.zip")
        logger.error(f"checkout evidence saved: {prefix}.png/.html/-trace.zip")
    except Exception as err:  # evidence capture must never mask the result
        logger.error(f"could not save checkout evidence: {err!r}")


if __name__ == "__main__":
    logger.info("You called me directly :)")
