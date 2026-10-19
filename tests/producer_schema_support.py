"""Exact empty future-layer removal for historical schema43/44 fixtures."""
def remove_schema46(connection):
    for table in ('mentat_project_producer_outputs','mentat_project_producer_stops','mentat_project_producer_bindings'):
        if connection.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]:
            raise AssertionError('Historical fixture cannot discard producer evidence')
    view=connection.execute("SELECT sql FROM sqlite_master WHERE name='mentat_retained_attachments'").fetchone()[0]
    connection.execute('DROP VIEW mentat_retained_attachments')
    prior=view.split('UNION SELECT attachment_id FROM mentat_project_producer_outputs')[0]
    connection.execute(prior)
    for name in ('binding','stop','output'):
        connection.execute('DROP TRIGGER mentat_project_producer_'+name+'_immutable')
        connection.execute('DROP TRIGGER mentat_project_producer_'+name+'_retained')
    for table in ('mentat_project_producer_outputs','mentat_project_producer_stops','mentat_project_producer_bindings'):
        connection.execute('DROP TABLE '+table)
    connection.execute('DELETE FROM schema_migrations WHERE version=46')
