import sqlite3
import unicodedata
import hashlib

def normalize(value):
    return ' '.join(unicodedata.normalize('NFKC', value).casefold().split())

class Database:
    def __init__(self, path):
        self.connection = sqlite3.connect(path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute('''CREATE TABLE IF NOT EXISTS manual_points (
            id INTEGER PRIMARY KEY, organization TEXT NOT NULL, organization_key TEXT NOT NULL,
            city TEXT NOT NULL, city_key TEXT NOT NULL, url TEXT NOT NULL, address TEXT NOT NULL,
            created_by INTEGER NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(organization_key, city_key, url))''')
        self.connection.commit()

    def add(self, organization, city, address, user_id):
        organization_key,city_key,address_key = normalize(organization),normalize(city),normalize(address)
        with self.connection:
            self.connection.execute('BEGIN IMMEDIATE')
            existing = self.connection.execute('SELECT address FROM manual_points WHERE organization_key=? AND city_key=?',
                                               (organization_key,city_key)).fetchall()
            if any(normalize(row['address']) == address_key for row in existing):
                return False
            # Keep the legacy NOT NULL/UNIQUE column so old databases need no destructive migration.
            internal_key = 'manual:'+hashlib.sha256(address_key.encode('utf-8')).hexdigest()
            cursor = self.connection.execute('''INSERT OR IGNORE INTO manual_points
                (organization,organization_key,city,city_key,url,address,created_by) VALUES (?,?,?,?,?,?,?)''',
                (organization,organization_key,city,city_key,internal_key,address,user_id))
        return cursor.rowcount == 1

    def organizations(self):
        return self.connection.execute('''SELECT organization_key AS key, MIN(organization) AS name,
            COUNT(*) AS count FROM manual_points GROUP BY organization_key ORDER BY organization_key''').fetchall()

    def cities(self, organization_key=None):
        where = 'WHERE organization_key=?' if organization_key is not None else ''
        return self.connection.execute(f'''SELECT city_key AS key, MIN(city) AS name, COUNT(*) AS count
            FROM manual_points {where} GROUP BY city_key ORDER BY city_key''',
            (organization_key,) if organization_key is not None else ()).fetchall()

    def points(self, organization_key, city_key):
        return self.connection.execute('SELECT * FROM manual_points WHERE organization_key=? AND city_key=? ORDER BY id',
                                       (organization_key,city_key)).fetchall()

    def exists(self, name):
        return self.connection.execute('SELECT 1 FROM manual_points WHERE organization_key=? LIMIT 1',
                                       (normalize(name),)).fetchone() is not None

    def total(self):
        return self.connection.execute('SELECT COUNT(*) FROM manual_points').fetchone()[0]

    def find_addresses(self, query):
        key = normalize(query)
        if not key:
            return []
        rows = self.connection.execute(
            'SELECT * FROM manual_points ORDER BY organization_key, city_key, id').fetchall()
        matches = [row for row in rows if key in normalize(row['address'])]
        # Show exact matches first, followed by partial matches.
        return sorted(matches, key=lambda row: normalize(row['address']) != key)

    def point(self, point_id):
        return self.connection.execute('SELECT * FROM manual_points WHERE id=?',(point_id,)).fetchone()

    def delete(self, point_id):
        with self.connection:
            cursor = self.connection.execute('DELETE FROM manual_points WHERE id=?',(point_id,))
        return cursor.rowcount == 1

    def close(self):
        self.connection.close()
