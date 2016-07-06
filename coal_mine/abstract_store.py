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
Abstract store for Coal Mine

Subclass for a specific storage engine.
"""

from abc import ABCMeta, abstractmethod


class AbstractStore(object, metaclass=ABCMeta):  # pragma: no cover
    @abstractmethod
    def __init__(self, *args, **kwargs):
        """Args and behavior are dependent on the storage engine."""
        raise NotImplementedError('__init__')

    @abstractmethod
    def create(self, canary):
        """Make sure you copy the data in `canary` rather than storing the dict
        internally."""
        raise NotImplementedError('create')

    @abstractmethod
    def update(self, identifier, updates):
        raise NotImplementedError('update')

    @abstractmethod
    def get(self, identifier):
        """Should raise KeyError if not found, or return a dict with these keys: id,
        name, description, slug, periodicity, emails, late, paused, deadline,
        history. History should be a list of tuples, each of which contains a
        naive UTC timestamp and a possibly empty comment, sorted from most to
        least recent. Deadline should be a naive UTC timestamp.

        NOTE: The caller could modify the dict you return, so don't return
        anything you have a pointer to internally! If you need to return a dict
        which you're also using internally, then deepcopy it."""
        raise NotImplementedError('get')

    @abstractmethod
    def list(self, *, verbose=False, paused=None, late=None, search=None):
        """Return an iterator which yields dicts (but see the note on get()). If
        verbose is False, then the dicts contain only name and id, otherwise,
        all fields (same as returned by get()) are returned. If paused, late,
        and/or search are specified, they are used to filter the results. The
        latter is a regular expression (string, not regular expression object),
        which is matched against the name, slug, and id of canaries and only
        matches are returned."""
        raise NotImplementedError('list')

    @abstractmethod
    def upcoming_deadlines(self):
        """Return an iterator which yields canaries (same as returned by get(); see in
        particular the note there) that are unpaused and not yet late, sorted
        by deadline in increasing order, i.e., the canary that will pass its
        deadline soonest is returned first."""
        raise NotImplementedError('upcoming_deadlines')

    @abstractmethod
    def delete(self, identifier):
        """Raise KeyError if a canary with the specified identifier
        doesn't exist."""
        raise NotImplementedError('delete')

    @abstractmethod
    def find_identifier(self, slug):
        """Should raise KeyError if a canary with the specified slug
        does not exist, or return the identifier string."""
        raise NotImplementedError('find_identifier')
