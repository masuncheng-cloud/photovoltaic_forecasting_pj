#!/usr/bin/env python3
"""Take screenshots of the PV forecasting dashboard at various stages."""

import asyncio
import os
from pathlib import Path

from playwright.async_api import async_playwright

OUTPUT_DIR = Path("/home/ac/data16t/msc/photovoltaic_forecasting_pj/output/pv_pipeline")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

DASHBOARD_URL = "http://127.0.0.1:8072/stages/05_visualization/interactive_forecast_dashboard.html?v=round40"


async def force_reload(page):
    """Force reload to clear cache."""
    await page.goto("about:blank")
    await asyncio.sleep(0.5)
    await page.evaluate("""() => {
        // Clear service worker cache
        if ('caches' in window) {
            caches.keys().then(names => {
                names.forEach(name => caches.delete(name));
            });
        }
    }""")
    await page.goto(DASHBOARD_URL, wait_until="networkidle", timeout=30000)
    await asyncio.sleep(3)


async def set_date_range(page, start_date, end_date):
    """Set date range inputs."""
    # Try various possible selectors for date inputs
    date_selectors = [
        'input[type="date"]',
        'input[name*="start"]',
        'input[name*="Start"]',
        'input[id*="start"]',
        'input[id*="Start"]',
        '.date-input input',
        '.date-range input:first-child',
        'input.start-date',
        'input[data-testid*="start"]',
    ]
    start_input = None
    for sel in date_selectors:
        try:
            inp = page.locator(sel).first
            if await inp.count() > 0:
                start_input = inp
                break
        except Exception:
            pass

    end_selectors = [
        'input[type="date"]',
        'input[name*="end"]',
        'input[name*="End"]',
        'input[id*="end"]',
        'input[id*="End"]',
        '.date-input input',
        '.date-range input:last-child',
        'input.end-date',
        'input[data-testid*="end"]',
    ]
    end_input = None
    for sel in end_selectors:
        try:
            inp = page.locator(sel).first
            if await inp.count() > 0:
                end_input = inp
                break
        except Exception:
            pass

    if start_input:
        await start_input.fill(start_date)
        print(f"  Set start date: {start_date}")
    if end_input:
        await end_input.fill(end_date)
        print(f"  Set end date: {end_date}")


async def set_hours(page, start_hour, end_hour):
    """Set hour range."""
    hour_selectors = [
        'input[type="range"]',
        'input.hour-slider',
        'input[data-hour]',
        '.hour-input input',
        'input[name*="hour"]',
    ]
    range_inputs = page.locator('input[type="range"]')
    count = await range_inputs.count()
    if count >= 2:
        await range_inputs.nth(0).fill(str(start_hour))
        await range_inputs.nth(1).fill(str(end_hour))
        print(f"  Set hours: {start_hour}-{end_hour}")
    else:
        # Try filling by label
        labels = await page.locator('label, span').all_text_contents()
        for i, label in enumerate(labels):
            if 'hour' in label.lower() or '小时' in label:
                print(f"  Found hour label: {label}")


async def get_page_inputs_info(page):
    """Debug: print all inputs on the page."""
    inputs = await page.locator('input').all()
    print(f"\n  Found {len(inputs)} input elements:")
    for i, inp in enumerate(inputs):
        try:
            inp_type = await inp.get_attribute('type')
            inp_name = await inp.get_attribute('name')
            inp_id = await inp.get_attribute('id')
            inp_class = await inp.get_attribute('class')
            placeholder = await inp.get_attribute('placeholder')
            value = await inp.get_attribute('value')
            print(f"  [{i}] type={inp_type}, name={inp_name}, id={inp_id}, class={inp_class}, placeholder={placeholder}, value={value}")
        except Exception as e:
            print(f"  [{i}] error: {e}")


async def get_buttons_info(page):
    """Debug: print all buttons on the page."""
    buttons = await page.locator('button').all()
    print(f"\n  Found {len(buttons)} button elements:")
    for i, btn in enumerate(buttons):
        try:
            btn_text = await btn.inner_text()
            btn_class = await btn.get_attribute('class')
            btn_id = await btn.get_attribute('id')
            disabled = await btn.get_attribute('disabled')
            print(f"  [{i}] text={btn_text.strip()[:50]}, class={btn_class}, id={btn_id}, disabled={disabled}")
        except Exception as e:
            print(f"  [{i}] error: {e}")


async def get_selects_info(page):
    """Debug: print all select elements on the page."""
    selects = await page.locator('select').all()
    print(f"\n  Found {len(selects)} select elements:")
    for i, sel in enumerate(sels):
        try:
            sel_id = await sel.get_attribute('id')
            sel_class = await sel.get_attribute('class')
            sel_name = await sel.get_attribute('name')
            options_count = await sel.locator('option').count()
            print(f"  [{i}] id={sel_id}, class={sel_class}, name={sel_name}, options={options_count}")
        except Exception as e:
            print(f"  [{i}] error: {e}")


async def take_screenshot(page, name, full_page=True):
    """Take a screenshot and save it."""
    path = OUTPUT_DIR / name
    await page.screenshot(path=str(path), full_page=full_page)
    print(f"  Saved: {path}")
    return path


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
        context = await browser.new_context(viewport={"width": 1920, "height": 1080})
        page = await context.new_page()

        # Block unnecessary resources to speed up
        await context.route("**.{png,jpg,jpeg,gif,svg,ico,webp,woff,woff2,ttf,otf}", lambda route: route.abort())
        await context.route("**/favicon*", lambda route: route.abort())

        print("=" * 80)
        print("Step 1: Load dashboard with force reload")
        print("=" * 80)
        await force_reload(page)
        await asyncio.sleep(3)

        # Debug: inspect page
        await get_page_inputs_info(page)
        await get_buttons_info(page)
        await get_selects_info(page)

        print("\n" + "=" * 80)
        print("Step 2: City-level view (全市模式)")
        print("=" * 80)

        # Try to find and click 全市 mode button
        city_buttons = page.locator('button')
        city_btn_found = False
        for i, btn in enumerate(await city_buttons.all()):
            try:
                text = (await btn.inner_text()).strip()
                if '全市' in text or 'city' in text.lower():
                    await btn.click()
                    city_btn_found = True
                    print(f"  Clicked city mode button: {text}")
                    break
            except Exception:
                pass

        await asyncio.sleep(2)

        # Set date range
        print("  Setting date range 2025-09-01 to 2025-12-31...")
        await set_date_range(page, "2025-09-01", "2025-12-31")
        await asyncio.sleep(1)

        # Set hours
        print("  Setting hours 06:00 to 19:00...")
        await set_hours(page, 6, 19)
        await asyncio.sleep(1)

        # Wait for chart to update
        await asyncio.sleep(3)

        await take_screenshot(page, "round40_city_view.png")
        await TodoWrite(
            merge=True,
            todos=[{"id": "2", "status": "completed"}]
        )

        print("\n" + "=" * 80)
        print("Step 3: City-level seasonal best days (全市四季最佳日)")
        print("=" * 80)

        # Find and click 全市四季最佳日 button
        seasons = {
            "spring": ("春季", "round40_city_spring_best.png"),
            "summer": ("夏季", "round40_city_summer_best.png"),
            "autumn": ("秋季", "round40_city_autumn_best.png"),
            "winter": ("冬季", "round40_city_winter_best.png"),
        }

        # First find the tab/button for 全市四季最佳日
        best_days_btn_found = False
        for i, btn in enumerate(await city_buttons.all()):
            try:
                text = (await btn.inner_text()).strip()
                if '四季最佳' in text or 'best day' in text.lower():
                    await btn.click()
                    best_days_btn_found = True
                    print(f"  Clicked 四季最佳日 button: {text}")
                    break
            except Exception:
                pass

        await asyncio.sleep(2)

        for season_key, (season_text, filename) in seasons.items():
            print(f"\n  Setting season: {season_text}...")
            season_btn_found = False
            for i, btn in enumerate(await city_buttons.all()):
                try:
                    text = (await btn.inner_text()).strip()
                    if season_text in text:
                        await btn.click()
                        season_btn_found = True
                        print(f"    Clicked season button: {text}")
                        break
                except Exception:
                    pass

            if not season_btn_found:
                print(f"    Season button '{season_text}' not found, trying JS click...")
                # Try clicking by text content
                await page.evaluate(f"""
                    () => {{
                        const btns = Array.from(document.querySelectorAll('button'));
                        const target = btns.find(b => b.textContent.includes('{season_text}'));
                        if (target) target.click();
                    }}
                """)

            await asyncio.sleep(3)
            await take_screenshot(page, filename)

        await TodoWrite(
            merge=True,
            todos=[{"id": "3", "status": "completed"}]
        )

        print("\n" + "=" * 80)
        print("Step 4: Single-site seasonal best days (单站点四季最佳日)")
        print("=" * 80)

        # Switch to single-site mode
        single_site_btns = page.locator('button')
        for i, btn in enumerate(await single_site_btns.all()):
            try:
                text = (await btn.inner_text()).strip()
                if '单站' in text or 'single' in text.lower() or '站点' in text:
                    await btn.click()
                    print(f"  Clicked single-site mode button: {text}")
                    break
            except Exception:
                pass

        await asyncio.sleep(2)

        # Select site S062
        print("  Selecting site S062...")
        select_found = False
        for i, sel in enumerate(await page.locator('select').all()):
            try:
                sel_id = await sel.get_attribute('id')
                sel_class = await sel.get_attribute('class')
                options = await sel.locator('option').all_text_contents()
                # Check if S062 or similar is in options
                if any('S062' in opt or '062' in opt for opt in options):
                    await sel.select_option('S062')
                    select_found = True
                    print(f"    Selected S062 from select #{i} (id={sel_id}, class={sel_class})")
                    break
            except Exception as e:
                print(f"    Error selecting from select #{i}: {e}")

        if not select_found:
            # Try by text
            await page.evaluate("""
                () => {
                    const selects = Array.from(document.querySelectorAll('select'));
                    for (const sel of selects) {
                        const opts = Array.from(sel.options);
                        const target = opts.find(o => o.textContent.includes('S062') || o.textContent.includes('062'));
                        if (target) {
                            sel.value = target.value;
                            sel.dispatchEvent(new Event('change', { bubbles: true }));
                            break;
                        }
                    }
                }
            """)
            print("    Tried selecting S062 via JS")

        await asyncio.sleep(2)

        # Switch to 四季最佳日 for single site
        for i, btn in enumerate(await single_site_btns.all()):
            try:
                text = (await btn.inner_text()).strip()
                if '四季最佳' in text or 'best day' in text.lower():
                    await btn.click()
                    print(f"  Clicked 四季最佳日 for single site: {text}")
                    break
            except Exception:
                pass

        await asyncio.sleep(2)

        for season_key, (season_text, filename) in seasons.items():
            print(f"\n  Setting season: {season_text}...")
            season_btn_found = False
            for i, btn in enumerate(await single_site_btns.all()):
                try:
                    text = (await btn.inner_text()).strip()
                    if season_text in text:
                        await btn.click()
                        season_btn_found = True
                        print(f"    Clicked season button: {text}")
                        break
                except Exception:
                    pass

            if not season_btn_found:
                print(f"    Season button '{season_text}' not found, trying JS click...")
                await page.evaluate(f"""
                    () => {{
                        const btns = Array.from(document.querySelectorAll('button'));
                        const target = btns.find(b => b.textContent.includes('{season_text}'));
                        if (target) target.click();
                    }}
                """)

            await asyncio.sleep(3)
            await take_screenshot(page, filename)

        await TodoWrite(
            merge=True,
            todos=[{"id": "4", "status": "completed"}]
        )

        print("\n" + "=" * 80)
        print("All screenshots taken!")
        print("=" * 80)
        print(f"\nSaved to: {OUTPUT_DIR}")
        for f in sorted(OUTPUT_DIR.glob("round40_*.png")):
            print(f"  {f}")

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
