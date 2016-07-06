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
Coal Mine WSGI server
"""

from coal_mine.business_logic import BusinessLogic, CanaryNotFoundError
from copy import copy
from cgi import parse_qs
from configparser import SafeConfigParser, NoSectionError, NoOptionError
from functools import partial, wraps
import json
import logbook
from coal_mine.mongo_store import MongoStore
import os
import re
import socket
import sys
from wsgiref.simple_server import make_server, WSGIRequestHandler

config_file = 'coal-mine.ini'
url_prefix = '/coal-mine/v1/canary/'

log = logbook.Logger('coal-mine')


def main():  # pragma: no cover
    config = SafeConfigParser()
    dirs = ('.', '/etc', '/usr/local/etc')
    if not config.read([os.path.join(dir, config_file) for dir in dirs]):
        sys.exit('Could not find {} in {}'.format(config_file, dirs))

    try:
        logfile = config.get('logging', 'file')
        rotating = config.getboolean('logging', 'rotate', fallback=False)
        if rotating:
            max_size = config.get('logging', 'max_size', fallback=1048576)
            backup_count = config.get('logging', 'backup_count', fallback=5)
            handler = logbook.RotatingFileHandler(logfile, max_size=max_size,
                                                  backup_count=backup_count)
        else:
            handler = logbook.FileHandler(logfile)
        handler.push_application()
    except:
        logbook.StderrHandler().push_application()

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
    args[0] = [s.strip() for s in args[0].split(',')]
    store = MongoStore(*args, **kwargs)

    try:
        email_sender = config.get('email', 'sender')
    except NoSectionError:
        sys.exit('No "email" section in config file')
    except NoOptionError:
        sys.exit('No "sender" setting in "email" section of config file')

    business_logic = BusinessLogic(store, email_sender)

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
        auth_key = None

    httpd = make_server('', listen_port,
                        partial(application, business_logic, auth_key),
                        handler_class=LogbookWSGIRequestHandler)
    business_logic.schedule_next_deadline()
    httpd.serve_forever()


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
