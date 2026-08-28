from odoo import fields, models


class ResUsers(models.Model):
    _inherit = "res.users"

    allowed_pos_ids = fields.Many2many(
        comodel_name="pos.config",
        relation="res_users_allowed_pos_config_rel",
        column1="user_id",
        column2="pos_config_id",
        string="Allowed POS Shops",
        help=(
            "POS shops this user is allowed to see and open sessions for. "
            "Only enforced for the internal POS User group — POS Managers "
            "and Administrators are not restricted."
        ),
    )
