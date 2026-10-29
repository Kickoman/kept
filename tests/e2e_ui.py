"""End-to-end UI smoke test (headless Chromium via Playwright). Not collected by pytest.

Usage: KEPT_BASE_URL=http://127.0.0.1:8000 python tests/e2e_ui.py
"""
import json, os, random, tempfile, time
from PIL import Image
from playwright.sync_api import sync_playwright

BASE = os.environ.get("KEPT_BASE_URL", "http://127.0.0.1:8000")
S = tempfile.mkdtemp(prefix="kept-ui-")
print("screenshots ->", S)
errors = []

def attach(page, name):
    page.on("console", lambda m: errors.append((name, m.type, m.text)) if m.type in ("error", "warning") else None)
    page.on("pageerror", lambda e: errors.append((name, "pageerror", str(e))))
    page.on("requestfailed", lambda r: errors.append((name, "requestfailed", r.url)) if "fonts.g" not in r.url and "unpkg" not in r.url else None)

Image.new("RGB", (900, 600), (120, 90, 200)).save(f"{S}/test.png")

with sync_playwright() as p:
    browser = p.chromium.launch()
    owner = browser.new_context(viewport={"width": 1200, "height": 900})
    page = owner.new_page(); attach(page, "owner")
    page.goto(BASE + "/"); page.wait_for_selector("section.hero h1")
    page.screenshot(path=f"{S}/01_landing.png", full_page=True)
    page.click("text=Start a list")
    page.wait_for_selector("form.auth-card")
    u = f"sam{random.randint(1000,9999)}"
    page.fill("#display_name", "Sam Okonjo"); page.fill("#username", u); page.fill("#password", "password123")
    page.screenshot(path=f"{S}/02_register.png")
    page.click("button[type=submit]")
    page.wait_for_url("**/me"); page.wait_for_selector(".grid-cards")
    page.click("text=New list")
    page.fill("#nl-title", "Sam's list"); page.fill("#nl-desc", "Birthday's in October, so nothing here is urgent. Claim anything you like — I can't see who took what.")
    page.click("button:has-text('Create list')")
    page.wait_for_url("**/lists/*/edit"); page.wait_for_selector(".linkbar")
    page.fill(".linkbar input", "https://example.com/")
    page.click(".linkbar button")
    page.wait_for_selector(".dialog")
    page.wait_for_selector(".dialog .reading", state="hidden", timeout=30000)
    time.sleep(0.3)
    print("enriched title:", page.input_value("#it-title"))
    page.screenshot(path=f"{S}/03_add_dialog.png")
    page.fill("#it-title", "Fellow Ode coffee grinder")
    page.fill("#it-desc", "The one with the dial, not the buttons.")
    page.click(".dialog button[type=submit]")
    page.wait_for_selector(".dialog", state="hidden")
    # text with a link inside: words become the title, the link is read for description/photo
    page.fill(".linkbar input", "Кружки для кофе https://example.com/cups."); page.press(".linkbar input", "Enter")
    page.wait_for_selector(".dialog"); page.wait_for_selector(".dialog .reading", state="hidden", timeout=30000); time.sleep(0.3)
    assert page.input_value("#it-title") == "Кружки для кофе", page.input_value("#it-title")
    assert "example.com" in page.locator(".dialog .linkline").inner_text()
    page.click(".dialog button:has-text('Cancel')"); page.wait_for_selector(".dialog", state="hidden")
    page.fill(".linkbar input", "Linen napkins"); page.press(".linkbar input", "Enter")
    page.wait_for_selector(".dialog")
    page.fill("#it-desc", "Sets of four; two sets would be perfect.")
    page.click(".dialog .stepper .btn >> nth=1")
    page.click(".dialog button[type=submit]"); page.wait_for_selector(".dialog", state="hidden")
    page.fill(".linkbar input", "Chemex filters, 100 pack"); page.press(".linkbar input", "Enter")
    page.wait_for_selector(".dialog")
    page.click(".dialog .stepper .btn:has-text('∞')")
    page.set_input_files(".dialog input[type=file]", f"{S}/test.png")
    page.wait_for_selector(".dialog .thumb img")
    page.click(".dialog button[type=submit]"); page.wait_for_selector(".dialog", state="hidden")
    page.wait_for_selector(".edit-row >> nth=2 >> img")
    assert page.locator(".edit-row").count() == 3
    page.screenshot(path=f"{S}/04_edit.png", full_page=True)
    share_url = page.get_attribute(".share-box .input", "title")
    print("share:", share_url)
    guest = browser.new_context(viewport={"width": 1200, "height": 900})
    g = guest.new_page(); attach(g, "guest")
    g.goto(share_url); g.wait_for_selector(".rows .row")
    assert g.locator(".row").count() == 3
    g.screenshot(path=f"{S}/05_guest.png", full_page=True)
    g.locator(".row").nth(1).locator(".row-main").click()
    g.wait_for_selector(".dialog .detail")
    g.screenshot(path=f"{S}/06_detail.png")
    # anonymous guest: claim dialog explains a sign-in is needed, then redirects and finishes the claim after registration
    g.click(".dialog .btn-claim")
    g.wait_for_selector("#cl-note")
    assert "Sign in" in g.locator(".dialog").inner_text()
    g.fill("#cl-note", "Bringing the washed-linen ones from Toast.")
    g.screenshot(path=f"{S}/07_claim.png")
    g.click(".dialog button[type=submit]")
    g.wait_for_url("**/login?next=*"); g.wait_for_selector("form.auth-card .banner")
    g.click("a:has-text('Create one')"); g.wait_for_url("**/register?next=*")
    anika = f"anika{random.randint(1000,9999)}"
    g.fill("#display_name", "Anika"); g.fill("#username", anika); g.fill("#password", "password123")
    g.click("button[type=submit]")
    g.wait_for_url("**/w/*"); g.wait_for_selector("text=Reserved by you")
    g.locator(".row").nth(0).locator(".btn-claim").click()
    g.wait_for_selector("#cl-note"); g.click(".dialog button[type=submit]"); g.wait_for_selector(".toast")
    g.wait_for_selector(".row.is-claimed")
    g.screenshot(path=f"{S}/08_guest_claimed.png", full_page=True)
    g.click("label.seg-opt:has-text('Reserved')")
    assert g.locator(".row").count() == 1
    g.click("label.seg-opt:has-text('All')")
    # a stale page picks up a claim made elsewhere when it becomes visible again, and refuses to double-claim
    watcher = browser.new_context(viewport={"width": 1200, "height": 900}).new_page(); attach(watcher, "watcher")
    watcher.goto(share_url); watcher.wait_for_selector(".rows .row")
    assert "Reserve" in watcher.locator(".row").nth(2).locator(".btn-claim").inner_text()
    g.locator(".row").nth(2).locator(".btn-claim").click(); g.wait_for_selector("#cl-note"); g.click(".dialog button[type=submit]"); g.wait_for_selector(".toast")
    watcher.evaluate("() => { Object.defineProperty(document, 'visibilityState', { value: 'visible', configurable: true }); document.dispatchEvent(new Event('visibilitychange')); }")
    watcher.wait_for_selector(".row >> nth=2 >> text=reserved")
    watcher.locator(".row").nth(2).locator(".btn-claim").click()  # unlimited item: still claimable -> dialog opens
    watcher.wait_for_selector("#cl-note"); watcher.keyboard.press("Escape")
    g.locator(".row").nth(2).locator(".row-main").click(); g.wait_for_selector(".dialog .detail")  # unlimited items are undone from the detail card
    g.click(".dialog button:has-text('Undo')"); g.wait_for_selector(".toast")
    g.locator(".row.is-claimed button:has-text('Undo')").click(); g.wait_for_selector(".toast")
    g.wait_for_selector(".row.is-claimed", state="hidden")
    # profile: change password, then sign in again with it
    g.goto(BASE + "/me"); g.click("button[title='Profile']"); g.wait_for_selector("#pf-cur")
    g.fill("#pf-cur", "password123"); g.fill("#pf-new", "newpassword1")
    g.screenshot(path=f"{S}/07b_profile.png")
    g.click(".dialog button:has-text('Change password')"); g.wait_for_selector(".toast")
    g.click("nav a:has-text('Sign out')"); g.wait_for_url(BASE + "/")
    g.goto(BASE + "/login"); g.fill("#username", anika); g.fill("#password", "newpassword1"); g.click("button[type=submit]")
    g.wait_for_url("**/me")
    g2 = browser.new_context(viewport={"width": 390, "height": 800}).new_page(); attach(g2, "guest2")
    g2.goto(share_url); g2.wait_for_selector(".rows .row")
    assert "Anika" not in g2.content()  # other guests never see who claimed
    assert "1 of 2 reserved" in g2.locator(".row").nth(1).inner_text()
    assert g2.locator(".made-with a").get_attribute("href") == "/"
    g2.screenshot(path=f"{S}/09_mobile.png", full_page=True)
    g2.locator(".row").nth(1).locator(".btn-claim").click(); g2.wait_for_selector("#cl-note")
    g2.screenshot(path=f"{S}/10_mobile_claim.png")
    page.goto(share_url); page.wait_for_selector(".banner")
    assert page.locator(".row.is-claimed").count() == 0 and "Anika" not in page.content()
    page.screenshot(path=f"{S}/11_owner_preview.png", full_page=True)
    assert page.locator("#how").count() == 0 and page.locator(".note").count() == 0
    page.goto(BASE + "/me"); page.select_option(".lang-switch", "ru"); page.wait_for_selector("text=Мои списки")
    page.screenshot(path=f"{S}/12_ru.png")
    page.select_option(".lang-switch", "be"); page.wait_for_selector("text=Мае спісы")
    page.goto(BASE + "/"); page.wait_for_url("**/be/"); page.wait_for_selector("text=Проста вішліст.")  # saved choice wins
    page.screenshot(path=f"{S}/13_be.png")
    page.select_option(".lang-switch", "en"); page.wait_for_url(BASE + "/"); page.wait_for_selector("text=Just a wishlist.")
    # first visit to "/": the browser language decides, a Russian browser in Minsk gets Belarusian, the switcher overrides both
    for locale, tz, want in [("ru-RU", "Europe/Moscow", "/ru/"), ("ru-RU", "Europe/Minsk", "/be/"), ("en-US", "Europe/Minsk", "/")]:
        v = browser.new_context(locale=locale, timezone_id=tz).new_page(); attach(v, f"visitor-{locale}-{tz}")
        v.goto(BASE + "/"); v.wait_for_selector("nav.nav")
        assert v.url == BASE + want, (locale, tz, v.url)
        if want == "/be/":
            v.select_option(".lang-switch", "ru"); v.wait_for_url("**/ru/")
            v.goto(BASE + "/"); v.wait_for_url("**/ru/"); v.wait_for_selector("text=Просто вишлист.")
            v.screenshot(path=f"{S}/13b_ru_landing.png", full_page=True)
        v.context.close()
    # theme: follows the OS by default, the switch overrides and persists
    bg = lambda pg: pg.evaluate("getComputedStyle(document.body).backgroundColor")
    page.emulate_media(color_scheme="light"); page.goto(BASE + "/me"); page.wait_for_selector(".grid-cards")
    assert bg(page) == "rgb(245, 246, 250)", bg(page)
    page.screenshot(path=f"{S}/17_light_system.png", full_page=True)
    page.click(".theme-switch"); assert bg(page) == "rgb(245, 246, 250)"  # explicit light
    page.click(".theme-switch"); assert bg(page) == "rgb(22, 24, 38)"      # explicit dark overrides the OS
    page.reload(); page.wait_for_selector(".grid-cards"); assert bg(page) == "rgb(22, 24, 38)"  # persisted, no flash
    page.click(".theme-switch"); assert bg(page) == "rgb(245, 246, 250)"  # back to system (light)
    page.emulate_media(color_scheme="dark"); page.reload(); page.wait_for_selector(".grid-cards"); assert bg(page) == "rgb(22, 24, 38)"
    page.emulate_media(color_scheme="light")
    for name, url in (("18_light_edit", f"{BASE}/lists/1/edit"), ("19_light_share", share_url)):
        page.goto(url); page.wait_for_selector(".nav"); page.wait_for_timeout(600); page.screenshot(path=f"{S}/{name}.png", full_page=True)
    g2.emulate_media(color_scheme="light"); g2.goto(share_url); g2.wait_for_selector(".rows .row"); g2.locator(".row").nth(1).locator(".btn-claim").click(); g2.wait_for_selector("#cl-note"); g2.screenshot(path=f"{S}/21_light_mobile_claim.png")
    page.emulate_media(color_scheme="dark"); g2.emulate_media(color_scheme="dark")
    # admin (server must run with ADMIN_USERNAMES containing "adminsmoke")
    adm = browser.new_context(viewport={"width": 1280, "height": 900}).new_page(); attach(adm, "admin")
    adm.goto(BASE + "/register"); adm.wait_for_selector("form.auth-card")
    adm.fill("#display_name", "Admin Smoke"); adm.fill("#username", f"adminsmoke{random.randint(1000,9999)}" if False else "adminsmoke"); adm.fill("#password", "password123")
    adm.click("button[type=submit]"); adm.wait_for_url("**/me")
    adm.click("nav a:has-text('Admin')"); adm.wait_for_selector(".grid-stats .card")
    adm.wait_for_selector("table.table")
    assert u in adm.locator("table.table").inner_text()
    adm.screenshot(path=f"{S}/14_admin_users.png", full_page=True)
    adm.emulate_media(color_scheme="light"); adm.wait_for_timeout(300); adm.screenshot(path=f"{S}/20_light_admin.png", full_page=True); adm.emulate_media(color_scheme="dark")
    # AI settings tab saves, and a configured image provider shows the "Generate photo" button in the item dialog
    adm.click("label.seg-opt:text-is('AI')"); adm.wait_for_selector("#ai-text")
    adm.select_option("#ai-image", "yandex"); adm.fill("#ai-ykey", "AQVNfakekey1234"); adm.fill("#ai-yfolder", "b1gfake")
    adm.click("button:has-text('Save')"); adm.wait_for_selector(".toast"); adm.wait_for_selector("text=…1234")
    adm.screenshot(path=f"{S}/22_admin_ai.png", full_page=True)
    page.goto(BASE + "/lists/1/edit"); page.wait_for_selector(".edit-row img")
    media_name = page.locator(".edit-row img").first.get_attribute("src").split("/media/")[1]
    page.route("**/api/ai/image", lambda route: route.fulfill(status=200, content_type="application/json", body=json.dumps({"image_url": f"/media/{media_name}", "image_path": media_name})))
    page.fill(".linkbar input", "Generated thing"); page.press(".linkbar input", "Enter"); page.wait_for_selector(".dialog")
    page.click(".dialog button:has-text('Generate photo')"); page.wait_for_selector(".dialog .thumb img")
    page.click(".dialog button[type=submit]"); page.wait_for_selector(".dialog", state="hidden")
    assert page.locator(".edit-row").count() == 4 and page.locator(".edit-row img").count() == 2
    adm.select_option("#ai-image", "none"); adm.click("button:has-text('Save')"); adm.wait_for_selector(".toast")
    adm.click("label.seg-opt:has-text('Users')"); adm.wait_for_selector("table.table th:has-text('Sessions')")
    adm.click("label.seg-opt:has-text('Lists')"); adm.wait_for_selector("table.table td.link:has-text('Sam')")
    adm.locator("table.table td.link").first.click(); adm.wait_for_selector(".dialog .detail-list")
    assert "Anika" in adm.locator(".dialog").inner_text()  # admin sees guest claims
    adm.screenshot(path=f"{S}/15_admin_list_detail.png")
    adm.keyboard.press("Escape")
    adm.click("label.seg-opt:has-text('Reservations')"); adm.wait_for_selector("table.table th:has-text('Guest')")
    assert "Anika" in adm.locator("table.table").inner_text()
    adm.click("label.seg-opt:has-text('Lists')"); adm.wait_for_selector("table.table th:has-text('Owner')")
    adm.locator("table.table .actions .btn-danger").first.click(); adm.wait_for_selector(".dialog")
    adm.click(".dialog .btn-danger"); adm.wait_for_selector(".toast")
    adm.wait_for_selector(".table-wrap .empty")
    adm.set_viewport_size({"width": 390, "height": 800}); adm.click("label.seg-opt:has-text('Users')"); adm.wait_for_selector("table.table th:has-text('Sessions')")
    adm.screenshot(path=f"{S}/16_admin_mobile.png", full_page=True)
    assert page.goto(BASE + "/admin") and page.wait_for_selector("text=administrators only")
    browser.close()
real = [e for e in errors if "401" not in e[2]]
print("console/network issues:", json.dumps(real, indent=1, ensure_ascii=False) if real else "none")
print("OK")
