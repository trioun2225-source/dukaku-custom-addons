import secrets

from odoo import _, api, fields, models


class SignageConfig(models.Model):
    _name = 'signage.config'
    _description = 'Dukaku Signage Settings'

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

    @api.model
    def _get_singleton(self):
        """The one settings row for this database, created with a fresh secret
        on first access. Sole entry point for backend and public controller
        alike, so exactly one row is ever used."""
        rec = self.sudo().search([], limit=1)
        if not rec:
            rec = self.sudo().create({})
        if not rec.secret:
            rec.secret = self._new_secret()
        return rec

    @api.model
    def _new_secret(self):
        # 64-char URL-safe token - same order of strength as the
        # dukaku_billing_notifications notify secret.
        return secrets.token_urlsafe(48)

    def action_regenerate_secret(self):
        self.ensure_one()
        self.secret = self._new_secret()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _("Signage secret regenerated"),
                'message': _("The previous display URL has stopped working."),
                'sticky': False,
                'type': 'warning',
            },
        }
