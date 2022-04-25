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
from coal_mine.server import (
    application,
    config_from_environment,
    config_from_ini,
    main,
    url_prefix,
)
import json
import os
from tempfile import TemporaryDirectory
from textwrap import dedent
from unittest import TestCase
from unittest.mock import patch
from urllib.parse import urlencode


class TemporaryIniFile(object):
    def __init__(self, contents):
        self.contents = contents
        self.d = None
        self.cwd = None

    def __enter__(self):
        self.d = TemporaryDirectory()
        self.cwd = os.getcwd()
        try:
            os.chdir(self.d.name)
            with open('coal-mine.ini', 'w') as f:
                f.write(self.contents)
        except Exception:
            self.cwd = None

    def __exit__(self, *args, **kwargs):
        if self.d:
            self.d.cleanup()
        if self.cwd:
            os.chdir(self.cwd)


class ServerIniTests(TestCase):
    @patch('coal_mine.server.config_file', 'this-file-does-not-exist.ini')
    def test_no_ini(self):
        with self.assertRaises(SystemExit) as cm:
            config_from_ini()
        self.assertRegex(cm.exception.args[0],
                         r'^Could not find this-file')

    def test_ini_file_exists(self):
        with TemporaryIniFile(''):
            with self.assertRaises(SystemExit) as cm:
                config_from_ini()
        self.assertRegex(cm.exception.args[0], r'^No "mongodb" section in ')

    def test_minimal_ini(self):
        with TemporaryIniFile(dedent('''\
            [logging]
            file=coal-mine.log
            [mongodb]
            hosts=localhost
            database=coal-mine-unit-tests
            [email]
            sender=example@example.com
        ''')):
            config = config_from_ini()
            self.assertEqual(config['logging']['file'], 'coal-mine.log')
            self.assertEqual(config['logging']['rotate'], False)
            self.assertEqual(config['email']['sender'], 'example@example.com')
            self.assertEqual(config['mongodb']['hosts'], ['localhost'])
            self.assertEqual(config['mongodb']['kwargs']['database'],
                             'coal-mine-unit-tests')
            self.assertEqual(config['wsgi']['port'], 80)

    def test_logging_rotate_defaults(self):
        with TemporaryIniFile(dedent('''\
            [logging]
            file=coal-mine.log
            rotate=True
            [mongodb]
            hosts=localhost
            database=coal-mine-unit-tests
            [email]
            sender=example@example.com
        ''')):
            config = config_from_ini()
            self.assertEqual(config['logging']['rotate'], True)
            self.assertEqual(config['logging']['max_size'], 1048576)
            self.assertEqual(config['logging']['backup_count'], 5)

    def test_logging_rotate_specified(self):
        with TemporaryIniFile(dedent('''\
            [logging]
            file=coal-mine.log
            rotate=True
            max_size=1000
            backup_count=2
            [mongodb]
            hosts=localhost
            database=coal-mine-unit-tests
            [email]
            sender=example@example.com
        ''')):
            config = config_from_ini()
            self.assertEqual(config['logging']['rotate'], True)
            self.assertEqual(config['logging']['max_size'], 1000)
            self.assertEqual(config['logging']['backup_count'], 2)

    def test_no_hosts(self):
        with TemporaryIniFile(dedent('''\
            [logging]
            file=coal-mine.log
            [mongodb]
            database=coal-mine-unit-tests
            [email]
            sender=example@example.com
        ''')):
            with self.assertRaises(SystemExit) as cm:
                config_from_ini()
            self.assertRegex(cm.exception.args[0],
                             r'^No "mongodb\.hosts" setting')

    def test_no_database(self):
        with TemporaryIniFile(dedent('''\
            [logging]
            file=coal-mine.log
            [mongodb]
            hosts=localhost
            [email]
            sender=example@example.com
        ''')):
            with self.assertRaises(SystemExit) as cm:
                config_from_ini()
            self.assertRegex(cm.exception.args[0],
                             r'^No "mongodb\.database" setting')

    def test_multiple_hosts(self):
        with TemporaryIniFile(dedent('''\
            [logging]
            file=coal-mine.log
            [mongodb]
            hosts=127.0.0.1, 127.0.0.2
            database=coal-mine-unit-tests
            [email]
            sender=example@example.com
        ''')):
            config = config_from_ini()
            self.assertEqual(config['mongodb']['hosts'],
                             ['127.0.0.1', '127.0.0.2'])

    def test_mongodb_uri(self):
        with TemporaryIniFile(dedent('''\
            [logging]
            file=coal-mine.log
            [mongodb]
            hosts=mongodb://localhost
            database=coal-mine-unit-tests
            [email]
            sender=example@example.com
        ''')):
            config = config_from_ini()
            self.assertEqual(config['mongodb']['hosts'], 'mongodb://localhost')

    def test_no_email_section(self):
        with TemporaryIniFile(dedent('''\
            [logging]
            file=coal-mine.log
            [mongodb]
            hosts=localhost
            database=coal-mine-unit-tests
        ''')):
            with self.assertRaises(SystemExit) as cm:
                config_from_ini()
            self.assertRegex(cm.exception.args[0], r'^No "email" section in ')

    def test_no_email_setting(self):
        with TemporaryIniFile(dedent('''\
            [logging]
            file=coal-mine.log
            [mongodb]
            hosts=localhost
            database=coal-mine-unit-tests
            [email]
        ''')):
            with self.assertRaises(SystemExit) as cm:
                config_from_ini()
            self.assertRegex(cm.exception.args[0], r'^No "sender" setting in ')

    def test_wsgi_settings(self):
        with TemporaryIniFile(dedent('''\
            [logging]
            file=coal-mine.log
            [mongodb]
            hosts=localhost
            database=coal-mine-unit-tests
            [email]
            sender=example@example.com
            [wsgi]
            port=8080
            auth_key=foobarbaz
        ''')):
            config = config_from_ini()
            self.assertEqual(config['wsgi']['port'], 8080)
            self.assertEqual(config['wsgi']['auth_key'], 'foobarbaz')


class ServerEnvVarTests(TestCase):
    def test_no_uri(self):
        config = config_from_environment()
        self.assertIsNone(config)

    @patch.dict(os.environ, {'MONGODB_URI': 'localhost'})
    def test_bad_uri(self):
        with self.assertRaises(SystemExit) as cm:
            config_from_environment()
        self.assertRegex(cm.exception.args[0], r'^Malformed MONGODB_URI')

    @patch.dict(os.environ, {'MONGODB_URI': 'mongodb://localhost',
                             'EMAIL_SENDER': 'example@example.com'})
    def test_minimal(self):
        config = config_from_environment()
        self.assertEqual(config['mongodb']['hosts'], 'mongodb://localhost')
        self.assertEqual(config['email']['sender'], 'example@example.com')

    @patch.dict(os.environ, {'MONGODB_URI': 'mongodb://localhost'})
    def test_no_sender(self):
        with self.assertRaises(SystemExit) as cm:
            config_from_environment()
            self.assertRegex(cm.exception.args[0],
                             r'^EMAIL_SENDER environment variable not set')

    @patch.dict(os.environ, {'MONGODB_URI': 'mongodb://localhost',
                             'EMAIL_SENDER': 'example@example.com',
                             'WSGI_PORT': '8080',
                             'WSGI_AUTH_KEY': 'frobnitz'})
    def test_wsgi_settings(self):
        config = config_from_environment()
        self.assertEqual(config['wsgi']['port'], 8080)
        self.assertEqual(config['wsgi']['auth_key'], 'frobnitz')

    @patch.dict(os.environ, {'MONGODB_URI': 'mongodb://localhost',
                             'EMAIL_SENDER': 'example@example.com',
                             'WSGI_PORT': 'foobar'})
    def test_bad_port(self):
        with self.assertRaises(SystemExit) as cm:
            config_from_environment()
        self.assertRegex(cm.exception.args[0], r'^Malformed WSGI_PORT foobar')


@patch('coal_mine.server.serve')
class ServerMainTests(TestCase):
    def test_no_ini(self, serve):
        with self.assertRaises(SystemExit) as cm:
            main()
        self.assertRegex(cm.exception.args[0],
                         r'Could not find coal-mine\.ini')
        serve.assert_not_called()

    def test_ini(self, serve):
        with TemporaryIniFile(dedent('''\
            [mongodb]
            hosts=localhost
            database=coal-mine-unit-tests
            [email]
            sender=example@example.com
            [wsgi]
            port=8080
            auth_key=frobnitz
        ''')):
            main()
            serve.assert_called_once()
            self.assertEqual(serve.call_args[0][0], 8080)
            self.assertIsInstance(serve.call_args[0][1], BusinessLogic)
            self.assertEqual(serve.call_args[0][2], 'frobnitz')

    @patch.dict(os.environ,
                {'MONGODB_URI': 'mongodb://localhost/coal-mine-unit-tests',
                 'EMAIL_SENDER': 'example@example.com',
                 'WSGI_PORT': '8080',
                 'WSGI_AUTH_KEY': 'frobnitz'})
    def test_environment(self, serve):
        main()
        serve.assert_called_once()
        self.assertEqual(serve.call_args[0][0], 8080)
        self.assertIsInstance(serve.call_args[0][1], BusinessLogic)
        self.assertEqual(serve.call_args[0][2], 'frobnitz')

    def test_log_file(self, serve):
        with TemporaryIniFile(dedent('''\
            [mongodb]
            hosts=localhost
            database=coal-mine-unit-tests
            [email]
            sender=example@example.com
            [logging]
            file=coal-mine.log
        ''')):
            main()
            log_contents = open('coal-mine.log', 'r').read()
            self.assertRegex(log_contents, r'Binding to port 80')

    def test_rotating_log_file(self, serve):
        with TemporaryIniFile(dedent('''\
            [mongodb]
            hosts=localhost
            database=coal-mine-unit-tests
            [email]
            sender=example@example.com
            [logging]
            file=coal-mine.log
            rotate=True
            max_size=10
        ''')):
            main()
            log_contents = open('coal-mine.log', 'r').read()
            log1_contents = open('coal-mine.log.1', 'r').read()
            self.assertRegex(log_contents, r'authentication DISABLED')
            self.assertRegex(log1_contents, r'Binding to port')


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
        self.assertRegex(response['error'],
                         'Must specify id, slug, or name')
        self.assertEqual(self.response_code, '400 Bad Request')
        response = self.call_application(self.make_url('update'), {})
        self.assertRegex(response['error'], 'Must specify id or slug')
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

    def test_scheduled_periodicity(self):
        self.call_application(
            self.make_url('create'),
            {'name': 'test_scheduled_periodicity',
             'periodicity': '* * * * sat,sun 600; * * * * mon-fri 90'})
        self.assertEqual(self.response_code, '200 OK')

    def test_not_found(self):
        self.call_application(
            self.make_url('trigger'),
            {'name': 'test_not_found'})
        self.assertEqual(self.response_code, '404 Not Found')
