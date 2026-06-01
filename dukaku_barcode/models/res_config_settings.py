from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    dukaku_barcode_ean13_prefix = fields.Integer(
        string='Internal EAN-13 Prefix (200-299)',
        config_parameter='dukaku_barcode.ean13_prefix',
        default=200,
        help=(
            'GS1 restricted-distribution prefix for auto-assigned internal EAN-13 barcodes. '
            'Set a unique value per tenant (200-299) to keep barcode spaces distinct across tenants.'
        ),
    )

    @api.constrains('dukaku_barcode_ean13_prefix')
    def _check_ean13_prefix_range(self):
        for rec in self:
            if not (200 <= rec.dukaku_barcode_ean13_prefix <= 299):
                raise ValidationError(_(
                    'Internal EAN-13 prefix must be between 200 and 299 '
                    '(GS1 restricted-distribution range).'
                ))
