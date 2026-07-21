{
    'name': 'Speedrun - Fabrication',
    'version': '19.0.1.0.0',
    'author': 'Scalizer',
    'category': 'Extra Tools',
    'summary': 'Tâches Speedrun pour la Fabrication (OF, nomenclatures, qualité, réparation, maintenance)',
    'description': """
        Pack de tâches Speedrun. Installe automatiquement les applications Odoo
        du domaine et ajoute les tâches de speedrun correspondantes.
    """,
    'depends': ['odoo_speedrun', 'mrp', 'mrp_plm', 'quality_control', 'repair', 'maintenance'],
    'data': [
        'data/speedrun_task_data.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
