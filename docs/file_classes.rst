File and Directory Classes
==========================

File Objects
------------

.. autoclass:: mediafs.File
	:members: crc, md5, fasthash, metadata, rename, get, size, abspath, relpath, exists, stat, atime, mtime, hash, matches, root, serialize, deserialize


Directory Objects
-----------------

.. autoclass:: mediafs.Directory
	:members: size, contents, order, refresh, filter, search, query, all, __len__, __getitem__, __contains__, metadata, rename, get, size, abspath, relpath, exists, stat, atime, mtime, hash, matches, root, serialize, deserialize


