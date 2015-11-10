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

from coal_mine import cli
from configparser import SafeConfigParser
from io import StringIO
import responses
import subprocess
import sys
import tempfile
from unittest import TestCase
from unittest.mock import patch


def add_response(query, method=responses.GET, host='localhost', port=80,
                 body='{"status": "ok"}', status=200):
    responses.add(
        method,
        'http://{}:{}/coal-mine/v1/canary/{}'.format(host, port, query),
        body=body, match_querystring=True, status=status)


class CLITests(TestCase):
    @responses.activate
    def test_configure(self):
        host = 'hellohost'
        port = '12345'
        auth_key = 'arglebargle'
        with tempfile.NamedTemporaryFile(delete=False) as tf:
            cli.main(('configure', '--host', host, '--port', port,
                      '--auth-key', auth_key), tf.name)
            config = SafeConfigParser()
            config.read([tf.name])
            self.assertEqual(host, config['coal-mine']['host'])
            self.assertEqual(port, config['coal-mine']['port'])
            self.assertEqual(auth_key, config['coal-mine']['auth-key'])

            add_response('pause?name=froodle&auth_key=arglebargle',
                         host=host, port=port)
            cli.main(('pause', '--name', 'froodle'), tf.name)

            cli.main(('configure', '--no-auth-key'), tf.name)
            config = SafeConfigParser()
            config.read([tf.name])
            with self.assertRaises(KeyError):
                self.assertEqual(auth_key, config['coal-mine']['auth-key'])

            add_response('pause?name=froodle', host=host, port=port)
            cli.main(('pause', '--name', 'froodle'), tf.name)

    def test_no_command(self):
        with patch('sys.stderr', StringIO()):
            with self.assertRaises(SystemExit):
                cli.main((), '/dev/null')
            self.assertRegexpMatches(sys.stderr.getvalue(),
                                     r'No command specified')

    @responses.activate
    def test_create(self):
        with patch('sys.stderr', StringIO()):
            with self.assertRaises(SystemExit):
                cli.main(('create', '--name', 'froodle'), '/dev/null')
            self.assertRegexpMatches(
                sys.stderr.getvalue(),
                r'error: the following arguments are required: --periodicity')

        add_response('create?paused=False&name=froodle&periodicity=60.0')
        cli.main(('create', '--name', 'froodle', '--periodicity', '60'),
                 '/dev/null')

    @responses.activate
    def test_delete(self):
        add_response('delete?slug=froodle')
        cli.main(('delete', '--slug', 'froodle'), '/dev/null')

    @responses.activate
    def test_update(self):
        with patch('sys.stderr', StringIO()):
            with self.assertRaises(SystemExit):
                cli.main(('update', '--id', 'abcdefgh', '--slug', 'foo'),
                         '/dev/null')
            self.assertRegexpMatches(
                sys.stderr.getvalue(),
                r'error: argument --slug: not allowed with argument --id')

        with self.assertRaisesRegexp(
                SystemExit,
                r'Must specify --name, --id, or --slug'):
            cli.main(('update', '--periodicity', '120'), '/dev/null')

        add_response('update?id=abcdefgh&name=freedle')
        cli.main(('update', '--id', 'abcdefgh', '--name', 'freedle'),
                 '/dev/null')

        add_response('get?name=froodle&auth_key=arglebargle',
                     body='{"status": "ok", "canary": {"id": "bcdefghi"}}')
        add_response('update?description=foodesc&id=bcdefghi&'
                     'auth_key=arglebargle')
        cli.main(('update', '--name', 'froodle', '--description', 'foodesc',
                  '--auth-key', 'arglebargle'),
                 '/dev/null')

    @responses.activate
    def test_get(self):
        add_response('get?name=froodle')
        cli.main(('get', '--name', 'froodle'), '/dev/null')

    @responses.activate
    def test_list(self):
        add_response('list')
        cli.main(('list',), '/dev/null')

        add_response('list?search=foo&late=True&paused=True')
        cli.main(('list', '--paused', '--late', '--search', 'foo'),
                 '/dev/null')

    @responses.activate
    def test_trigger(self):
        add_response('trigger?name=froodle')
        cli.main(('trigger', '--name', 'froodle'), '/dev/null')

    @responses.activate
    def test_pause(self):
        add_response('pause?name=froodle')
        cli.main(('pause', '--name', 'froodle'), '/dev/null')

    @responses.activate
    def test_unpause(self):
        add_response('unpause?name=froodle')
        cli.main(('unpause', '--name', 'froodle'), '/dev/null')

    @responses.activate
    def test_bad_response(self):
        with self.assertRaisesRegexp(SystemExit, r'^Not Found$'):
            add_response('get?name=froodle', status=404, body='Not Found')
            cli.main(('get', '--name', 'froodle'), '/dev/null')

    def test_periodicity_string(self):
        val = '* * * * * 65'
        self.assertEqual(val, cli.periodicity(val))

    def test_subprocess_invocation(self):
        with self.assertRaises(subprocess.CalledProcessError) as cm:
            subprocess.check_output(
                ('python', '-m', 'coal_mine.cli', 'froodle'),
                stderr=subprocess.STDOUT)
        self.assertRegexpMatches(cm.exception.output.decode('ascii'),
                                 r"invalid choice: 'froodle'")
