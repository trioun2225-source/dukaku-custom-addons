/** @odoo-module **/
import { Navbar } from "@point_of_sale/app/components/navbar/navbar";
import { DukakuBillingBanner } from "@dukaku_billing_notifications/js/billing_notification_banner";

// Register the banner as a Navbar sub-component so the inherited template
// (templates.xml) can mount <DukakuBillingBanner/> inside the topheader.
Navbar.components = { ...Navbar.components, DukakuBillingBanner };
