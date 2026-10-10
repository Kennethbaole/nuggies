"""Exercise the local UI and save reference screenshots; optional Playwright."""

import argparse
import json
from pathlib import Path

from playwright.sync_api import sync_playwright, expect


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8765")
    parser.add_argument("--chrome", help="Optional installed Chromium/Chrome executable")
    parser.add_argument("--output", default="artifacts", help="Screenshot output directory")
    args = parser.parse_args()
    output = Path(args.output)
    output.mkdir(exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=args.chrome)
        context = browser.new_context(viewport={"width": 1440, "height": 1000}, device_scale_factor=1)
        page = context.new_page()
        page.add_init_script("""window.__spoken = []; if ('speechSynthesis' in window) {
          speechSynthesis.speak = utterance => window.__spoken.push(utterance.text);
          speechSynthesis.cancel = () => {};
        }""")
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(args.url)
        page.wait_for_selector('.slot[data-slot="0"]:not([disabled])')
        page.click("#reset")
        expect(page.locator("#screen-name")).to_have_text("CONVERSATION")
        page.click(".signal-details summary")
        page.click("#expand-signal")
        expect(page.locator("#expand-signal")).to_have_attribute("aria-pressed", "true")
        assert page.locator("#trace").bounding_box()["width"] > 1200
        page.keyboard.press("Escape")
        expect(page.locator("#expand-signal")).to_have_attribute("aria-pressed", "false")
        expect(page.locator("#screen-name")).to_have_text("CONVERSATION")
        page.select_option("#trial-label", "left")
        expect(page.locator("#trial-label")).to_have_value("left")
        page.click(".signal-details summary")
        page.keyboard.press("ArrowRight")
        expect(page.locator('[data-slot="1"]')).to_have_attribute("aria-pressed", "true")
        page.keyboard.press("Space")
        expect(page.locator("#center-text")).to_have_text("Thank you for being here with me.")
        assert page.locator("#phone-text").inner_text() == page.locator("#center-text").inner_text()
        hud = context.new_page(); hud.goto(args.url + "/hud")
        expect(hud.locator("#hud-status")).to_contain_text("Connected")
        assert hud.locator("#hud-only").is_visible()
        # More changes the five phrases without rotating the ring geometry.
        positions = page.locator(".slot").evaluate_all("nodes => nodes.map(n => [n.style.left,n.style.top])")
        page.click('[data-slot="6"]'); page.keyboard.press("Space")
        expect(page.locator('[data-slot="0"]')).to_have_text("Day")
        assert positions == page.locator(".slot").evaluate_all("nodes => nodes.map(n => [n.style.left,n.style.top])")
        page.click('[data-slot="7"]'); page.keyboard.press("Space")
        expect(page.locator("#screen-name")).to_have_text("SPELL YOUR WORDS")
        page.click('[data-slot="0"]'); page.keyboard.press("Space")
        expect(page.locator('[data-slot="0"]')).to_have_text("A–G")
        page.keyboard.press("Escape")
        expect(page.locator('[data-slot="0"]')).to_have_text("A–M")
        page.keyboard.press("Escape")
        expect(page.locator("#screen-name")).to_have_text("CONVERSATION")
        page.keyboard.press("Escape")
        expect(page.locator("#screen-name")).to_have_text("EVERYDAY NEEDS")
        assert page.locator("#center-text").inner_text() == "Give me a moment."
        page.click("#audio-toggle")
        page.click('[data-slot="0"]'); page.keyboard.press("Space")
        page.wait_for_timeout(500)
        assert page.evaluate("window.__spoken.length") == 1
        assert page.evaluate("window.__spoken[0]") == "I would like some water, please."
        page.keyboard.press("ArrowRight"); page.wait_for_timeout(350)
        assert page.evaluate("window.__spoken.length") == 1, "Highlight must not speak"
        page.click("#audio-toggle")
        page.click("#reset"); page.wait_for_timeout(350)
        page.click('[data-slot="3"]'); page.keyboard.press("Space")
        expect(page.locator("#center-text")).to_have_text("Could you stay with me for a little while?")
        page.wait_for_timeout(300)
        page.screenshot(path=str(output / "companion-desktop.png"), full_page=True)
        hud.wait_for_timeout(350)
        hud.screenshot(path=str(output / "hud-preview.png"))
        page.set_viewport_size({"width": 390, "height": 844})
        page.wait_for_timeout(200)
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), "Mobile page overflows horizontally"
        page.screenshot(path=str(output / "companion-mobile.png"), full_page=True)
        assert not errors, errors
        print(json.dumps(dict(ok=True, checks=["trial labeling", "navigation", "explicit selection", "phone mirror",
              "HUD shared state", "stationary ring", "fresh More page", "spell groups", "Back behavior",
              "browser speech fallback", "highlight stays silent", "mobile overflow", "no browser exceptions"], screenshots=str(output)), indent=2))
        browser.close()


if __name__ == "__main__":
    main()
