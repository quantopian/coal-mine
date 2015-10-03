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

from coal_mine.business_logic import BusinessLogic
from coal_mine.memory_store import MemoryStore
from coal_mine.server import application, url_prefix
import json
from unittest import TestCase
from urllib.parse import urlencode


class ServerTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.store = MemoryStore()
        cls.logic = BusinessLogic(cls.store, 'example@example.com')

    @staticmethod
    def environ(path, params):
        return {
            'PATH_INFO': path,
            'QUERY_STRING': urlencode(params),
        }

    @staticmethod
    def make_url(command):
        return url_prefix + command

    def start_response(self, status_code, headers):
        self.response_code = status_code
        self.response_headers = headers

    def call_application(self, url, params, auth_key=None):
        self.response_code = self.response_headers = None
        iterator = application(self.logic, auth_key, self.environ(url, params),
                               self.start_response)
        data = ''.join(d.decode('utf-8') for d in iterator)
        return json.loads(data) if data else None

    def test_create(self):
        self.call_application(
            self.make_url('create'),
            {'name': 'test_create', 'periodicity': 12345})
        self.assertEqual(self.response_code, '200 OK')

    def test_create_name_missing(self):
        self.call_application(
            self.make_url('create'), {'periodicity': 12345})
        self.assertEqual(self.response_code, '400 Bad Request')

    def test_trigger(self):
        created = self.call_application(
            self.make_url('create'),
            {'name': 'test_trigger', 'periodicity': 12346})
        self.call_application('/{}'.format(created['canary']['id']), {})
        self.assertEqual(self.response_code, '200 OK')
        self.call_application(
            '/{}'.format(created['canary']['id']),
            {'comment': 'test_trigger trigger comment'})
        self.assertEqual(self.response_code, '200 OK')

    def test_url_invalid(self):
        self.call_application('/froodle', {})
        self.assertEqual(self.response_code, '404 Not Found')
        self.call_application(self.make_url('froodle'), {})
        self.assertEqual(self.response_code, '404 Not Found')

    def test_auth(self):
        auth_key = 'key_for_test_auth'
        self.call_application(
            self.make_url('create'),
            {'name': 'test_auth', 'periodicity': 12347, 'auth_key': auth_key},
            auth_key=auth_key)
        self.assertEqual(self.response_code, '200 OK')

    def test_auth_missing(self):
        self.call_application(self.make_url('create'), {}, auth_key='froodle')
        self.assertEqual(self.response_code, '401 Unauthorized')

    def test_auth_invalid(self):
        self.call_application(
            self.make_url('create'),
            {'name': 'test_auth_invalid', 'periodicity': 12348,
             'auth_key': 'bad_key'},
            auth_key='good_key')
        self.assertEqual(self.response_code, '401 Unauthorized')

    def test_find_identifier_slug(self):
        self.call_application(
            self.make_url('create'),
            {'name': 'test_find_identifier_slug', 'periodicity': 12349})
        self.call_application(
            self.make_url('get'),
            {'slug': 'test-find-identifier-slug'})
        self.assertEqual(self.response_code, '200 OK')

    def test_find_identifier_name(self):
        self.call_application(
            self.make_url('create'),
            {'name': 'test_find_identifier_name', 'periodicity': 12350})
        self.call_application(
            self.make_url('get'),
            {'name': 'test_find_identifier_name'})
        self.assertEqual(self.response_code, '200 OK')

    def test_find_identifier_missing(self):
        response = self.call_application(self.make_url('get'), {})
        self.assertRegexpMatches(response['error'],
                                 'Must specify id, slug, or name')
        self.assertEqual(self.response_code, '400 Bad Request')
        response = self.call_application(self.make_url('update'), {})
        self.assertRegexpMatches(response['error'], 'Must specify id or slug')
        self.assertEqual(self.response_code, '400 Bad Request')

    def test_boolean_parameters(self):
        self.call_application(
            self.make_url('create'),
            {'name': 'test_boolean_parameters', 'periodicity': 12351,
             'paused': 'true'})
        self.assertEqual(self.response_code, '200 OK')
        self.call_application(
            self.make_url('create'),
            {'name': 'test_boolean_parameters2', 'periodicity': 12352,
             'paused': 'false'})
        self.assertEqual(self.response_code, '200 OK')
        self.call_application(
            self.make_url('create'),
            {'name': 'test_boolean_parameters3', 'periodicity': 12352,
             'paused': 'froodle'})
        self.assertEqual(self.response_code, '400 Bad Request')

    def test_invalid_parameter(self):
        self.call_application(
            self.make_url('create'),
            {'name': 'test_handle_delete', 'periodicity': 12352,
             'froodle': 'freedle'})
        self.assertEqual(self.response_code, '400 Bad Request')

    def test_handle_delete(self):
        self.call_application(
            self.make_url('create'),
            {'name': 'test_handle_delete', 'periodicity': 12353})
        self.assertEqual(self.response_code, '200 OK')
        self.call_application(
            self.make_url('delete'), {'name': 'test_handle_delete'})
        self.assertEqual(self.response_code, '200 OK')

    def test_handle_update(self):
        response = self.call_application(
            self.make_url('create'),
            {'name': 'test_handle_update', 'periodicity': 12354,
             'email': 'test_handle_update@example.com'})
        self.assertEqual(self.response_code, '200 OK')
        self.call_application(
            self.make_url('update'),
            {'id': response['canary']['id'], 'periodicity': 12355,
             'email': ''})
        self.assertEqual(self.response_code, '200 OK')
        self.call_application(
            self.make_url('update'),
            {'id': response['canary']['id'], 'email': '-'})
        self.assertEqual(self.response_code, '200 OK')

    def test_handle_list(self):
        self.call_application(self.make_url('list'), {})
        self.assertEqual(self.response_code, '200 OK')

    def test_handle_pause(self):
        response = self.call_application(
            self.make_url('create'),
            {'name': 'test_handle_pause', 'periodicity': 12356})
        self.assertEqual(self.response_code, '200 OK')
        self.call_application(
            self.make_url('pause'),
            {'id': response['canary']['id']})
        self.assertEqual(self.response_code, '200 OK')

    def test_handle_unpause(self):
        response = self.call_application(
            self.make_url('create'),
            {'name': 'test_handle_unpause', 'periodicity': 12357})
        self.assertEqual(self.response_code, '200 OK')
        self.call_application(
            self.make_url('pause'),
            {'id': response['canary']['id']})
        self.assertEqual(self.response_code, '200 OK')
        self.call_application(
            self.make_url('unpause'),
            {'id': response['canary']['id']})
        self.assertEqual(self.response_code, '200 OK')
