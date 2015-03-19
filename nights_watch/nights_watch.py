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
Night's Watch WSGI server
"""

from nights_watch.business_logic import BrickBusinessLogic
from cgi import parse_qs
from configparser import SafeConfigParser, NoSectionError, NoOptionError
from functools import wraps
import json
import logbook
from nights_watch.mongo_store import MongoBrickStore
import os
import re
import sys
from wsgiref.simple_server import make_server, WSGIRequestHandler

config_file = 'nights-watch.ini'
url_prefix = '/nights-watch/v1/brick/'

log = logbook.Logger('nights-watch')
business_logic = None
auth_key = None


def main():
    global business_logic, auth_key

    config = SafeConfigParser()
    dirs = ('.', '/etc', '/usr/local/etc')
    if not config.read([os.path.join(dir, config_file) for dir in dirs]):
        sys.exit('Could not find {} in {}'.format(config_file, dirs))

    try:
        logfile = config.get('logging', 'file')
        try:
            rotating = config.getboolean('logging', 'rotate')
            max_size = config.get('logging', 'max_size', fallback=1048576)
            backup_count = config.get('logging', 'backup_count', fallback=5)
            handler = logbook.RotatingFileHandler(logfile, max_size=max_size,
                                                  backup_count=backup_count)
            print('rotating')
        except:
            handler = logbook.FileHandler(logfile)
        handler.push_application()
    except:
        pass

    try:
        kwargs = dict(config.items('mongodb'))
    except NoSectionError:
        sys.exit('No "mongodb" section in config file')
    args = []
    for arg in ('hosts', 'database', 'username', 'password'):
        try:
            args.append(config.get('mongodb', arg))
        except NoOptionError:
            sys.exit('No "{}" setting in "mongodb" section of config file'.
                     format(arg))
        kwargs.pop(arg)
    store = MongoBrickStore(*args, **kwargs)

    try:
        email_sender = config.get('email', 'sender')
    except NoSectionError:
        sys.exit('No "email" section in config file')
    except NoOptionError:
        sys.exit('No "sender" setting in "email" section of config file')

    business_logic = BrickBusinessLogic(store, email_sender)

    try:
        listen_port = int(config.get('wsgi', 'port'))
        log.info('Binding to port {}'.format(listen_port))
    except:
        listen_port = 80
        log.info('Binding to default port {}'.format(listen_port))

    try:
        auth_key = config.get('wsgi', 'auth_key')
        log.info('Server authentication enabled')
    except:
        log.warning('Server authentication DISABLED')

    httpd = make_server('localhost', listen_port, application,
                        handler_class=LogbookWSGIRequestHandler)
    business_logic.schedule_next_deadline()
    httpd.serve_forever()


def application(environ, start_response):
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

    if not path_info.startswith(url_prefix):
        start_response('404 Not Found', headers=[])
        return []

    command = path_info[len(url_prefix):]

    if command not in handlers:
        start_response('404 Not Found', headers=[])
        return []

    q = parse_qs(environ['QUERY_STRING'])
    if auth_key and command != 'trigger' and \
       q.pop('auth_key', [None])[0] != auth_key:
        start_response('401 Unauthorized', headers=[])
        return []

    (status_code, data) = handlers[command](q, start_response)

    data = [json.dumps(data, indent=4).encode('utf-8'),
            '\n'.encode('utf-8')]

    start_response(status_code,
                   headers=[('Content-Type', 'text/json; charset=utf-8')])
    return data


def required_parameters(*args):
    def decorator(f):
        @wraps(f)
        def wrapper(query, start_response):
            for arg in args:
                if arg not in query:
                    raise Exception('Missing argument "{}"'.format(arg))
            return f(query, start_response)
        return wrapper
    return decorator


def find_identifier(name_ok=True):
    def decorator(f):
        @wraps(f)
        def wrapper(query, start_response):
            name = slug = identifier = None
            if 'id' in query:
                identifier = query.pop('id')[-1]
            elif 'slug' in query:
                slug = query.pop('slug')[-1]
            elif name_ok and 'name' in query:
                name = query.pop('name')[-1]
            query['id'] = business_logic.find_identifier(
                name, slug, identifier)
            return f(query, start_response)
        return wrapper
    return decorator


def string_parameters(*args):
    def decorator(f):
        @wraps(f)
        def wrapper(query, start_response):
            for arg in args:
                if arg in query:
                    query[arg] = query[arg][-1]
            return f(query, start_response)
        return wrapper
    return decorator


def int_parameters(*args):
    def decorator(f):
        @wraps(f)
        def wrapper(query, start_response):
            for arg in args:
                if arg in query:
                    query[arg] = int(query[arg][-1])
            return f(query, start_response)
        return wrapper
    return decorator


def boolean_parameters(*args):
    def decorator(f):
        @wraps(f)
        def wrapper(query, start_response):
            for arg in args:
                if arg not in query:
                    continue
                val = query[arg][-1]
                if val.lower() in ('true', 'yes', '1'):
                    val = True
                elif val.lower() in ('false', 'no', '0', ''):
                    val = False
                else:
                    raise Exception(
                        'Bad boolean value "{}" for parameter "{}"'.format(
                            val, arg))
            return f(query, start_response)
        return wrapper
    return decorator


def valid_parameters(*args):
    def decorator(f):
        @wraps(f)
        def wrapper(query, start_response):
            for arg in query:
                if arg not in args:
                    raise Exception('Unexpected argument "{}"'.format(arg))
            return f(query, start_response)
        return wrapper
    return decorator


def handle_exceptions(f):
    @wraps(f)
    def wrapper(query, start_response):
        try:
            return f(query, start_response)
        except Exception as e:
            log.exception('Exception in {}'.format(f))
            return ('400 Bad Request', {'status': 'error', 'error': repr(e)})
    return wrapper


@handle_exceptions
@required_parameters('name', 'periodicity')
@string_parameters('name', 'description')
@int_parameters('periodicity')
@boolean_parameters('paused')
@valid_parameters('name', 'periodicity', 'description', 'email', 'paused')
def handle_create(query, start_response):
    brick = business_logic.create(query['name'],
                                  query['periodicity'],
                                  query.get('description', ''),
                                  query.get('email', []),
                                  query.get('paused', False))
    return ('200 OK', {'status': 'ok', 'brick': jsonify_brick(brick)})


@handle_exceptions
@find_identifier()
@valid_parameters('id')
def handle_delete(query, start_response):
    business_logic.delete(query['id'])
    return ('200 OK', {'status': 'ok'})


@handle_exceptions
@find_identifier(name_ok=False)
@string_parameters('name', 'description')
@int_parameters('periodicity')
@valid_parameters('id', 'name', 'periodicity', 'description', 'email')
def handle_update(query, start_response):
    brick = business_logic.update(query['id'],
                                  query.get('name', None),
                                  query.get('periodicity', None),
                                  query.get('description', None),
                                  query.get('email', None))
    return ('200 OK', {'status': 'ok', 'brick': jsonify_brick(brick)})


@handle_exceptions
@find_identifier()
@valid_parameters('id')
def handle_get(query, start_response):
    brick = business_logic.get(query['id'])

    return ('200 OK', {'status': 'ok', 'brick': jsonify_brick(brick)})


@handle_exceptions
@boolean_parameters('verbose', 'paused', 'late')
@valid_parameters('verbose', 'paused', 'late')
def handle_list(query, start_response):
    bricks = [jsonify_brick(brick)
              for brick in business_logic.list(
                  query.get('verbose', False),
                  query.get('paused', False),
                  query.get('late', False))]
    return ('200 OK', {'status': 'ok', 'bricks': bricks})


@handle_exceptions
@find_identifier()
@string_parameters('comment')
@valid_parameters('id', 'comment')
def handle_trigger(query, start_response):
    (recovered, unpaused) = business_logic.trigger(query['id'],
                                                   query.get('comment', ''))
    return ('200 OK',
            {'status': 'ok', 'recovered': recovered, 'unpaused': unpaused})


@handle_exceptions
@find_identifier()
@string_parameters('comment')
@valid_parameters('id', 'comment')
def handle_pause(query, start_response):
    brick = business_logic.pause(query['id'],
                                 query.get('comment', ''))
    return ('200 OK', {'status': 'ok', 'brick': jsonify_brick(brick)})


@handle_exceptions
@find_identifier()
@string_parameters('comment')
@valid_parameters('id', 'comment')
def handle_unpause(query, start_response):
    brick = business_logic.unpause(query['id'],
                                   query.get('comment', ''))
    return ('200 OK', {'status': 'ok', 'brick': jsonify_brick(brick)})


def jsonify_brick(brick):
    for key, value in [(k, v) for k, v in brick.items()]:
        if value is None:
            del brick[key]

    if 'deadline' in brick:
        brick['deadline'] = brick['deadline'].isoformat()

    if 'history' in brick:
        brick['history'] = tuple((d.isoformat(), c)
                                 for d, c in brick['history'])
    return brick


class LogbookWSGIRequestHandler(WSGIRequestHandler):
    def log_message(self, format, *args):
        msg = format % args
        msg = re.sub(r'\b(auth_key=)[^&;]+', r'\1<key>', msg)
        log.info("%s - - %s\n" % (self.address_string(), msg))


if __name__ == '__main__':
    main()
