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

"""
Business logic for Coal Mine
"""

from copy import copy
from .crontab_schedule import CronTabSchedule, CronTabScheduleException
import datetime
from logbook import Logger
import math
from numbers import Number
from random import choice
import re
import smtplib
import signal
from textwrap import dedent

log = Logger('BusinessLogic')


class AlreadyExistsError(Exception):
    pass


class AlreadyPausedError(Exception):
    pass


class AlreadyUnpausedError(Exception):
    pass


class BusinessLogic(object):
    def __init__(self, store, email_sender):
        self.store = store
        self.email_sender = email_sender

    def create(self, name, periodicity, description=None, emails=[],
               paused=False):
        canary = {'id': self.create_identifier()}

        if not isinstance(name, str):
            raise TypeError('name must be a string')
        if not name:
            raise TypeError('name must be non-empty')
        canary['name'] = name

        slug = self.slug(name)
        try:
            conflict = self.store.find_identifier(slug)
            raise AlreadyExistsError(
                'Canary {} already exists with identifier {}'.format(
                    slug, conflict))
        except KeyError:
            pass
        canary['slug'] = slug

        self.validate_periodicity(periodicity)
        canary['periodicity'] = periodicity

        if not description:
            description = ''
        if not isinstance(description, str):
            raise TypeError('description must be a string')
        canary['description'] = description

        if emails is None:  # Be generous in what you accept...
            emails = []
        if isinstance(emails, str):
            raise TypeError('emails should be a list of zero or more '
                            'addresses')
        canary['emails'] = list(emails)

        if not isinstance(paused, bool):
            raise TypeError('paused should be a bool')
        canary['paused'] = paused

        canary['history'] = [(datetime.datetime.utcnow(), 'Canary created')]
        canary['late'] = False

        if not canary['paused']:
            canary['deadline'] = canary['history'][0][0] + \
                self.calculate_periodicity_delta(
                    periodicity, canary['history'][0][0])

        self.store.create(canary)

        log.info('Created canary {} ({})'.format(canary['id'],
                                                 canary_log_string(canary)))

        self.schedule_next_deadline()

        self.periodicity_schedule(canary)
        return canary

    def update(self, identifier, name=None, periodicity=None,
               description=None, emails=None):
        canary = self.store.get(identifier)
        updates = {}
        notify = False

        if name is not None and name != canary['name']:
            if not isinstance(name, str):
                raise TypeError('name must be a string')
            if not name:
                raise TypeError('name must be non-empty')
            old_slug = canary['slug']
            new_slug = self.slug(name)
            if old_slug != new_slug:
                try:
                    conflict = self.find_identifier(new_slug)
                    raise AlreadyExistsError(
                        "Canary {} already exists with identifier {}".
                        format(new_slug, conflict))
                except KeyError:
                    pass
                updates['slug'] = new_slug
            updates['name'] = name

        if periodicity is not None and periodicity != canary['periodicity']:
            self.validate_periodicity(periodicity)
            updates['periodicity'] = periodicity

            if not canary['paused']:
                updates['deadline'] = canary['history'][0][0] + \
                    self.calculate_periodicity_delta(
                        periodicity, canary['history'][0][0])
                is_late = updates['deadline'] < datetime.datetime.utcnow()
                if is_late != canary['late']:
                    updates['late'] = is_late
                    notify = True

        if description is not None and description != canary['description']:
            if not isinstance(description, str):
                raise TypeError('description must be a string')
            updates['description'] = description

        if emails is not None and set(emails) != set(canary['emails']):
            if isinstance(emails, str):
                raise TypeError('emails should be a list of zero or more '
                                'addresses')
            updates['emails'] = list(emails)

        if not updates:
            raise ValueError('No updates specified')

        self.store.update(identifier, updates)
        canary.update(updates)

        log.info('Updated canary {} ({}, {})'.format(
            canary['name'], identifier, canary_log_string(updates)))

        if notify:
            self.notify(canary)

        self.schedule_next_deadline()

        self.periodicity_schedule(canary)
        return canary

    def trigger(self, identifier, comment=None):
        canary = self.store.get(identifier)
        updates = {}
        was_late = canary['late']
        was_paused = canary['paused']

        if comment:
            comment = 'Triggered ({})'.format(comment)
        else:
            comment = 'Triggered'

        history = copy(canary['history'])
        self.add_history(history, comment)
        updates['history'] = history

        updates['deadline'] = history[0][0] + \
            self.calculate_periodicity_delta(
                canary['periodicity'], history[0][0])
        if canary['late']:
            updates['late'] = False
        if canary['paused']:
            updates['paused'] = False

        self.store.update(identifier, updates)
        canary.update(updates)

        log.info('Triggered canary {} ({}, {}, {})'.format(
            canary['name'], identifier, comment, canary_log_string(updates)))

        if 'late' in updates:
            self.notify(canary)

        self.schedule_next_deadline()

        return (was_late, was_paused)

    def pause(self, identifier, comment=None):
        canary = self.store.get(identifier)
        updates = {}

        if canary['paused']:
            raise AlreadyPausedError()

        updates['paused'] = True

        if comment:
            comment = 'Paused ({})'.format(comment)
        else:
            comment = 'Paused'

        history = copy(canary['history'])
        self.add_history(history, comment)
        updates['history'] = history

        updates['deadline'] = None

        if canary['late']:
            updates['late'] = False

        self.store.update(identifier, updates)
        canary.update(updates)

        log.info('Paused canary {} ({}, {}, {})'.format(
            canary['name'], identifier, comment, canary_log_string(updates)))

        self.schedule_next_deadline()

        self.periodicity_schedule(canary)
        return canary

    def unpause(self, identifier, comment=None):
        canary = self.store.get(identifier)
        updates = {}

        if not canary['paused']:
            raise AlreadyUnpausedError()

        updates['paused'] = False

        if comment:
            comment = 'Unpaused ({})'.format(comment)
        else:
            comment = 'Unpaused'

        history = copy(canary['history'])
        self.add_history(history, comment)
        updates['history'] = history

        updates['deadline'] = history[0][0] + \
            self.calculate_periodicity_delta(
                canary['periodicity'], history[0][0])

        self.store.update(identifier, updates)
        canary.update(updates)

        log.info('Unpaused canary {} ({}, {}, {})'.format(
            canary['name'], identifier, comment, canary_log_string(updates)))

        self.schedule_next_deadline()

        self.periodicity_schedule(canary)
        return canary

    def delete(self, identifier):
        canary = self.store.get(identifier)
        self.store.delete(identifier)

        log.info('Deleted canary {} ({})'.format(canary['name'], identifier))

        self.schedule_next_deadline()

    def get(self, identifier):
        canary = self.store.get(identifier)
        self.periodicity_schedule(canary)
        return canary

    def list(self, *, verbose=False, paused=None, late=None, search=None):
        """N.B.: Returns an iterator."""
        return self.store.list(
            verbose=verbose,
            paused=paused,
            late=late,
            search=search,
        )

    def notify(self, canary):
        if canary['late']:
            subject = '[LATE] {} has not reported'.format(canary['name'])
        else:
            subject = '[RESUMED] {} is reporting again'.format(canary['name'])

        if not canary['emails']:
            log.info('No emails for canary {} ({}, {})'.format(
                canary['name'], canary['id'], subject))
            return

        body = ''

        if canary['late']:
            body += 'The canary {} ({}) was expected to report before {}.\n'.\
                format(canary['name'], canary['id'], canary['deadline'])
        else:
            body += 'The canary {} ({}) is reporting again as of {}.\n'.\
                format(canary['name'], canary['id'],
                       canary['history'][0][0])
            body += '\nThe next trigger for this canary is due before {}.\n'.\
                format(canary['deadline'])

        body += '\nRecent events for this canary:\n\n'

        for event in canary['history'][0:15]:
            # For some reason, when I omit the str() wrapper around
            # the datetime, the resulting string contains "30" instead
            # of the stringified datetime. I'm sure there's a good
            # reason for this, but I can't figure out what it is.
            body += '{:30} {}\n'.format(str(event[0]), event[1])

        try:
            smtp = smtplib.SMTP()
            smtp.connect()
            message_template = dedent('''
                From: Coal Mine <{}>
                To: {}
                Subject: {}

                {}
            ''').strip()
            smtp.sendmail(self.email_sender, canary['emails'],
                          message_template.format(
                              self.email_sender,
                              ', '.join(canary['emails']),
                              subject,
                              body))
            smtp.quit()
        except:
            log.exception('Notify failed for canary {} ({}, {})'.format(
                canary['name'], canary['id'], subject))
        else:
            log.info('Notified for canary {} ({}, {})'.format(
                canary['name'], canary['id'], subject))

    def schedule_next_deadline(self, canary=None):
        if not canary:
            try:
                canary = next(self.store.upcoming_deadlines())
            except StopIteration:
                return
        when = max(1, (canary['deadline'] - datetime.datetime.utcnow()).
                   total_seconds())

        log.info('Setting alarm for canary {} ({}) at {}'.format(
            canary['name'], canary['id'], str(canary['deadline'])))
        signal.signal(signal.SIGALRM, self.deadline_handler)
        signal.alarm(int(math.ceil(when)))

    def deadline_handler(self, signum, frame):
        now = datetime.datetime.utcnow()

        for canary in self.store.upcoming_deadlines():
            if canary['deadline'] <= now:
                updates = {'late': True}
                self.store.update(canary['id'], updates)
                canary.update(updates)
                self.notify(canary)
            else:
                self.schedule_next_deadline(canary)
                return

    def slug(self, name):
        name = name.lower()
        name = re.sub(r'[-\s_]+', '-', name)
        name = re.sub(r'[^-\w]+', '', name)
        return name

    def find_identifier(self, name=None, slug=None, identifier=None):
        num_specified = sum(1 for x in (name, slug, identifier) if x)
        if not num_specified:
            raise Exception("Must specify name, slug, or identifier")
        if num_specified > 1:
            raise Exception("Specify only one of name, slug, or identifier")

        if identifier:
            return identifier

        if name:
            slug = self.slug(name)

        return self.store.find_identifier(slug)

    def create_identifier(self):
        while True:
            identifier = ''.join((choice('abcdefghijklmnopqrstuvwxyz')
                                  for c in range(8)))
            try:
                self.store.get(identifier)
            except KeyError:
                return identifier

    def add_history(self, history, comment):
        if comment is None:  # Be generous in what you accept...
            comment = ''
        if not isinstance(comment, str):
            raise TypeError('comment must be a string')

        now = datetime.datetime.utcnow()
        one_week_ago = now - datetime.timedelta(days=7)

        history.insert(0, (now, comment))

        while len(history) > 1000 or (len(history) > 100 and
                                      history[-1][0] < one_week_ago):
            history.pop()

    def calculate_periodicity_delta(self, periodicity, whence=None):
        if whence is None:
            whence = datetime.datetime.utcnow()
        if isinstance(periodicity, Number):
            if periodicity > 0:
                return datetime.timedelta(seconds=periodicity)
            raise TypeError('numeric periodicities must be positive')
        if periodicity.find('\n') > -1:
            raise TypeError('malformed periodicity: no newlines allowed')
        try:
            s = CronTabSchedule(periodicity, delimiter=';')
        except:
            raise TypeError('malformed periodicity: must be positive number '
                            'or semicolon-delimited crontab schedule; see '
                            'documentation for more information')
        for i in range(len(s)):
            number_string = s.key_of(i)
            try:
                value = float(number_string)
                if value <= 0:
                    raise Exception()
            except:
                raise TypeError('malformed periodicity; each crontab schedule '
                                '"command" must be a positive number')
        try:
            dt, i = s.next_active(now=whence, multi=False)
        except CronTabScheduleException:
            raise TypeError('malformed periodicity: overlapping schedule '
                            'entries are not allowed')
        td = datetime.timedelta(seconds=float(s.key_of(i)))
        if dt > whence:
            td += dt - whence
        return td

    # Syntactic sugar.
    def validate_periodicity(self, periodicity):
        self.calculate_periodicity_delta(periodicity)

    def periodicity_schedule(self, canary):
        if isinstance(canary['periodicity'], Number):
            return
        schedule = CronTabSchedule(canary['periodicity'], delimiter=';')
        start = datetime.datetime.utcnow()
        ranges1 = [r for r in schedule.schedule_iter(start=start, multi=False)]
        ranges2 = [r for r in schedule.schedule_iter(
            start=start,
            end=start + datetime.timedelta(days=7),
            multi=False)]
        ranges = ranges1 if len(ranges1) > len(ranges2) else ranges2
        ranges = [(r[0], r[1],
                   float(r[2]) if r[2] is not None else 'Inactive')
                  for r in ranges]
        canary['periodicity_schedule'] = ranges


def canary_log_string(canary):
    new_canary = copy(canary)
    if 'history' in canary and canary['history']:
        new_canary['history'] = [(str(canary['history'][0][0]),
                                  canary['history'][0][1])]
        if len(canary['history']) > 1:
            new_canary['history'].append('...')
    return str(new_canary)
