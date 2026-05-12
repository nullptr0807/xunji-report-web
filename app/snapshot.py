"""Headless chromium → full-page JPG snapshot of a report."""
from __future__ import annotations
from pathlib import Path
from playwright.sync_api import sync_playwright


def snapshot_report(report_url: str, out_path: Path, viewport_width: int = 1080) -> Path:
    """Render report_url in headless chromium, save full-page JPG to out_path."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--no-sandbox"])
        ctx = browser.new_context(viewport={"width": viewport_width, "height": 1200}, device_scale_factor=2)
        page = ctx.new_page()
        page.goto(report_url, wait_until="networkidle", timeout=30000)
        # Wait for our explicit ready signal
        try:
            page.wait_for_function("document.body.dataset.ready === '1'", timeout=15000)
        except Exception:
            pass
        # Let chart animations settle
        page.wait_for_timeout(900)
        page.screenshot(path=str(out_path), full_page=True, type="jpeg", quality=88)
        browser.close()
    return out_path
