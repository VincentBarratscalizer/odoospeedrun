{
    'name': 'Speedrun - Ventes',
    'version': '19.0.1.0.0',
    'author': 'Scalizer',
    'category': 'Extra Tools',
    'summary': 'Tâches Speedrun pour le domaine Ventes (devis, abonnements, location)',
    'description': """
        Pack de tâches Speedrun. Installe automatiquement les applications Odoo
        du domaine et ajoute les tâches de speedrun correspondantes.
    """,
    'depends': ['odoo_speedrun', 'sale', 'sale_subscription', 'sale_renting'],
    'data': [
        'data/speedrun_task_data.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
