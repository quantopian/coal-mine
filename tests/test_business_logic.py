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

from coal_mine.business_logic import (
    AlreadyExistsError,
    AlreadyPausedError,
    AlreadyUnpausedError,
    CanaryNotFoundError,
    BusinessLogic,
)
from coal_mine.memory_store import MemoryStore
from coal_mine.mongo_store import MongoStore
from datetime import datetime, timedelta
import signal
import smtplib
import time
from unittest import TestCase
from unittest.mock import patch
import uuid


class MemoryStoreTester(object):
    def get_store(self):
        return MemoryStore()

    def free_store(self):
        pass


class MongoStoreTester(object):
    def get_store(self):
        self.db_hosts = ['localhost']
        self.db_name = "coal-mine-test-" + str(uuid.uuid4())
        return MongoStore(self.db_hosts, self.db_name, None, None)

    def free_store(self):
        self.store.db.client.drop_database(self.db_name)


class BusinessLogicTests(object):
    def setUp(self):
        self.store = self.get_store()
        self.logic = BusinessLogic(self.store, 'example@example.com')

    def tearDown(self):
        signal.alarm(0)
        signal.signal(signal.SIGALRM, signal.SIG_DFL)
        self.free_store()

    def test_noop(self):
        # Just tests that setUp() and tearDown() don't crash.
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

    def test_update_same_slug(self):
        created = self.logic.create(name='test_update_same_slug',
                                    periodicity=5)
        self.logic.update(created['id'], name='Test_Update_Same_Slug')
        fetched = self.logic.get(created['id'])
        self.assertEqual(fetched['name'], 'Test_Update_Same_Slug')
        self.assertEqual(created['slug'], fetched['slug'])

    def test_update_paused(self):
        created = self.logic.create('test_update_paused', periodicity=5)
        self.logic.pause(created['id'])
        self.logic.update(created['id'], periodicity=10)
        fetched = self.logic.get(created['id'])
        self.assertNotIn('deadline', fetched)

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
        fetched = self.logic.get(created['id'])
        # Note that this test is mostly for code coverage, but we should at
        # least check that the change we expected is there.
        self.assertNotEqual(created['periodicity'], fetched['periodicity'])

    def test_update_not_found(self):
        with self.assertRaises(CanaryNotFoundError):
            self.logic.update('testunfo', name='test_update_not_found')

    def test_store_unset(self):
        created = self.logic.create('foo', 20)
        self.logic.pause(created['id'])

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

    def test_trigger_not_found(self):
        with self.assertRaises(CanaryNotFoundError):
            self.logic.trigger('testtnfo')

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

    def test_pause_not_found(self):
        with self.assertRaises(CanaryNotFoundError):
            self.logic.pause('testpnfo')

    def test_unpause_not_found(self):
        with self.assertRaises(CanaryNotFoundError):
            self.logic.unpause('testunfo')

    def test_delete(self):
        created = self.logic.create(name='test_delete', periodicity=12354)
        self.logic.get(created['id'])
        self.logic.delete(created['id'])
        with self.assertRaises(CanaryNotFoundError):
            self.logic.get(created['id'])

    def test_delete_not_found(self):
        with self.assertRaises(CanaryNotFoundError):
            self.logic.delete('testdnfo')

    def test_list(self):
        self.logic.list()

    def test_list_no_paused_canaries(self):
        self.logic.create('not-paused', 20)
        self.assertEqual(next(self.logic.list())['name'], 'not-paused')
        self.assertEqual(next(self.logic.list(paused=False))['name'],
                         'not-paused')
        with self.assertRaises(StopIteration):
            next(self.logic.list(paused=True))

    def test_list_only_paused_canary(self):
        self.logic.create('paused', 20, paused=True)
        self.assertEqual(next(self.logic.list())['name'], 'paused')
        self.assertEqual(next(self.logic.list(paused=True))['name'],
                         'paused')
        with self.assertRaises(StopIteration):
            next(self.logic.list(paused=False))

    def test_list_paused_and_unpaused_canary(self):
        self.logic.create('not-paused', 10)
        self.logic.create('paused', 20, paused=True)
        iterator = self.logic.list()
        self.assertEqual(set((next(iterator)['name'], next(iterator)['name'])),
                         set(('not-paused', 'paused')))
        iterator = self.logic.list(paused=True)
        self.assertEqual(next(iterator)['name'], 'paused')
        with self.assertRaises(StopIteration):
            next(iterator)
        iterator = self.logic.list(paused=False)
        self.assertEqual(next(iterator)['name'], 'not-paused')
        with self.assertRaises(StopIteration):
            next(iterator)

    def test_list_no_late_canaries(self):
        self.logic.create('not-late', 20)
        self.assertEqual(next(self.logic.list())['name'], 'not-late')
        self.assertEqual(next(self.logic.list(late=False))['name'],
                         'not-late')
        with self.assertRaises(StopIteration):
            next(self.logic.list(late=True))

    def test_list_only_late_canary(self):
        self.logic.create('late', 1)
        time.sleep(1.1)
        self.assertEqual(next(self.logic.list())['name'], 'late')
        self.assertEqual(next(self.logic.list(late=True))['name'],
                         'late')
        with self.assertRaises(StopIteration):
            next(self.logic.list(late=False))

    def test_list_late_and_not_late_canary(self):
        self.logic.create('late', 1)
        self.logic.create('not-late', 20)
        time.sleep(1.1)
        iterator = self.logic.list()
        self.assertEqual(set((next(iterator)['name'], next(iterator)['name'])),
                         set(('not-late', 'late')))
        iterator = self.logic.list(late=True)
        self.assertEqual(next(iterator)['name'], 'late')
        with self.assertRaises(StopIteration):
            next(iterator)
        iterator = self.logic.list(late=False)
        self.assertEqual(next(iterator)['name'], 'not-late')
        with self.assertRaises(StopIteration):
            next(iterator)

    def test_list_search(self):
        self.logic.create('foo', 20)
        next(self.logic.list(search='foo'))
        with self.assertRaises(StopIteration):
            next(self.logic.list(search='froodlefreedle'))
        next(self.logic.list(verbose=True))

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
        with self.assertRaisesRegex(Exception, 'Must specify'):
            self.logic.find_identifier()
        with self.assertRaisesRegex(Exception, 'Specify only one'):
            self.logic.find_identifier(name='foo', slug='bar')

    def test_find_identifier_slug_not_found(self):
        with self.assertRaisesRegex(
                CanaryNotFoundError,
                r"'slug': 'test-find-identifier-slug-not-found'"):
            self.logic.find_identifier(
                slug='test-find-identifier-slug-not-found')

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
        self.logic.schedule_next_deadline()

    def test_periodicity_numeric(self):
        created = self.logic.create(name='test_periodicity_numeric',
                                    periodicity=1200)
        delta = (created['deadline'] - datetime.utcnow()).total_seconds()
        self.assertAlmostEqual(delta / 10, 120, places=0)

    def test_periodicity_schedule_inactive(self):
        now = datetime.utcnow()
        midnight_tomorrow = (now + timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0)
        tomorrow_schedule = '* * * * {} 1200'.format(
            midnight_tomorrow.isoweekday())
        created = self.logic.create(name='test_periodicity_schedule_inactive',
                                    periodicity=tomorrow_schedule)
        delta = (created['deadline'] - midnight_tomorrow).total_seconds()
        self.assertAlmostEqual(delta / 10, 120, places=0)

    def test_periodicity_schedule_active(self):
        now = datetime.utcnow()
        created = self.logic.create(name='test_periodicity_schedule_active',
                                    periodicity='* * * * * 1200')
        delta = (created['deadline'] - now).total_seconds()
        self.assertAlmostEqual(delta / 10, 120, places=0)

    def test_periodicity_invalid(self):
        with self.assertRaises(TypeError):
            self.logic.create(name='test_periodicity_invalid',
                              periodicity='* * * * 1200')

    def test_periodicity_invalid_newline(self):
        with self.assertRaises(TypeError):
            self.logic.create(name='test_periodicity_invalid_newline',
                              periodicity='* * * * sat 1200\n* * * * sun 400')

    def test_periodicity_invalid_command(self):
        with self.assertRaises(TypeError):
            self.logic.create(name='test_periodicity_invalid_command',
                              periodicity='* * * * * froodle')

    def test_periodicity_invalid_negative(self):
        with self.assertRaises(TypeError):
            self.logic.create(name='test_periodicity_invalid_negative',
                              periodicity='* * * * * -1')

    def test_periodicity_invalid_overlapping(self):
        with self.assertRaises(TypeError):
            self.logic.create(name='test_periodicity_invalid_overlapping',
                              periodicity='* * * * * 30; * * * * * 60')

    def test_periodicity_delta_case_2(self):
        periodicity = '* 0 * * * 120'
        whence = datetime(2016, 6, 30, 1, 0)
        delta = self.logic.calculate_periodicity_delta(periodicity, whence)
        next_deadline = whence + delta
        self.assertEqual(next_deadline, datetime(2016, 7, 1, 0, 2))

    def test_periodicity_delta_case_3(self):
        periodicity = '* 0 * * * 120'
        whence = datetime(2016, 6, 30, 0, 59)
        delta = self.logic.calculate_periodicity_delta(periodicity, whence)
        next_deadline = whence + delta
        self.assertEqual(next_deadline, datetime(2016, 7, 1, 0, 2))

    def test_periodicity_delta_case_4(self):
        periodicity = '* 0 * * * 120; * 1 * * * 600'
        whence = datetime(2016, 6, 30, 0, 59)
        delta = self.logic.calculate_periodicity_delta(periodicity, whence)
        next_deadline = whence + delta
        self.assertEqual(next_deadline, datetime(2016, 6, 30, 1, 9))

    def test_deadline_handler_next_deadline(self):
        self.logic.create(name='sooner', periodicity=1)
        later = self.logic.create(name='later', periodicity=2)
        time.sleep(1.1)
        next_deadline = next(self.store.upcoming_deadlines())
        self.assertEqual(later['name'], next_deadline['name'])


class BusinessLogicMemoryTests(MemoryStoreTester, BusinessLogicTests,
                               TestCase):
    pass


class BusinessLogicMongoTests(MongoStoreTester, BusinessLogicTests,
                              TestCase):
    pass
