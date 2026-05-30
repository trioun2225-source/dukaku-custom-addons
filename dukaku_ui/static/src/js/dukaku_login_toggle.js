(function () {
    var STORAGE_KEY = 'dukaku_theme';
    var DARK_CLASS  = 'dukaku_dark';
    var toggleBtn   = null;

    function applyTheme(dark) {
        document.body.classList.toggle(DARK_CLASS, dark);
        localStorage.setItem(STORAGE_KEY, dark ? 'dark' : 'light');
        if (toggleBtn) {
            toggleBtn.textContent = dark ? '☀' : '🌙'; // ☀ / 🌙
            toggleBtn.title = dark ? 'Switch to light mode' : 'Switch to dark mode';
        }
    }

    function createToggleButton(isDark) {
        var btn = document.createElement('button');
        btn.id        = 'dukaku-login-toggle';
        btn.textContent = isDark ? '☀' : '🌙';
        btn.title     = isDark ? 'Switch to light mode' : 'Switch to dark mode';
        btn.setAttribute('aria-label', btn.title);

        var s = btn.style;
        s.position     = 'fixed';
        s.top          = '16px';
        s.right        = '16px';
        s.width        = '36px';
        s.height       = '36px';
        s.borderRadius = '50%';
        s.border       = '1.5px solid #F5A800';
        s.background   = '#F5A800';
        s.color        = '#1A1A1A';
        s.fontSize     = '16px';
        s.lineHeight   = '1';
        s.padding      = '0';
        s.cursor       = 'pointer';
        s.zIndex       = '9999';
        s.display      = 'flex';
        s.alignItems   = 'center';
        s.justifyContent = 'center';
        s.boxShadow    = '0 2px 8px rgba(0,0,0,0.25)';
        s.transition   = 'background 0.2s, color 0.2s';

        btn.addEventListener('mouseenter', function () {
            btn.style.background = '#E07000';
        });
        btn.addEventListener('mouseleave', function () {
            btn.style.background = '#F5A800';
        });

        btn.addEventListener('click', function () {
            applyTheme(!document.body.classList.contains(DARK_CLASS));
        });

        return btn;
    }

    function injectLogo() {
        // dukaku_branding already injects a logo above the form — skip if present
        if (document.querySelector('.card-body img, .o_database_list img')) return;

        var form = document.querySelector('.oe_login_form');
        if (!form) return;

        var wrap = document.createElement('div');
        wrap.style.cssText = 'text-align:center; padding-bottom:16px; margin-bottom:16px; border-bottom:1px solid #3A3A3A;';

        var img = document.createElement('img');
        img.src   = '/dukaku_ui/static/src/img/dukaku_logo.png';
        img.alt   = 'Dukaku POS';
        img.style.cssText = 'max-height:80px; max-width:100%; width:auto;';

        wrap.appendChild(img);
        form.parentNode.insertBefore(wrap, form);
    }

    document.addEventListener('DOMContentLoaded', function () {
        var saved  = localStorage.getItem(STORAGE_KEY);
        var isDark = saved === 'dark';

        // Apply saved theme immediately (before paint if possible)
        if (isDark) document.body.classList.add(DARK_CLASS);

        // Inject toggle button
        toggleBtn = createToggleButton(isDark);
        document.body.appendChild(toggleBtn);

        // Inject logo only if dukaku_branding hasn't already done so
        injectLogo();
    });
})();
