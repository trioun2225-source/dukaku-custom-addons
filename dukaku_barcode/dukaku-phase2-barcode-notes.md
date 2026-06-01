# Dukaku Barcode & QR — Phase 2 Handoff Notes

**Module:** `dukaku_barcode`  
**Path:** `/opt/odoo19/custom_addons/dukaku_barcode/`  
**Odoo version:** 19.0 Community  
**Module version:** 19.0.1.0.0  

---

## Phase 2 status

| Task | Status |
|------|--------|
| Task 0 — Environment confirm | Complete |
| Task 1 — Module scaffold | Complete |
| Task 2 — EAN-13/Code128 auto-assign, check-digit, backfill | Complete |
| Task 3 — Thermal label report (40×30mm Xprinter) | **Complete** |
| Task 4 — QR code on POS digital receipt | Complete |
| Task 5 — Handoff notes | This document |

**Phase 2 is fully shipped.** All tasks complete including hardware verification.

---

## Task 2 — Barcode auto-assign

- Auto-assigns EAN-13 or Code128 on product create and on explicit barcode clear.
- Skips multi-variant products (`product_variant_count > 1`) — barcode lives on the variant, not the template.
- EAN-13 prefix: configurable per-tenant in Settings → Dukaku Barcode & QR (field `dukaku_barcode.ean13_prefix`, default 200, range 200–299). GS1 restricted-distribution range — never assigned to real products.
- **EAN-13 check digit:** generated via `get_barcode_check_digit(twelve + '0')`. The `+ '0'` placeholder is mandatory — the helper strips its last character before computing, so 12 real digits + 1 placeholder = correct result over all 12 digits.
- **Constraint:** `@api.constrains('barcode')` validates check digit on every 13-digit all-numeric barcode using raw `get_barcode_check_digit` math — NOT `check_barcode_encoding`. Reason: `check_barcode_encoding` falsely rejects valid EAN-13 codes starting with `0` (UPC-A overlap guard). Raw math has zero false rejections across all barcode shapes.
- **`product_variant_count` search caveat:** this field is computed/unstored — cannot be used in ORM domain filters. Backfill action searches `('barcode', '=', False)` then filters with `.filtered(lambda p: p.product_variant_count <= 1)` in Python.
- **Phase 4 note (in code):** 200–299 gives 100 prefix slots. True at-scale multi-tenant uniqueness (e.g. sharding the 9-digit sequence body per tenant) is deliberately deferred to the self-serve onboarding phase.
- **Backfill tested and working.** The batch "Assign Missing Barcodes" action (`action_assign_missing_barcodes`) was verified against 3 simultaneous empty products (2× EAN-13, 1× Code128) — all received correctly typed barcodes in one call.
- **Global scope — important:** the action uses `self.search(...)` internally, so it always backfills **all** products in the DB that lack a barcode, regardless of which records are selected in the UI when Action → Assign Missing Barcodes is clicked. Selecting 1 product and clicking the action will fill every unassigned product in the tenant. This is intentional (it's a global backfill tool), but operators should know not to expect selection-scoped behaviour.

---

## Task 3 — Thermal label report

**Report:** `dukaku_barcode.report_product_label_document`  
**Paperformat:** `paperformat_thermal_label_40x30` (40×30mm, 300 DPI, 2mm margins)  
**Bound to:** `product.template` Print menu (list and form views)

### Barcode rendering approach

Labels use `doc._barcode_svg_uri()` — a method on `product.template` that generates the barcode as an inline SVG data URI via `reportlab.graphics.renderSVG`. No HTTP round-trip, no external dependencies.

**Why SVG and not the `barcode` QWeb widget or HTTP URL:**
- The `barcode` widget (`t-options="{'widget': 'barcode', ...}"`) calls `report.barcode()` → `barcode.asString('png')` → requires `rlPyCairo` or `_rl_renderPM` renderlab backends. Neither is installed in `/opt/odoo19/odoo-venv`.
- The HTTP URL approach (`/report/barcode/EAN13/...`) requires wkhtmltopdf to fetch from `web.base.url` (= `https://staging.dukaku.com`), which hits authentication/proxy issues in CLI and cron contexts.
- `renderSVG.drawToString()` works without any pixel-rendering backend. SVG is also vector, so it scales to the Xprinter's native DPI without aliasing.

**If PNG is ever needed:** install `pkg-config libcairo2-dev` (system packages) then `pip install rlPyCairo==0.4.0` in the shared venv — requires a VPS snapshot and an Odoo service restart (affects all tenants). Propose and approve separately.

### Hardware gate — PASSED

Both labels printed on the Xprinter and scanned correctly:
- EAN-13 decoded to `2000000000015` ✓
- Code128 decoded to `DK-000001` ✓

---

## Task 4 — QR code on POS digital receipt

**Files:**
- `static/src/app/screens/receipt_screen/receipt/dukaku_order_receipt.js`
- `static/src/app/screens/receipt_screen/receipt/dukaku_order_receipt.xml`

**What it does:** Patches `OrderReceipt` to add a `dukakuQrCode` getter that calls `generateQRCodeDataUrl(order.name)`. The QR block is injected before the `before-footer` div in the receipt template, inside the `!props.basic_receipt` guard (full receipts only).

**Payload:** `order.name` — the POS order reference (e.g. `Order 00001-001-0001`). No URL, no access token, no server round-trip.

**Offline:** `generateQRCodeDataUrl` uses the bundled `QRCode` JS library — pure DOM, no HTTP. Works in airplane mode. The getter is wrapped in try/catch; any failure returns `''`, the `t-if` hides the block silently, and the receipt renders normally.

**Tested on staging:** QR appears on receipt, scans to correct order reference, offline path confirmed.

**Phase 4 note:** When per-tenant portal URLs are provisioned, replace `this.order.name` in the getter with a full portal URL (e.g. `${baseUrl}/pos/ticket/${order.name}`). No structural changes needed.

---

## Leading-0 EAN-13 cosmetic fallback

`report.barcode()` (used internally by the `barcode` QWeb widget and Odoo's `/report/barcode/` route) calls `check_barcode_encoding()` before rendering. That function falsely rejects valid EAN-13 codes starting with `0` and falls back to Code128 rendering. **This does not affect our auto-assigned 200–299 prefix codes.** It only affects manually entered manufacturer EAN-13 codes with a leading `0` — the barcode will render as Code128 bars but still scan correctly. Cosmetic only. Document for operators if they report label symbology mismatch.

Note: our `_barcode_svg_uri()` method calls `createBarcodeDrawing` directly (not `report.barcode()`), so it does not have this fallback. It will render leading-0 EAN-13 codes correctly as EAN-13 bars.

---

## Multi-label printing — deferred

Printing multiple products at once (select N on list view → Print → Product Label) fails with wkhtmltopdf 0.12.6 unpatched Qt. Single-label works. Multi-label deferred — requires installing a patched-Qt wkhtmltopdf build (separate VPS operation, not bundled here).

---

## Staging credentials (testing only)

During Task 4 testing, the password for `service@dukaku.com` on the `staging` DB was reset. See password manager for current credential. This is the only internal user on staging. Reset again after testing if needed.

---

## Operational safety

**This box runs live production tenants alongside staging.** All tenants share the same Odoo process (`/opt/odoo19/odoo-venv`), the same `systemctl odoo19` service, and the same PostgreSQL instance. Check `psql postgres -c '\l'` for the current tenant list — not hardcoded here.

Consequences:
- `systemctl restart odoo19` interrupts service for every tenant — requires explicit approval each time, never bundle with an upgrade step
- Any `pip install` or system package change in `/opt/odoo19/odoo-venv` affects production — take a VPS snapshot first
- Never target a production DB in any script; always pass `--database=staging` explicitly and confirm the target in output before committing

**Auto mode:** Claude Code's auto-accept classifier re-enabled itself multiple times during this session despite being turned off with Shift+Tab. Each time it was on, commands ran without prompts — including a `systemctl restart odoo19` that hit all tenants. **Confirm auto mode is OFF (Shift+Tab, look for 1.Yes / 2.No prompts) at the start of every session before any work begins.** Do not rely on "I'll show commands anyway" as a substitute — the gate must be off at the UI level.

## Safety rules (standing)

1. Never touch a production tenant — check the live DB list with `su -s /bin/bash odoo19 -c "psql postgres -c '\\l'"` rather than hardcoding names here
2. Snapshot VPS before any shared-venv pip install or system package change
3. Odoo service restart (`systemctl restart odoo19`) affects all tenants — propose and approve separately, never bundle
4. Module upgrades run as `odoo19` user: `su -s /bin/bash odoo19 -c "source /opt/odoo19/odoo-venv/bin/activate && python3 /opt/odoo19/odoo/odoo-bin --config=/etc/odoo19.conf --database=staging --update=dukaku_barcode --no-http --stop-after-init"`
