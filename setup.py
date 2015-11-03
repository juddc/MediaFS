import sys
import os
from setuptools import setup


long_description = ("MediaFS is a Python API that makes it easy to search a "
    "directory tree. It has support for custom metadata as well as caching "
    "for faster searching. The primary design goal for MediaFS is to be a "
    "backend for managing media collections, such as for music or video, "
    "but the implementation is filetype-agnostic and can be used for working "
    "with any type of data.")

# encourage the use of scandir, but it comes with python >= 3.5, so only suggest for old versions
extras = {}
if sys.version_info.major <= 2 or (sys.version_info.major == 3 and sys.version_info.minor <= 4):
    extras['scandir'] = ['scandir']
    

setup(name='mediafs',
      version='1.0',
      description='MediaFS filesystem searching and indexing API',
      long_description=long_description,
      maintainer='Judd Cohen',
      maintainer_email='jcohen@juddnet.com',
      url='https://mediafs.readthedocs.org',
      packages=['mediafs'],
      license='MIT',
      install_requires=[],
      package_data={'': ['LICENSE', 'README.md']},
      extras_require=extras,
      scripts=['mediasearch.py'])

