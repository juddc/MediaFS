Customizing File and Directory Classes
======================================

Defining custom classes
-----------------------

Customizing the ``File``, ``Directory``, and ``RootDirectory`` classes gives you some very powerful tools for managing a large collection of similar files. For example, you could add custom attributes to files that hook into database systems or web scrapers.

First, how do you specify a custom ``File`` and ``Directory`` class?


.. code:: python

	from mediafs import File, Directory, RootDirectory

	class MyFile(File):
	    pass

	class MyDirectory(Directory):
	    pass

	class MyRootDirectory(RootDirectory):
	    FileClass = MyFile
	    DirectoryClass = MyDirectory


There, now we have a place to put code for files, directories, and the root directory.


Custom methods on files and directories
---------------------------------------

It is very useful to be able to add helper methods to files or directories.

.. code:: python

	class MyFile(File):
	    def isSong(self):
	        # return True if this file has an 'artist' metadata key and
	        # the filename has a .mp3 extension.
	        return 'artist' in self.metadata and self.name.lower().endswith(".mp3")


.. code:: python

	class MyDirectory(Directory):
	    def isAlbum(self):
	        # return True if this directory has an 'artist' metadata key and
	        # if its contents are 60MB or larger.
	        return 'artist' in self.metadata and self.size // 2**20 > 60


Keep in mind that all files and directories have an ``isdir`` attribute (which is True for directories and False for files), so if your custom file class has a property that your directories don't have, it's easy to check which you're working with without resorting to an ``isinstance`` call.



Custom behavior on refresh
--------------------------

While you probably won't need to add custom methods to the root directory, it does contain several important callback methods that can be overridden for custom behavior. For example, if we wanted to add metadata to every file object immediately after it was created, we could add the following method to ``MyRootDirectory``:

.. code:: python

	class MyRootDirectory(RootDirectory):
	    def _fileRefresh(self, item):
	        if 'author' not in item.metadata:
	            item.metadata['author'] = "Some Guy"


Now every single file in the filesystem will have a metadata key ``'author'`` with the value ``'Some Guy'``. Obviously, to make this useful, you'll want to write some code that retrieves the author data from somewhere, perhaps based on the filename (which you can access with ``item.name``).

You can also override ``_directoryRefresh`` to customize what happens after a directory object is created.

.. code:: python

	class MyRootDirectory(RootDirectory):
	    def _directoryRefresh(self, item):
	        if item.name.lower().startswith("."):
	            item.metadata['hidden'] = True



Ignoring files
--------------

Now lets say our filesystem contained some files that are really just getting in the way. Files like ``.DS_Store`` or ``thumbs.db``. To stop these from being tracked, we need to implement ``_ignorePath``.


.. code:: python

	class MyRootDirectory(RootDirectory):
	    def _ignorePath(self, name, fullpath, isdir):
	        if not isdir:
	            if name.lower() in ("thumbs.db", ".ds_store"):
	                return True
	        return False


If we're subclassing ``CachedRootDirectory`` we might also want to ignore the metadata and tree JSON files:


.. code:: python

	class MyRootDirectory(RootDirectory):
	    def _ignorePath(self, name, fullpath, isdir):
	        if not isdir:
	            if name.lower() in ("thumbs.db", ".ds_store", self._mdFile, self._treeFile):
	                return True
	        return False


Or maybe we want to ONLY include mp3 files and ignore everything else:

.. code:: python

	class MyRootDirectory(RootDirectory):
	    def _ignorePath(self, name, fullpath, isdir):
	        if not isdir and name.lower().endswith(".mp3"):
	            return True
	        else:
	            return False


Or maybe you want to exclude any directory called "Specials":

.. code:: python

	class MyRootDirectory(RootDirectory):
	    def _ignorePath(self, name, fullpath, isdir):
	        if isdir and name.lower() == "specials":
	            return True
	        else:
	            return False


Customizing directory ordering
------------------------------

Directories use plain dicts under the hood to store FSObjects that point to files and directories. This makes serialization and deserialization easy, but presents an issue - most people expect directories to be ordered. To give the user full control over this process, each directory has an ``order`` attribute that is an ordered list of keys in the ``contents`` dict.

The root directory has a method ``_orderDirectory`` that is called by Directory objects to create this list.
The method is passed the ``contents`` dict and is expected to return an ordered list of keys. Here is the default implementation:

.. code:: python

	class MyRootDirectory(RootDirectory):
	    def _orderDirectory(self, contents):
	        order = list(contents.keys())
	        order.sort()
	        return order


As you can see, this is easy to re-implement in any way you need. Note that the ``contents`` argument is the entire dict, and the values are the FSObjects themselves. This means we could easily sort based on file size, for example:

.. code:: python

	class MyRootDirectory(RootDirectory):
	    def _orderDirectory(self, contents):
	        order = list(contents.keys())
	        order.sort(key=lambda k: contents[k].size)
	        return order


Because we have access to the file and directory objects, we can also utilize any custom methods or properties we've added to those objects.



Total control over metadata
---------------------------

Assume you had some functions ``getMetadataValue(path, key)``, ``setMetadataValue(path, key, val)`` and ``hasMetadataKey(path, key)``. Say these functions called out to a database somewhere. If you can build a dict-like object to access this data, you can implement that in a RootDirectory.

``_getMetadataForObject`` should return a dict-like object that represents the file's metadata. In this example, the metadata is based on the file's absolute path (``item.abspath``), but it could also be based on the file's relative path ``item.relpath``, the file's ``item.hash()`` value, or anything else.

.. code:: python

	class DictLikeObject(object):
	    def __init__(self, path):
	        self._path = path
	    def __getitem__(self, key):
	        return getMetadataValue(self._path, key)
	    def __setitem__(self, key):
	        setMetadataValue(self._path, key)
	    def __contains__(self, key):
	        return hasMetadataKey(self._path, key)

	class MyRootDirectory(RootDirectory):
	    def _getMetadataForObject(self, item):
	        return DictLikeObject(item.abspath)


For your dict-like object, you'll want to implement as many dict traits as is reasonable to keep things that expect a dict from breaking. At the very least you'll need to implement ``__getitem__``, ``__setitem__`` and ``__contains__`` to avoid breaking MediaFS code. In practice, you'll also want to implement ``__delitem__``, ``__iter__``, ``__len__``, ``keys()``, ``items()``, and ``values()``. Check out ``mediafs/xattrs.py`` and look at the source of the ``XAttrMetadata`` class for an example implementation.

