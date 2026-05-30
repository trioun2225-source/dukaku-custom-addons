def migrate(cr, version):
    cr.execute("""
        UPDATE res_users
        SET action_id = (
            SELECT res_id
            FROM ir_model_data
            WHERE module = 'point_of_sale'
              AND name   = 'action_pos_config_kanban'
        )
        WHERE share  = false
          AND active = true
    """)
