from odoo import models, _
from odoo.exceptions import UserError


class PosOrder(models.Model):
    _inherit = 'pos.order'

    def _get_valid_session(self, order):
        try:
            return super()._get_valid_session(order)
        except UserError as exc:
            # [POS_NO_SESSION] — sentinel matched by pos_store_patch.js to detect
            # a closed-session sync failure with no rescue session available.
            raise UserError(f'[POS_NO_SESSION] {exc.args[0]}') from exc
