import { patch } from "@web/core/utils/patch";
import { PosData } from "@point_of_sale/app/services/data_service";

patch(PosData.prototype, {
    /**
     * Guard path #3: config change detected during startup wipes IndexedDB at
     * data_service.js:306-310, destroying locally-queued offline orders before
     * they can sync.  Intercept and suppress the wipe when unsynced orders exist.
     *
     * When blocked:
     *   - resetIndexedDB() becomes a no-op for this call only (prototype restored
     *     in finally so future reloads after a successful sync work normally)
     *   - _wipeBlockedByUnsyncedOrders signals PosStore to show a cashier dialog
     */
    async loadInitialData() {
        // Read all three databaseTable stores needed for the content check.
        const snap = await this.indexedDB.readAll(["pos.order", "pos.order.line", "pos.payment"]);

        // isSynced ≡ typeof id === "number" (base.js:31-33).
        // Locally-created offline orders have string/UUID ids — no server id yet.
        // many2one raw value = linkedRecord.id (index.js:835), so line.order_id
        // and payment.pos_order_id carry the parent order's id in the same form.
        const unsyncedOrderIds = new Set(
            (snap?.["pos.order"] || [])
                .filter((o) => typeof o.id !== "number")
                .map((o) => o.id)
        );

        // Mirror shouldCreatePendingOrder: block if any unsynced order has a line
        // OR a payment.  We check all payments (not only pay_later) because at
        // startup the payment method type is not in scope — and any payment on an
        // unsynced order means a sale is in flight and must not be wiped.
        const hasUnsynced =
            unsyncedOrderIds.size > 0 && (
                (snap?.["pos.order.line"] || []).some((l) => unsyncedOrderIds.has(l.order_id)) ||
                (snap?.["pos.payment"]    || []).some((p) => unsyncedOrderIds.has(p.pos_order_id))
            );

        if (hasUnsynced) {
            // Signal PosStore to surface a cashier-visible warning after init.
            this._wipeBlockedByUnsyncedOrders = true;
            // Shadow the prototype method on this instance only.
            // super.loadInitialData() calls this.resetIndexedDB(); the no-op
            // lets initIndexedDB() re-open the existing DB (data preserved)
            // and localData={} clear only the server-cache variable (pos.order
            // is not in that variable — it lives in the databaseTable stores).
            this.resetIndexedDB = async () => {};
            try {
                return await super.loadInitialData();
            } finally {
                // Remove the instance override; prototype method is restored.
                delete this.resetIndexedDB;
            }
        }

        return await super.loadInitialData();
    },
});
