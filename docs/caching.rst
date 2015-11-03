Caching
=======

Using the cache
---------------

MediaFS can cache the entire directory tree. This reduces the need to crawl the entire filesystem recursively for files and directories. Data that is cached as part of the directory tree include most lazily evaluated properties such as ``File.abspath``, ``File.relpath``, ``File.size`` and ``Directory.size``, ``File.md5()``, ``File.crc()``, and others. This means that if you need to, for example, get the md5sum of a bunch of large files, you can do that once and not have to recalculate them again until you choose to call refresh, even between multiple program runs.


.. code:: python

	from mediafs import CachedRootDirectory
	fs = CachedRootDirectory("/home/john/documents")
	fs.refresh(recursive=True)

	# might take 5-6 seconds to run
	print(fs['large_archive.zip'].md5())

	# write out the cache to a file
	fs.save()
	del fs

	fs = CachedRootDirectory("/home/john/documents")

	# runs almost instantly - uses cached data
	print(fs['large_archive.zip'].md5())

	# might take 5-6 seconds to run - refresh means ignore the cache and recalculate
	print(fs['large_archive.zip'].md5(refresh=True))

	# write out the cache to a file
	fs.save()


Calling ``save()`` will create a ``.tree.json`` file in the root directory of the specified filesystem path. You can specify the name and location of this file by passing in a path (relative to the root path) to the ``treeFile`` argument of the constructor.


.. code:: python

	# create the cache in /home/john/treeFileCache.json:
	fs = CachedRootDirectory("/home/john/documents", treeFile="../treeFileCache.json")


When a filesystem object is instantiated, it will check if ``treeFile`` exists, and if so, it will load it into the directory tree data structure.


Disabling caching
-----------------

If you need to use functionality in CachedRootDirectory (such as serialized metadata) but don't want to use any of the caching functionality, it's easy to disable it. Just pass ``None`` to the ``treeFile`` argument.

.. code:: python

	from mediafs import CachedRootDirectory
	fs = CachedRootDirectory("/home/john/documents", treeFile=None)
