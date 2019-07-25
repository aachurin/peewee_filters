#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import re

from setuptools import setup


def get_version(package):
    """
    Return package version as listed in `__version__` in `init.py`.
    """
    init_py = open(os.path.join(package, '__init__.py')).read()
    return re.search("__version__ = ['\"]([^'\"]+)['\"]", init_py).group(1)


def get_packages(package):
    """
    Return root package and all sub-packages.
    """
    return [dirpath
            for dirpath, dirnames, filenames in os.walk(package)
            if os.path.exists(os.path.join(dirpath, '__init__.py'))]


def get_long_description(long_description_file):
    """
    Read long description from file.
    """
    with open(long_description_file, encoding='utf-8') as f:
        long_description = f.read()

    return long_description


version = get_version('peewee_filters')


setup(
    name='peewee_filters',
    version=version,
    url='https://github.com/aachurin/peewee_filters',
    license='BSD',
    description='Generic filters for peewee',
    long_description=get_long_description('README.md'),
    long_description_content_type='text/markdown',
    author='Churin Andrey',
    author_email='aachurin@gmail.com',
    packages=get_packages('peewee_filters'),
    install_requires=[
        'peewee',
        'typesystem'
    ],
    classifiers=[
        'Development Status :: 3 - Alpha',
        'Environment :: Web Environment',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: BSD License',
        'Operating System :: OS Independent',
        'Topic :: Internet :: WWW/HTTP',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3 :: Only',
        'Programming Language :: Python :: 3.5',
        'Programming Language :: Python :: 3.6',
        'Programming Language :: Python :: 3.7',
        'Programming Language :: Python :: Implementation :: PyPy',
        'Programming Language :: Python :: Implementation :: CPython'
    ]
)
