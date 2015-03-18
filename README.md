Night's Watch - Periodic task execution monitor
===============================================

Track tasks (called, here, "bricks") that are supposed to execute
periodically. Alert by email when a brick is late. Alert again when a
late brick resumes. Keep a (truncated) history of brick trigger times.

Data model
----------

For each brick, we store:

* name
* description
* slug - the name, lower-cased, with spaces and underscores converted
  to hyphens and other non-alphanumeric characters removed
* internal identifier, not exposed in the API
* random external identifier, guaranteed unique
* periodicity, in seconds
* notification email address(es)
* late state (boolean)
* paused state (boolean)
* deadline for next update
* history of previous week's worth of triggers

Timestamps in database are UTC.

API
---

All API endpoints are submitted as http(s) GET requests. Results are
returned in JSON.

All results have a "status" field which is "ok" on success or "error"
on failure. Failures also return a reasonable HTTP error status code.

API endpoints required basic HTTP authentication.

Boolean fields in API should be specified as "true", "yes", or "1" for
true, or "false", "no", "0", or empty string for false. Boolean fields
in responses are standard JSON, i.e., "true" or "false".

Timestamps returned by API are always UTC.

### Create brick

Endpoint: /nights-watch/brick/v1/create

Side effects:

Adds brick to database. Creates history record at current time with
"Brick created" as its comment. Sets deadline for next update to
current time plus periodicity, unless "paused" was specified.

Required parameters:

* name
* periodicity

Optional parameters:

* description - empty if unspecified
* email - specify multiple times for multiple addresses; no
  notifications if unspecified
* paused - allows brick to be created already in paused state

Response:

    {'status': 'ok', 'id': identifier}

### Delete brick

Endpoint: /nights-watch/brick/v1/delete

Required parameters:

* name, id, _or_ slug

Response:

    {'status': 'ok', 'name': name, 'id': identifier}

### Update brick

Endpoint: /nights-watch/brick/v1/update

Required parameters:

* name, id, _or_ slug

Optional parameters:

* periodicity
* description
* email

### Query brick

Endpoint: /nights-watch/brick/v1/query

Required parameters:

* name, id, _or_ slug

Response:

    {'status': 'ok',
     'brick': {'name': name,
               'description': description,
               'id': identifier,
               'slug': slug,
               'periodicity': seconds,
               'email': [address, ...],
               'late': boolean,
               'paused': boolean,
               'deadline': 'YYYY-MM-DDTHH:MM:SSZ',
               'history': {'YYYY-MM-DDTHH:MM:SSZ': comment, ...}}}

### List bricks

Endpoint: /nights-watch/brick/v1/list

Required parameters:

None

Optional parameters:

* verbose - include all query output for each brick

Response:

    {'status': 'ok',
     'bricks': [{'name': name,
                 'id': identifier},
                ...]}

If "verbose" is true, then the JSON for each brick includes all the
fields shown above, not just the name and identifier.
                
### Trigger brick

Endpoint: /nights-watch/brick/v1/trigger

Side effects:

Sets late state to false. Sets deadline for next trigger. Adds history
record. Prunes history records more than a week old. Unpauses brick.

Required parameters:

* name, id, _or_ slug

Optional parameters:

* comment - stored in history with trigger record

Response:

    {'status': 'ok', 'recovered': boolean, 'unpaused': boolean}

* recovered - indicates whether the brick was previously late before
  this trigger
* unpaused - indicates whether the brick was previously paused before
  this trigger

### Pause brick

Endpoint: /nights-watch/brick/v1/pause

Side effects:

Clears deadline. Sets late state to false. Pauses brick. Adds history
record about pause. Prunes history records more than a week old.

Required parameters:

* name, id, _or_ slug

### Unpause brick

Endpoint /nights-watch/brick/v1/unpause

Side effects:

Sets deadline. Unpauses brick. Adds history record about
unpause. Prunes history records.

Required parameters:

* name, id, _or_ slug
