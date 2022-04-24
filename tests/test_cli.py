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
from configparser import ConfigParser
from io import StringIO
import responses
import subprocess
import sys
import tempfile
from unittest import TestCase
from unittest.mock import patch


def add_response(query, method=responses.GET, host='localhost', port=80,
                 body='{"status": "ok"}', status=200):
    port = '' if port == 80 else ':{}'.format(port)
    full_url = 'http://{}{}/coal-mine/v1/canary/{}'.format(host, port, query)
    try:
        base_url, query_string = full_url.split('?')
    except ValueError:
        base_url = full_url
        query_string = ''
    responses.add(
        method, base_url, body=body, status=status,
        match=[responses.matchers.query_string_matcher(query_string)])


class CLITests(TestCase):
    get_body = '{"status": "ok", "canary": {"history": []}}'
    list_body = '{"status": "ok", "canaries": [{"history": []}]}'
    pause_body = '{"status": "ok", "canary": {"paused": true, "history": []}}'
    unpause_body = \
        '{"status": "ok", "canary": {"paused": false, "history": []}}'
    update_body = '{"status": "ok", "canary": {"history": []}}'

    def test_parse_args(self):
        hostname = 'hellohost'
        with tempfile.NamedTemporaryFile(delete=False) as tf:
            args = cli.parse_args(('configure', '--host', hostname),
                                  tf.name)
            self.assertEqual(args.host, hostname)
            self.assertEqual(args.url, 'http://{}/coal-mine/v1/canary/'.format(
                hostname))
            hostname = 'https://' + hostname
            args = cli.parse_args(('configure', '--host', hostname),
                                  tf.name)
            self.assertEqual(args.host, hostname)
            self.assertEqual(args.url, '{}/coal-mine/v1/canary/'.format(
                hostname))

    @responses.activate
    def test_configure(self):
        host = 'hellohost'
        port = '12345'
        auth_key = 'arglebargle'
        with tempfile.NamedTemporaryFile(delete=False) as tf:
            cli.doit(('configure', '--host', host, '--auth-key', auth_key),
                     tf.name)
            config = ConfigParser()
            config.read([tf.name])
            self.assertEqual(host, config['coal-mine']['host'])
            with self.assertRaises(KeyError):
                config['coal-mine']['port']
            self.assertEqual(auth_key, config['coal-mine']['auth-key'])

            cli.doit(('configure', '--host', host, '--port', port,
                      '--auth-key', auth_key), tf.name)
            config = ConfigParser()
            config.read([tf.name])
            self.assertEqual(host, config['coal-mine']['host'])
            self.assertEqual(port, config['coal-mine']['port'])
            self.assertEqual(auth_key, config['coal-mine']['auth-key'])

            add_response('pause?name=froodle&auth_key=arglebargle',
                         host=host, port=port)
            cli.doit(('pause', '--name', 'froodle'), tf.name)

            cli.doit(('configure', '--no-auth-key'), tf.name)
            config = ConfigParser()
            config.read([tf.name])
            with self.assertRaises(KeyError):
                self.assertEqual(auth_key, config['coal-mine']['auth-key'])

            add_response('pause?name=froodle', host=host, port=port)
            cli.doit(('pause', '--name', 'froodle'), tf.name)

            cli.doit(('configure', '--host', host + '2'), tf.name)
            config = ConfigParser()
            config.read([tf.name])
            self.assertEqual(host + '2', config['coal-mine']['host'])

    def test_no_command(self):
        with patch('sys.stderr', StringIO()):
            with self.assertRaises(SystemExit):
                cli.doit((), '/dev/null')
            self.assertRegex(sys.stderr.getvalue(), r'No command specified')

    @responses.activate
    def test_create(self):
        with patch('sys.stderr', StringIO()):
            with self.assertRaises(SystemExit):
                cli.doit(('create', '--name', 'froodle'), '/dev/null')
            self.assertRegex(
                sys.stderr.getvalue(),
                r'error: the following arguments are required: --periodicity')

        add_response('create?paused=False&name=froodle&periodicity=60.0')
        cli.doit(('create', '--name', 'froodle', '--periodicity', '60'),
                 '/dev/null')

    @responses.activate
    def test_delete(self):
        add_response('delete?slug=froodle')
        cli.doit(('delete', '--slug', 'froodle'), '/dev/null')

    @responses.activate
    def test_update(self):
        with patch('sys.stderr', StringIO()):
            with self.assertRaises(SystemExit):
                cli.doit(('update', '--id', 'abcdefgh', '--slug', 'foo'),
                         '/dev/null')
            self.assertRegex(
                sys.stderr.getvalue(),
                r'error: argument --slug: not allowed with argument --id')

        with self.assertRaisesRegex(
                SystemExit,
                r'Must specify --name, --id, or --slug'):
            cli.doit(('update', '--periodicity', '120'), '/dev/null')

        add_response('update?id=abcdefgh&name=freedle', body=self.update_body)
        cli.doit(('update', '--id', 'abcdefgh', '--name', 'freedle'),
                 '/dev/null')

        add_response('get?name=froodle&auth_key=arglebargle',
                     body='{"status": "ok", "canary": {"id": "bcdefghi"}}')
        add_response('update?description=foodesc&id=bcdefghi&'
                     'auth_key=arglebargle', body=self.update_body)
        cli.doit(('update', '--name', 'froodle', '--description', 'foodesc',
                  '--auth-key', 'arglebargle'),
                 '/dev/null')

        # Same as above but without --auth-key, for code branch coverage,
        # and with history test added.
        add_response('get?name=froodle',
                     body='{"status": "ok", "canary": {"id": "bcdefghi"}}')
        add_response('update?description=foodesc&id=bcdefghi',
                     body=self.update_body)
        with patch('sys.stdout', StringIO()):
            cli.doit(('update', '--name', 'froodle', '--description',
                      'foodesc'), '/dev/null')
            self.assertIn("{'history': []}", sys.stdout.getvalue())

    @responses.activate
    def test_update_no_history(self):
        add_response('get?name=froodle',
                     body='{"status": "ok", "canary": {"id": "bcdefghi"}}')
        add_response('update?description=foodesc&id=bcdefghi',
                     body=self.update_body)
        with patch('sys.stdout', StringIO()):
            cli.doit(('update', '--name', 'froodle', '--description',
                      'foodesc', '--no-history'), '/dev/null')
            self.assertNotIn("{'history': []}", sys.stdout.getvalue())

    @responses.activate
    def test_get(self):
        add_response('get?name=froodle', body=self.get_body)
        with patch('sys.stdout', StringIO()):
            cli.doit(('get', '--name', 'froodle'), '/dev/null')
            self.assertIn("{'history': []}", sys.stdout.getvalue())

    @responses.activate
    def test_get_no_history(self):
        add_response('get?name=froodle', body=self.get_body)
        with patch('sys.stdout', StringIO()):
            cli.doit(('get', '--no-history', '--name', 'froodle'), '/dev/null')
            self.assertNotIn("{'history': []}", sys.stdout.getvalue())

    @responses.activate
    def test_list(self):
        add_response('list')
        cli.doit(('list',), '/dev/null')

        add_response('list?search=foo&late=True&paused=True&verbose=True',
                     body=self.list_body)
        with patch('sys.stdout', StringIO()):
            cli.doit(('list', '--verbose', '--paused', '--late', '--search',
                      'foo'), '/dev/null')
            self.assertIn("{'history': []}", sys.stdout.getvalue())

    @responses.activate
    def test_list_no_history(self):
        add_response('list')
        cli.doit(('list',), '/dev/null')

        add_response('list?search=foo&late=True&paused=True&verbose=True',
                     body=self.list_body)
        with patch('sys.stdout', StringIO()):
            cli.doit(('list', '--verbose', '--no-history', '--paused',
                      '--late', '--search', 'foo'), '/dev/null')
            self.assertNotIn("{'history': []}", sys.stdout.getvalue())

    @responses.activate
    def test_trigger(self):
        add_response('trigger?name=froodle')
        cli.doit(('trigger', '--name', 'froodle'), '/dev/null')

    @responses.activate
    def test_pause(self):
        add_response('pause?name=froodle', body=self.pause_body)
        with patch('sys.stdout', StringIO()):
            cli.doit(('pause', '--name', 'froodle'), '/dev/null')
            self.assertIn("'history': []", sys.stdout.getvalue())

    @responses.activate
    def test_pause_no_history(self):
        add_response('pause?name=froodle', body=self.pause_body)
        with patch('sys.stdout', StringIO()):
            cli.doit(('pause', '--no-history', '--name', 'froodle'),
                     '/dev/null')
            self.assertNotIn("'history': []", sys.stdout.getvalue())

    @responses.activate
    def test_unpause(self):
        add_response('unpause?name=froodle', body=self.unpause_body)
        with patch('sys.stdout', StringIO()):
            cli.doit(('unpause', '--name', 'froodle'), '/dev/null')
            self.assertIn("'history': []", sys.stdout.getvalue())

    @responses.activate
    def test_unpause_no_history(self):
        add_response('unpause?name=froodle', body=self.unpause_body)
        with patch('sys.stdout', StringIO()):
            cli.doit(('unpause', '--no-history', '--name', 'froodle'),
                     '/dev/null')
            self.assertNotIn("'history': []", sys.stdout.getvalue())

    @responses.activate
    def test_bad_response(self):
        with self.assertRaisesRegex(SystemExit, r'^Not Found$'):
            add_response('get?name=froodle', status=404, body='Not Found')
            cli.doit(('get', '--name', 'froodle'), '/dev/null')

    def test_periodicity_string(self):
        val = '* * * * * 65'
        self.assertEqual(val, cli.periodicity(val))

    def test_subprocess_invocation(self):
        with self.assertRaises(subprocess.CalledProcessError) as cm:
            subprocess.check_output(
                ('python', '-m', 'coal_mine.cli', 'froodle'),
                stderr=subprocess.STDOUT)
        self.assertRegex(cm.exception.output.decode('ascii'),
                         r"invalid choice: 'froodle'")
