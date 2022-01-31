# Copyright 2016 Quantopian, Inc.
# Copyright 2022 Jonathan Kamens
#
# Licensed under the Apache License, Version 2.0 (the "License"); you
# may not use this file except in compliance with the License.  You
# may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.  See the License for the specific language governing
# permissions and limitations under the License.

from coal_mine.mongo_store import MongoStore
from pymongo import MongoClient, IndexModel, ASCENDING
from pymongo.errors import OperationFailure
from unittest import TestCase
import uuid


class MongoStoreInitTests(TestCase):
    def setUp(self):
        self.db_hosts = ['localhost']
        self.db_name = "coal-mine-test-" + str(uuid.uuid4())
        self.db_conn = MongoClient()
        self.db = self.db_conn[self.db_name]

    def tearDown(self):
        self.db_conn.drop_database(self.db)

    def test_basic_init(self):
        MongoStore(self.db_hosts, self.db_name, None, None)
        pass

    def test_init_auth(self):
        with self.assertRaises(OperationFailure):
            MongoStore(self.db_hosts, self.db_name, 'nope', 'nope')

    def test_init_index_compatibility(self):
        collection = self.db['canaries']
        collection.create_indexes([IndexModel([('id', ASCENDING)])])
        existing_indexes = collection.index_information()
        self.assertNotIn('unique', existing_indexes['id_1'])
        MongoStore(self.db_hosts, self.db_name, None, None)
        new_existing_indexes = collection.index_information()
        self.assertTrue(new_existing_indexes['id_1']['unique'])
        # For code coverage, testing when is_unique is already True as it
        # should be.
        MongoStore(self.db_hosts, self.db_name, None, None)


class MongoStoreTests(TestCase):
    def setUp(self):
        self.db_hosts = ['localhost']
        self.db_name = "coal-mine-test-" + str(uuid.uuid4())
        self.db_conn = MongoClient()
        self.db = self.db_conn[self.db_name]
        self.store = MongoStore(self.db_hosts, self.db_name, None, None)

    def tearDown(self):
        self.db_conn.drop_database(self.db)

    def test_create(self):
        self.store.create({'id': 'abcdefgh'})

    def test_update_noop(self):
        self.store.create({'id': 'abcdefgh'})
        self.store.update('abcdefgh', {})

    def test_update_set(self):
        self.store.create({'id': 'abcdefgh'})
        self.store.update('abcdefgh', {'periodicity': 10})
        self.assertEqual(self.store.get('abcdefgh')['periodicity'], 10)

    def test_update_unset(self):
        self.store.create({'id': 'abcdefgh'})
        self.store.update('abcdefgh', {'periodicity': 10})
        self.store.update('abcdefgh', {'periodicity': None})
        self.assertNotIn('periodicity', self.store.get('abcdefgh'))

    def test_get_nonexistent(self):
        with self.assertRaises(KeyError):
            self.store.get('abcdefgh')

    def test_list(self):
        self.store.create({'id': 'abcdefgh', 'name': 'freedle',
                           'periodicity': 600, 'paused': False,
                           'late': False})
        iterator = self.store.list()
        next(iterator)
        with self.assertRaises(StopIteration):
            next(iterator)
        next(self.store.list(verbose=True))
        next(self.store.list(paused=False))
        next(self.store.list(late=False))
        next(self.store.list(order_by='deadline'))
        next(self.store.list(search=r'freedle'))

    def test_upcoming_deadlines(self):
        self.store.create({'id': 'abcdefgh', 'paused': False, 'late': False})
        next(self.store.upcoming_deadlines())

    def test_delete(self):
        self.store.create({'id': 'abcdefgh'})
        self.store.delete('abcdefgh')
        with self.assertRaises(KeyError):
            self.store.delete('abcdefgh')

    def test_find_identifier(self):
        self.store.create({'id': 'abcdefgh', 'slug': 'froodle'})
        self.assertEqual(self.store.find_identifier('froodle'), 'abcdefgh')
        with self.assertRaises(KeyError):
            self.store.find_identifier('freedle')
