import json
import re

_ODOO_FOOTER_LINK_RE = re.compile(
    r'<a[^>]*(?:href|t-attf-href)="[^"]*odoo\.com[^"]*"[^>]*>\s*Odoo\s*</a>',
    re.IGNORECASE,
)

# auth_signup ships these 3 mail.template records (invite/welcome/portal-invite
# emails) inside a <data noupdate="1"> block. A <record> re-declaration of the
# same external id from another module is silently skipped by
# models._load_records() whenever the module is *updated* rather than freshly
# installed (only a fresh install honors the override) - see
# views/auth_signup_branding.xml for the longer explanation. So the footer
# link is patched here instead, via a direct write that isn't subject to that
# noupdate gate. body_html is stored as one jsonb blob per language
# (e.g. {"en_US": "...", "fr_FR": "..."}), so each language variant is patched
# independently - a raw SQL round-trip on the jsonb column is used rather than
# ORM field assignment to avoid any ambiguity about how a translated field
# handles a dict value passed to write().
_AUTH_SIGNUP_FOOTER_TEMPLATES = [
    'auth_signup.set_password_email',
    'auth_signup.mail_template_user_signup_account_created',
    'auth_signup.portal_set_password_email',
]


def _rebrand_auth_signup_emails(env):
    for xml_id in _AUTH_SIGNUP_FOOTER_TEMPLATES:
        template = env.ref(xml_id, raise_if_not_found=False)
        if not template:
            continue
        cr = env.cr
        cr.execute("SELECT body_html FROM mail_template WHERE id = %s", [template.id])
        row = cr.fetchone()
        raw = row[0] if row and row[0] else {}
        patched = {lang: _ODOO_FOOTER_LINK_RE.sub('Dukaku POS', html or '') for lang, html in raw.items()}
        if patched != raw:
            cr.execute(
                "UPDATE mail_template SET body_html = %s::jsonb WHERE id = %s",
                [json.dumps(patched), template.id],
            )


def _set_pos_home_action(env):
    action = env.ref('point_of_sale.action_pos_config_kanban')
    users = env['res.users'].search([('share', '=', False), ('active', '=', True)])
    users.write({'action_id': action.id})


def post_init_hook(env):
    _set_pos_home_action(env)
    _rebrand_auth_signup_emails(env)
