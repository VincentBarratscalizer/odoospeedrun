{
    'name': 'Speedrun - CRM',
    'version': '19.0.1.0.0',
    'author': 'Scalizer',
    'category': 'Extra Tools',
    'summary': 'Tâches Speedrun pour le domaine CRM (pistes, opportunités)',
    'description': """
        Pack de tâches Speedrun. Installe automatiquement les applications Odoo
        du domaine et ajoute les tâches de speedrun correspondantes.
    """,
    'depends': ['odoo_speedrun', 'crm'],
    'data': [
        'data/speedrun_task_data.xml',
        'data/speedrun_task_group_data.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
