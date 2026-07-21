{
    'name': 'Speedrun - Marketing',
    'version': '19.0.1.0.0',
    'author': 'Scalizer',
    'category': 'Extra Tools',
    'summary': 'Tâches Speedrun pour le Marketing (emailing, SMS, automatisation, événements, sondages)',
    'description': """
        Pack de tâches Speedrun. Installe automatiquement les applications Odoo
        du domaine et ajoute les tâches de speedrun correspondantes.
    """,
    'depends': ['odoo_speedrun', 'mass_mailing', 'mass_mailing_sms', 'marketing_automation', 'event', 'survey', 'appointment'],
    'data': [
        'data/speedrun_task_data.xml',
        'data/speedrun_task_group_data.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
