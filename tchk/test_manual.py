import unittest
import tempfile
from pathlib import Path
from database import Database
from config import valid_url

class ManualTests(unittest.TestCase):
    def test_persistence_duplicates_and_statistics(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'db.sqlite3'
            db=Database(path)
            self.assertTrue(db.add('Velma','Москва','Адрес 1',123))
            self.assertFalse(db.add(' VELMA ',' Москва ',' адрес 1 ',123))
            self.assertTrue(db.add('Velma','Казань','Адрес 2',123))
            self.assertTrue(db.add('Other','Москва','Адрес 3',456))
            self.assertEqual(db.total(),3)
            self.assertEqual(len(db.organizations()),2)
            self.assertEqual(len(db.cities()),2)
            self.assertEqual(len(db.cities('velma')),2)
            self.assertEqual(db.points('velma','москва')[0]['address'],'Адрес 1')
            self.assertTrue(db.exists('VELMA'))
            self.assertFalse(db.exists('Unknown'))
            db.close()
            db=Database(path)
            self.assertEqual(db.total(),3)
            db.close()

    def test_existing_records_are_preserved(self):
        db=Database(':memory:')
        db.connection.execute('''INSERT INTO manual_points
            (organization,organization_key,city,city_key,url,address,created_by)
            VALUES (?,?,?,?,?,?,?)''',('Velma','velma','Москва','москва','https://example.org/1','Адрес 1',123))
        db.connection.commit()
        self.assertFalse(db.add('Velma','Москва','Адрес 1',123))
        self.assertTrue(db.add('Velma','Москва','Адрес 2',123))
        self.assertEqual(db.total(),2)
        self.assertEqual(db.points('velma','москва')[0]['url'],'https://example.org/1')
        db.close()

    def test_url_validation(self):
        self.assertTrue(valid_url('https://yandex.ru/maps/-/example'))
        for value in ['javascript:alert(1)','https://','https://user:pass@example.org','https://example.org/a b','https://example.org:abc']:
            self.assertFalse(valid_url(value))

if __name__=='__main__':
    unittest.main()
