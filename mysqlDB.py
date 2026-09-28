from contextlib import contextmanager

import mysql.connector
from flask import current_app, g, has_request_context

from bin.config_utils import DBDATA as DB
from bin.appslib import handle_error


def init_app(app):
    """Release request-local connections, including when a view fails."""
    app.extensions['mysqlDB'] = True
    app.teardown_request(close_database_connections)


def close_database_connections(error=None):
    for connection in g.pop('_database_connections', {}).values():
        try:
            connection.close()
        except Exception as exc:
            handle_error(exc, log_path='./logs/errors.log')


@contextmanager
def _connection(user, password, host, database):
    request_local = has_request_context() and current_app.extensions.get('mysqlDB', False)
    connections = g.setdefault('_database_connections', {}) if request_local else {}
    key = (user, password, host, database)
    if key not in connections:
        connections[key] = mysql.connector.connect(
            user=user, password=password, host=host, database=database)
    connection = connections[key]
    try:
        yield connection
    finally:
        if not request_local:
            connection.close()


def _execute(query, params, user, password, host, database):
    with _connection(user, password, host, database) as connection:
        cursor = None
        try:
            cursor = connection.cursor()
            cursor.execute(query, params)
            if cursor.with_rows:
                return cursor.fetchall()
            connection.commit()
            return []
        except Exception:
            connection.rollback()
            raise
        finally:
            if cursor is not None:
                cursor.close()


def connect_to_database(queryA, userA=DB['user'], passwordA=DB['pass'], hostA=DB['host'], databaseA=DB['base']):
    """Read rows without committing; reuse the connection during a request."""
    return safe_connect_to_database(queryA, None, userA, passwordA, hostA, databaseA)


def safe_connect_to_database(queryA, queryB, userA=DB['user'], passwordA=DB['pass'], hostA=DB['host'], databaseA=DB['base']):
    try:
        return _execute(queryA, queryB, userA, passwordA, hostA, databaseA)
    except Exception as exc:
        handle_error(exc, log_path='./logs/errors.log')
        return []


def insert_to_database(queryA, queryB, userA=DB['user'], passwordA=DB['pass'], hostA=DB['host'], databaseA=DB['base']):
    try:
        _execute(queryA, queryB, userA, passwordA, hostA, databaseA)
    except Exception as exc:
        handle_error(exc, log_path='./logs/errors.log')
        return False
    return True


def delete_row_from_database(queryA, queryB, userA=DB['user'], passwordA=DB['pass'], hostA=DB['host'], databaseA=DB['base']):
    # Preserve the existing return value (None).
    insert_to_database(queryA, queryB, userA, passwordA, hostA, databaseA)
