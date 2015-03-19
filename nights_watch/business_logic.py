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


class BrickBusinessLogic(object):
    def __init__(self, store, email_sender):
        self.store = store
        self.email_sender = email_sender

    def create(self, name, periodicity, description=None, emails=[],
               paused=False):
        brick = {'id': self.create_identifier()}

        if not isinstance(name, str):
            raise TypeError('name must be a string')
        if not name:
            raise TypeError('name must be non-empty')
        brick['name'] = name

        slug = self.slug(name)
        try:
            conflict = self.store.find_identifier(slug)
            raise AlreadyExistsError(
                'Brick {} already exists with identifier {}'.format(
                    slug, conflict))
        except KeyError:
            pass
        brick['slug'] = slug

        if not isinstance(periodicity, Number):
            raise TypeError('periodicity must be a number')
        if periodicity <= 0:
            raise TypeError('periodicity must be positive')
        brick['periodicity'] = periodicity

        if not description:
            description = ''
        if not isinstance(description, str):
            raise TypeError('description must be a string')
        brick['description'] = description

        if emails is None:  # Be generous in what you accept...
            emails = []
        if isinstance(emails, str):
            raise TypeError('emails should be a list of zero or more '
                            'addresses')
        brick['emails'] = list(emails)

        if not isinstance(paused, bool):
            raise TypeError('paused should be a bool')
        brick['paused'] = paused

        brick['history'] = [(datetime.datetime.utcnow(), 'Snitch created')]
        brick['late'] = False

        if not brick['paused']:
            brick['deadline'] = brick['history'][0][0] + \
                datetime.timedelta(seconds=periodicity)

        self.store.create(brick)

        log.info('Created brick {} ({})'.format(brick['id'],
                                                brick_log_string(brick)))

        self.schedule_next_deadline()

        return brick

    def update(self, identifier, name=None, periodicity=None,
               description=None, emails=None):
        brick = self.store.get(identifier)
        updates = {}
        notify = False

        if name is not None and name != brick['name']:
            if not isinstance(name, str):
                raise TypeError('name must be a string')
            if not name:
                raise TypeError('name must be non-empty')
            old_slug = brick['slug']
            new_slug = self.slug(name)
            if old_slug != new_slug:
                try:
                    conflict = self.find_identifier(new_slug)
                    raise AlreadyExistsError(
                        "Brick {} already exists with identifier {}".
                        format(new_slug, conflict))
                except KeyError:
                    pass
                updates['slug'] = new_slug
            updates['name'] = name

        if periodicity is not None and periodicity != brick['periodicity']:
            if not isinstance(periodicity, Number):
                raise TypeError('periodicity must be a number')
            if periodicity <= 0:
                raise TypeError('periodicity must be positive')
            updates['periodicity'] = periodicity

            if not brick['paused']:
                updates['deadline'] = brick['history'][0][0] + \
                    datetime.timedelta(seconds=periodicity)
                is_late = updates['deadline'] < datetime.datetime.utcnow()
                if is_late != brick['late']:
                    updates['late'] = is_late
                    notify = True

        if description is not None and description != brick['description']:
            if not isinstance(description, str):
                raise TypeError('description must be a string')
            updates['description'] = description

        if emails is None:  # dummy caller specified None
            emails = []
        if emails is not None and set(emails) != set(brick['emails']):
            if isinstance(emails, str):
                raise TypeError('emails should be a list of zero or more '
                                'addresses')
            updates['emails'] = list(emails)

        if not updates:
            raise ValueError('No updates specified')

        self.store.update(identifier, updates)
        brick.update(updates)

        log.info('Updated brick {} ({}, {})'.format(
            brick['name'], identifier, brick_log_string(updates)))

        if notify:
            self.notify(brick)

        self.schedule_next_deadline()

        return brick

    def trigger(self, identifier, comment=None):
        brick = self.store.get(identifier)
        updates = {}
        was_late = brick['late']
        was_paused = brick['paused']

        if comment:
            comment = 'Triggered ({})'.format(comment)
        else:
            comment = 'Triggered'

        history = copy(brick['history'])
        self.add_history(history, comment)
        updates['history'] = history

        updates['deadline'] = history[0][0] + \
            datetime.timedelta(seconds=brick['periodicity'])
        if brick['late']:
            updates['late'] = False
        if brick['paused']:
            updates['paused'] = False

        self.store.update(identifier, updates)
        brick.update(updates)

        log.info('Triggered brick {} ({}, {}, {})'.format(
            brick['name'], identifier, comment, brick_log_string(updates)))

        if 'late' in updates:
            self.notify(brick)

        self.schedule_next_deadline()

        return (was_late, was_paused)

    def pause(self, identifier, comment=None):
        brick = self.store.get(identifier)
        updates = {}

        if brick['paused']:
            raise AlreadyPausedError()

        updates['paused'] = True

        if comment:
            comment = 'Paused ({})'.format(comment)
        else:
            comment = 'Paused'

        history = copy(brick['history'])
        self.add_history(history, comment)
        updates['history'] = history

        updates['deadline'] = None

        if brick['late']:
            updates['late'] = False

        self.store.update(identifier, updates)
        brick.update(updates)

        log.info('Paused brick {} ({}, {}, {})'.format(
            brick['name'], identifier, comment, brick_log_string(updates)))

        self.schedule_next_deadline()

        return brick

    def unpause(self, identifier, comment=None):
        brick = self.store.get(identifier)
        updates = {}

        if not brick['paused']:
            raise AlreadyUnpausedError()

        updates['paused'] = False

        if comment:
            comment = 'Unpaused ({})'.format(comment)
        else:
            comment = 'Unpaused'

        history = copy(brick['history'])
        self.add_history(history, comment)
        updates['history'] = history

        updates['deadline'] = history[0][0] + \
            datetime.timedelta(seconds=brick['periodicity'])

        self.store.update(identifier, updates)
        brick.update(updates)

        log.info('Unpaused brick {} ({}, {}, {})'.format(
            brick['name'], identifier, comment, brick_log_string(updates)))

        self.schedule_next_deadline()

        return brick

    def delete(self, identifier):
        brick = self.store.get(identifier)
        self.store.delete(identifier)

        log.info('Deleted brick {} ({})'.format(brick['name'], identifier))

        self.schedule_next_deadline()

    def get(self, identifier):
        return self.store.get(identifier)

    def list(self, verbose=False, paused=None, late=None):
        """N.B.: Returns an iterator."""
        return self.store.list(verbose, paused, late)

    def notify(self, brick):
        if brick['late']:
            subject = '[LATE] {} has not reported'.format(brick['name'])
        else:
            subject = '[RESUMED] {} is reporting again'.format(brick['name'])

        if not brick['emails']:
            log.info('No emails for brick {} ({}, {})'.format(
                brick['name'], brick['id'], subject))
            return

        body = ''

        if brick['late']:
            body += 'The brick {} ({}) was expected to report before {}.'.\
                format(brick['name'], brick['id'], brick['deadline'])
        else:
            body += 'The brick {} ({}) is reporting again as of {}.\n'.\
                format(brick['name'], brick['id'], brick['history'][0][0])
            body += '\nThe next trigger for this brick is due before {}.\n'.\
                format(brick['deadline'])

        body += '\nRecent events for this brick:\n\n'

        for event in brick['history'][0:15]:
            # For some reason, when I omit the str() wrapper around
            # the datetime, the resulting string contains "30" instead
            # of the stringified datetime. I'm sure there's a good
            # reason for this, but I can't figure out what it is.
            body += '{:30} {}\n'.format(str(event[0]), event[1])

        try:
            smtp = smtplib.SMTP()
            smtp.connect()
            smtp.sendmail(self.email_sender, brick['emails'],
                          'From: {}\nTo: {}\nSubject: {}\n\n{}'.format(
                              self.email_sender,
                              ', '.join(brick['emails']),
                              subject,
                              body))
            smtp.quit()
        except:
            log.exception('Notify failed for brick {} ({}, {})'.format(
                brick['name'], brick['id'], subject))
        else:
            log.info('Notified for brick {} ({}, {})'.format(
                brick['name'], brick['id'], subject))

    def schedule_next_deadline(self, brick=None):
        if not brick:
            try:
                brick = next(self.store.upcoming_deadlines())
            except StopIteration:
                return
        when = max(1, (brick['deadline'] - datetime.datetime.utcnow()).
                   total_seconds())

        log.info('Setting alarm for brick {} ({}) at {}'.format(
            brick['name'], brick['id'], str(brick['deadline'])))
        signal.signal(signal.SIGALRM, self.deadline_handler)
        signal.alarm(int(math.ceil(when)))

    def deadline_handler(self, signum, frame):
        now = datetime.datetime.utcnow()

        for brick in self.store.upcoming_deadlines():
            if brick['deadline'] <= now:
                updates = {'late': True}
                self.store.update(brick['id'], updates)
                brick.update(updates)
                self.notify(brick)
            else:
                self.schedule_next_deadline(brick)
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


def brick_log_string(brick):
    new_brick = copy(brick)
    if 'history' in brick and brick['history']:
        new_brick['history'] = [(str(brick['history'][0][0]),
                                 brick['history'][0][1])]
        if len(brick['history']) > 1:
            new_brick['history'].append('...')
    return str(new_brick)
