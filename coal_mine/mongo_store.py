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
MongoDB store for Coal Mine
"""

from coal_mine.abstract_store import AbstractStore
import bson
from copy import copy
from logbook import Logger
import pymongo
import re
import time

log = Logger('MongoStore')


class MongoStore(AbstractStore):
    def __init__(self, hosts, database, username, password, **kwargs):
        """Keyword arguments are the same as what would be passed to
        MongoClient or MongoReplicaSetClient."""

        if 'replicaSet' in kwargs:
            client = pymongo.MongoReplicaSetClient
        else:
            client = pymongo.MongoClient
        connection = client(hosts, **kwargs)
        db = connection[database]
        if username or password:
            db.authenticate(username, password)
        self.db = db
        self.collection = self.db['canaries']

        self.collection.ensure_index([('id', pymongo.ASCENDING)],
                                     unique=True)

        # for list()
        self.collection.ensure_index([('paused', pymongo.ASCENDING),
                                      ('late', pymongo.ASCENDING),
                                      ('deadline', pymongo.ASCENDING)])
        self.collection.ensure_index([('paused', pymongo.ASCENDING),
                                      ('deadline', pymongo.ASCENDING)])
        self.collection.ensure_index([('late', pymongo.ASCENDING),
                                      ('deadline', pymongo.ASCENDING)])

        # for find_identifier(), as well as to ensure unique slugs
        self.collection.ensure_index([('slug', pymongo.ASCENDING)],
                                     unique=True)

    def create(self, canary):
        canary['_id'] = bson.ObjectId()
        while True:
            try:
                self.collection.save(canary)
                del canary['_id']
                break
            except pymongo.errors.AutoReconnect:
                log.exception('save failure, retrying')
                time.sleep(1)

    def update(self, identifier, updates):
        updates = copy(updates)
        unset = {}
        for key, value in [(k, v) for k, v in updates.items()]:
            if value is None:
                del updates[key]
                unset[key] = ''
        doc = {'$set': updates}
        if unset:
            doc['$unset'] = unset
        while True:
            try:
                self.collection.update({'id': identifier}, doc)
                return
            except pymongo.errors.AutoReconnect:
                log.exception('update failure, retrying')
                time.sleep(1)

    def get(self, identifier):
        while True:
            try:
                canary = self.collection.find_one({'id': identifier},
                                                  fields={'_id': False})
                if not canary:
                    raise KeyError('No such canary {}'.format(identifier))
                return canary
            except pymongo.errors.AutoReconnect:
                log.exception('find_one failure, retrying')
                time.sleep(1)

    def list(self, *, verbose=False, paused=None, late=None, search=None,
             order_by=None):
        if verbose:
            fields = {'_id': False}
        else:
            fields = {'_id': False, 'name': True, 'id': True}

        spec = {}

        if paused is not None:
            spec['paused'] = paused

        if late is not None:
            spec['late'] = late

        if order_by is not None:
            order_by = [(order_by, pymongo.ASCENDING)]

        if search is not None:
            search = re.compile(search)
            spec['$or'] = [{'name': search}, {'slug': search}, {'id': search}]

        skip = 0

        while True:
            try:
                for canary in self.collection.find(spec, fields=fields,
                                                   sort=order_by, skip=skip):
                    yield canary
                break
            except pymongo.errors.AutoReconnect:
                log.exception('find failure, retrying')
                time.sleep(1)

    def upcoming_deadlines(self):
        return self.list(verbose=True, paused=False, late=False,
                         order_by='deadline')

    def delete(self, identifier):
        while True:
            try:
                result = self.collection.remove({'id': identifier})
                if result['n'] == 0:
                    raise KeyError('No such canary {}'.format(identifier))
                return
            except pymongo.errors.AutoReconnect:
                log.exception('remove failure, retrying')
                time.sleep(1)

    def find_identifier(self, slug):
        while True:
            try:
                result = self.collection.find_one({'slug': slug})
                if not result:
                    raise KeyError('No such canary {}'.format(slug))
                return result['id']
            except pymongo.errors.AutoReconnect:
                log.exception('find_one failure, retrying')
                time.sleep(1)
