def _set_pos_home_action(env):
    action = env.ref('point_of_sale.action_pos_config_kanban')
    users = env['res.users'].search([('share', '=', False), ('active', '=', True)])
    users.write({'action_id': action.id})


def post_init_hook(env):
    _set_pos_home_action(env)
