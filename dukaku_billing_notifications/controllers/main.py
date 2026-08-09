import hmac
import json
import logging

from odoo import fields, http
from odoo.http import request

_logger = logging.getLogger(__name__)

SECRET_PARAM = 'dukaku_billing.notify_secret'
VALID_URGENCY = {'info', 'warning', 'critical'}


class DukakuBillingController(http.Controller):

    # ── Daemon → server: push the current notification ───────────────────────
    # type='http' so we control status codes (403/400/200). Auth is the shared
    # secret (constant-time), NOT the client IP: proxy_mode makes remote_addr
    # spoofable by local processes; ufw keeps 8069 off the internet.
    @http.route('/dukaku_billing/notify', type='http', auth='none',
                methods=['POST'], csrf=False, save_session=False)
    def notify(self, **kw):
        try:
            payload = json.loads(request.httprequest.get_data() or b'{}')
        except (ValueError, TypeError):
            return request.make_response('bad json', status=400)

        secret = str(payload.get('secret') or '')
        param = request.env['ir.config_parameter'].sudo().get_param(SECRET_PARAM) or ''
        if not param or not secret or not hmac.compare_digest(secret, param):
            _logger.warning('dukaku_billing: notify auth failed (remote=%s)',
                            request.httprequest.remote_addr)
            return request.make_response('forbidden', status=403)

        message = (payload.get('message') or '').strip()[:2000]
        if not message:
            return request.make_response('message required', status=400)
        cycle_key = str(payload.get('cycle_key') or '').strip()
        if not cycle_key:
            return request.make_response('cycle_key required', status=400)
        urgency = payload.get('urgency')
        if urgency not in VALID_URGENCY:
            urgency = 'info'

        request.env['dukaku.billing.notification'].sudo().upsert_current({
            'message': message,
            'urgency': urgency,
            'renew_url': (payload.get('renew_url') or '')[:500],
            'expires_at': (payload.get('expires_at') or '')[:64],
            'cycle_key': cycle_key,
            'active': True,
        })
        return request.make_response(
            json.dumps({'status': 'ok'}),
            headers=[('Content-Type', 'application/json')],
        )

    # ── POS → server: fetch the current (non-dismissed) notification ─────────
    @http.route('/dukaku_billing/poll', type='jsonrpc', auth='user')
    def poll(self):
        rec = request.env['dukaku.billing.notification'].sudo()._get_current()
        if not rec:
            return {}
        uid = request.env.uid
        dismissal = request.env['dukaku.billing.notification.dismissal'].sudo().search(
            [('user_id', '=', uid)], limit=1)
        if dismissal and dismissal.cycle_key == rec.cycle_key:
            return {}
        return {
            'message': rec.message,
            'urgency': rec.urgency,
            'renew_url': rec.renew_url or '',
            'expires_at': rec.expires_at or '',
            'cycle_key': rec.cycle_key,
        }

    # ── POS → server: dismiss the current cycle for this user ────────────────
    @http.route('/dukaku_billing/dismiss', type='jsonrpc', auth='user')
    def dismiss(self, cycle_key=None):
        uid = request.env.uid
        Dis = request.env['dukaku.billing.notification.dismissal'].sudo()
        rec = Dis.search([('user_id', '=', uid)], limit=1)
        vals = {'cycle_key': cycle_key or '', 'dismissed_at': fields.Datetime.now()}
        if rec:
            rec.write(vals)
        else:
            Dis.create(dict(vals, user_id=uid))
        return {'status': 'ok'}
