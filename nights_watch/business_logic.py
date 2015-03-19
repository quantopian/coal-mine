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
Business logic for Night's Watch
"""

from copy import copy
import datetime
from logbook import Logger
import math
from numbers import Number
from random import choice
import re
import smtplib
import signal

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
        watcher = {'id': self.create_identifier()}

        if not isinstance(name, str):
            raise TypeError('name must be a string')
        if not name:
            raise TypeError('name must be non-empty')
        watcher['name'] = name

        slug = self.slug(name)
        try:
            conflict = self.store.find_identifier(slug)
            raise AlreadyExistsError(
                'Watcher {} already exists with identifier {}'.format(
                    slug, conflict))
        except KeyError:
            pass
        watcher['slug'] = slug

        if not isinstance(periodicity, Number):
            raise TypeError('periodicity must be a number')
        if periodicity <= 0:
            raise TypeError('periodicity must be positive')
        watcher['periodicity'] = periodicity

        if not description:
            description = ''
        if not isinstance(description, str):
            raise TypeError('description must be a string')
        watcher['description'] = description

        if emails is None:  # Be generous in what you accept...
            emails = []
        if isinstance(emails, str):
            raise TypeError('emails should be a list of zero or more '
                            'addresses')
        watcher['emails'] = list(emails)

        if not isinstance(paused, bool):
            raise TypeError('paused should be a bool')
        watcher['paused'] = paused

        watcher['history'] = [(datetime.datetime.utcnow(), 'Snitch created')]
        watcher['late'] = False

        if not watcher['paused']:
            watcher['deadline'] = watcher['history'][0][0] + \
                datetime.timedelta(seconds=periodicity)

        self.store.create(watcher)

        log.info('Created watcher {} ({})'.format(watcher['id'],
                                                  watcher_log_string(watcher)))

        self.schedule_next_deadline()

        return watcher

    def update(self, identifier, name=None, periodicity=None,
               description=None, emails=None):
        watcher = self.store.get(identifier)
        updates = {}
        notify = False

        if name is not None and name != watcher['name']:
            if not isinstance(name, str):
                raise TypeError('name must be a string')
            if not name:
                raise TypeError('name must be non-empty')
            old_slug = watcher['slug']
            new_slug = self.slug(name)
            if old_slug != new_slug:
                try:
                    conflict = self.find_identifier(new_slug)
                    raise AlreadyExistsError(
                        "Watcher {} already exists with identifier {}".
                        format(new_slug, conflict))
                except KeyError:
                    pass
                updates['slug'] = new_slug
            updates['name'] = name

        if periodicity is not None and periodicity != watcher['periodicity']:
            if not isinstance(periodicity, Number):
                raise TypeError('periodicity must be a number')
            if periodicity <= 0:
                raise TypeError('periodicity must be positive')
            updates['periodicity'] = periodicity

            if not watcher['paused']:
                updates['deadline'] = watcher['history'][0][0] + \
                    datetime.timedelta(seconds=periodicity)
                is_late = updates['deadline'] < datetime.datetime.utcnow()
                if is_late != watcher['late']:
                    updates['late'] = is_late
                    notify = True

        if description is not None and description != watcher['description']:
            if not isinstance(description, str):
                raise TypeError('description must be a string')
            updates['description'] = description

        if emails is None:  # dummy caller specified None
            emails = []
        if emails is not None and set(emails) != set(watcher['emails']):
            if isinstance(emails, str):
                raise TypeError('emails should be a list of zero or more '
                                'addresses')
            updates['emails'] = list(emails)

        if not updates:
            raise ValueError('No updates specified')

        self.store.update(identifier, updates)
        watcher.update(updates)

        log.info('Updated watcher {} ({}, {})'.format(
            watcher['name'], identifier, watcher_log_string(updates)))

        if notify:
            self.notify(watcher)

        self.schedule_next_deadline()

        return watcher

    def trigger(self, identifier, comment=None):
        watcher = self.store.get(identifier)
        updates = {}
        was_late = watcher['late']
        was_paused = watcher['paused']

        if comment:
            comment = 'Triggered ({})'.format(comment)
        else:
            comment = 'Triggered'

        history = copy(watcher['history'])
        self.add_history(history, comment)
        updates['history'] = history

        updates['deadline'] = history[0][0] + \
            datetime.timedelta(seconds=watcher['periodicity'])
        if watcher['late']:
            updates['late'] = False
        if watcher['paused']:
            updates['paused'] = False

        self.store.update(identifier, updates)
        watcher.update(updates)

        log.info('Triggered watcher {} ({}, {}, {})'.format(
            watcher['name'], identifier, comment, watcher_log_string(updates)))

        if 'late' in updates:
            self.notify(watcher)

        self.schedule_next_deadline()

        return (was_late, was_paused)

    def pause(self, identifier, comment=None):
        watcher = self.store.get(identifier)
        updates = {}

        if watcher['paused']:
            raise AlreadyPausedError()

        updates['paused'] = True

        if comment:
            comment = 'Paused ({})'.format(comment)
        else:
            comment = 'Paused'

        history = copy(watcher['history'])
        self.add_history(history, comment)
        updates['history'] = history

        updates['deadline'] = None

        if watcher['late']:
            updates['late'] = False

        self.store.update(identifier, updates)
        watcher.update(updates)

        log.info('Paused watcher {} ({}, {}, {})'.format(
            watcher['name'], identifier, comment, watcher_log_string(updates)))

        self.schedule_next_deadline()

        return watcher

    def unpause(self, identifier, comment=None):
        watcher = self.store.get(identifier)
        updates = {}

        if not watcher['paused']:
            raise AlreadyUnpausedError()

        updates['paused'] = False

        if comment:
            comment = 'Unpaused ({})'.format(comment)
        else:
            comment = 'Unpaused'

        history = copy(watcher['history'])
        self.add_history(history, comment)
        updates['history'] = history

        updates['deadline'] = history[0][0] + \
            datetime.timedelta(seconds=watcher['periodicity'])

        self.store.update(identifier, updates)
        watcher.update(updates)

        log.info('Unpaused watcher {} ({}, {}, {})'.format(
            watcher['name'], identifier, comment, watcher_log_string(updates)))

        self.schedule_next_deadline()

        return watcher

    def delete(self, identifier):
        watcher = self.store.get(identifier)
        self.store.delete(identifier)

        log.info('Deleted watcher {} ({})'.format(watcher['name'], identifier))

        self.schedule_next_deadline()

    def get(self, identifier):
        return self.store.get(identifier)

    def list(self, verbose=False, paused=None, late=None):
        """N.B.: Returns an iterator."""
        return self.store.list(verbose, paused, late)

    def notify(self, watcher):
        if watcher['late']:
            subject = '[LATE] {} has not reported'.format(watcher['name'])
        else:
            subject = '[RESUMED] {} is reporting again'.format(watcher['name'])

        if not watcher['emails']:
            log.info('No emails for watcher {} ({}, {})'.format(
                watcher['name'], watcher['id'], subject))
            return

        body = ''

        if watcher['late']:
            body += 'The watcher {} ({}) was expected to report before {}.'.\
                format(watcher['name'], watcher['id'], watcher['deadline'])
        else:
            body += 'The watcher {} ({}) is reporting again as of {}.\n'.\
                format(watcher['name'], watcher['id'],
                       watcher['history'][0][0])
            body += '\nThe next trigger for this watcher is due before {}.\n'.\
                format(watcher['deadline'])

        body += '\nRecent events for this watcher:\n\n'

        for event in watcher['history'][0:15]:
            # For some reason, when I omit the str() wrapper around
            # the datetime, the resulting string contains "30" instead
            # of the stringified datetime. I'm sure there's a good
            # reason for this, but I can't figure out what it is.
            body += '{:30} {}\n'.format(str(event[0]), event[1])

        try:
            smtp = smtplib.SMTP()
            smtp.connect()
            smtp.sendmail(self.email_sender, watcher['emails'],
                          'From: {}\nTo: {}\nSubject: {}\n\n{}'.format(
                              self.email_sender,
                              ', '.join(watcher['emails']),
                              subject,
                              body))
            smtp.quit()
        except:
            log.exception('Notify failed for watcher {} ({}, {})'.format(
                watcher['name'], watcher['id'], subject))
        else:
            log.info('Notified for watcher {} ({}, {})'.format(
                watcher['name'], watcher['id'], subject))

    def schedule_next_deadline(self, watcher=None):
        if not watcher:
            try:
                watcher = next(self.store.upcoming_deadlines())
            except StopIteration:
                return
        when = max(1, (watcher['deadline'] - datetime.datetime.utcnow()).
                   total_seconds())

        log.info('Setting alarm for watcher {} ({}) at {}'.format(
            watcher['name'], watcher['id'], str(watcher['deadline'])))
        signal.signal(signal.SIGALRM, self.deadline_handler)
        signal.alarm(int(math.ceil(when)))

    def deadline_handler(self, signum, frame):
        now = datetime.datetime.utcnow()

        for watcher in self.store.upcoming_deadlines():
            if watcher['deadline'] <= now:
                updates = {'late': True}
                self.store.update(watcher['id'], updates)
                watcher.update(updates)
                self.notify(watcher)
            else:
                self.schedule_next_deadline(watcher)
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

        while len(history) > 100 and history[-1][0] < one_week_ago:
            history.pop()


def watcher_log_string(watcher):
    new_watcher = copy(watcher)
    if 'history' in watcher and watcher['history']:
        new_watcher['history'] = [(str(watcher['history'][0][0]),
                                   watcher['history'][0][1])]
        if len(watcher['history']) > 1:
            new_watcher['history'].append('...')
    return str(new_watcher)
