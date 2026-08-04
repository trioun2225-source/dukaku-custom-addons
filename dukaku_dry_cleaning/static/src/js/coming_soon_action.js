/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component } from "@odoo/owl";

export class DryCleaningComingSoon extends Component {
    static template = "dukaku_dry_cleaning.ComingSoon";
    static props = ["*"];
}

registry.category("actions").add("dukaku_dry_cleaning.coming_soon", DryCleaningComingSoon);
