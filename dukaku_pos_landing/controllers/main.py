from odoo import http
from odoo.addons.web.controllers.home import Home


class PosLandingHome(Home):

    def _login_redirect(self, uid, redirect=None):
        # If an explicit redirect was passed in the request, honour it and fall through.
        if redirect:
            return super()._login_redirect(uid, redirect=redirect)

        user = http.request.env['res.users'].sudo().browse(uid)
        pos_groups = [
            'point_of_sale.group_pos_user',
            'point_of_sale.group_pos_manager',
        ]
        if any(user.has_group(g) for g in pos_groups):
            return '/odoo/point-of-sale'

        return super()._login_redirect(uid, redirect=redirect)
