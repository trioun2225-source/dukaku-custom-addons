import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import OrderPaymentValidation from "@point_of_sale/app/utils/order_payment_validation";
import { ask } from "@point_of_sale/app/utils/make_awaitable_dialog";

// Stage 4 frontend UX check only - fast feedback before the order reaches
// the server. The authoritative rule lives server-side as an
// @api.constrains on pos.order (dukaku_dry_cleaning/models/pos_order.py):
// this check cannot be bypassed by skipping or breaking this patch, it can
// only make the operator wait for a server round-trip to find out.
patch(OrderPaymentValidation.prototype, {
    async isOrderValid(isForceValidate) {
        if (!(await this._dryCleaningCustomerCheck())) {
            return false;
        }
        return super.isOrderValid(isForceValidate);
    },

    async _dryCleaningCustomerCheck() {
        const order = this.order;
        if (order.getPartner()) {
            return true;
        }
        // Same qualifying-line condition frozen in Stage 2: requires_garment_tag
        // and a positive quantity - refund lines (negative qty) never qualify.
        const hasQualifyingLine = order
            .getOrderlines()
            .some((line) => line.product_id.requires_garment_tag && line.qty > 0);
        if (!hasQualifyingLine) {
            return true;
        }
        const confirmed = await ask(this.pos.dialog, {
            title: _t("Customer Required"),
            body: _t("A customer is required for orders containing a dry-cleaning item."),
        });
        if (confirmed) {
            await this.pos.selectPartner();
        }
        return false;
    },
});
