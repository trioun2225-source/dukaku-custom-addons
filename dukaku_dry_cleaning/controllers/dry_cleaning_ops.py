# -*- coding: utf-8 -*-
"""Stage 8B: Dry Cleaning Operations Workspace - route, service worker, and
read-sync endpoint.

Deliberately NOT the POS controller and NOT built on point_of_sale's route/
session machinery: loading this workspace never requires an open
pos.session and never requires point_of_sale.group_pos_user (Stage 8B
review, §5/§35 - group_pos_user grants real CRUD on pos.order/pos.payment/
pos.session, which a processing-only employee must never receive merely to
reach this screen).

Access is gated on the existing, frozen Dry Cleaning capability model
(dry_cleaning.access.mixin._ensure_authorized("process")) - the same single
source of truth the business methods themselves already enforce. This is
enforced here server-side, at the route itself, not only by hiding a
navigation link (Stage 8B §8).
"""
import logging

from odoo import http
from odoo.exceptions import AccessError
from odoo.http import request
from odoo.tools import file_open

_logger = logging.getLogger(__name__)


def _ops_authorized():
    """True if the current authenticated user may load the workspace.

    Mirrors exactly what dry_cleaning.access.mixin._ensure_authorized
    already enforces for the "process" capability (internal user + Can
    Process or Manager) - reusing that single existing check rather than
    re-declaring the group xmlids here, so there is exactly one place that
    defines what "may process dry cleaning" means.
    """
    user = request.env.user
    if not user._is_internal():
        return False
    try:
        request.env["dry_cleaning.ticket"]._ensure_authorized("process")
    except AccessError:
        return False
    return True


class DryCleaningOpsController(http.Controller):

    # Route disabled pending frontend (static/src/ops/ does not exist on
    # disk yet - see the module manifest's assets_ops bundle) and pending
    # Claude architecture/security review of the Stage 8A/8B backend. Do
    # not re-enable until both have landed. See "Stage 8A Remediation &
    # Review Prep" task spec.
    # @http.route("/dukaku_dry_cleaning/ops", type="http", auth="user")
    def dry_cleaning_ops_shell(self, **kwargs):
        """Serve the Dry Cleaning Operations workspace application shell.

        Denies at the route itself (not merely by hiding a link) when the
        authenticated user lacks the required capability - a direct/typed-
        in URL gets exactly the same denial as a hidden navigation item
        would have prevented (Stage 8B §8).
        """
        if not _ops_authorized():
            response = request.render("dukaku_dry_cleaning.ops_unauthorized", {})
            response.status_code = 403
            return response

        session_info = request.env["ir.http"].session_info()
        response = request.render("dukaku_dry_cleaning.ops_index", {
            "session_info": session_info,
        })
        # Never cached by an intermediary - this page embeds this user's
        # own live session bootstrap data.
        response.headers["Cache-Control"] = "no-store"
        return response

    # Route disabled: file_open() below targets
    # static/src/ops/service_worker.js, which does not exist on disk yet.
    # Reachable would mean an unconditional FileNotFoundError. Same
    # re-enable condition as dry_cleaning_ops_shell above.
    # @http.route("/dukaku_dry_cleaning/ops/service-worker.js", type="http", auth="user")
    def dry_cleaning_ops_service_worker(self):
        """Serve the workspace's own, narrowly-scoped service worker.

        auth='user': matches dukaku_offline's existing POS service-worker
        route convention - an unauthenticated request still gets a 303 to
        the login page rather than the worker script, so a genuinely
        unauthenticated browser is never handed even the static shell
        caching logic under this scope.
        """
        with file_open("dukaku_dry_cleaning/static/src/ops/service_worker.js") as f:
            body = f.read()
        return request.make_response(
            body,
            headers=[
                ("Content-Type", "text/javascript"),
                # Confines the worker to exactly this workspace's own URL
                # tree - it must never intercept POS, the backend webclient,
                # or any other route (Stage 8B §9).
                ("Service-Worker-Allowed", "/dukaku_dry_cleaning/ops"),
            ],
        )

    # Route disabled: no frontend exists yet to consume this endpoint, and
    # the backend method it calls has not had a Claude review pass. The
    # underlying model method (dry_cleaning.ticket._ops_read_sync) stays
    # enabled and covered by tests - only this HTTP surface is disabled.
    # @http.route("/dukaku_dry_cleaning/ops/read_sync", type="jsonrpc", auth="user")
    def dry_cleaning_ops_read_sync(self, cursor=None, limit=200):
        """Authenticated, closed-shape, cursor-based read-only feed.

        All authorization, field minimization, and record-rule scoping
        happen inside dry_cleaning.ticket._ops_read_sync() (called under
        this request's own non-sudo env) - this controller only adapts the
        HTTP/RPC boundary and never widens what that method already
        decides to return. Not part of Stage 8A's mutation architecture;
        see that method's own docstring.
        """
        return request.env["dry_cleaning.ticket"]._ops_read_sync(
            cursor=cursor, limit=limit,
        )
