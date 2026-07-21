{
    'name': 'Speedrun - Projet',
    'version': '19.0.1.0.0',
    'author': 'Scalizer',
    'category': 'Extra Tools',
    'summary': 'Tâches Speedrun pour les Projets (tâches, feuilles de temps, planning, services sur site)',
    'description': """
        Pack de tâches Speedrun. Installe automatiquement les applications Odoo
        du domaine et ajoute les tâches de speedrun correspondantes.
    """,
    'depends': ['odoo_speedrun', 'project', 'hr_timesheet', 'planning', 'industry_fsm', 'project_todo'],
    'data': [
        'data/speedrun_task_data.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
