# -*- coding: utf-8 -*-
from odoo import _, models
from odoo.exceptions import AccessError


class DryCleaningAccessMixin(models.AbstractModel):
    """Centralized capability-authorization helper (Stage 6).

    Odoo's ir.model.access ACLs are model-level only - they cannot express
    "this group may call action_mark_ready but not action_pick_up", or
    "this group may print but not reprint". Every method in this module
    that needs that kind of finer-grained check calls _ensure_authorized()
    as its first line instead of repeating has_group() calls inline, so
    the capability -> group mapping lives in exactly one place.

    Mixed into dry_cleaning.ticket and dry_cleaning.garment_tag - both
    need capability checks (workflow transitions, printing, intake notes)
    and neither needs anything else from this class beyond the method
    below, so a plain AbstractModel mixin is enough; it carries no fields
    and needs no ACL/access rows of its own.
    """

    _name = "dry_cleaning.access.mixin"
    _description = "Dry Cleaning Capability Authorization"

    # capability name -> xmlid of the group that grants it. Deliberately
    # separate from the Manager check below: Manager is authorized for
    # every capability without needing its own entry here, and without
    # capability groups ever having to imply Manager (frozen Stage 5
    # decision - keeps the hierarchy narrow and one-directional).
    _CAPABILITY_GROUPS = {
        "process": "dukaku_dry_cleaning.group_dry_cleaning_can_process",
        "pickup": "dukaku_dry_cleaning.group_dry_cleaning_can_pickup",
        "reprint": "dukaku_dry_cleaning.group_dry_cleaning_can_reprint",
    }
    _MANAGER_GROUP = "dukaku_dry_cleaning.group_dry_cleaning_manager"

    def _ensure_authorized(self, capability):
        """Raise AccessError unless the current user holds `capability` or
        is a Dry Cleaning Manager.

        Server-side and unconditional: called from the lowest reusable
        business method (action_start/action_mark_ready/action_pick_up,
        action_print_garment_tags, action_update_intake_note), so it runs
        for every caller - UI button, barcode wizard, or direct RPC alike -
        regardless of what any view's groups= attribute hides.
        """
        user = self.env.user
        if user.has_group(self._MANAGER_GROUP):
            return
        group_xmlid = self._CAPABILITY_GROUPS.get(capability)
        if group_xmlid and user.has_group(group_xmlid):
            return
        raise AccessError(_(
            "You are not authorized to perform this action."
        ))
