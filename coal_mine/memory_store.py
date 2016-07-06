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
In-memory store for Coal Mine, primarily for use by tests
"""

from .abstract_store import AbstractStore
from copy import deepcopy
import re


class MemoryStore(AbstractStore):
    def __init__(self):
        self.canaries = {}

    def create(self, canary):
        self.canaries[canary['id']] = deepcopy(canary)

    def update(self, identifier, updates):
        canary = self.canaries[identifier]
        for key, value in ((k, v) for k, v in updates.items()):
            if value is None:
                if key in canary:  # pragma: no branch
                    del canary[key]
            else:
                canary[key] = value

    def get(self, identifier):
        return deepcopy(self.canaries[identifier])

    def list(self, *, verbose=False, paused=None, late=None, search=None):
        iterator = self.canaries.values()

        if paused is not None:
            iterator = (i for i in iterator if i['paused'] == paused)

        if late is not None:
            iterator = (i for i in iterator if i['late'] == late)

        if search is not None:
            regex = re.compile(search)
            iterator = (i for i in iterator
                        if regex.search(i['name']) or
                        regex.search(i['slug']) or
                        regex.search(i['id']))

        if not verbose:
            iterator = ({'id': i['id'], 'name': i['name']} for i in iterator)

        return (deepcopy(i) for i in iterator)

    def upcoming_deadlines(self):
        iterator = self.canaries.values()
        iterator = (i for i in iterator if not i['paused'])
        iterator = (i for i in iterator if not i['late'])
        return (deepcopy(i)
                for i in sorted(iterator, key=lambda i: i['deadline']))

    def delete(self, identifier):
        del self.canaries[identifier]

    def find_identifier(self, slug):
        matches = (i for i in self.canaries.values() if i['slug'] == slug)
        try:
            return next(matches)['id']
        except StopIteration:
            raise KeyError()
