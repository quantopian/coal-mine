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

from coal_mine.crontab_schedule import \
    CronTabSchedule, CronTabScheduleException, FastCronTab
from datetime import datetime, timedelta
import time
from unittest import TestCase

SCHEDULE = '''
# This is a comment.
    *          * * * Sun 300

# Leave the blank line above and this comment in place.
    * 22-23,0-12 * * Mon-Fri 300
 0-29         13 * * Mon-Fri 300
30-59         13 * * Mon-Fri 90
    *      14-21 * * Mon-Fri 90
'''

MULTI_SCHEDULE = '''
* 0-11 * * * A
* 7-18 * * * B
* 12-23 * * * C
'''

GAP_SCHEDULE = '''
* 12-23 * * * A
'''

GAP_EXPECTED = [
    (datetime(2015, 1, 1, 0, 0), datetime(2015, 1, 1, 11, 59), None),
    (datetime(2015, 1, 1, 12, 0), datetime(2015, 1, 1, 12, 1), ('A',))]

FIXED_EXPECTED = [
    (datetime(2015, 1, 1, 0, 0), datetime(2015, 1, 1, 13, 29), '300'),
    (datetime(2015, 1, 1, 13, 30), datetime(2015, 1, 1, 21, 59), '90'),
    (datetime(2015, 1, 1, 22, 0), datetime(2015, 1, 2, 13, 29), '300'),
    (datetime(2015, 1, 2, 13, 30), datetime(2015, 1, 2, 21, 59), '90'),
    (datetime(2015, 1, 2, 22, 0), datetime(2015, 1, 2, 23, 59), '300'),
    (datetime(2015, 1, 3, 0, 0), datetime(2015, 1, 3, 23, 59), None),
    (datetime(2015, 1, 4, 0, 0), datetime(2015, 1, 5, 13, 29), '300'),
    (datetime(2015, 1, 5, 13, 30), datetime(2015, 1, 5, 21, 59), '90'),
    (datetime(2015, 1, 5, 22, 0), datetime(2015, 1, 6, 13, 29), '300'),
    (datetime(2015, 1, 6, 13, 30), datetime(2015, 1, 6, 21, 59), '90'),
    (datetime(2015, 1, 6, 22, 0), datetime(2015, 1, 7, 13, 29), '300'),
    (datetime(2015, 1, 7, 13, 30), datetime(2015, 1, 7, 21, 59), '90'),
    (datetime(2015, 1, 7, 22, 0), datetime(2015, 1, 8, 0, 0), '300')
]

DYNAMIC_EXPECTED = [
    (datetime(2015, 1, 1, 0, 0), datetime(2015, 1, 1, 13, 29), '300'),
    (datetime(2015, 1, 1, 13, 30), datetime(2015, 1, 1, 21, 59), '90'),
    (datetime(2015, 1, 1, 22, 0), datetime(2015, 1, 2, 13, 29), '300'),
    (datetime(2015, 1, 2, 13, 30), datetime(2015, 1, 2, 21, 59), '90'),
    (datetime(2015, 1, 2, 22, 0), datetime(2015, 1, 2, 23, 59), '300'),
    (datetime(2015, 1, 3, 0, 0), datetime(2015, 1, 3, 23, 59), None)
]

MULTI_EXPECTED = [
    (datetime(2015, 1, 1, 0, 0), datetime(2015, 1, 1, 6, 59), ('A',)),
    (datetime(2015, 1, 1, 7, 0), datetime(2015, 1, 1, 11, 59), ('A', 'B')),
    (datetime(2015, 1, 1, 12, 0), datetime(2015, 1, 1, 18, 59), ('B', 'C'))
]


class CronTabScheduleTests(TestCase):
    maxDiff = None

    def test_init(self):
        s = CronTabSchedule(SCHEDULE)
        self.assertEqual(len(s.entries), 5)
        self.assertEqual(s.entries[2][1], '300')
        # The rest is thrown in here for code coverage.
        s.next_minute()
        s.next_minute(now=datetime.now())

    def test_schedule_iter_fixed(self):
        s = CronTabSchedule(SCHEDULE)
        slots = [slot for slot in s.schedule_iter(
            start=datetime(2015, 1, 1),
            end=datetime(2015, 1, 8),
            multi=False)]
        self.assertEqual(slots, FIXED_EXPECTED)
        # Code coverage.
        next(s.schedule_iter())

    def test_schedule_iter_dynamic(self):
        s = CronTabSchedule(SCHEDULE)
        slots = [slot for slot in s.schedule_iter(
            start=datetime(2015, 1, 1),
            multi=False)]
        self.assertEqual(slots, DYNAMIC_EXPECTED)

    def test_schedule_iter_gap(self):
        s = CronTabSchedule(GAP_SCHEDULE)
        slots = [slot for slot in s.schedule_iter(
            start=datetime(2015, 1, 1),
            end=datetime(2015, 1, 1, 12, 1))]
        self.assertEqual(slots, GAP_EXPECTED)

    def test_schedule_iter_end_endless(self):
        s = CronTabSchedule(SCHEDULE)
        with self.assertRaises(ValueError):
            next(s.schedule_iter(end=datetime.now(), endless=True))

    def test_multi_ok(self):
        s = CronTabSchedule(MULTI_SCHEDULE)
        slots = [slot for slot in s.schedule_iter(
            start=datetime(2015, 1, 1))]
        self.assertEqual(slots, MULTI_EXPECTED)

    def test_multi_exception(self):
        s = CronTabSchedule(MULTI_SCHEDULE)
        with self.assertRaises(CronTabScheduleException):
            [slot for slot in s.schedule_iter(
                start=datetime(2015, 1, 1),
                multi=False)]

    def test_add_entry_invalid(self):
        with self.assertRaises(CronTabScheduleException):
            CronTabSchedule('* * *')

    def test_delimiter(self):
        # Paranoia: Make sure we're actually testing what we think
        # we're testing, by ensuring that the original schedule had
        # newlines in it and the one we're using doesn't.
        self.assertNotEqual(SCHEDULE.find('\n'), -1)
        with_semis = SCHEDULE.replace('\n', ';')
        self.assertEqual(with_semis.find('\n'), -1)
        s = CronTabSchedule(with_semis, delimiter=';')
        slots = [slot for slot in s.schedule_iter(
            start=datetime(2015, 1, 1),
            multi=False)]
        self.assertEqual(slots, DYNAMIC_EXPECTED)

    def test_no_schedule(self):
        s = CronTabSchedule('')
        with self.assertRaises(CronTabScheduleException):
            s.soonest()

    def test_soonest_no_now(self):
        s = CronTabSchedule('* * * * * foo\n* * * * * bar')
        now = datetime.now()
        if not now.second:
            time.sleep(1)
            now = datetime.now()
        nxt = s.soonest()
        self.assertEqual(nxt, now + timedelta(
            seconds=60 - now.second - now.microsecond / 1000000))

    def test_soonest_with_seconds(self):
        s = CronTabSchedule('* * * * * foo')
        now = datetime(2015, 1, 1, 1, 1, 1, 1)
        nxt = s.soonest(now=now)
        self.assertEqual(nxt, datetime(2015, 1, 1, 1, 2))

    def test_soonest_backtrack_needed(self):
        s = CronTabSchedule('* * * * * foo')
        now = datetime(2015, 1, 1)
        nxt = s.soonest(now=now)
        self.assertEqual(now, nxt)

    def test_FastCronTab_default_now(self):
        e = FastCronTab('* * * * *')
        now = datetime.now()
        # Avoid race conditions. What happens if between when we call
        # datetime.now() and when crontab_schedule.py calls it, the
        # minute rolls over?
        if now.second > 55:
            time.sleep(60 - now.second + 1)
            now = datetime.now()
        self.assertAlmostEqual(e.next(), e.next(now), places=2)

    def test_FastCronTab_default_utc(self):
        e = FastCronTab('* * * * *')
        self.assertNotEqual(e.next(default_utc=False),
                            e.next(default_utc=True))

    def test_FastCronTab_default_utc_unspecified(self):
        e = FastCronTab('*/5 * * * *')
        now = datetime.now()
        first = e.next(now)
        second = e.next(now + timedelta(seconds=first + 1), default_utc=False)
        self.assertEqual(second, 299.0)
