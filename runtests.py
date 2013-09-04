import os.path
import subprocess
import sys
from django.conf import settings

DATABASES = {
    'postgresql': {
        'ENGINE': 'django.db.backends.postgresql_psycopg2',
        'NAME': 'django_database_constraints',
        'USER': '',
        'PASSWORD': '',
        'HOST': 'localhost',
        'PORT': '',
    },
    'mysql': {
        'ENGINE': 'django.db.backends.mysql',
        'NAME': 'test_dummy',
        'USER': '',
        'PASSWORD': '',
        'HOST': 'localhost',
        'PORT': '',
    },
    # can't figure out how to run sqlite3 with multithreaded support
    # during tests, so worthless trying this
    #'sqlite3': {
    #    'ENGINE': 'django.db.backends.sqlite3',
    #    'TEST_NAME': os.path.join(os.path.realpath(os.path.dirname(__file__)), 'test_sqlite_database'),
    #},
}

settings.configure(
    DEBUG=True,
    INSTALLED_APPS = [
        'django_database_constraints',
    ],
    DATABASES = {
        'default': DATABASES['postgresql'],
    },
)


# after we have some settings
from django.test.utils import override_settings


def run_against(db):
    @override_settings(DATABASES = { 'default': DATABASES[db] })
    def run_tests():
        print "Running tests against %s database." % db

        #from django.test.simple import DjangoTestSuiteRunner
        #test_runner = DjangoTestSuiteRunner(verbosity=1, failfast=False)
        from django.test.runner import DiscoverRunner
        test_runner = DiscoverRunner(verbosity=1, failfast=False)
        failures = test_runner.run_tests(['django_database_constraints', ])
        if failures: #pragma no cover
            sys.exit(failures)
    run_tests()


if len(sys.argv) == 1: #pragma no cover
    # we can't call run_against() multiple times and have it actually work
    # (possibly only since Django 1.6) for reasons I don't have time to
    # track down now (it's ignoring @override_settings on subsequent calls)
    failures = 0
    for db in DATABASES.keys():
        args = [ sys.executable, sys.argv[0], db ]
        rc = subprocess.call(args)
        failures += rc
    if failures != 0:
        print "\nTOTAL FAILURES: %i" % failures
        sys.exit(failures)
elif len(sys.argv) == 2:
    run_against(sys.argv[1])
else: #pragma: no cover
    print >>sys.stderr, "Cannot run against multiple databases in one run."
    sys.exit(100)
