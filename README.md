Coal Mine - Periodic task execution monitor
===========================================

Home page is [on Github](https://github.com/quantopian/coal-mine/).
Releases are available [in PyPI](https://pypi.python.org/pypi/coal_mine).

What is Coal Mine?
------------------

Periodic, recurring tasks are ubiquitous in computing, and so one of
the most common problems in systems administration and operations is
ensuring that such tasks execute as expected. Designing the tasks to
report errors is necessary but not sufficient; what if a task isn't
being run at all (crashed daemon, misconfigured crontab) or is running
much more slowly than it should be?

Coal Mine provides a simple yet powerful tool for solving this
problem. In a nutshell:

* Each recurring task has a Coal Mine "canary" associated with it.
* The task triggers the canary when it is finished executing.
* The canary knows how often the task is supposed to execute.
* Coal Mine alerts by email when a canary is late and alerts again
  when the late canary resumes.
* Coal Mine keeps a (partial) history of when each canary was
  triggered.


Track tasks that are supposed to execute periodically using "canaries"
that the tasks trigger when they execute. Alert by email when a canary
is late. Alert again when a late canary resumes. Keep a partial
history of canary trigger times.

The server notifies immediately when the deadline for an unpaused
canary passes. Similarly, the server notifies immediately when a
previously late canary is triggered.

Prerequisites
-------------

* Python 3.2
* MongoDB for storage (pull requests to add additional storage engines
  are welcome)
* requirements listed in requirements.txt
* for development, requirements listed in requirements_dev.txt

Concepts
--------

Coal Mine provides two interfaces, a REST API and a command-line
interface (CLI). Since triggering a canary requires nothing more than
hitting its endpoint with a GET or POST query, it's best to do
triggering through the API, so that the CLI doesn't need to be
installed on every system running monitoring tasks. For administrative
operations, on the other hand, the CLI is usually easier.

All timestamps stored and displayed by Coal Mine are in UTC.

### Operations

The operations that can be performed on canaries through the CLI or
API are:

* create
* delete
* reconfigure
* get information about
* pause -- stop monitoring and alerting
* unpause
* trigger
* list -- all canaries or the ones matching search terms

Coal Mine security is rudimentary. If the server is configured with an
optional authentication key, then the key must be specified with all
operations except trigger.

### Data

These canary attributes are specified when it is created or updated:

* name
* description
* periodicity -- the maximum number of seconds that can elapse before
  a canary is late, _or_ a schedule in the format described
  [below](#periodicity), which allows the periodicity of the canary to
  vary over time
* zero or more notification email address(es)

These are created and maintained by Coal Mine:

* slug -- the canary's name, lower-cased, with spaces and underscores
  converted to hyphens and other non-alphanumeric characters removed
* a random identifier consisting of eight lower-case letters,
  generated when the canary is created and guaranteed to be unique
  against other canaries in the database
* late state (boolean)
* notify state (boolean) indicating whether a notification needs to be
  sent out for this canary (used when notifications are being handled
  by a separate background task)
* paused state (boolean)
* deadline by which the canary should be triggered to avoid being late
* a history of triggers, pruned when >1000 or (>100 and older than one
  week)

#### Scheduled periodicity  <a name="periodicity"></a>

Coal Mine allows the periodicity of a canary to vary automatically
based on the time, date, day of week, etc. There are three contexts in
which this is useful:

1. a recurring task executes with different frequencies at different
   times;
2. a continuous recurring task takes more or less time to finish at
   different times; or
3. the urgency of responding to delays in a recurring task varies at
   different times.

To specify a varying periodicity for a canary, instead of just
specifying a number of seconds, you specify a serious of
[crontab-like directives](https://github.com/josiahcarlson/parse-crontab)
separated by semicolons. Here's an example, split onto multiple lines
for clarity:

    # 5-minute delays are ok on weekends ;
    * * * * sat,sun 300 ;
    # 5-minute days are ok overnight ;
    * 0-12 * * mon-fri 300 ;
    # otherwise, we require a shorter periodicity ;
    * 13-23 * * mon-fri 90

Notes:

* The last field in each directive is the periodicity value, i.e., the
  maximum number of seconds to allow between triggers during the
  specified time range.

* As indicated above, even though the example is shown split across
  multiple lines, it must be specified all on one line when providing
  it to Coal Mine.

* Note that comments like the ones shown above really are allowed in
  the schedule you specify to Coal Mine -- they're not just for
  decoration in the example -- but you need to remember to end them
  with semicolons.

* Schedule directives _cannot overlap_. For example, this won't work,
  because the second directive overlaps with the first one every
  Saturday and Sunday between midnight and noon:

        * * * * sat,sun 60 ;
        * 0-11 * * * 90

* If a canary's schedule has gaps, then _the canary is effectively
  paused_ during them. For example, in this schedule, the canary would
  be paused all day Saturday:

        * * * * sun 300 ;
        * * * * mon-fri 60

* As with everything else in Coal Mine, the hours and minutes
  specified here are in UTC.

* When you create or update a canary with a periodicity schedule, the
  canary data returned to you in response will include a
  "periodicity_schedule" field showing how the schedule you specified
  plays out. The schedule will extend far enough into the future for
  each of the directives you specified to be be shown at least once,
  or for a week, whichever is longer.

Installation and configuration
------------------------------

### Server

1. `pip install coal-mine`
2. Create `/etc/coal-mine.ini` (see [below](#ini-file)) or [use
   environment variables](#env-vars-config)
3. Run `coal-mine &`
4. Put that in `/etc/rc.local` or something as needed to ensure that
   it is restarted on reboot.

#### Server configuration file  <a name="ini-file"></a>

The server configuration file, `coal-mine.ini`, can go in the current
directory where the server is launched, `/etc`, or
`/usr/local/etc`. (If you need to put it somewhere else, modify the
list of directories near the top of `main()` in `server.py`.)

The file is (obviously) in INI format. Here are the sections and
settings that it can or must contain:

* \[logging\] -- optional
  * file -- log file path; otherwise logging goes to stderr
  * rotate -- if true, then rotate the log file when it gets too large
  * max\_size -- max log file size before rotating (default: 1048576)
  * backup\_count -- number of rotated log files to keep (default: 5)
* \[mongodb\] -- required
  * hosts -- MongoDB URI or comma-separated list of one or more host
    names
  * database -- database name. Coal Mine will create only one
    collection in the database, called "canaries". Omit if
    `hosts` contains a MongoDB URI
  * username -- omit if no authentication is required or `hosts`
    contains a URI
  * password -- omit if no authentication is required or if `hosts`
    contains a URI
  * replicaSet -- must be specified if using a replicaset and `hosts`
    isn't a URI
  * other arguments will be passed through to MongoClient
     * for example, tls can be set to True or False
* \[email\]
  * sender (required) -- email address to put in the From line of
    notification emails
  * host (optiona) -- SMTP host to connect to
  * port (optional) -- SMTP port to connect to
  * username (optional) -- SMTP username, must be specified if
    password is
  * password (optional) -- SMTP password, must be specified if
    username is
* \[wsgi\] -- optional
  * port -- port number the server should listen on (default: 80)
  * auth\_key -- if non-empty, then the specified key must be
    specified as a parameter of the same name with all API requests
    except "trigger".

#### Configurating via environment variables  <a name="env-vars-config"></a>

If the environment variable `MONGODB_URI` is set, then the server will
read its configuration from environment variables _instead of_
`coal-mine.ini`. (i.e., the configuration file will neither be
searched for nor read). When configured this way, logging
configuration is not supported, the `mongodb` configuration file
section is replaced with the `MONGODB_URI` variable, and the remaining
configuration settings are specified as follows:

* email.sender -> `EMAIL_SENDER`
* email.host -> `SMTP_HOST`
* email.port -> `SMTP_PORT`
* email.username -> `SMTP_USERNAME`
* email.password -> `SMTP_PASSWORD`
* wsgi.port -> `WSGI_PORT`
* wsgi.auth_key -> `WSGI_AUTH_KEY`

### Deploying the Server to Heroku

There's a `Procfile` in the source tree which allows you to deploy
this app to Heroku. This is new functionality which has not been
extensively tested, so please [file bug reports][bugs] if you run into
any issues! Here's how to do it in a nutshell:

[bugs]: https://github.com/quantopian/coal-mine/issues

1. Create a new Heroku app to hold it.
2. Connect a MongoDB database to the Heroku app via the `MONGODB_URI`
   config variable, via an add-on (I think ObjectRocket will work?),
   MongoDB Atlas, your own self-hosted MongoDB cluster, or whatever.
   It doesn't matter where the MongoDB database lives as long as
   Heroku can connect to it and its full URI is in `MONGODB_URI`.
3. Set `EMAIL_SENDER`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`,
   `SMTP_PASSWORD`. You'll need to add an SMTP add-on to the Heroku
   app or have an SMTP server somewhere else you can use; if you use
   an add-on, it'll probably call these settings by different names,
   so you'll have to copy them into the names that Coal Mine expects.
4. Set `WSGI_AUTH_KEY` to something long and random, since you don't
   want anyone on the internet to be able to mess with your Coal Mine
   instance.
5. Push the code to the Heroku app.
6. Make sure the app is configured to run at least one web dyno
   (should happen by default) and exactly 1 worker dyno.

Once all that's done you'll need to configure your CLI to talk to the
Heroku app as described below. Make sure to specify `https://` at the
start of the host name when configuring the CLI.

### CLI

1. `pip install coal-mine`
2. `cmcli configure [--host server-host-name] [--port server-port]
        [--auth-key key | --no-auth-key]`

The `--host` argument can take a URL base (i.e.,
`http://server-host-name` or `https://server-host-name`) as well. This
is useful if, for example, you've put your Coal Mine server behind an
SSL proxy so the CLI needs to use SSL to connect to it (which you
probably will, e.g., if you are deploying to Heroku as described
above).

The CLI stores its configuration in `~/.coal-mine.ini`. Note that the
authentication key is stored in plaintext. Any configuration
parameters the CLI needs that aren't stored in the INI file must be
specified explicitly on the command line when using the CLI.

Using Coal Mine
---------------

### CLI

The Coal Mine CLI, `cmcli`, provides convenient access to the full
range of Coal Mine's functionality.

To make the CLI easier to use, you can configure it as shown above,
but you also have the option of specifying the server connection
information every time you use it. Also, connnection information
specified on the command line overrides the stored configuration.

Here are some example commands:

    cmcli create --help
    
    cmcli create --name 'My Second Canary' --periodicity $((60*60*25))  # $((60*60*25)) is 25 hours
    cmcli trigger --id aseprogj
    cmcli delete --slug 'my-second-canary'

Run `cmcli --help` for more information.

For commands that operate on individual canaries, you can identify the
canary with `--id`, `--name`, or `--slug`. Note that for the `update`
command, if you want to update the name of a canary you will need to
identify it `--id` or `--slug`, because in that case the `--name`
argument is used to specify the new name.

API usage examples
------------------

### Example commands

    $ coal-mine &
    [1] 7564
    $ curl 'http://coal-mine-server/coal-mine/v1/canary/create?name=My+First+Canary&periodicity=3600'
    {
        "status": "ok",
        "canary": {
            "deadline": "2015-03-19T02:08:44.885182",
            "id": "fbkvlsby",
            "paused": false,
            "description": "",
            "periodicity": 3600,
            "name": "My First Canary",
            "slug": "my-first-canary",
            "emails": [],
            "history": [
                [
                    "2015-03-19T01:08:44.885182",
                    "Canary created"
                ]
            ],
            "late": false
        }
    }
    $ curl 'http://coal-mine-server/fbkvlsby?comment=short+form+trigger+url'
    {
        "recovered": false,
        "unpaused": false,
        "status": "ok"
    }
    $ curl 'http://coal-mine-server/coal-mine/v1/canary/trigger?slug=my-first-canary&comment=long+form+trigger+url'
    {
        "recovered": false,
        "unpaused": false,
        "status": "ok"
    }
    $ curl 'http://coal-mine-server/coal-mine/v1/canary/get?name=My+First+Canary'
    {
        "canary": {
            "paused": false,
            "name": "My First Canary",
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
                    "Canary created"
                ]
            ],
            "emails": [],
            "id": "fbkvlsby",
            "late": false,
            "slug": "my-first-canary",
            "deadline": "2015-03-19T02:11:56.408000",
            "periodicity": 3600,
            "description": ""
        },
        "status": "ok"
    }

All API endpoints are fully documented below.

### Watching a cron job

     0 0 * * * my-backup-script.sh && (curl http://coal-mine-server/fbkvlsby &>/dev/null)

API reference
-------------

All API endpoints are submitted as http(s) GET requests. Results are
returned in JSON.

All results have a "status" field which is "ok" on success or "error"
on failure. Failures also return a reasonable HTTP error status code.

Boolean fields in API should be specified as "true", "yes", or "1" for
true, or "false", "no", "0", or empty string for false. Boolean fields
in responses are standard JSON, i.e., "true" or "false".

Timestamps returned by the API are always UTC.

### Create canary

Endpoint: `/coal-mine/v1/canary/create`

Side effects:

Adds canary to database. Creates history record at current time with
"Canary created" as its comment. Sets deadline to current time plus
periodicity, unless "paused" was specified.

Required parameters:

* name
* periodicity
* auth\_key (if authentication is enabled in the server)

Optional parameters:

* description - empty if unspecified
* email - specify multiple times for multiple addresses; no
  notifications if unspecified
* paused - allows canary to be created already in paused state

Response is the same as shown for get().

### Delete canary

Endpoint: `/coal-mine/v1/canary/delete`

Required parameters:

* name, id, or slug
* auth\_key

Response:

    {'status': 'ok'}

### Update canary

Endpoint: `/coal-mine/v1/canary/update`

Side effects:

Updates the specified canary attributes. Updates deadline to latest
history timestamp plus periodicity if periodicity is updated and
canary is unpaused, and sets late state if new deadline is before
now. Sends notification if canary goes from not late to late or vice
versa.

Required parameters:

* id or slug (_not_ name, which should only be specified to update the
  name and slug)
* auth\_key

Optional parameters:

* name
* periodicity
* description
* email - specify a single value of "-" to clear existing email addresses

Response is the same as shown for get().

### Get canary

Endpoint: `/coal-mine/v1/canary/get`

Required parameters:

* name, id, or slug
* auth\_key

Response:

    {'status': 'ok',
     'canary': {'name': name,
               'description': description,
               'id': identifier,
               'slug': slug,
               'periodicity': seconds,
               'emails': [address, ...],
               'late': boolean,
               'paused': boolean,
               'deadline': 'YYYY-MM-DDTHH:MM:SSZ',
               'history': [['YYYY-MM-DDTHH:MM:SSZ', comment], ...]}}

### List canaries

Endpoint: `/coal-mine/v1/canary/list`

Required parameters:

* auth\_key

Optional parameters:

* verbose - include all query output for each canary
* paused - boolean, whether to list paused / unpaused canaries only
* late - boolean, whether to list late / timely canaries only
* search - string, regular expression to match against name, identifier, and
  slug

Response:

    {'status': 'ok',
     'canaries': [{'name': name,
                 'id': identifier},
                ...]}

If "verbose" is true, then the JSON for each canary includes all the
fields shown above, not just the name and identifier.

### Trigger canary

Endpoint: `/coal-mine/v1/canary/trigger`

Also: /_identifier_, in which case the "id" parameter is implied

Note that the server will accept POST requests for triggers as well as
GET requests, so that you can use triggers as webhooks in applications
that expect to be able to POST. The content of the POST is ignored;
even when using POST, the API parameters must still be specified as a
query string.

Side effects:

Sets late state to false. Sets deadline to now plus periodicity. Adds
history record. Prunes history records. Unpauses canary. Generates
notification email if canary was previously late.

Required parameters:

* name, id, or slug

Optional parameters:

* comment - stored in history with trigger record

Response:

    {'status': 'ok', 'recovered': boolean, 'unpaused': boolean}

* recovered - indicates whether the canary was previously late before
  this trigger
* unpaused - indicates whether the canary was previously paused before
  this trigger

### Pause canary

Endpoint: `/coal-mine/v1/canary/pause`

Side effects:

Clears deadline. Sets late state to false if necessary. Pauses
canary. Adds history record about pause. Prunes history records.

Required parameters:

* name, id, or slug
* auth\_key

Optional parameters:

* comment

Response is the same as shown for get().

### Unpause canary

Endpoint: `/coal-mine/v1/canary/unpause`

Side effects:

Sets deadline to now plus periodicity. Unpauses canary. Adds history
record about unpause. Prunes history records.

Required parameters:

* name, id, or slug
* auth\_key

Optional parameters:

* comment

Response is the same as shown for get().

Quis custodiet ipsos custodes?
------------------------------

Obviously, if you're relying on Coal Mine to let you know when
something is wrong, you need to make sure that Coal Mine itself stays
running. One way to do that is to have a cron job which periodically
triggers a canary and generates output (which crond will email to you)
if the trigger fails. Something like:

    0 * * * * (curl http://coal-mine-server/atvywzoa | grep -q -s '"status": "ok"') || echo "Failed to trigger canary."

I also recommend using a log-monitoring service such as Papertrail to
monitor and alert about errors in the Coal Mine log.

Contacts
--------

[Github](https://github.com/quantopian/coal-mine)

[Email](mailto:jik@kamens.us)

[PyPI](https://pypi.python.org/pypi/coal_mine)

Contributors
------------

Coal Mine was created by Jonathan Kamens, with design help from the
awesome folks at [Quantopian](https://www.quantopian.com/). Thanks,
also, to Quantopian for supporting the development and open-sourcing
of this project.

Maintaining the package
-----------------------

### Tests

Tests are expecting to be run with `pytest`. With all the packages in
`requirements.txt` and `requirements_dev.txt` installed, run `python
-m pytest`.

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

Alternatives
------------

Alternatives to Coal Mine include:

* [Dead Man's Snitch](https://deadmanssnitch.com/)
* [Cronitor.io](https://cronitor.io/)
* [Sheriff](https://github.com/dawanda/sheriff)

We chose to write something new, rather than using what's already out
there, for several reasons:

* We wanted more control over the stability and reliability of our
  watch service than the commercial alternatives provide.
* We wanted fine-grained control over the periodicity of our watches,
  as well as assurance that we would be notified immediately when a
  watch is late, something that not all of the alternatives
  guarantee.
* We like Python.
* We like OSS.

### To Do

(Pull requests welcome!)

Other storage engines.

Other notification mechanisms.

Web UI.

Links to Web UI in email notifications.

Repeat notifications if a canary remains late for an extended period
of time? Not even sure I want this.

Better authentication?

Support time-zone localization of displayed timestamps.

SSL support in server
