/** @odoo-module **/
import { registry } from "@web/core/registry";
import { reactive } from "@odoo/owl";
import { rpc } from "@web/core/network/rpc";

const POLL_MS = 5 * 60 * 1000; // daemon fires at most every 15 min; 5 min is ample

export const dukakuBillingNotificationService = {
    start() {
        const state = reactive({ current: null });

        async function poll() {
            try {
                const res = await rpc("/dukaku_billing/poll", {});
                state.current = res && res.cycle_key ? res : null;
            } catch {
                // transient network error — keep last state, retry next tick
            }
        }

        poll();
        setInterval(poll, POLL_MS);

        return {
            state,
            poll,
            async dismiss(cycleKey) {
                try {
                    await rpc("/dukaku_billing/dismiss", { cycle_key: cycleKey });
                } catch {
                    // ignore — the local hide below still applies this cycle
                }
                state.current = null;
            },
        };
    },
};

registry.category("services").add("dukaku_billing_notification", dukakuBillingNotificationService);
