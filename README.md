Night's Watch - Periodic task execution monitor
===============================================

Track tasks (called, here, "bricks") that are supposed to execute
periodically. Alert by email when a brick is late. Alert again when a
late brick resumes. Keep a partial history of brick trigger times.

Uses MongoDB for storage. Pull requests to add additional storage
engines are welcome.

The server notifies immediately when the deadline for an unpaused
brick passes. Similarly, the server notifies immediately when a
previously late brick is triggered.

All timestamps are stored and displayed in UTC.

Prerequisites
-------------

Python 3.

Requirements listed in requirements.txt.

For development, requirements listed in requirements_dev.txt.

Usage examples
--------------

    $ nights-watch &
    [1] 7564
    $ curl 'http://localhost:8080/nights-watch/v1/brick/create?name=My+First+Brick&periodicity=3600'
    {
        "status": "ok",
        "brick": {
            "deadline": "2015-03-19T02:08:44.885182",
            "id": "fbkvlsby",
            "paused": false,
            "description": "",
            "periodicity": 3600,
            "name": "My First Brick",
            "slug": "my-first-brick",
            "emails": [],
            "history": [
                [
                    "2015-03-19T01:08:44.885182",
                    "Snitch created"
                ]
            ],
            "late": false
        }
    }
    $ curl 'http://localhost:8080/fbkvlsby?comment=shot+form+trigger+url'
    {
        "recovered": false,
        "unpaused": false,
        "status": "ok"
    }
    $ curl 'http://localhost:8080/nights-watch/v1/brick/trigger?slug=my-first-brick&comment=long+form+trigger+url'
    {
        "recovered": false,
        "unpaused": false,
        "status": "ok"
    }
    $ curl 'http://localhost:8080/nights-watch/v1/brick/get?name=My+First+Brick'
    {
        "brick": {
            "paused": false,
            "name": "My First Brick",
            "history": [
                [
                    "2015-03-19T01:11:56.408000",
                    "Triggered (long form trigger url)"
                ],
                [
                    "2015-03-19T01:10:42.608000",
                    "Triggered (short form trigger url)"
                ],
                [
                    "2015-03-19T01:08:44.885000",
                    "Snitch created"
                ]
            ],
            "emails": [],
            "id": "fbkvlsby",
            "late": false,
            "slug": "my-first-brick",
            "deadline": "2015-03-19T02:11:56.408000",
            "periodicity": 3600,
            "description": ""
        },
        "status": "ok"
    }

All API endpoints are fully documented below.

Server configuration
--------------------

Create <tt>nights-watch.ini</tt> in the current directory, or
<tt>/etc</tt>, or <tt>/usr/local/etc</tt>, or modify the list of
directories hear the top of <tt>main()</tt> in
<tt>nights-watch.py</tt> if you want to put it somewhere else.

Here's what can go in the config file:

* [logging] - optional
  * file - specify the log file; otherwise logging goes to stderr
  * rotate - if true, then rotate the log file when it gets too large
  * max\_size - max log file size before rotating (default: 1048576)
  * backup\_count - number of rotated log files to keep (default: 5)
* [mongodb] - required
  * hosts - the first argument to pymongo's MongoClient or
    MongoReplicaSetClient
  * database - database name
  * username - must be specified, but can be blank if no
    authentication is required
  * password - must be specified, but can be blank if no
    authentication is required
  * replicaSet - must be specified if using a replicaset
  * other arguments will be passed through to MongoClient or
    MongoReplicaSetClient
* [email] - required
  * sender - email address to put in the From line of notification
    emails
* [wsgi] - optional
  * port - port number the server should listen on (default: 80)
  * auth\_key - if non-empty, then the specified key must be specified
    as a parameter of the same name with all API requests except
    "trigger".

API
---

All API endpoints are submitted as http(s) GET requests. Results are
returned in JSON.

All results have a "status" field which is "ok" on success or "error"
on failure. Failures also return a reasonable HTTP error status code.

Boolean fields in API should be specified as "true", "yes", or "1" for
true, or "false", "no", "0", or empty string for false. Boolean fields
in responses are standard JSON, i.e., "true" or "false".

Timestamps returned by API are always UTC.

### Create brick

Endpoint: /nights-watch/v1/brick/create

Side effects:

Adds brick to database. Creates history record at current time with
"Brick created" as its comment. Sets deadline to current time plus
periodicity, unless "paused" was specified.

Required parameters:

* name
* periodicity
* auth_key (if authentication is enabled in the server)

Optional parameters:

* description - empty if unspecified
* email - specify multiple times for multiple addresses; no
  notifications if unspecified
* paused - allows brick to be created already in paused state

Response is the same as shown for get().

### Delete brick

Endpoint: /nights-watch/v1/brick/delete

Required parameters:

* name, id, or slug
* auth_key

Response:

    {'status': 'ok'}

### Update brick

Endpoint: /nights-watch/v1/brick/update

Side effects:

Updates the specified brick attributes. Updates deadline to latest
history timestamp plus periodicity if periodicity is updated and brick
is unpaused, and sets late state if new deadline is before now. Sends
notification if brick goes from not late to late or vice versa.

Required parameters:

* id or slug (_not_ name, which should only be specified to update the
  name and slug)
* auth_key

Optional parameters:

* name
* periodicity
* description
* email

Response is the same as shown for get().

### Get brick

Endpoint: /nights-watch/v1/brick/get

Required parameters:

* name, id, or slug
* auth_key

Response:

    {'status': 'ok',
     'brick': {'name': name,
               'description': description,
               'id': identifier,
               'slug': slug,
               'periodicity': seconds,
               'emails': [address, ...],
               'late': boolean,
               'paused': boolean,
               'deadline': 'YYYY-MM-DDTHH:MM:SSZ',
               'history': [['YYYY-MM-DDTHH:MM:SSZ', comment], ...]}}

### List bricks

Endpoint: /nights-watch/v1/brick/list

Required parameters:

* auth_key

Optional parameters:

* verbose - include all query output for each brick
* paused - boolean, whether to list paused / unpaused bricks only
* late - boolean, whether to list late / timely bricks only

Response:

    {'status': 'ok',
     'bricks': [{'name': name,
                 'id': identifier},
                ...]}

If "verbose" is true, then the JSON for each brick includes all the
fields shown above, not just the name and identifier.
                
### Trigger brick

Endpoint: /nights-watch/v1/brick/trigger

Also: /_identifier_, in which case the "id" parameter is implied

Side effects:

Sets late state to false. Sets deadline to now plus periodicity. Adds
history record. Prunes history records. Unpauses brick. Generates
notification email if brick was previously late.

Required parameters:

* name, id, or slug
* auth_key

Optional parameters:

* comment - stored in history with trigger record

Response:

    {'status': 'ok', 'recovered': boolean, 'unpaused': boolean}

* recovered - indicates whether the brick was previously late before
  this trigger
* unpaused - indicates whether the brick was previously paused before
  this trigger

### Pause brick

Endpoint: /nights-watch/v1/brick/pause

Side effects:

Clears deadline. Sets late state to false if necessary. Pauses
brick. Adds history record about pause. Prunes history records.

Required parameters:

* name, id, or slug
* auth_key

Optional parameters:

* comment

Response is the same as shown for get().

### Unpause brick

Endpoint /nights-watch/v1/brick/unpause

Side effects:

Sets deadline to now plus periodicity. Unpauses brick. Adds history
record about unpause. Prunes history records.

Required parameters:

* name, id, or slug
* auth_key

Optional parameters:

* comment

Response is the same as shown for get().

Development philosophy
----------------------

Use Python.

Do one, simple thing well. There are several similar projects out
there that do more than this project attempts to do.

Make the implementation as simple and straightforward as possible. The
code should be small. What everything does should be obvious from
reading it.

Minimize external dependencies. If something is simple and
straightforward to do ourselves, don't use a third-party package just
for the sake of using a third-party package.

Data model
----------

For each brick, we store:

* name
* description
* slug - the name, lower-cased, with spaces and underscores converted
  to hyphens and other non-alphanumeric characters removed
* random identifier, guaranteed unique
* periodicity - maximum number of seconds that can elapse before a
  brick is late.
* notification email address(es)
* late state (boolean)
* paused state (boolean)
* deadline for next update
* history of triggers, a week's worth or 100, whichever is larger

Timestamps in database are UTC.

To Do
-----

(Pull requests welcome!)

Other storage engines.

Unit tests would be nice.

Web UI.

Links to Web UI in email notifications.

Repeat notifications if a brick remains late for an extended period of
time? Not even sure I want this.

Release to PyPI.

Better authentication?

Support time-zone localization of displayed timestamps.
