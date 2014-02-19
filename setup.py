# Use setuptools if we can
try:
    from setuptools.core import setup
except ImportError:
    from distutils.core import setup

PACKAGE = 'django_database_constraints'
VERSION = '0.2'

setup(
    name=PACKAGE, version=VERSION,
    description="Django library for more easily working with transactions and constraints in Forms, ModelForms and the Views that use them.",
    packages=[
        'django_database_constraints',
    ],
    license='MIT',
    author='James Aylett',
    author_email='james@tartarus.org',
    install_requires=[
        'Django>=1.6.0',
    ],
    url = 'https://github.com/jaylett/django-database-constraints',
    classifiers = [
        'Intended Audience :: Developers',
        'Framework :: Django',
        'License :: OSI Approved :: MIT License',
        'Programming Language :: Python :: 2',
    ],
)
