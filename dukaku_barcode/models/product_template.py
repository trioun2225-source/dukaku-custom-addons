from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
from odoo.tools.barcode import get_barcode_check_digit


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    barcode_symbology = fields.Selection(
        selection=[('ean13', 'EAN-13'), ('code128', 'Code 128')],
        string='Barcode Symbology',
        default='ean13',
        help='Symbology used when auto-assigning an internal barcode to this product.',
    )

    def _get_ean13_prefix(self):
        """Return the tenant-configured 3-digit EAN-13 internal prefix (200-299)."""
        try:
            prefix = int(self.env['ir.config_parameter'].sudo().get_param(
                'dukaku_barcode.ean13_prefix', default='200'
            ))
        except (TypeError, ValueError):
            prefix = 200
        return str(prefix) if 200 <= prefix <= 299 else '200'

    def _generate_ean13(self):
        """Generate a collision-free internal EAN-13.

        Format: [3-digit prefix][9-digit sequence body][1 check digit] = 13 digits.
        Prefix is in the GS1 restricted-distribution range (200-299) — these codes
        are never assigned to real products by GS1.

        # Phase 4 note: 200-299 gives 100 prefix slots. True at-scale multi-tenant
        # uniqueness (e.g. sharding the 9-digit sequence body per tenant) is
        # deliberately deferred to the self-serve onboarding phase.
        """
        prefix = self._get_ean13_prefix()
        for _ in range(100):
            body = self.env['ir.sequence'].next_by_code('dukaku.barcode.ean13')
            if not body:
                raise ValidationError(_(
                    "EAN-13 sequence not found. Try reinstalling dukaku_barcode."
                ))
            twelve = prefix + body
            if len(twelve) != 12:
                raise ValidationError(_(
                    "EAN-13 generation error: prefix+body is %d digits, expected 12.",
                    len(twelve),
                ))
            # get_barcode_check_digit strips its last character before computing,
            # so we append '0' as a placeholder to let it operate over all 12 digits.
            barcode = twelve + str(get_barcode_check_digit(twelve + '0'))
            if not self.search([('barcode', '=', barcode)], limit=1):
                return barcode
        raise ValidationError(_("Could not generate a unique EAN-13 after 100 attempts."))

    def _generate_code128(self):
        """Generate a collision-free internal Code128 barcode (DK-{seq})."""
        for _ in range(100):
            barcode = self.env['ir.sequence'].next_by_code('dukaku.barcode.code128')
            if not barcode:
                raise ValidationError(_(
                    "Code128 sequence not found. Try reinstalling dukaku_barcode."
                ))
            if not self.search([('barcode', '=', barcode)], limit=1):
                return barcode
        raise ValidationError(_("Could not generate a unique Code128 after 100 attempts."))

    def _auto_assign_barcode(self):
        """Assign an internal barcode to any record in self that has none.

        Skips multi-variant products — barcode lives on the variant, not the template.
        """
        for rec in self:
            if rec.barcode or rec.product_variant_count > 1:
                continue
            if rec.barcode_symbology == 'code128':
                rec.barcode = rec._generate_code128()
            else:
                rec.barcode = rec._generate_ean13()

    @api.constrains('barcode')
    def _validate_ean13_check_digit(self):
        """Reject any 13-digit all-numeric barcode with a wrong check digit.

        Skips everything that isn't exactly 13 numeric characters:
        EAN-8 (8 digits), UPC-A (12 digits), Code128 (alphanumeric), etc.
        Uses raw get_barcode_check_digit math — no check_barcode_encoding —
        so valid EAN-13 codes starting with '0' are accepted correctly.
        """
        for rec in self:
            b = rec.barcode
            if not b or len(b) != 13 or not b.isdigit():
                continue
            computed = get_barcode_check_digit(b)
            if computed != int(b[-1]):
                raise ValidationError(_(
                    "Barcode %s has an invalid EAN-13 check digit "
                    "(expected %s, got %s).",
                    b, computed, b[-1],
                ))

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._auto_assign_barcode()
        return records

    def write(self, vals):
        result = super().write(vals)
        # Auto-assign when barcode is explicitly cleared via write
        if 'barcode' in vals and not vals.get('barcode'):
            self._auto_assign_barcode()
        return result

    def _barcode_svg_uri(self):
        """Inline SVG data URI for the product barcode, for use in QWeb label reports.
        Uses renderSVG (no renderPM/Cairo dependency) — works in all render contexts.
        """
        from reportlab.graphics.barcode import createBarcodeDrawing
        from reportlab.graphics import renderSVG
        import base64
        bc_type = 'EAN13' if self.barcode_symbology == 'ean13' else 'Code128'
        drawing = createBarcodeDrawing(
            bc_type, value=self.barcode,
            width=420, height=150, humanReadable=True,
        )
        svg_str = renderSVG.drawToString(drawing)
        return 'data:image/svg+xml;base64,' + base64.b64encode(
            svg_str.encode('utf-8')).decode('ascii')

    def action_assign_missing_barcodes(self):
        """Batch-assign barcodes to all single-variant products without one."""
        # product_variant_count is computed/unstored — filter in Python after the search
        products = self.search([('barcode', '=', False)])
        products = products.filtered(lambda p: p.product_variant_count <= 1)
        count = len(products)
        products._auto_assign_barcode()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Barcodes Assigned'),
                'message': _('%d product(s) were assigned barcodes.', count),
                'sticky': False,
                'type': 'success',
            },
        }
