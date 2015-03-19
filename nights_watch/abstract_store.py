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
Abstract store for Night's Watch

Subclass for a specific storage engine.
"""


class AlreadyExistsError(Exception):
    pass


class AbstractStore(object):
    def __init__(self, *args, **kwargs):
        """Args and behavior are dependent on the storage engine."""
        raise NotImplementedError()

    def create(self, watcher):
        """Should return string identifier of created watcher."""
        raise NotImplementedError()

    def update(self, identifier, updates):
        raise NotImplementedError()

    def get(self, identifier):
        """Should raise KeyError if not found, or return a dict with these
        keys: id, name, description, slug, periodicity, emails, late,
        paused, deadline, history. History should be a list of tuples,
        each of which contains a naive UTC timestamp and a possibly
        empty comment, sorted from most to least recent. Deadline
        should be a naive UTC timestamp."""
        raise NotImplementedError()

    def list(self, verbose=False, paused=None, late=None):
        """Return an iterator which yields dicts. If verbose is False,
        then the dicts contain only name and id, otherwise, all fields
        (same as returned by get()) are returned. If paused and/or
        late are specified, they are used to filter the results."""
        raise NotImplementedError()

    def upcoming_deadlines(self):
        """Return an iterator which yields watchers (same as returned by
        get()) that are unpaused and not yet late, sorted by deadline
        in increasing order, i.e., the watcher that will pass its
        deadline soonest is returned first."""
        return NotImplementedError()

    def delete(self, identifier):
        """Raise KeyError if a watcher with the specified identifier
        doesn't exist."""
        raise NotImplementedError()

    def find_identifier(self, slug):
        """Should raise KeyError if a watcher with the specified slug
        does not exist, or return the identifier string."""
        raise NotImplementedError()
