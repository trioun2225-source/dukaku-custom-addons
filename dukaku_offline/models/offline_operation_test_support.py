# -*- coding: utf-8 -*-
"""Test-only handler registrations for dukaku_offline's own test suite.

Only ever imported when tools.config['test_enable'] is set (see
models/__init__.py) - never part of a production registry.

Deliberately a real, always-loadable model file rather than something
defined inside tests/: Odoo imports an addon's tests/ package strictly
AFTER that addon's own model classes have already been collected into the
registry (registry.load(package) runs before loader.make_suite() imports
test files, even for that same addon's own post_install tests - confirmed
by reading odoo/modules/loading.py directly). A model class defined only
inside a test file is therefore never incorporated into the runtime class
MRO at all, for any test, at_install or post_install. This file exists
purely to satisfy that Odoo loading-order constraint while keeping the
registration itself genuinely test-only, gated on test_enable rather than
unconditionally shipped.
"""
from odoo import models

from .offline_operation import OfflineOperationRejected

TEST_ECHO_TYPE = "dukaku_offline.test_echo"
TEST_REJECT_TYPE = "dukaku_offline.test_reject"
TEST_REJECT_WITH_SNAPSHOT_TYPE = "dukaku_offline.test_reject_with_snapshot"
TEST_FLAKY_MUTATION_TYPE = "dukaku_offline.test_flaky_mutation"
TEST_STREAM_TYPE = "dukaku_offline.test_stream"

# Test-only, in-memory call counter keyed by a caller-supplied payload
# "key" - lets a test simulate "fails once, then succeeds on retry"
# without any persistent state of its own.
_flaky_state = {}


class _TestOfflineHandlerRegistry(models.AbstractModel):
    _inherit = "dukaku.offline.handler.registry"

    def _get_offline_handlers(self):
        handlers = super()._get_offline_handlers()
        handlers.update({
            TEST_ECHO_TYPE: self._offline_test_echo,
            TEST_REJECT_TYPE: self._offline_test_reject,
            TEST_REJECT_WITH_SNAPSHOT_TYPE: self._offline_test_reject_with_snapshot,
            TEST_FLAKY_MUTATION_TYPE: self._offline_test_flaky_mutation,
            TEST_STREAM_TYPE: self._offline_test_stream,
        })
        return handlers

    def _get_offline_stream_key(self, env, operation_type, payload):
        if operation_type == TEST_STREAM_TYPE:
            key = payload.get("stream")
            return f"test.stream:{key}" if key else None
        return super()._get_offline_stream_key(env, operation_type, payload)

    def _offline_test_echo(self, env, payload):
        return {"echo": payload, "uid": env.uid}

    def _offline_test_reject(self, env, payload):
        raise OfflineOperationRejected("TEST_REASON", "always rejects")

    def _offline_test_reject_with_snapshot(self, env, payload):
        raise OfflineOperationRejected(
            "TEST_STALE_STATE", "rejects with a snapshot", snapshot={"safe": "data"}
        )

    def _offline_test_stream(self, env, payload):
        if payload.get("fail"):
            raise OfflineOperationRejected("TEST_REASON", "stream member fails")
        return {"ok": True}

    def _offline_test_flaky_mutation(self, env, payload):
        """First call for a given payload['key'] mutates a real record then
        raises an UNEXPECTED (non-OfflineOperationRejected) error; a
        second call with the same key succeeds. Proves both rollback of
        the partial mutation and successful resumption on retry.
        """
        key = payload.get("key")
        attempt = _flaky_state.get(key, 0)
        _flaky_state[key] = attempt + 1
        partner = env["res.partner"].browse(payload["partner_id"])
        if attempt == 0:
            partner.write({"comment": "PARTIAL - SHOULD NOT PERSIST"})
            raise RuntimeError("simulated unexpected failure")
        partner.write({"comment": "COMMITTED"})
        return {"attempt": attempt + 1}
