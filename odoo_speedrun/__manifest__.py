{
    'name': 'Odoo Speedrun',
    'version': '19.0.2.0.0',
    'author': 'Scalizer',
    'category': 'Extra Tools',
    'summary': 'Multiplayer speedrun game - race to complete Odoo tasks!',
    'description': """
        Create game rooms, invite players, and race to complete
        random Odoo tasks (create invoices, products, contacts...)
        as fast as possible. Real-time updates via WebSocket.
    """,
    'depends': ['base', 'bus', 'web', 'auth_signup'],
    'data': [
        'security/speedrun_security.xml',
        'security/ir.model.access.csv',
        'data/speedrun_badge_data.xml',
        'data/speedrun_equipment_data.xml',
        'data/speedrun_equipment_sets.xml',
        'data/speedrun_matchmaking_cron.xml',
        'data/auth_signup_data.xml',
        'views/speedrun_task_views.xml',
        'views/speedrun_game_views.xml',
        'views/speedrun_tournament_views.xml',
        'views/speedrun_leaderboard_views.xml',
        'views/speedrun_profile_views.xml',
        'wizard/speedrun_task_import_views.xml',
        'views/speedrun_menus.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'odoo_speedrun/static/src/**/*.js',
            'odoo_speedrun/static/src/**/*.xml',
            'odoo_speedrun/static/src/**/*.scss',
        ],
    },
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}
