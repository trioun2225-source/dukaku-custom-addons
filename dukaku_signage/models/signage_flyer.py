from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class SignageFlyer(models.Model):
    _name = 'signage.flyer'
    _description = 'Dukaku Signage Flyer'
    _order = 'sequence, id'

    name = fields.Char(required=True)
    image = fields.Image(string='Image', max_width=1920, max_height=1920, required=True)
    # One stored companion for the backend list thumbnail only. The public TV
    # route resizes on the fly from `image` via
    # ir.binary._get_image_stream_from(), so the full image_1024/512/256 ladder
    # is unnecessary here.
    image_128 = fields.Image(
        string='Thumbnail', related='image',
        max_width=128, max_height=128, store=True,
    )
    sequence = fields.Integer(default=10)
    display_seconds = fields.Integer(string='Display Seconds', default=8)
    active = fields.Boolean(default=True)

    @api.constrains('display_seconds')
    def _check_display_seconds(self):
        for rec in self:
            if rec.display_seconds < 1:
                raise ValidationError(_("Display seconds must be at least 1."))
