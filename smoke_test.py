# smoke_test.py – CPT Canteen Pre-Order afternoon-slot & workflow smoke test
# Run: pip install playwright && python -m playwright install chromium && python smoke_test.py

import re
import time
from playwright.sync_api import sync_playwright, expect

BASE = "http://127.0.0.1:5000"


def test_all():
    suffix = str(int(time.time()))[-5:]
    student_id = f"50112{suffix}"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, slow_mo=250)
        ctx = browser.new_context()
        page = ctx.new_page()
        results = []

        # ── STEP 1: Login page + Afternoon Banner ─────────────────────────
        page.goto(f"{BASE}/login")
        page.wait_for_load_state("networkidle")
        assert page.locator(".notice-banner").is_visible()
        assert "12:00 PM" in page.locator(".notice-banner").inner_text()
        assert "2:30 PM" in page.locator(".notice-banner").inner_text()
        assert page.locator("input[name='remember']").is_visible()
        assert page.locator(".demo").count() == 0
        results.append("STEP 1 – Login page & afternoon banner: ✅ PASS")
        print(results[-1])

        # ── STEP 2: Register Student (no auto-login, 0 wallet) ────────────
        page.goto(f"{BASE}/register")
        page.locator("input[name='name']").fill("Smoke Student")
        page.locator("input[name='login_id']").fill(student_id)
        page.locator("input[name='password']").fill("pass1234")
        page.locator("button[type='submit']").click()
        page.wait_for_url(f"{BASE}/login")
        assert "account created successfully" in page.locator(".alert.ok").inner_text().lower()
        results.append("STEP 2 – Student registration: ✅ PASS")
        print(results[-1])

        # ── STEP 3: Admin setup (add wallet, set slot max_orders=1, disable cutoff for test) ──
        page.locator("input[name='login_id']").fill("admin")
        page.locator("input[name='password']").fill("admin123")
        page.locator("button[type='submit']").click()
        page.wait_for_url(f"{BASE}/admin")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(1000)

        # Ensure cutoff is disabled during afternoon-agnostic smoke test
        cutoff_cb = page.locator("#set-cutoff")
        if cutoff_cb.is_checked():
            cutoff_cb.uncheck()
        page.locator("#settings-form button[type='submit']").click()
        page.wait_for_timeout(800)

        # Set first slot max_orders to 1 to test overbooking prevention
        first_cap = page.locator("input[data-cap]").first
        first_cap.fill("1")
        first_cap.dispatch_event("change")
        page.wait_for_timeout(800)

        # Add ₹200 to the new student's wallet
        page.locator(f"tr:has-text('{student_id}') input[data-wallet-amt]").fill("200")
        page.locator(f"tr:has-text('{student_id}') button[data-add-wallet]").click()
        page.wait_for_timeout(800)

        page.locator("form[action='/logout'] button").click()
        page.wait_for_url(f"{BASE}/login")
        results.append("STEP 3 – Admin slot capacity & wallet setup: ✅ PASS")
        print(results[-1])

        # ── STEP 4: Student order + confirmation alert + QR modal ─────────
        page.locator("input[name='login_id']").fill(student_id)
        page.locator("input[name='password']").fill("pass1234")
        page.locator("button[type='submit']").click()
        page.wait_for_url(f"{BASE}/student")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(1200)

        assert page.locator("#afternoon-banner").is_visible()
        assert "200" in page.locator("#wallet-chip").inner_text()

        page.locator(".dish", has_text="Ghee Masala Dosa").locator("button[data-inc]").click()
        page.locator("button[data-slot]:not([disabled])").first.click()
        page.locator("input[name='pay'][value='Wallet']").click()

        page.once("dialog", lambda d: d.accept())
        page.locator("#pay-btn").click()

        qr_modal = page.locator("#qr-modal")
        expect(qr_modal).not_to_have_class(re.compile(r"hidden"), timeout=5000)
        order_id = page.locator("#qr-title").inner_text().replace("Pickup pass · ", "").strip()
        page.locator("button[data-close]").click()
        page.wait_for_timeout(600)

        # First slot (max_orders=1) should now show Full and be disabled (prevents overbooking)
        expect(page.locator("button[data-slot]").first).to_be_disabled()
        results.append(f"STEP 4 – Student order ({order_id}) & Full slot lock: ✅ PASS")
        print(results[-1])

        # ── STEP 5: Kitchen prepares and marks ready ──────────────────────
        page.locator("form[action='/logout'] button").click()
        page.wait_for_url(f"{BASE}/login")
        page.locator("input[name='login_id']").fill("kitchen1")
        page.locator("input[name='password']").fill("kitchen123")
        page.locator("button[type='submit']").click()
        page.wait_for_url(f"{BASE}/kitchen")
        page.wait_for_timeout(1200)

        card = page.locator(f".order:has-text('{order_id}')")
        expect(card).to_be_visible()
        card.locator("button[data-to='preparing']").click()
        page.wait_for_timeout(1000)
        page.locator(f".order:has-text('{order_id}') button[data-to='ready']").click()
        page.wait_for_timeout(1000)
        expect(page.locator(f"#kds-ready .order:has-text('{order_id}')")).to_be_visible()
        results.append(f"STEP 5 – Kitchen flow ({order_id}): ✅ PASS")
        print(results[-1])

        # ── STEP 6: Admin verifies pickup -> picked_up keeps slot booked ──
        page.locator("form[action='/logout'] button").click()
        page.wait_for_url(f"{BASE}/login")
        page.locator("input[name='login_id']").fill("admin")
        page.locator("input[name='password']").fill("admin123")
        page.locator("button[type='submit']").click()
        page.wait_for_url(f"{BASE}/admin")
        page.wait_for_timeout(1200)

        page.locator("#verify-token").fill(order_id)
        page.locator("#verify-form button[type='submit']").click()
        page.wait_for_timeout(1200)
        expect(page.locator("#verify-result.ok")).to_be_visible()

        # Verify slot load still shows 1/1 (picked_up did NOT decrement booked count)
        first_slot_row = page.locator("#slot-load .load-row").first.inner_text()
        assert "1 picked up" in first_slot_row, first_slot_row
        assert "1/" in first_slot_row, first_slot_row
        results.append("STEP 6 – Admin pickup keeps slot load counted: ✅ PASS")
        print(results[-1])

        # ── STEP 7: 403 guard ──────────────────────────────────────────────
        page.goto(f"{BASE}/student")
        assert page.url == f"{BASE}/student"
        assert "403" in page.locator("h2").inner_text()
        results.append("STEP 7 – 403 guard: ✅ PASS")
        print(results[-1])

        browser.close()
        return results


if __name__ == "__main__":
    test_all()
