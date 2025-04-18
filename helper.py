import os
import sqlite3
from queryrunner_client import Client
import logging
from querylist import query_to_fetch_uri

# Presto client for executing queries
qr_client = Client(user_email='mkanna3@ext.uber.com')
db_path = os.path.join(os.path.dirname(__file__), 'testcase_cache.db')
# Query for fetching test data

def create(epic_name):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    query = f"""
    CREATE TABLE IF NOT EXISTS "{epic_name}" (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      uri TEXT NOT NULL,
      uuid TEXT NOT NULL,
      last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """
    cursor.execute(query)
    conn.commit()
    conn.close()

def save_testcase(epic_name, uri, uuid):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    query = f'''
        INSERT INTO "{epic_name}" (uri, uuid) 
        VALUES (?, ?)
    '''
    cursor.execute(query, (uri, uuid))
    conn.commit()
    conn.close()

def update(epic_name):
    #conn = sqlite3.connect('testcase_cache.db')
    create(epic_name)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute(f'SELECT uri FROM "{epic_name}"')
    existing_uris = {row[0] for row in cursor.fetchall()}
    query = query_to_fetch_uri.format(epic_name=epic_name)
    result = qr_client.execute('presto', query)
    new_tests = [row for row in result.fetchall()]
    print("existing_uris",existing_uris)
    new_testcases = []
    for row in new_tests:
        if row['uri'] not in existing_uris:
            save_testcase(epic_name, row['uri'], row['uuid'])
            new_testcases.append({'uri': row['uri'], 'uuid': row['uuid']})
    conn.close()
    print("new_testcases",new_testcases)
    return new_testcases
