import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { user } from "@web/core/user";
import { rpc } from "@web/core/network/rpc";
import { downloadReport } from "@web/webclient/actions/reports/utils";
import { useTrackedAsync } from "@point_of_sale/app/hooks/hooks";
import { ReceiptScreen } from "@point_of_sale/app/screens/receipt_screen/receipt_screen";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";

// Stage 4 post-payment print action. Tags are never generated here - they
// were already created server-side by the existing Stage 2
// _dry_cleaning_process_order logic when the order was paid.
//
// Freeze-hardening fix: this must NOT call report.doAction()/report/download
// directly - that path only downloads the PDF, it never runs
// dry_cleaning.garment_tag.action_print_garment_tags() (Stage 2), so
// printed/printed_date bookkeeping was silently skipped when printing from
// POS. Instead this calls that exact existing method by RPC (same
// pos.data.call(model, method, args) bridge already used a few lines below
// for the receipt email/whatsapp send), gets back the very report action
// dict action_print_garment_tags() already returns, and feeds it straight
// into the same downloadReport() helper the core "report" service itself
// uses - no bookkeeping logic is duplicated here, and no new server method
// was added to do it: the Stage 2 method is called as-is.
patch(ReceiptScreen.prototype, {
    setup() {
        super.setup();
        this.doDryCleaningPrint = useTrackedAsync(() => this._printDryCleaningLabels());
    },

    // Raw ids only (never resolved into linked records - dry_cleaning.garment_tag
    // is not a POS-loaded model), which is all action_print_garment_tags() needs.
    get dryCleaningGarmentTagIds() {
        const ids = [];
        for (const line of this.currentOrder.getOrderlines()) {
            const tagIds = line.raw && line.raw.garment_tag_ids;
            if (tagIds) {
                ids.push(...tagIds);
            }
        }
        return ids;
    },

    // Gated on the order actually being synced: before that, the server
    // hasn't generated any tags yet, and there is nothing authoritative to
    // print. No offline queuing is attempted - printing simply isn't
    // offered until the order has a confirmed server state.
    get canPrintDryCleaningLabels() {
        const order = this.currentOrder;
        return Boolean(order.isSynced && (order.dry_cleaning_garment_tag_count || 0) > 0);
    },

    async _printDryCleaningLabels() {
        const ids = this.dryCleaningGarmentTagIds;
        if (!ids.length) {
            this.dialog.add(AlertDialog, {
                title: _t("Nothing to Print"),
                body: _t("No garment labels were found for this order."),
            });
            return;
        }
        // Calls the existing Stage 2 method as-is: it sets printed/printed_date
        // itself and returns the report action, exactly like the backend
        // "Print Garment Labels" button does.
        const reportAction = await this.pos.data.call(
            "dry_cleaning.garment_tag",
            "action_print_garment_tags",
            [ids]
        );
        await downloadReport(rpc, reportAction, "pdf", user.context);
    },
});
