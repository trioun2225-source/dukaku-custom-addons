import base64
import io
import secrets

import qrcode

from odoo import _, api, fields, models


class SignageConfig(models.Model):
    _name = 'signage.config'
    _description = 'Dukaku Signage Settings'

    # Unambiguous alphabet for the typed short code: excludes 0/O and 1/I/L.
    _SHORT_CODE_ALPHABET = '23456789ABCDEFGHJKMNPQRSTUVWXYZ'

    transition_style = fields.Selection(
        [('cut', 'Cut'), ('fade', 'Fade')],
        string='Transition Style', default='cut', required=True,
    )
    orientation = fields.Selection(
        [('landscape', 'Landscape'), ('portrait', 'Portrait')],
        string='Orientation', default='landscape', required=True,
    )
    secret = fields.Char(
        string='Display Secret', copy=False,
        help="Token that gates the public /signage/display URL. This is the "
             "only access control on the public page - treat it like a "
             "password. Regenerating it immediately invalidates the old URL.",
    )
    short_code = fields.Char(
        string='Short Code', copy=False, readonly=True,
        help="8-character code for typing the display URL on a TV remote. "
             "Always regenerated together with 'secret' - never valid alone "
             "without a matching secret behind it.",
    )
    qr_image = fields.Binary(
        string='Display QR Code', compute='_compute_qr_image',
        help="QR code of the full /signage/display?secret=... URL, for "
             "one-time setup by scanning with a phone.",
    )

    @api.model
    def _get_singleton(self):
        """The one settings row for this database, created with a fresh secret
        and short code on first access. Sole entry point for backend and public
        controller alike, so exactly one row is ever used."""
        rec = self.sudo().search([], limit=1)
        if not rec:
            rec = self.sudo().create({})
        if not rec.secret:
            rec.secret = self._new_secret()
        if not rec.short_code:
            rec.short_code = self._new_short_code()
        return rec

    @api.model
    def _new_secret(self):
        # 64-char URL-safe token - same order of strength as the
        # dukaku_billing_notifications notify secret.
        return secrets.token_urlsafe(48)

    @api.model
    def _new_short_code(self):
        # 8 chars from a 31-symbol unambiguous alphabet. Deliberately weak
        # next to `secret`: convenience credential for the one-time TV hand-off
        # only, never used for ongoing page traffic; rate-limiting was
        # explicitly ruled out (low-value target).
        return ''.join(secrets.choice(self._SHORT_CODE_ALPHABET) for _ in range(8))

    def _compute_qr_image(self):
        # No @api.depends: recomputed on every read so the encoded URL always
        # reflects the current base URL and secret, with no stored copy to go
        # stale.
        for rec in self:
            if not rec.secret:
                rec.qr_image = False
                continue
            url = f"{rec.get_base_url()}/signage/display?secret={rec.secret}"
            img = qrcode.make(url)
            buf = io.BytesIO()
            img.save(buf, format='PNG')
            rec.qr_image = base64.b64encode(buf.getvalue())

    def action_regenerate_secret(self):
        self.ensure_one()
        self.secret = self._new_secret()
        self.short_code = self._new_short_code()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _("Signage secret regenerated"),
                'message': _("The previous display URL and short code have "
                             "stopped working."),
                'sticky': False,
                'type': 'warning',
            },
        }
