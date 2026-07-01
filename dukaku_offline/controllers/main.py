import json
import logging

from odoo import http
from odoo.http import request
from odoo.tools import file_open
from odoo.addons.point_of_sale.controllers.main import PosController

_logger = logging.getLogger(__name__)


# ── Service-worker override ───────────────────────────────────────────────────
# Replace the stock helper so /pos/service-worker.js serves our enhanced SW.
# The route method (pos_web_service_worker) stays on PosController unchanged;
# only the body it reads is replaced.

def _dukaku_get_pos_service_worker(self):
    with file_open('dukaku_offline/static/src/app/service_worker.js') as f:
        return f.read()


PosController._get_pos_service_worker = _dukaku_get_pos_service_worker


# ── Manifest controller ───────────────────────────────────────────────────────

class DukakuOfflineController(http.Controller):

    @http.route('/pos/manifest.json', type='http', auth='public', methods=['GET'])
    def pos_manifest(self, config_id=None, **kwargs):
        """Return a Web App Manifest scoped to the given POS config.

        The <link rel="manifest"> in the POS template passes config_id as a
        query parameter so each POS config gets its own start_url — no
        hardcoding in any tracked file, and multi-tenant safe.
        """
        if not config_id:
            return request.make_response('config_id required', status=400)

        try:
            cid = int(config_id)
        except (ValueError, TypeError):
            return request.make_response('invalid config_id', status=400)

        # start_url must be the exact URL the SW has in its cache.
        # _get_url_to_cache() caches "/pos/ui/{id}" (no query string), so
        # start_url must match that string character-for-character.
        # The ?from_backend=True variant is cached separately and must NOT
        # be used here — it changes the JS boot context.
        start_url = f'/pos/ui/{cid}'

        manifest = {
            'id': f'/pos/ui/{cid}',
            'name': 'Dukaku POS',
            'short_name': 'Dukaku',
            'description': 'Dukaku Point of Sale',
            'start_url': start_url,
            'scope': '/pos/',
            'display': 'standalone',
            'orientation': 'any',
            'theme_color': '#1A1A1A',
            'background_color': '#1A1A1A',
            'icons': [
                {
                    'src': '/dukaku_offline/static/src/img/icon-192.png',
                    'sizes': '192x192',
                    'type': 'image/png',
                    'purpose': 'any',
                },
                {
                    'src': '/dukaku_offline/static/src/img/icon-512.png',
                    'sizes': '512x512',
                    'type': 'image/png',
                    'purpose': 'any',
                },
                {
                    'src': '/dukaku_offline/static/src/img/icon-512-maskable.png',
                    'sizes': '512x512',
                    'type': 'image/png',
                    'purpose': 'maskable',
                },
            ],
        }

        return request.make_response(
            json.dumps(manifest, indent=2),
            headers=[
                ('Content-Type', 'application/manifest+json'),
                # no-store: the SW is not supposed to cache this; the browser
                # fetches it once for install and re-checks it in background.
                ('Cache-Control', 'no-store'),
            ],
        )
