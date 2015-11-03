Root Directory Classes
======================

Root directory
--------------

.. autoclass:: mediafs.RootDirectory
	:members: save, scrubMetadata, _getFileClass, _getDirectoryClass, _orderDirectory, _ignorePath, _directoryRefresh, _fileRefresh, _readMetadata, _writeMetadata, _readTreeData, _writeTreeData, _getMetadataForObject


Root directory with caching and metadata persistance
----------------------------------------------------
.. autoclass:: mediafs.CachedRootDirectory


Root directory that keeps itself in sync with the filesystem
------------------------------------------------------------

Requirements:
	* ``butter``: https://pypi.python.org/pypi/butter
	* Linux: The ``butter`` library is Linux-specific
	* ``asyncio``: Python 3.4+

Example:

.. code:: python

	import asyncio
	from mediafs.synced import SyncedRootDirectory

	loop = asyncio.get_event_loop()
	fs = SyncedRootDirectory("/home/john/documents", loop)

	# make sure we start perfectly in sync
	fs.refresh(recursive=True)

	@asyncio.coroutine
	def mainloop():
	    while True:
	        filesystemEvents = yield from fs.processFilesystemEvents()
	        for event in filesystemEvents:
	            # event is a namedtuple with 3 elements
	            print(event.type, event.parent, event.name)
	        yield from asyncio.sleep(1)

	loop.run_until_complete(mainloop())


.. autoclass:: mediafs.synced.SyncedRootDirectory
	:members: processFilesystemEvents, isSynced


Root directory that stores metadata in extended filesystem attributes
---------------------------------------------------------------------

Requirements:
	* ``pyxattr``: https://pypi.python.org/pypi/pyxattr
	* Linux: The ``pyxattr`` library is Linux-specific


Example:

.. code:: python

	from mediafs.xattrs import XAttrRootDirectory
	
	fs = XAttrRootDirectory("/home/john/documents")
	fs['file1.txt'].metadata['author'] = "John Smith"
	# done! no need to call save()


.. autoclass:: mediafs.xattrs.XAttrRootDirectory
	:members: _getMetadataForObject

.. autoclass:: mediafs.xattrs.XAttrMetadata
	:members: __getitem__, __setitem__, __delitem__, __contains__, __iter__, __len__, keys, values, items, pop, copy
