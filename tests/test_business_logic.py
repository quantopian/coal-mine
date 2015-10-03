# Copyright 2015 Quantopian, Inc.
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

from coal_mine.business_logic import \
    AlreadyExistsError, AlreadyPausedError, AlreadyUnpausedError, BusinessLogic
from coal_mine.memory_store import MemoryStore
import smtplib
import time
from unittest import TestCase
from unittest.mock import patch


class BusinessLogicTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.store = MemoryStore()
        cls.logic = BusinessLogic(cls.store, 'example@example.com')

    def test_noop(self):
        # Just tests that setUpClass() doesn't crash.
        pass

    def test_create(self):
        created = self.logic.create(name='test_create', periodicity=12345)
        fetched = self.logic.get(created['id'])
        self.assertEqual(created, fetched)

    def test_create_invalid(self):
        with self.assertRaises(TypeError):
            self.logic.create(name=2, periodicity=12346)
        with self.assertRaises(TypeError):
            self.logic.create(name='', periodicity=12346)
        self.logic.create(name='test_create_invalid', periodicity=12346)
        with self.assertRaises(AlreadyExistsError):
            self.logic.create(name='test_create_invalid', periodicity=12346)
        with self.assertRaises(TypeError):
            self.logic.create(name='test_create_invalid2', periodicity='abc')
        with self.assertRaises(TypeError):
            self.logic.create(name='test_create_invalid2', periodicity=-1)
        with self.assertRaises(TypeError):
            self.logic.create(name='test_create_invalid2', periodicity=12346,
                              description=2)
        with self.assertRaises(TypeError):
            self.logic.create(name='test_create_invalid2', periodicity=12346,
                              emails='test_create_invalid@example.com')
        with self.assertRaises(TypeError):
            self.logic.create(name='test_create_invalid2', periodicity=12346,
                              paused='abc')

    def test_create_emails_none(self):
        self.logic.create(name='test_create_emails_none',
                          periodicity=12347,
                          emails=None)

    def test_update(self):
        created = self.logic.create(name='test_update',
                                    periodicity=12347)
        self.logic.update(created['id'],
                          name='test_update2',
                          periodicity=12348,
                          description='test_update2 description',
                          emails=['test_update@example.com'])
        fetched = self.logic.get(created['id'])
        self.assertEqual(fetched['name'], 'test_update2')
        self.assertEqual(fetched['periodicity'], 12348)
        self.assertEqual(fetched['description'], 'test_update2 description')
        self.assertEqual(fetched['emails'], ['test_update@example.com'])

    def test_update_invalid(self):
        created = self.logic.create(name='test_update_invalid',
                                    periodicity=12349)
        with self.assertRaises(TypeError):
            self.logic.update(created['id'], name=2)
        with self.assertRaises(TypeError):
            self.logic.update(created['id'], name='')
        self.logic.create(name='test_update_invalid2', periodicity=12350)
        with self.assertRaises(AlreadyExistsError):
            self.logic.update(created['id'], name='test_update_invalid2')
        with self.assertRaises(TypeError):
            self.logic.update(created['id'], periodicity='abc')
        with self.assertRaises(TypeError):
            self.logic.update(created['id'], periodicity=-1)
        with self.assertRaises(TypeError):
            self.logic.update(created['id'], description=2)
        with self.assertRaises(TypeError):
            self.logic.update(created['id'],
                              emails='test_update_invalid@example.com')
        with self.assertRaises(ValueError):
            self.logic.update(created['id'])

    def test_update_late_change(self):
        created = self.logic.create(name='test_update_late_change',
                                    periodicity=12351)
        time.sleep(1)
        self.logic.update(created['id'], periodicity=1)

    def test_trigger(self):
        created = self.logic.create(name='test_trigger', periodicity=12352)
        self.logic.trigger(created['id'])
        self.logic.trigger(created['id'], comment='test_trigger comment')

    def test_trigger_late(self):
        created = self.logic.create(name='test_trigger_late', periodicity=1)
        time.sleep(1.1)
        self.logic.trigger(created['id'])

    def test_trigger_paused(self):
        created = self.logic.create(name='test_trigger_paused',
                                    periodicity=12353,
                                    paused=True)
        self.logic.trigger(created['id'])

    def test_pause(self):
        created = self.logic.create(name='test_pause', periodicity=1)
        time.sleep(1.1)
        self.logic.pause(created['id'])
        with self.assertRaises(AlreadyPausedError):
            self.logic.pause(created['id'])
        self.logic.unpause(created['id'])
        with self.assertRaises(AlreadyUnpausedError):
            self.logic.unpause(created['id'])
        self.logic.pause(created['id'], comment='test_pause pause comment')
        self.logic.unpause(created['id'],
                           comment='test_pause unpause comment')

    def test_delete(self):
        created = self.logic.create(name='test_delete', periodicity=12354)
        self.logic.get(created['id'])
        self.logic.delete(created['id'])
        with self.assertRaises(KeyError):
            self.logic.get(created['id'])

    def test_list(self):
        self.logic.list()

    def test_notify(self):
        with patch('smtplib.SMTP'):
            created = self.logic.create(name='test_notify',
                                        periodicity=1,
                                        emails=['test_notify@example.com'])
            time.sleep(1.1)
            self.logic.trigger(created['id'])
        with patch.object(smtplib.SMTP, 'connect', side_effect=Exception):
            time.sleep(1.1)
            self.logic.trigger(created['id'])
        # Not needed for test, but let's clean up after ourselves to avoid
        # unwanted notifications while other tests are running!
        self.logic.delete(created['id'])

    def test_find_identifier(self):
        created = self.logic.create(name='test_find_identifier',
                                    periodicity=12355)
        self.assertEqual(created['id'],
                         self.logic.find_identifier(identifier=created['id']))
        self.assertEqual(created['id'],
                         self.logic.find_identifier(name=created['name']))

    def test_find_identifier_invalid(self):
        with self.assertRaisesRegexp(Exception, 'Must specify'):
            self.logic.find_identifier()
        with self.assertRaisesRegexp(Exception, 'Specify only one'):
            self.logic.find_identifier(name='foo', slug='bar')

    def test_add_history(self):
        history = []
        self.logic.add_history(history, None)
        for i in range(1000):
            self.logic.add_history(history, str(i))

    def test_add_history_invalid(self):
        history = []
        with self.assertRaises(TypeError):
            self.logic.add_history(history, 2)

    def test_schedule_next_deadline(self):
        # Make sure StopIteration is handled properly when there are no
        # active canaries.
        self.store.canaries.clear()
        self.logic.schedule_next_deadline()
