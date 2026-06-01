import { OrderReceipt } from "@point_of_sale/app/screens/receipt_screen/receipt/order_receipt";
import { generateQRCodeDataUrl } from "@point_of_sale/utils";
import { patch } from "@web/core/utils/patch";

// Adds a QR code encoding the order reference to the POS digital receipt.
// Payload is order.name (e.g. "Order 00001-001-0001") — no server round-trip,
// no access token required, works fully offline.
// Swappable: replace the body of dukakuQrCode to change payload (e.g. add a
// portal URL in Phase 4 once per-tenant URLs are provisioned).
patch(OrderReceipt.prototype, {
    get dukakuQrCode() {
        try {
            return generateQRCodeDataUrl(this.order.name);
        } catch {
            return '';
        }
    },
});
