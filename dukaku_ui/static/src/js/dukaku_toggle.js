/** @odoo-module **/

import { Component, useState, onMounted } from "@odoo/owl";
import { registry } from "@web/core/registry";

const STORAGE_KEY = "dukaku_theme";
const DARK_CLASS  = "dukaku_dark";

class DarkModeToggle extends Component {
    static template = "dukaku_ui.DarkModeToggle";
    static props = {};

    setup() {
        this.state = useState({ isDark: false });
        onMounted(() => {
            const saved = localStorage.getItem(STORAGE_KEY);
            if (saved === "dark") {
                this._applyDark(true);
            }
        });
    }

    get isDark() {
        return this.state.isDark;
    }

    toggle() {
        this._applyDark(!this.state.isDark);
    }

    _applyDark(dark) {
        document.body.classList.toggle(DARK_CLASS, dark);
        this.state.isDark = dark;
        localStorage.setItem(STORAGE_KEY, dark ? "dark" : "light");
    }
}

// Register as a systray item so it appears in the top-right navbar area
registry.category("systray").add("dukaku_ui.DarkModeToggle", {
    Component: DarkModeToggle,
    sequence: 1,  // low sequence = rightmost; adjust if needed
});
