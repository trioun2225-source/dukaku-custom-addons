from odoo import api, fields, models


class DukakuBillingNotification(models.Model):
    """The single current billing notification for this database (upsert singleton)."""
    _name = 'dukaku.billing.notification'
    _description = 'Dukaku Billing Notification'

    message = fields.Text(required=True)
    urgency = fields.Selection(
        [('info', 'Info'), ('warning', 'Warning'), ('critical', 'Critical')],
        default='info', required=True,
    )
    renew_url = fields.Char()
    expires_at = fields.Char()          # ISO8601 string from the daemon (display only)
    cycle_key = fields.Char(required=True, index=True)
    active = fields.Boolean(default=True)

    @api.model
    def _get_current(self):
        return self.search([('active', '=', True)], order='write_date desc, id desc', limit=1)

    @api.model
    def upsert_current(self, vals):
        """Keep exactly one row per DB: update the existing one, else create it."""
        rec = self.search([], order='id desc', limit=1)
        if rec:
            rec.write(vals)
        else:
            rec = self.create(vals)
        others = self.search([('id', '!=', rec.id)])
        if others:
            others.write({'active': False})
        return rec


class DukakuBillingNotificationDismissal(models.Model):
    """Per-user record of the last notification cycle that user dismissed."""
    _name = 'dukaku.billing.notification.dismissal'
    _description = 'Dukaku Billing Notification Dismissal (per user)'

    user_id = fields.Many2one('res.users', required=True, ondelete='cascade', index=True)
    cycle_key = fields.Char()
    dismissed_at = fields.Datetime()

    _user_uniq = models.Constraint('unique(user_id)', 'One dismissal row per user.')
