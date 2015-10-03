#!/usr/bin/env python

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
Coal Mine CLI
"""

import argparse
from configparser import SafeConfigParser
import os
import pprint
import re
import requests
import sys

config_file = '~/.coal-mine.ini'
config_section = 'coal-mine'


def main():
    config = SafeConfigParser()
    config.read([os.path.expanduser(config_file)])
    try:
        section = config[config_section]
    except KeyError:
        config['coal-mine'] = {}
        section = config['coal-mine']

    connect_parser = argparse.ArgumentParser(add_help=False)
    connect_parser.add_argument('--host', action='store',
                                help="Server host name",
                                default=section.get('host', 'localhost'))
    connect_parser.add_argument('--port', action='store', type=int,
                                help='Server port',
                                default=section.getint('port', 80))
    auth_key_group = connect_parser.add_mutually_exclusive_group()
    auth_key_group.add_argument('--auth-key', action='store',
                                help='Authentication key',
                                default=section.get('auth-key', None))
    auth_key_group.add_argument('--no-auth-key', action='store_true',
                                help='Disable authentication',
                                default=False)

    parser = argparse.ArgumentParser(description="CLI wrapper for Coal "
                                     "Mine's HTTP API")
    subparsers = parser.add_subparsers()

    configure_parser = subparsers.add_parser('configure', help='Save '
                                             'configuration from command line '
                                             'to ' + config_file,
                                             parents=[connect_parser])
    configure_parser.set_defaults(func=handle_configure,
                                  config_parser=config)

    create_parser = subparsers.add_parser('create', help='Create canary',
                                          parents=[connect_parser])
    create_parser.add_argument('--name', action='store', required=True)
    create_parser.add_argument('--periodicity', action='store',
                               type=periodicity, required=True)
    create_parser.add_argument('--description', action='store')
    create_parser.add_argument('--email', action='append')
    create_parser.add_argument('--paused', action='store_true', default=False)
    create_parser.set_defaults(func=handle_create)

    id_parser = argparse.ArgumentParser(add_help=False)
    id_parser_group = id_parser.add_mutually_exclusive_group(required=True)
    id_parser_group.add_argument('--name', action='store')
    id_parser_group.add_argument('--slug', action='store')
    id_parser_group.add_argument('--id', action='store')

    delete_parser = subparsers.add_parser('delete', help='Delete canary',
                                          parents=[connect_parser, id_parser])
    delete_parser.set_defaults(func=handle_delete)

    update_parser = subparsers.add_parser('update', help='Update canary',
                                          parents=[connect_parser])
    update_parser.add_argument('--name', action='store')
    update_parser_group = update_parser.add_mutually_exclusive_group()
    update_parser_group.add_argument('--slug', action='store')
    update_parser_group.add_argument('--id', action='store')
    update_parser.add_argument('--periodicity', action='store',
                               type=periodicity)
    update_parser.add_argument('--description', action='store')
    update_parser.add_argument('--email', action='append', help='Specify "-" '
                               'to clear existing email(s)')
    update_parser.set_defaults(func=handle_update)

    get_parser = subparsers.add_parser('get', help='Get canary',
                                       parents=[connect_parser, id_parser])
    get_parser.set_defaults(func=handle_get)

    list_parser = subparsers.add_parser('list', help='List canaries',
                                        parents=[connect_parser])
    list_parser.add_argument('--verbose', action='store_true', default=None)
    paused_group = list_parser.add_mutually_exclusive_group()
    paused_group.add_argument('--paused', action='store_true', default=None)
    paused_group.add_argument('--no-paused', dest='paused',
                              action='store_false', default=None)
    late_group = list_parser.add_mutually_exclusive_group()
    late_group.add_argument('--late', action='store_true', default=None)
    late_group.add_argument('--no-late', dest='late',
                            action='store_false', default=None)
    list_parser.add_argument('--search', action='store', default=None,
                             help='Regular expression to match against name, '
                             'slug, and identifier')
    list_parser.set_defaults(func=handle_list)

    trigger_parser = subparsers.add_parser('trigger', help='Trigger canary',
                                           parents=[connect_parser, id_parser])
    trigger_parser.add_argument('--comment', action='store')
    trigger_parser.set_defaults(func=handle_trigger)

    pause_parser = subparsers.add_parser('pause', help='Pause canary',
                                         parents=[connect_parser, id_parser])
    pause_parser.add_argument('--comment', action='store')
    pause_parser.set_defaults(func=handle_pause)

    unpause_parser = subparsers.add_parser('unpause', help='Unpause canary',
                                           parents=[connect_parser, id_parser])
    unpause_parser.add_argument('--comment', action='store')
    unpause_parser.set_defaults(func=handle_unpause)

    args = parser.parse_args()
    if args.no_auth_key:
        args.auth_key = None
    del args.no_auth_key
    args.func(args)


def handle_configure(args):
    section = args.config_parser[config_section]
    section['host'] = args.host
    section['port'] = str(args.port)
    if args.auth_key:
        section['auth-key'] = args.auth_key
    elif args.no_auth_key:
        section.pop('auth-key', None)
    with open(os.path.expanduser(config_file), 'w') as configfile:
        args.config_parser.write(configfile)


def handle_create(args):
    call('create', args)


def handle_delete(args):
    call('delete', args)


def handle_update(args):
    if args.id and args.slug:
        sys.exit("Don't specify both --id and --slug")
    elif not (args.name or args.id or args.slug):
        sys.exit('Must specify --name, --id, or --slug')
    if args.name and not (args.id or args.slug):
        found = call('get', args, {'name': args.name}, action='return')
        del args.name
        args.id = found['canary']['id']
    call('update', args)


def handle_get(args):
    call('get', args)


def handle_list(args):
    if args.paused is None:
        del args.paused
    if args.late is None:
        del args.late
    if args.search is None:
        del args.search
    call('list', args)


def handle_trigger(args):
    del args.auth_key
    call('trigger', args)


def handle_pause(args):
    call('pause', args)
    pass


def handle_unpause(args):
    call('unpause', args)
    pass


def call(command, args, payload=None, action='print'):
    url = 'http://{}:{}/coal-mine/v1/canary/{}'.format(
        args.host, args.port, command)
    if payload:
        if args.auth_key:
            payload['auth_key'] = args.auth_key
    else:
        payload = {key: (getattr(args, key) if key == 'email'
                         else str(getattr(args, key)))
                   for key in dir(args)
                   if key not in ('host', 'port', 'func') and
                   not key.startswith('_') and
                   getattr(args, key) is not None and
                   not (key == 'email' and getattr(args, key) == [])}
    response = requests.get(url, params=payload)
    if response.status_code != 200:
        sys.stderr.write('{} {}\n'.format(
            response.status_code, response.reason))
        try:
            pprint.pprint(response.json(), sys.stderr)
        except:
            sys.stderr.write(response.text + '\n')
        sys.exit(1)
    if action == 'print':
        pprint.pprint(response.json())
    elif action == 'return':
        return response.json()
    else:
        raise Exception('Unrecognized action: {}'.format(action))


def periodicity(str):
    if re.match(r'[0-9.]+$', str):
        return float(str)
    return str

if __name__ == '__main__':
    main()
