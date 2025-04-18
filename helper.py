import os
import sqlite3
from queryrunner_client import Client
import logging
from querylist import query_to_fetch_uri

# Presto client for executing queries
qr_client = Client(user_email='mkanna3@ext.uber.com')
db_path = os.path.join(os.path.dirname(__file__), 'testcase_cache.db')

# Initialize database if it doesn't exist
def init_db():
    try:
        conn = sqlite3.connect(db_path)
        conn.close()
        logging.info("Database initialized successfully")
    except Exception as e:
        logging.error(f"Failed to initialize database: {e}")
        raise

# Query for fetching test data

def create(epic_name):
    try:
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
        logging.info(f"Table {epic_name} created successfully")
    except Exception as e:
        logging.error(f"Failed to create table {epic_name}: {e}")
        raise

def save_testcase(epic_name, uri, uuid):
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        query = f'''
            INSERT INTO "{epic_name}" (uri, uuid)
            VALUES (?, ?)
        '''
        cursor.execute(query, (uri, uuid))
        conn.commit()
        conn.close()
        logging.info(f"Test case saved successfully for {epic_name}")
    except Exception as e:
        logging.error(f"Failed to save test case: {e}")
        raise

def update(epic_name):
    try:
        # Ensure database exists
        init_db()
        # Create table if it doesn't exist
        create(epic_name)

        conn = sqlite3.connect(db_path, check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute(f'SELECT uri FROM "{epic_name}"')
        existing_uris = {row[0] for row in cursor.fetchall()}
        query = query_to_fetch_uri.format(epic_name=epic_name)
        result = qr_client.execute('presto', query)
        new_tests = [row for row in result.fetchall()]
        logging.info(f"Found {len(existing_uris)} existing URIs")

        new_testcases = []
        for row in new_tests:
            if row['uri'] not in existing_uris:
                save_testcase(epic_name, row['uri'], row['uuid'])
                new_testcases.append({'uri': row['uri'], 'uuid': row['uuid']})
        conn.close()
        logging.info(f"Added {len(new_testcases)} new test cases")
        return new_testcases
    except Exception as e:
        logging.error(f"Failed to update test cases: {e}")
        raise
