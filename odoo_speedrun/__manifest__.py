{
    'name': 'Odoo Speedrun',
    'version': '19.0.1.0.0',
    'category': 'Extra Tools',
    'summary': 'Multiplayer speedrun game - race to complete Odoo tasks!',
    'description': """
        Create game rooms, invite players, and race to complete
        random Odoo tasks (create invoices, products, contacts...)
        as fast as possible. Real-time updates via WebSocket.
    """,
    'depends': ['base', 'bus', 'web'],
    'data': [
        'security/speedrun_security.xml',
        'security/ir.model.access.csv',
        'data/speedrun_task_data.xml',
        'views/speedrun_task_views.xml',
        'views/speedrun_game_views.xml',
        'views/speedrun_leaderboard_views.xml',
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
