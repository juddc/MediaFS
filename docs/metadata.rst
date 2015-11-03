Working with Metadata
=====================

Metadata introduction
---------------------

Metadata allows you to store values alongside files and directories so you can search that data later.

Every file and directory object has a ``metadata`` property, which you can use as a dict.

Let's set up some test metadata that we can use in examples. In this example, we'll assume there is a directory called ``/home/john/documents`` and that it contains these files: ``file1.txt``, ``qwerty.txt``, ``important_info.txt``, ``work_docs.txt``, and ``recording.mp3``. It also contains a subdirectory called ``workfiles``.

.. code:: python

	from mediafs import RootDirectory
	fs = RootDirectory("/home/john/documents")
	fs["file1.txt"].metadata['author'] = "John Smith"
	fs["file1.txt"].metadata['year'] = 2007

	fs["qwerty.txt"].metadata['author'] = "Luke Smith"
	fs["qwerty.txt"].metadata['year'] = 2008

	fs["important_info.txt"].metadata['author'] = "John Smith"
	fs["important_info.txt"].metadata['year'] = 2009

	fs["work_docs.txt"].metadata['author'] = "Luke Smith"
	fs["work_docs.txt"].metadata['year'] = 2010

	fs["recording.mp3"].metadata['artist'] = "John Smith"
	fs["recording.mp3"].metadata['album'] = "Garage Sessions 1"
	fs["recording.mp3"].metadata['year'] = 2010


All we've done here is store some information on some files. Now lets try searching those files.

.. code:: python

	# Don't do this, it won't work
	for item in fs.query(lambda f: f.metadata['author'] == "John Smith"):
	    print(item.name)

This would fail because the lambda function will get passed ``recording.mp3``. That file does not have an author, it has an artist, so a ``KeyError`` exception will be raised.

We could just check if the key exists before checking its contents:

.. code:: python

	# This would work, but it's ugly
	for item in fs.query(lambda f: 'author' in f.metadata and f.metadata['author'] == "John Smith"):
	    print(item.name)

But the easiest solution is to use ``get()``.

.. code:: python

	# Do this instead
	for item in fs.query(lambda f: f.get('author') == "John Smith"):
	    print(item.name)

The ``get()`` method takes two arguments, and the second argument is optional. The first is a metadata dict key. If that key is contained in the metadata, ``get()`` will return the value corresponding to that key. If the key does not exist, it will return the second argument, which by default is ``None``.

If you are comparing values directly, such as ``f.get('author') == "John Smith"``, the default value of ``None`` works just fine. However, if you wanted to compare by some numeric value (say, less than or greater than), or use a string method, then you'll need to pass a better default argument. For example, to search by the author's last name:

.. code:: python

	for item in fs.query(lambda f: f.get('author', default="").endswith("Smith")):
	    print(item.name)

	# prints file1.txt, qwerty.txt, important_info.txt and work_docs.txt


Or to find all files from 2010 or newer:

.. code:: python

	for item in fs.query(lambda f: f.get('year', default=0) >= 2010):
	    print(item.name)

	# prints work_docs.txt and recording.mp3


Saving metadata
---------------

The ``RootDirectory`` class has no way to serialize metadata, however, so as soon as the root directory object goes away, our metadata goes with it. That's not that useful, but there are several solutions. The simplest is to use ``CachedRootDirectory``.

.. note::

	Because the metadata dict will get serialized as JSON, you'll want to stick with simple types: strings, floats, ints, dicts, lists - anything that will easily convert to JSON.


.. code:: python

	from mediafs import CachedRootDirectory
	fs = CachedRootDirectory("/home/john/documents")

This root directory class has two important features that the basic ``RootDirectory`` lacks. It can serialize the metadata to a file, and it can serialize the whole directory tree to a file. Let's just look at the metadata part of that now.

.. code:: python

	fs = CachedRootDirectory("/home/john/documents")
	fs['workfiles'].metadata['company'] = "BigCo"       # directory
	fs['file1.txt'].metadata['author'] = "John Smith"   # file
	fs.save()

	# Get rid of the fs object and start from scratch
	del fs
	fs = CachedRootDirectory("/home/john/documents")
	print(fs['workfiles'].metadata['company'])          # prints "BigCo"
	print(fs['file1.txt'].metadata['author'])           # prints "John Smith"


.. note::

	Changing the name and path of the metadata file is easy, just pass a path, relative to the root directory, to the constructor like so:

	``fs = CachedRootDirectory("/home/john/documents", metadataFile="myMetadata.json")``


What's going on behind the scenes here? When ``fs.save()`` is called, a file named ``.metadata.json`` is written to the root directory with the following contents:

::

	{
	    "workfiles": {
	        "company": "BigCo"
	    },
	    "384ff2cb35f45b645775a2d6fa3d4ea8": {
	        "author": "John Smith"
	    }
	}


The directory clearly has a readable key in the metadata JSON file, but what's with the weird, unreadable string for the file data? One of the primary design goals of MediaFS is to work with large media collections, and something that happens frequently with managing large media collections is that files get renamed and moved around. That's why the default behavior is to use a hash of the file (or, on larger files, a faster hash algorithm - see ``File.fasthash()``) to identify the file's metadata rather than the filename. If ``file1.txt`` was renamed or even moved into a subdirectory, its metadata would still be associated with the correct file.

.. note::

	This also has the side effect that two identical files will actually share metadata. In a directory structure containing hundreds of media files, this was deemed an acceptable effect, because two files with identical contents would probably have identical metadata anyway.


What if you wanted to override this behavior? This is very simple. Every object derived from ``FSObject`` has a ``hash()`` method. This method is what gets called to generate the metadata dict key. So to change this value, we'll need to subclass ``File``.

We also need to tell our root directory object to use this custom ``File`` class instead of the default one. This is also very straightforward. We just need to subclass ``CachedRootDirectory``.


.. code:: python

	from mediafs import File, CachedRootDirectory

	class MyFile(File):
	    def hash(self):
	        return self.relpath

	class MyRootDirectory(CachedRootDirectory):
	    FileClass = MyFile

	fs = MyRootDirectory("/home/john/documents")
	fs['workfiles'].metadata['company'] = "BigCo"
	fs['file1.txt'].metadata['author'] = "John Smith"
	fs.save()


After running this, the ``.metadata.json`` file will contain the following:

::

	{
	    "workfiles": {
	        "company": "BigCo"
	    },
	    "file1.txt": {
	        "author": "John Smith"
	    }
	}


What we have done here is change the key used for file objects from a hash of the file to the relative path to the file (if the file was in a directory called ``stuff``, the key would be ``stuff/file1.txt``). This means that renaming a file will result in the metadata for it being orphaned (and if a new file is named the same as the old file, the new file will take on its metadata).

.. note::

	You can use ``RootDirectory.scrubMetadata()`` to remove metadata entries that are no longer associated with a valid file or directory, but keep in mind this is a somewhat slow operation on larger directory trees.



Auto-generating metadata
------------------------

This is all well and good for manually setting metadata on files, but what if we wanted to automatically generate metadata. Maybe we wanted to do a database lookup for some information, or scrape a website for information about a file.

``RootDirectory`` contains several callbacks to make this easy.

.. code:: python

	from mediafs import CachedRootDirectory

	def getAuthorDataFromFilename(filename):
	    # do some magic here to get the author name
	    # (perhaps with a database query)
	    return authorName

	class MyRootDirectory(CachedRootDirectory):
	    # called every time a file is refreshed:
	    def _fileRefresh(self, item):
	        item.metadata['author'] = getAuthorDataFromFilename(item.name)

	    # called every time a directory is refreshed:
	    def _directoryRefresh(self, item):
	        pass

	fs = MyRootDirectory("/home/john/documents")
	fs.refresh(recursive=True)
	fs.save()

	# prints whatever getAuthorDataFromFilename returned for "file1.txt"
	print(fs['file1.txt'].metadata['author'])


Now, the whole point of storing this metadata is to avoid having to look up the data later, especially if that lookup involves remote servers or expensive calculations. So lets improve the ``_fileRefresh`` method to make this more efficient:

.. code:: python

	def getAuthorDataFromFilename(filename):
	    # do some magic here to get the author name
	    # (perhaps with a database query)
	    return authorName

	class MyRootDirectory(CachedRootDirectory):
	    # called every time a file is refreshed:
	    def _fileRefresh(self, item):
	        if 'author' not in item.metadata:
	            item.metadata['author'] = getAuthorDataFromFilename(item.name)


Now it will only call ``getAuthorDataFromFilename`` if the data does not already exist in the metadata dict. This is good, because ``_fileRefresh`` and ``_directoryRefresh`` are called every time a refresh of that data happens, which you may wish to do several times in one run of your program.

This way you have control over when metadata would be recalculated:

.. code:: python

	fs = MyRootDirectory(CachedRootDirectory)

	print(fs['file1.txt'].get('author')) # oh no, we got the wrong value?

	# remove the 'author' metadata key
	del fs['file1.txt'].metadata['author']

	# this will result in _fileRefresh being called on just this one file
	fs.refresh("file1.txt")

	print(fs['file1.txt'].get('author')) # ah, thats better



Storing metadata directly in the filesystem
-------------------------------------------

Storing metadata in a JSON file is all well and good, but wouldn't it be better if we could store metadata directly in the filesystem? After all, if you have thousands of files and lots of metadata in each file, there's a certain overhead in loading that up every time you create a root filesystem object.

On Linux, you can do exactly this. It requires the ``pyxattr`` library (https://pypi.python.org/pypi/pyxattr) and comes with a few caveats. First, it only works on certain filesystems (tmpfs, for example, doesn't support it). Second, it may require some system configuration changes - for example, you may find that you're able to set and get attributes, but get a permissions error on removing them. Check out the command line tools ``attr``, ``getfattr``, and ``setfattr``. If you have the same issues with those tools that you do with this library, then your issue is with your OS. Those tools are a great way to debug issues with extended filesystem attributes, plus they enable shell scripts to read and write to the same metadata you'll be using.

Example:

.. code:: python

	from mediafs.xattrs import XAttrRootDirectory

	fs = XAttrRootDirectory("/home/john/documents")

	fs['file1.txt'].metadata['author'] = "John Smith"

	# done! no need to call save()


It's as simple as that (assuming you had no OS config issues). When you use ``XAttrRootDirectory``, the ``metadata`` attribute on files and directories refers to a ``XAttrMetadata`` instead of a dict. This object is a dict-like class that works on extended filesystem attributes directly, which means that any value you set is set on the file immediately.

.. note::

	Because filesystem attributes must be strings, any value that you set is passed through ``json.dumps`` to serialize individual values. This means that the int value ``5`` is converted into the string ``5`` and the string value ``abcd`` is converted into the string ``"abcd"`` (the quotes are part of the string).

	A pleasant side effect of using ``json`` in this way is that you can just as easily set a list or dict of ints/floats/strings and it will deserialize correctly.

