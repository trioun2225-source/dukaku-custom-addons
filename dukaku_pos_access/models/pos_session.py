from odoo import _, api, models
from odoo.exceptions import UserError


class PosSession(models.Model):
    _inherit = "pos.session"

    def _check_pos_config_allowed(self, config):
        user = self.env.user
        if user.has_group("point_of_sale.group_pos_manager") or user.has_group(
            "base.group_system"
        ):
            return
        if user.has_group("point_of_sale.group_pos_user"):
            if config not in user.allowed_pos_ids:
                raise UserError(
                    _("You are not authorized to open a session for this POS shop.")
                )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            # Mirror the base pos.session.create() fallback: a caller may pass
            # the config through the context instead of the vals dict.
            config_id = vals.get("config_id") or self.env.context.get(
                "default_config_id"
            )
            if config_id:
                config = self.env["pos.config"].browse(config_id)
                self._check_pos_config_allowed(config)
        return super().create(vals_list)
