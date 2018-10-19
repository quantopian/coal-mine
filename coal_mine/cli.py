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
import copy
import os
import pprint
import re
import requests
try:
    from simplejson.errors import JSONDecodeError as JSONError
except ImportError:
    JSONError = ValueError
import sys

config_file = '~/.coal-mine.ini'
config_section = 'coal-mine'


def doit(args, config_file):
    config = SafeConfigParser()
    config.read([config_file])
    try:
        section = config[config_section]
    except KeyError:
        config['coal-mine'] = {}
        section = config['coal-mine']

    connect_parser = argparse.ArgumentParser(add_help=False)
    host_default = section.get('host', 'localhost')
    connect_parser.add_argument('--host', action='store',
                                help="Server host name or URL (default {})".
                                format(host_default), default=host_default)
    connect_parser.add_argument('--port', action='store', type=int,
                                help='Server port')
    auth_key_group = connect_parser.add_mutually_exclusive_group()
    auth_key_default = section.get('auth-key', None)
    auth_key_group.add_argument('--auth-key', action='store',
                                help='Authentication key (default {})'.format(
                                    '<hidden>' if auth_key_default else None),
                                default=auth_key_default)
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
                                  config_parser=config,
                                  config_file=config_file)

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
    update_parser.add_argument('--no-history', '--terse', action='store_true',
                               help='Omit history in output')
    update_parser.add_argument('--periodicity', action='store',
                               type=periodicity)
    update_parser.add_argument('--description', action='store')
    update_parser.add_argument('--email', action='append', help='Specify "-" '
                               'to clear existing email(s)')
    update_parser.set_defaults(func=handle_update)

    get_parser = subparsers.add_parser('get', help='Get canary',
                                       parents=[connect_parser, id_parser])
    get_parser.add_argument('--no-history', '--terse', action='store_true',
                            help='Omit history in output')
    get_parser.set_defaults(func=handle_get)

    list_parser = subparsers.add_parser('list', help='List canaries',
                                        parents=[connect_parser])
    list_parser.add_argument('--verbose', action='store_true', default=None)
    list_parser.add_argument('--no-history', '--terse', action='store_true',
                             help='Omit history in output')
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
                             'slug, identifier, and email addresses')
    list_parser.set_defaults(func=handle_list)

    trigger_parser = subparsers.add_parser('trigger', help='Trigger canary',
                                           parents=[connect_parser, id_parser])
    trigger_parser.add_argument('--comment', action='store')
    trigger_parser.set_defaults(func=handle_trigger)

    pause_parser = subparsers.add_parser('pause', help='Pause canary',
                                         parents=[connect_parser, id_parser])
    pause_parser.add_argument('--no-history', '--terse', action='store_true',
                              help='Omit history in output')
    pause_parser.add_argument('--comment', action='store')
    pause_parser.set_defaults(func=handle_pause)

    unpause_parser = subparsers.add_parser('unpause', help='Unpause canary',
                                           parents=[connect_parser, id_parser])
    unpause_parser.add_argument('--no-history', '--terse', action='store_true',
                                help='Omit history in output')
    unpause_parser.add_argument('--comment', action='store')
    unpause_parser.set_defaults(func=handle_unpause)

    args = parser.parse_args(args)

    url = ''
    if not re.match(r'^https?:', args.host):
        url += 'http://'
    url += args.host
    if args.port:
        url += ':{}'.format(args.port)
    url += '/coal-mine/v1/canary/'
    args.url = url

    try:
        if args.no_auth_key:
            args.auth_key = None
        if args.func is not handle_configure:
            del args.no_auth_key
        args.func(args)
    except AttributeError:
        parser.error("No command specified")


def handle_configure(args):
    section = args.config_parser[config_section]
    section['host'] = args.host
    if args.port:
        section['port'] = str(args.port)
    if args.auth_key:
        section['auth-key'] = args.auth_key
    elif args.no_auth_key:
        section.pop('auth-key', None)
    with open(args.config_file, 'w') as configfile:
        args.config_parser.write(configfile)


def handle_create(args):
    call('create', args)


def handle_delete(args):
    call('delete', args)


def get_no_history_filter(d):
    if 'canary' in d:
        d = copy.deepcopy(d)
        del d['canary']['history']
        return d
    if 'canaries' in d:
        d = copy.deepcopy(d)
        for canary in d['canaries']:
            del canary['history']
        return d
    return d


def handle_update(args):
    if not (args.name or args.id or args.slug):
        sys.exit('Must specify --name, --id, or --slug')
    if args.name and not (args.id or args.slug):
        found = call('get', args, {'name': args.name}, action='return')
        del args.name
        args.id = found['canary']['id']
    if vars(args).pop('no_history', None):
        filter = get_no_history_filter
    else:
        filter = None
    call('update', args, filter=filter)


def handle_get(args):
    if vars(args).pop('no_history', None):
        filter = get_no_history_filter
    else:
        filter = None
    call('get', args, filter=filter)


def handle_list(args):
    if args.paused is None:
        del args.paused
    if args.late is None:
        del args.late
    if args.search is None:
        del args.search
    if vars(args).pop('no_history', None):
        filter = get_no_history_filter
    else:
        filter = None
    call('list', args, filter=filter)


def handle_trigger(args):
    del args.auth_key
    call('trigger', args)


def handle_pause(args):
    if vars(args).pop('no_history', None):
        filter = get_no_history_filter
    else:
        filter = None
    call('pause', args, filter=filter)


def handle_unpause(args):
    if vars(args).pop('no_history', None):
        filter = get_no_history_filter
    else:
        filter = None
    call('unpause', args, filter=filter)


def call(command, args, payload=None, action='print', filter=None):
    url = args.url + command
    if payload:
        if args.auth_key:
            payload['auth_key'] = args.auth_key
    else:
        payload = {key: (getattr(args, key) if key == 'email'
                         else str(getattr(args, key)))
                   for key in dir(args)
                   if key not in ('host', 'port', 'func', 'url') and
                   not key.startswith('_') and
                   getattr(args, key) is not None and
                   not (key == 'email' and getattr(args, key) == [])}
    response = requests.get(url, params=payload)
    if response.status_code != 200:
        sys.stderr.write('{} {}\n'.format(
            response.status_code, response.reason))
        try:
            sys.exit(pprint.pformat(response.json()).strip())
        except JSONError:
            sys.exit(response.text)
    if action == 'print':
        try:
            content = response.json()
            if filter:
                content = filter(content)
            pprint.pprint(content)
        except BrokenPipeError:
            pass
    elif action == 'return':
        return response.json()
    else:  # pragma: no cover
        raise Exception('Unrecognized action: {}'.format(action))


def periodicity(str):
    if re.match(r'[0-9.]+$', str):
        return float(str)
    return str


def main():  # pragma: no cover
    doit(sys.argv[1:], os.path.expanduser(config_file))


if __name__ == '__main__':  # pragma: no cover
    main()
