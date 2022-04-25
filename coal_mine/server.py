#!/usr/bin/env python

# Copyright 2015 Quantopian, Inc.
# Copyright 2022 Jonathan Kamens
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
Coal Mine WSGI server
"""

import argparse
from coal_mine.business_logic import BusinessLogic, CanaryNotFoundError
from copy import copy
from configparser import ConfigParser, NoSectionError, NoOptionError
from functools import partial, wraps
import json
import logbook
from coal_mine.mongo_store import MongoStore
import os
import re
import signal
import socket
import sys
from wsgiref.simple_server import make_server, WSGIRequestHandler

try:
    # Python 3.8+
    from urllib.parse import parse_qs
except ImportError:  # pragma: no cover
    from cgi import parse_qs


config_file = 'coal-mine.ini'
url_prefix = '/coal-mine/v1/canary/'

log = logbook.Logger('coal-mine')


def parse_args():
    parser = argparse.ArgumentParser(description='Coal Mine Server')
    parser.add_argument('--port', type=int, action='store', default=80,
                        help='Port number to listen on (default 80)')
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--web', action='store_true', help='Process web '
                       'requests but do not do background tasks such as '
                       'notifications of late canaries')
    group.add_argument('--background', action='store_true', help='Do '
                       'background tasks such as notifications of late '
                       'canaries but do not process web requests')

    args = parser.parse_args()
    return args


def main():
    args = parse_args()
    config = config_from_environment(args)
    if config is None:
        config = config_from_ini(args)

    logfile = config['logging']['file']
    if logfile:
        if config['logging']['rotate']:
            max_size = config['logging']['max_size']
            backup_count = config['logging']['backup_count']
            handler = logbook.RotatingFileHandler(logfile, max_size=max_size,
                                                  backup_count=backup_count)
        else:
            handler = logbook.FileHandler(logfile)
    else:
        handler = logbook.StderrHandler()

    if sum(1 for k in ('username', 'password') if config['email'][k]) == 1:
        sys.exit('Must specify both or neither of email username and password')

    with handler.applicationbound():
        store = MongoStore(config['mongodb']['hosts'],
                           create_indexes=not args.web,
                           **config['mongodb']['kwargs'])

        business_logic = BusinessLogic(
            store, config['email']['sender'],
            smtp_host=config['email']['host'],
            smtp_port=config['email']['port'],
            smtp_username=config['email']['username'],
            smtp_password=config['email']['password'],
            background_tasks=not args.web,
            background_interval=10 if args.background else None)

        if not args.web:
            business_logic.schedule_next_deadline()

        if args.background:
            background(business_logic)
        else:
            listen_port = config['wsgi']['port']
            log.info('Binding to port {}'.format(listen_port))

            auth_key = config['wsgi']['auth_key']
            if auth_key:
                log.info('Server authentication enabled')
            else:
                log.warning('Server authentication DISABLED')

            serve(listen_port, business_logic, auth_key)


def background(business_logic):  # pragma: no cover
    while True:
        signal.pause()


def serve(port, business_logic, auth_key):  # pragma: no cover
    httpd = make_server(
        '', port, partial(application, business_logic, auth_key),
        handler_class=LogbookWSGIRequestHandler)
    httpd.serve_forever()


def blank_config(args):
    return {
        'logging': {
            'file': None,
            'rotate': None,
            'max_size': None,
            'backup_count': None,
        },
        'mongodb': {
            'hosts': None,
            'kwargs': {},
        },
        'email': {
            'sender': None,
            'host': None,
            'port': None,
            'username': None,
            'password': None,
        },
        'wsgi': {
            'port': args.port,
            'auth_key': None,
        },
    }


def config_from_ini(args):
    parser = ConfigParser()
    dirs = ('.', '/etc', '/usr/local/etc')
    if not parser.read([os.path.join(dir, config_file) for dir in dirs]):
        sys.exit('Could not find {} in {}'.format(config_file, dirs))

    config = blank_config(args)

    try:
        config['logging']['file'] = parser.get('logging', 'file')
    except Exception:
        pass
    else:
        config['logging']['rotate'] = parser.getboolean(
            'logging', 'rotate', fallback=False)
        if config['logging']['rotate']:
            config['logging']['max_size'] = parser.getint(
                'logging', 'max_size', fallback=1048576)
            config['logging']['backup_count'] = parser.getint(
                'logging', 'backup_count', fallback=5)

    try:
        kwargs = dict(parser.items('mongodb'))
    except NoSectionError:
        sys.exit('No "mongodb" section in config file')

    try:
        config['mongodb']['hosts'] = kwargs.pop('hosts')
    except KeyError:
        sys.exit('No "mongodb.hosts" setting in config file')

    if ':' not in config['mongodb']['hosts']:
        config['mongodb']['hosts'] = [
            s.strip() for s in config['mongodb']['hosts'].split(',')]
        if 'database' not in kwargs:
            sys.exit('No "mongodb.database" setting in config file')

    config['mongodb']['kwargs'] = kwargs

    try:
        email = dict(parser.items('email'))
    except NoSectionError:
        sys.exit('No "email" section in config file')

    try:
        config['email']['sender'] = email['sender']
    except KeyError:
        sys.exit('No "email.sender" setting in config file')

    for setting in ('host', 'username', 'password'):
        config['email'][setting] = email.get(setting, None)

    if 'port' in email:
        try:
            config['email']['port'] = int(email['port'])
        except ValueError:
            sys.exit(f'Malformed email.port {email["port"]}')

    try:
        config['wsgi']['port'] = parser.getint('wsgi', 'port')
    except (NoSectionError, NoOptionError):
        pass
    except ValueError:
        sys.exit(f'Malformed wsgi.port {parser.get("wsgi", "port")}')

    try:
        config['wsgi']['auth_key'] = parser.get('wsgi', 'auth_key')
    except (NoSectionError, NoOptionError):
        pass

    return config


def config_from_environment(args):
    config = blank_config(args)

    try:
        uri = os.environ['MONGODB_URI']
    except KeyError:
        return None

    if ':' not in uri:
        sys.exit(f'Malformed MONGODB_URI {uri}')
    config['mongodb']['hosts'] = uri

    try:
        config['email']['sender'] = os.environ['EMAIL_SENDER']
    except KeyError:
        sys.exit('EMAIL_SENDER environment variable not set')

    for key in ('host', 'username', 'password'):
        try:
            config['email'][key] = os.environ[f'SMTP_{key.upper()}']
        except KeyError:
            pass

    try:
        config['email']['port'] = int(os.environ['SMTP_PORT'])
    except KeyError:
        pass
    except Exception:
        sys.exit(f'Malformed SMTP_PORT {os.environ["SMTP_PORT"]}')

    try:
        config['wsgi']['port'] = int(os.environ['WSGI_PORT'])
    except KeyError:
        pass
    except Exception:
        sys.exit(f'Malformed WSGI_PORT {os.environ["WSGI_PORT"]}')

    config['wsgi']['auth_key'] = os.environ.get('WSGI_AUTH_KEY')

    return config


def application(business_logic, auth_key, environ, start_response):
    handlers = {
        'create': handle_create,
        'delete': handle_delete,
        'update': handle_update,
        'get': handle_get,
        'list': handle_list,
        'trigger': handle_trigger,
        'pause': handle_pause,
        'unpause': handle_unpause,
    }

    path_info = environ['PATH_INFO']
    # Special case: make trigger URLs easy
    match = re.match(r'/([a-z]{8})$', path_info)
    if match:
        id = match.group(1)
        qs = 'id={}'.format(id)
        if environ['QUERY_STRING']:
            environ['QUERY_STRING'] += '&' + qs
        else:
            environ['QUERY_STRING'] = qs
        path_info = environ['PATH_INFO'] = url_prefix + 'trigger'

    command = path_info[len(url_prefix):]
    q = parse_qs(environ['QUERY_STRING'])

    if not path_info.startswith(url_prefix) or command not in handlers:
        status_code = '404 Not Found'
        data = {'status': 'error', 'error': status_code}
    elif (auth_key and command != 'trigger' and
          q.pop('auth_key', [None])[0] != auth_key):
        status_code = '401 Unauthorized'
        data = {'status': 'error', 'error': status_code}
    else:
        (status_code, data) = handlers[command](business_logic, q)

    # If you give wsgiref a single, huge response blob to send, it sends the
    # data to the socket in a single call to write(), which isn't guaranteed
    # to send the whole block of data, and wsgiref doesn't check if all the
    # data was sent and send the rest if it wasn't. This is arguably a bug in
    # wsgiref, but fixing that will take time and effort, so we work around it
    # here.
    data = (s.encode('utf-8') for s in
            (json.dumps(data, indent=4) + '\n').splitlines(True))

    start_response(status_code,
                   headers=[('Content-Type', 'text/json; charset=utf-8')])
    return data


def required_parameters(*args):
    def decorator(f):
        @wraps(f)
        def wrapper(business_logic, query):
            for arg in args:
                if arg not in query:
                    raise Exception('Missing argument "{}"'.format(arg))
            return f(business_logic, query)
        return wrapper
    return decorator


def find_identifier(business_logic, query, name_ok=True):
    name = slug = identifier = None
    if 'id' in query:
        identifier = query.pop('id')[-1]
    elif 'slug' in query:
        slug = query.pop('slug')[-1]
    elif name_ok and 'name' in query:
        name = query.pop('name')[-1]
    if not (name or slug or identifier):
        if name_ok:
            raise Exception('Must specify id, slug, or name')
        else:
            raise Exception('Must specify id or slug')
    query['id'] = business_logic.find_identifier(
        name, slug, identifier)


def string_parameters(*args):
    def decorator(f):
        @wraps(f)
        def wrapper(business_logic, query):
            for arg in args:
                if arg in query:
                    query[arg] = query[arg][-1]
            return f(business_logic, query)
        return wrapper
    return decorator


def periodicity(f):
    @wraps(f)
    def wrapper(business_logic, query):
        if 'periodicity' in query:
            periodicity = query['periodicity'][-1]
            if re.match(r'[\d.]+$', periodicity):
                query['periodicity'] = float(periodicity)
            else:
                query['periodicity'] = periodicity
        return f(business_logic, query)
    return wrapper


def boolean_parameters(*args):
    def decorator(f):
        @wraps(f)
        def wrapper(business_logic, query):
            for arg in args:
                if arg not in query:
                    continue
                val = query[arg][-1]
                if val.lower() in ('true', 'yes', '1'):
                    query[arg] = True
                elif val.lower() in ('false', 'no', '0', ''):
                    query[arg] = False
                else:
                    raise Exception(
                        'Bad boolean value "{}" for parameter "{}"'.format(
                            val, arg))
            return f(business_logic, query)
        return wrapper
    return decorator


def valid_parameters(*args):
    def decorator(f):
        @wraps(f)
        def wrapper(business_logic, query):
            for arg in query:
                if arg not in args:
                    raise Exception('Unexpected argument "{}"'.format(arg))
            return f(business_logic, query)
        return wrapper
    return decorator


def handle_exceptions(f):
    @wraps(f)
    def wrapper(business_logic, query):
        try:
            return f(business_logic, query)
        except CanaryNotFoundError as e:
            log.warning('Canary not found: {}', str(e))
            return ('404 Not Found',
                    {'status': 'error', 'error': 'Canary Not Found'})
        except Exception as e:
            log.exception('Exception in {}'.format(f))
            return ('400 Bad Request', {'status': 'error', 'error': repr(e)})
    return wrapper


@handle_exceptions
@required_parameters('name', 'periodicity')
@string_parameters('name', 'description')
@periodicity
@boolean_parameters('paused')
@valid_parameters('name', 'periodicity', 'description', 'email', 'paused')
def handle_create(business_logic, query):
    canary = business_logic.create(query['name'],
                                   query['periodicity'],
                                   query.get('description', ''),
                                   query.get('email', []),
                                   query.get('paused', False))
    return ('200 OK', {'status': 'ok', 'canary': jsonify_canary(canary)})


@handle_exceptions
@valid_parameters('id', 'name', 'slug')
def handle_delete(business_logic, query):
    find_identifier(business_logic, query)
    business_logic.delete(query['id'])
    return ('200 OK', {'status': 'ok'})


@handle_exceptions
@string_parameters('name', 'description')
@periodicity
@valid_parameters('id', 'name', 'slug', 'periodicity', 'description', 'email')
def handle_update(business_logic, query):
    find_identifier(business_logic, query, name_ok=False)
    # Specifying '-' for email means to erase any existing email addresses.
    emails = query.get('email', None)
    if emails == []:
        # No update specified
        emails = None  # pragma: no cover  # it's a pain to simulate this
    elif emails == ['-']:
        emails = []
    canary = business_logic.update(query['id'],
                                   query.get('name', None),
                                   query.get('periodicity', None),
                                   query.get('description', None),
                                   emails)
    return ('200 OK', {'status': 'ok', 'canary': jsonify_canary(canary)})


@handle_exceptions
@valid_parameters('id', 'name', 'slug')
def handle_get(business_logic, query):
    find_identifier(business_logic, query)
    canary = business_logic.get(query['id'])

    return ('200 OK', {'status': 'ok', 'canary': jsonify_canary(canary)})


@handle_exceptions
@boolean_parameters('verbose', 'paused', 'late')
@string_parameters('search')
@valid_parameters('verbose', 'paused', 'late', 'search')
def handle_list(business_logic, query):
    canaries = [jsonify_canary(canary)
                for canary in business_logic.list(
                    verbose=query.get('verbose', False),
                    paused=query.get('paused', None),
                    late=query.get('late', None),
                    search=query.get('search', None))]
    return ('200 OK', {'status': 'ok', 'canaries': canaries})


@handle_exceptions
@string_parameters('comment', 'm')
@valid_parameters('id', 'name', 'slug', 'comment', 'm')
def handle_trigger(business_logic, query):
    find_identifier(business_logic, query)
    comment = query.get('comment', query.get('m', ''))
    (recovered, unpaused) = business_logic.trigger(query['id'], comment)
    return ('200 OK',
            {'status': 'ok', 'recovered': recovered, 'unpaused': unpaused})


@handle_exceptions
@string_parameters('comment')
@valid_parameters('id', 'name', 'slug', 'comment')
def handle_pause(business_logic, query):
    find_identifier(business_logic, query)
    canary = business_logic.pause(query['id'], query.get('comment', ''))
    return ('200 OK', {'status': 'ok', 'canary': jsonify_canary(canary)})


@handle_exceptions
@string_parameters('comment')
@valid_parameters('id', 'name', 'slug', 'comment')
def handle_unpause(business_logic, query):
    find_identifier(business_logic, query)
    canary = business_logic.unpause(query['id'], query.get('comment', ''))
    return ('200 OK', {'status': 'ok', 'canary': jsonify_canary(canary)})


def jsonify_canary(canary):
    canary = copy(canary)
    for key, value in [(k, v) for k, v in canary.items()]:
        # This should never happen, but just in case...
        if value is None:  # pragma: no cover
            del canary[key]

    if 'deadline' in canary:
        canary['deadline'] = canary['deadline'].isoformat()

    if 'history' in canary:
        canary['history'] = tuple((d.isoformat(), c)
                                  for d, c in canary['history'])

    if 'periodicity_schedule' in canary:
        canary['periodicity_schedule'] = \
            tuple((d1.isoformat(), d2.isoformat(), p)
                  for d1, d2, p in canary['periodicity_schedule'])

    return canary


class LogbookWSGIRequestHandler(WSGIRequestHandler):  # pragma: no cover
    # Timeout incoming requests within 10 seconds to prevent somebody
    # from DoS'ing the service by connecting to the port and simply
    # sitting there without sending a request.
    timeout = 10

    def handle(self):
        try:
            return super(LogbookWSGIRequestHandler, self).handle()
        except socket.timeout as e:
            # Why WSGIRequestHandler doesn't handle this, I have no idea.
            self.log_error("Request timed out: %r", e)
            raise

    def log_message(self, format, *args):
        msg = format % args
        msg = re.sub(r'\b(auth_key=)[^&;]+', r'\1<key>', msg)
        log.info("%s - - %s" % (self.address_string(), msg))


if __name__ == '__main__':  # pragma: no cover
    main()
