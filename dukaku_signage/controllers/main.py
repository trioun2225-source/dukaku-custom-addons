import hmac
import json
import logging

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class SignageController(http.Controller):

    def _secret_ok(self):
        """Constant-time compare of ?secret= against the single
        signage.config secret for this database.

        Pure read: never creates the config row. Every failure mode -- no
        config record, secret not yet generated, or a mismatch -- returns
        False identically, so an unauthenticated caller learns nothing about
        whether this database/tenant exists or is configured.
        """
        provided = request.params.get('secret') or ''
        cfg = request.env['signage.config'].sudo().search([], limit=1)
        stored = cfg.secret or ''
        if not stored or not provided:
            return False
        return hmac.compare_digest(provided.encode(), stored.encode())

    def _code_ok(self, provided):
        """Constant-time compare of a caller-supplied code against short_code.

        The candidate is passed in -- from ?code= for /signage/display, or the
        <code> path segment for /tv/<code> -- and upper-cased here: the short
        code is generated from an all-uppercase alphabet, so a TV remote
        entering lowercase still matches. Same pure-read posture as
        _secret_ok: never materializes the config row, identical failure
        behavior for every reason (no row, no code set, mismatch).
        """
        provided = (provided or '').upper()
        cfg = request.env['signage.config'].sudo().search([], limit=1)
        stored = cfg.short_code or ''
        if not stored or not provided:
            return False
        return hmac.compare_digest(provided.encode(), stored.encode())

    @staticmethod
    def _forbidden():
        return request.make_response(
            'Forbidden', status=403, headers=[('Content-Type', 'text/plain')],
        )

    def _render_display(self, cfg):
        """Render the full-screen TV page for an already-authorized request.

        The boot JSON always carries the real long `secret` -- it drives all
        ongoing polling / image traffic from the page -- regardless of which
        credential (?secret=, ?code=, or /tv/<code>) got the caller in.
        """
        flyers = request.env['signage.flyer'].sudo().search([('active', '=', True)])
        response = request.render('dukaku_signage.signage_display', {
            'flyers': flyers,
            'config': cfg,
            'secret': cfg.secret or '',
        })
        response.headers['Cache-Control'] = 'no-store'
        return response

    # ── TV page ─────────────────────────────────────────────────────────────
    # Shape modeled on dukaku_offline's /pos/manifest.json: type='http',
    # auth='public', GET-only, no CSRF, no session persistence. The secret is
    # the ONLY access boundary (the route is registered process-wide the
    # moment this module is importable from the shared custom_addons path).
    @http.route('/signage/display', type='http', auth='public',
                methods=['GET'], csrf=False, save_session=False)
    def signage_display(self, **kw):
        if not self._secret_ok() and not self._code_ok(request.params.get('code') or ''):
            _logger.debug('signage: /signage/display rejected (remote=%s)',
                          request.httprequest.remote_addr)
            return self._forbidden()

        cfg = request.env['signage.config'].sudo().search([], limit=1)
        return self._render_display(cfg)

    # ── Short typed entry point ────────────────────────────────────────────
    # /tv/<code> renders the exact same page as /signage/display?code=<code>,
    # just a shorter path for typing on a TV remote. Short-code only by
    # design: no ?secret= fallback (the QR flow uses /signage/display?secret=
    # and nobody types that).
    @http.route('/tv/<string:code>', type='http', auth='public',
                methods=['GET'], csrf=False, save_session=False)
    def tv(self, code, **kw):
        if not self._code_ok(code):
            _logger.debug('signage: /tv/<code> rejected (remote=%s)',
                          request.httprequest.remote_addr)
            return self._forbidden()

        cfg = request.env['signage.config'].sudo().search([], limit=1)
        return self._render_display(cfg)

    # ── Lightweight JSON playlist for in-place refresh (polled ~5 min) ──────
    # Separate from /signage/display so the TV page can diff playlist/config
    # and rebuild slides without a full reload. Same secret gate, same
    # make_response(json.dumps(...)) shape as dukaku_offline /pos/manifest.json.
    @http.route('/signage/playlist', type='http', auth='public',
                methods=['GET'], csrf=False, save_session=False, readonly=True)
    def signage_playlist(self, **kw):
        if not self._secret_ok():
            return self._forbidden()

        cfg = request.env['signage.config'].sudo().search([], limit=1)
        flyers = request.env['signage.flyer'].sudo().search([('active', '=', True)])
        payload = {
            'transition_style': (cfg.transition_style or 'cut') if cfg else 'cut',
            'orientation': (cfg.orientation or 'landscape') if cfg else 'landscape',
            'flyers': [
                {'id': f.id,
                 'seconds': max(1, f.display_seconds),
                 'v': str(f.write_date)}
                for f in flyers
            ],
        }
        return request.make_response(
            json.dumps(payload),
            headers=[('Content-Type', 'application/json'),
                     ('Cache-Control', 'no-store')],
        )

    # ── Flyer image, behind the same secret ────────────────────────────────
    # Deliberately NOT the stock /web/image route (that one is not
    # secret-gated). Delegates the actual byte-serving to ir.binary per the
    # recon Task 3 recommendation.
    @http.route('/signage/image/<int:flyer_id>', type='http', auth='public',
                methods=['GET'], csrf=False, save_session=False, readonly=True)
    def signage_image(self, flyer_id, **kw):
        if not self._secret_ok():
            return self._forbidden()

        flyer = request.env['signage.flyer'].sudo().browse(flyer_id).exists()
        if not flyer or not flyer.active:
            return request.make_response(
                'Not Found', status=404, headers=[('Content-Type', 'text/plain')],
            )
        stream = request.env['ir.binary']._get_image_stream_from(flyer, 'image')
        return stream.get_response()
