from . import pos_order
from . import offline_operation

from odoo.tools import config as _config

if _config.get("test_enable"):
    # Test-only handler registrations for dukaku_offline's own test suite -
    # see offline_operation_test_support.py for why this must be a real,
    # always-loadable module file rather than something defined inside
    # tests/, and why gating on test_enable keeps it out of any
    # production registry.
    from . import offline_operation_test_support
