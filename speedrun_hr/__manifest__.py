{
    'name': 'Speedrun - Ressources Humaines',
    'version': '19.0.1.0.0',
    'author': 'Scalizer',
    'category': 'Extra Tools',
    'summary': 'Tâches Speedrun pour les RH (employés, congés, notes de frais, recrutement, présences...)',
    'description': """
        Pack de tâches Speedrun. Installe automatiquement les applications Odoo
        du domaine et ajoute les tâches de speedrun correspondantes.
    """,
    'depends': ['odoo_speedrun', 'hr', 'hr_holidays', 'hr_expense', 'hr_recruitment', 'hr_attendance', 'hr_appraisal', 'hr_skills', 'hr_payroll', 'fleet', 'lunch', 'approvals'],
    'data': [
        'data/speedrun_task_data.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
