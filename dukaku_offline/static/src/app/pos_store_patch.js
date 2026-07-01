import { patch } from "@web/core/utils/patch";
import { PosStore } from "@point_of_sale/app/services/pos_store";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { _t } from "@web/core/l10n/translation";
import { countUnsyncedSales } from "@dukaku_offline/app/offline_guard";

// [POS_NO_SESSION] — sentinel embedded by models/pos_order.py when _get_valid_session
// finds no open rescue session.  Checked here to surface a cashier dialog instead of
// the silent errorOccurred path; loop and readDataFromServer fallback are unaffected.
function isPosNoSession(error) {
    return typeof error?.data?.message === "string" &&
        error.data.message.includes("[POS_NO_SESSION]");
}

patch(PosStore.prototype, {
    /**
     * Guard path #1: "Reload Data" menu item.
     * reloadData() at pos_store.js:277-288 calls this.data.resetIndexedDB()
     * which deletes the entire IndexedDB — including locally-queued offline orders.
     * Block it when any unsynced sales exist.  countUnsyncedSales() uses the model
     * layer (getPendingOrder / shouldCreatePendingOrder).  The startup guard in
     * data_service_patch.js mirrors the same rule against raw IndexedDB bytes
     * (pos.order string-ids, cross-referenced with pos.order.line and pos.payment)
     * because the model layer is not yet available at that point.
     */
    async reloadData(fullReload = false) {
        const pending = countUnsyncedSales(this);
        if (pending > 0) {
            this.dialog.add(AlertDialog, {
                title: _t("Cannot Reload — Unsynced Sales"),
                body: _t(
                    "You have %(n)s unsynced sale(s). Reconnect and let them sync before reloading.",
                    { n: pending }
                ),
            });
            return;
        }
        return await super.reloadData(fullReload);
    },

    async syncAllOrders(options = {}) {
        const data = this.data;

        // Guard: only the outermost concurrent call installs the shadow.
        // syncAllOrders has many unprotected call sites that bypass pushOrderMutex
        // (lines 368, 724, 1675, 1774, 1934, 2000, 3021 in pos_store.js), so
        // overlap is possible.  An inner call skips installation and cleanup;
        // the outermost shadow covers it automatically.
        const isOutermost = !Object.prototype.hasOwnProperty.call(data, "call");
        if (isOutermost) {
            const origCall = data.call.bind(data);
            data.call = async (model, method, ...args) => {
                try {
                    return await origCall(model, method, ...args);
                } catch (error) {
                    // [POS_NO_SESSION] — re-throw so super's catch sets errorOccurred
                    // and the loop continues; show dialog once per sync cycle.
                    if (!data._posNoSessionDialogShown &&
                            model === "pos.order" && method === "sync_from_ui" &&
                            isPosNoSession(error)) {
                        data._posNoSessionDialogShown = true;
                        this.dialog.add(AlertDialog, {
                            title: _t("Session Closed — Cannot Sync"),
                            body: _t(
                                "The POS session was closed before these orders synced, "
                                + "and no open session is available to receive them. "
                                + "Open a new session, then the orders will sync automatically."
                            ),
                        });
                    }
                    throw error;
                }
            };
        }
        try {
            return await super.syncAllOrders(options);
        } finally {
            if (isOutermost) {
                delete data.call;
                delete data._posNoSessionDialogShown;
            }
        }
    },

    async afterProcessServerData() {
        const result = await super.afterProcessServerData();
        if (this.data._wipeBlockedByUnsyncedOrders) {
            this.data._wipeBlockedByUnsyncedOrders = false;
            this.dialog.add(AlertDialog, {
                title: _t("Config Change Pending — Sync Before Refreshing"),
                body: _t(
                    "A POS configuration update is waiting to be applied, "
                    + "but you have unsynced sales. Reconnect and let them sync, "
                    + "then refresh the page to load the new configuration."
                ),
            });
        }
        return result;
    },
});
