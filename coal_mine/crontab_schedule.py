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

from crontab import CronTab
from datetime import datetime, timedelta

ONE_MINUTE = timedelta(minutes=1)


class CronTabScheduleException(Exception):
    pass


class FastCronTab(CronTab):
    def __init__(self, *args, **kwargs):
        super(FastCronTab, self).__init__(*args, **kwargs)
        self.cached_now = None
        self.cached_next = None

    def next(self, now=None, *args, **kwargs):
        if now is None:
            now = datetime.now()
        if self.cached_now is not None and now > self.cached_now and \
           now < self.cached_now + self.cached_next:
            self.cached_next -= now - self.cached_now
            self.cached_now = now
        else:
            self.cached_now = now
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
        for line in entry_lines:
            self.add_entry(line)

    def __len__(self):
        return len(self.entries)

    def add_entry(self, entry_line):
        """Internal function."""
        fields = entry_line.split(None, 5)
        if len(fields) < 6:
            raise CronTabScheduleException(
                '{} does not have six fields'.format(entry_line))
        e = FastCronTab(' '.join(fields[0:5]))
        self.entries.append((e, fields[5]))

    def next_minute(self, now=None, multi=True):
        """Get the entry / entries active in the following minute.

        Kwrgs:
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

    def next_active(self, now=None, multi=True):
        """Returns the next active schedule(s) on or after now.

        Kwargs:
            now (datetime.datetime): Defaults to the beginning of the current
                minute.
            multi (bool): Whether to allow multiple entries to be active in the
                same minute. Defaults to True.

        Returns:
            A tuple of a datetime indicating when the returned entry/ies are
            next active, and either a single entry index if `multi` is false,
            or a list of entry indexes.

        Raises:
            CronTabScheduleException, if `multi` is False and more than one
            entry is active in the following minute.
        """
        if now is None:
            now = datetime.now().replace(second=0, microsecond=0)
        elif now.second or now.microsecond:
            now = now.replace(second=0, microsecond=0)
        now -= ONE_MINUTE
        end = now + timedelta(days=366)
        while now < end:
            matches = self.next_minute(now=now, multi=multi)
            if matches is not None:
                return (now + ONE_MINUTE, matches)
            now += ONE_MINUTE
        raise CronTabScheduleException(
            'No active schedule matches in the year preceding {}'.format(end))

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

    def schedule_iter(self, start=None, end=None, multi=True):
        """Iterate through time ranges and their active entries.

        Kwargs:
            start (datetime.datetime): Start of time range to schedule.
                Defaults to now.
            end (datetime.datetime): End of time range to schedule. Defaults to
                scheduling until all entries have been used at least once, but
                not for longer than a year.
            multi: See `next`.

        Returns:
            An iterator which yields tuples of (range start, range end, active
            entry/ies), where the last item in the tuple is None if there are
            no active entries during the time range, or the key of a single
            entry if `multi` is False, or a tuple of all active entry keys if
            `multi` is True.

        Raises:
            See `next`.
        """
        if start is None:
            start = datetime.now().replace(
                hour=0, minute=0, second=0, microsecond=0)
        else:
            start = start.replace(second=0, microsecond=0)
        if end is None:
            # Escape hatch, don't loop forever!
            end = start + timedelta(days=366)
            hard_stop = False
        else:
            end = end.replace(second=0, microsecond=0)
            hard_stop = True
        used_rules = set()
        num_rules = len(self.entries)
        current_start = current_end = start
        new_entries = self.next_minute(start - ONE_MINUTE, multi)
        if not multi or new_entries is None:
            new_entries = [new_entries]
        current_key = tuple(self.key_of(e) for e in new_entries)
        current_rules = set()
        while (not hard_stop and len(used_rules) < num_rules) or \
              (hard_stop and current_end < end):
            new_entries = self.next_minute(current_end, multi)
            if not multi or new_entries is None:
                new_entries = [new_entries]
            new_key = tuple(self.key_of(e) for e in new_entries)
            # The second half of this boolean is a safety valve for the
            # degenerate case of there being only one schedule entry active all
            # the time ("* * * * * periodicity").
            if new_key != current_key or \
               current_end - current_start > timedelta(days=31):
                if not multi or current_key[0] is None:
                    current_key = current_key[0]
                yield (current_start, current_end, current_key)
                current_start = current_end = current_end + ONE_MINUTE
                current_key = new_key
                used_rules.update(current_rules)
                current_rules.clear()
            else:
                current_end = current_end + ONE_MINUTE
            if new_entries != [None]:
                current_rules.update(new_entries)
        if current_end > current_start:
            if not multi or current_key[0] is None:
                current_key = current_key[0]
            yield (current_start, current_end, current_key)
