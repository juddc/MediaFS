Introduction to MediaFS
=======================

MediaFS is a Python library that makes it easy to search and manage a directory
tree. It has support for custom metadata as well as caching for faster searching.

The primary design goal for MediaFS is to be a backend for managing media
collections, such as for music or video, but the implementation is
filetype-agnostic and can be used for working with any type of data.


Simple Examples
---------------

.. code:: python

	from mediafs import RootDirectory

	fs = RootDirectory("/some/directory")

	# prints number of top-level files and directories
	print(len(fs))

	# prints file size of a file in bytes
	print(fs['some_file.txt'].size)



Iterating over files and directories
------------------------------------

There are a few ways to iterate over files and directories. The primary way is with ``Directory.all()``. This is a generator function, so if you want to assign the results of it to a variable, you'll need to wrap it in a call to ``list()``.

.. code:: python

	items = fs.all() # won't work :(
	items = list(fs.all()) # works :)


``all()`` takes several arguments - ``recursive``, ``reverse``, ``dirs``, and ``files``, all of which are optional arguments, and all of which take boolean values.

	* ``recursive``: If True, will iterate recursively. If False, will just give top-level items. (defaults to False)
	* ``reverse``: If True, will reverse the item order. (defaults to False)
	* ``dirs``: If True, will return directories. If False, will not return directories. (defaults to True)
	* ``files``: If True, will return files. If False, will not return files. (defaults to True)

.. code:: python

	# print the names of all top-level files and directories
	for item in fs.all():
	    print(item.name)

	# print the names of every file and directory
	for item in fs.all(recursive=True):
	    print(item.name)

	# print the names of every directory
	for item in fs.all(recursive=True, files=False):
	    print(item.name)

	# print the names of every file
	for item in fs.all(recursive=True, dirs=False):
	    print(item.name)

Because ``filter()``, ``search()``, and ``query()`` all use ``all()`` under the hood, they each take ``recursive``, ``dirs``, and ``files`` arguments and pass them directly to ``all()``. This means that when searching, the semantics of these three arguments are the same across all four methods.


