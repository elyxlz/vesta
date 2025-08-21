#!/usr/bin/env python3
# /// script
# dependencies = ["playwright", "asyncio"]
# ///

import asyncio
from playwright.async_api import async_playwright

async def fill_ef_form():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()
        
        # Navigate to the form
        url = "https://joinef.fillout.com/t/kcSR374PuAus?current_contacts=rec3IYXtS6w6a3Zj7%2CrecbDwPiuVBBp7noA%2CreceUJBm5GonKt6oC&company_name=Audiogen&company_id=rec7jO6NzeWFAjm7r&current_contact_names=Elio%20Pascarelli%2CEmilio%20Pascarelli%2CJacopo%20Madaluni"
        await page.goto(url)
        
        # Wait for the form to load
        await page.wait_for_load_state('networkidle')
        
        print("Form loaded. Please check the browser window.")
        print("The script will keep the browser open for you to fill and submit manually.")
        print("Press Ctrl+C to close when done.")
        
        # Keep browser open
        try:
            while True:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            await browser.close()

if __name__ == "__main__":
    asyncio.run(fill_ef_form())