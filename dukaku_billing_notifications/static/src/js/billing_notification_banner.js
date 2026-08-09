/** @odoo-module **/
import { Component, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

export class DukakuBillingBanner extends Component {
    static template = "dukaku_billing_notifications.Banner";
    static props = {};

    setup() {
        this.billing = useService("dukaku_billing_notification");
        this.state = useState(this.billing.state);
    }

    get notif() {
        return this.state.current;
    }

    onRenew() {
        const url = this.notif?.renew_url;
        if (url) {
            window.open(url, "_blank", "noopener,noreferrer");
        }
    }

    onDismiss() {
        if (this.notif) {
            this.billing.dismiss(this.notif.cycle_key);
        }
    }
}
