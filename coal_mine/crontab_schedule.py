# Copyright 2015 Quantopian, Inc.
# Copyright 2021 Jonathan Kamens
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

from crontab import CronTab
from datetime import datetime, timedelta

ONE_MINUTE = timedelta(minutes=1)
ONE_HOUR = timedelta(hours=1)
ONE_DAY = timedelta(days=1)
LIKE_FOREVER = timedelta(days=31)


class CronTabScheduleException(Exception):
    pass


class FastCronTab(CronTab):
    def __init__(self, *args, **kwargs):
        super(FastCronTab, self).__init__(*args, **kwargs)
        # Degenerate case where CronTab is much too slow
        self.every_minute = args[0] == '* * * * *'
        self.cached_now = None
        self.cached_next = None

    def next(self, now=None, *args, **kwargs):
        if now is None:
            now = datetime.now()
        if self.every_minute:
            return 60.0 - now.second - now.microsecond / 1000000
        if self.cached_now is not None and now > self.cached_now and \
           now < self.cached_now + self.cached_next:
            self.cached_next -= now - self.cached_now
            self.cached_now = now
        else:
            self.cached_now = now
            if 'default_utc' not in kwargs:
                kwargs = kwargs.copy()
                kwargs['default_utc'] = False
            self.cached_next = timedelta(seconds=super(FastCronTab, self).next(
                now, *args, **kwargs))
        return self.cached_next.total_seconds()


class CronTabSchedule(object):
    """Use crontab syntax for specifying continuous scheduling.

    The crontab syntax is typically used to specify tasks intended to
    be performed at fixed times. However, with a bit of cleverness, it
    can also be used to specify a continuous schedule, i.e., a set of
    events with start and end times, and to determine the active
    events at any given time or over any given time range.
    """
    def __init__(self, crontab, delimiter='\n'):
        """Initialize a new crontab schedule.

        Args:
            crontab (str): Delimiter-separated crontab entries in the form
                "minute hour day-of-month month day-of-week key", where the
                first five fields are anything supported by [parse-crontab]
                (https://github.com/josiahcarlson/parse-crontab), and the key,
                which may contain whitespace, is an arbitrary string
                describing or identifying the entry.

        Kwargs:
            delimiter (str): The string which separates crontab entries.
                Defaults to newline.
        """
        self.entries = []
        entry_lines = [s for s in (s.strip() for s in crontab.split(delimiter))
                       if s and s[0] != '#']
        self.smallest_change_gap = None
        for line in entry_lines:
            self.add_entry(line)

    def __len__(self):
        return len(self.entries)

    def check(self):
        if not self.entries:
            raise CronTabScheduleException('Schedule has no entries')

    def add_entry(self, entry_line):
        """Add an entry to the schedule

        Can be used to build a schedule incrementally rather than all in one
        shot when the object is created."""

        fields = entry_line.split(None, 5)
        if len(fields) < 6:
            raise CronTabScheduleException(
                '{} does not have six fields'.format(entry_line))

        if fields[0] != '*':
            gap = ONE_MINUTE
        elif fields[1] != '*':
            gap = ONE_HOUR
        elif fields[2] == '*' and fields[3] == '*' and fields[4] == '*':
            gap = LIKE_FOREVER
        else:
            gap = ONE_DAY

        if self.smallest_change_gap is None:
            self.smallest_change_gap = gap
        else:
            self.smallest_change_gap = min(self.smallest_change_gap, gap)

        e = FastCronTab(' '.join(fields[0:5]))
        self.entries.append((e, fields[5]))

    def next_minute(self, now=None, multi=True):
        """Get the entry / entries active in the following minute.

        Kwargs:
            now (datetime.datetime): The minute *before* the minute whose
                active entries you want. Defaults to the beginning of the
                current minute.
            multi (bool): Whether to allow multiple entries to be active in the
                same minute. Defaults to True.

        Returns:
            None, if there are no entries active in the next minute.
            The index of a single active entry, if `multi` is False.
            A list of the active entries, if `multi` is True.

        Raises:
            CronTabScheduleException, if `multi` is False and more than one
            entry is active in the following minute.
        """
        self.check()
        if now is None:
            now = datetime.now().replace(second=0, microsecond=0)
        elif now.second or now.microsecond:
            now = now.replace(second=0, microsecond=0)
        matches = []
        for i in range(len(self.entries)):
            if self.entries[i][0].next(now) == 60:
                matches.append(i)
        if len(matches) == 0:
            return None
        if len(matches) > 1 and not multi:
            raise CronTabScheduleException(
                'Multiple schedule matches at {}'.format(now + ONE_MINUTE))
        return matches[0] if not multi else matches

    def soonest(self, now=None):
        """The datetime of the soonest active schedule on or after now"""
        self.check()
        if now is None:
            now = datetime.now()
        if not (now.second or now.microsecond):
            now -= ONE_MINUTE
        soonest = self.entries[0][0].next(now)
        for entry in self.entries[1:]:
            soonest = min(soonest, entry[0].next(now))
        return now + timedelta(seconds=soonest)

    def round_up(self, now):
        self.check()
        if self.smallest_change_gap == ONE_MINUTE:
            return now
        if self.smallest_change_gap == LIKE_FOREVER:
            return now + LIKE_FOREVER
        if self.smallest_change_gap == ONE_HOUR:
            return now + timedelta(minutes=60 - now.minute)
        if self.smallest_change_gap == ONE_DAY:
            return now + timedelta(hours=24 - now.hour) - \
                timedelta(minutes=now.minute)
        raise CronTabScheduleException(  # pragma: no cover
            'Unrecognized smallest change gap {}'.format(
                self.smallest_change_gap))

    def key_of(self, entry):
        """Returns the key for an entry.

        Args:
            entry (str or None): Index of entry whose key you want.

        Returns:
            The key for the entry with the specified index, or None if the
            index you pass in is None. I.e., it's always safe to call `key_of`
            with the return value of `next_minute(..., multi=False)`.
        """
        return self.entries[entry][1] if entry is not None else None

    @staticmethod
    def fix_key(key, multi):
        return key[0] if not multi or key[0] is None else key

    def schedule_iter(self, start=None, end=None, multi=True, endless=False):
        """Iterate through time ranges and their active entries.

        Kwargs:
            start (datetime.datetime): Start of time range to schedule.
                Defaults to now.
            end (datetime.datetime): End of time range to schedule. Defaults to
                scheduling until all entries have been used at least once.
            multi: See `next_active`.
            endless: Yield forever, not only until all schedule entries are
                used. It is an error to to both set this to True and specify a
                value for `end`.

        Returns:
            An iterator which yields tuples of (range start, range end, active
            entry/ies), where the last item in the tuple is None if there are
            no active entries during the time range, or the key of a single
            entry if `multi` is False, or a tuple of all active entry keys if
            `multi` is True.

        Raises:
            See `next`.
        """
        # Strategy:
        #
        # Get the active entries for the start time.
        #
        # Set the next start time to the start time rounded up to the next
        # possible change time.
        #
        # Loop:
        #
        #   Get the active entries for the next start time.
        #
        #   If they are different, then:
        #
        #     Yield the start time, a minute _before_ the next start time, and
        #     the old active entries.
        #
        #     Set our start time equal to the next start time.
        #
        #     Set active entries equal to the new active entries.
        #
        #   Add the smallest change gap to the next start time.
        self.check()
        if start is None:
            start = datetime.now().replace(
                hour=0, minute=0, second=0, microsecond=0)
        else:
            start = start.replace(second=0, microsecond=0)
        if end is None:
            hard_stop = False
        else:
            if endless:
                raise ValueError("Can't specify both 'end' and 'endless")
            end = end.replace(second=0, microsecond=0)
            hard_stop = True
        used_rules = set()
        current_rules = set()
        num_rules = len(self.entries)
        current_start = start
        current_entries = self.next_minute(current_start - ONE_MINUTE, multi)
        if not multi or current_entries is None:
            current_entries = [current_entries]
        if current_entries != [None]:
            current_rules.update(current_entries)
        current_key = tuple(sorted(set(
            self.key_of(e) for e in current_entries)))

        next_start = self.round_up(current_start)
        while (not hard_stop and (endless or len(used_rules) < num_rules)) or \
              (hard_stop and next_start < end):
            new_entries = self.next_minute(next_start - ONE_MINUTE, multi)
            if not multi or new_entries is None:
                new_entries = [new_entries]
            new_key = tuple(sorted(set(
                self.key_of(e) for e in new_entries)))
            if new_key != current_key or \
               self.smallest_change_gap == LIKE_FOREVER:
                yield(current_start, next_start - ONE_MINUTE,
                      self.fix_key(current_key, multi))
                used_rules.update(current_rules)
                current_rules = set(new_entries)
                current_start = next_start
                current_entries = new_entries
                current_key = new_key
            elif new_entries != [None]:
                current_rules.update(new_entries)

            next_start += self.smallest_change_gap
        if not hard_stop:
            return
        # Even though our unit tests _do_ have cases where this if condition is
        # false and true, for some reason the coverage analyzer is claiming
        # otherwise. I can't figure out how to convince it that both branches
        # are executed, so I'm just exluding it from coverage analysis.
        if current_start < end:  # pragma: no cover
            yield(current_start, end, self.fix_key(current_key, multi))
