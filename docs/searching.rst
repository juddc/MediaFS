Searching
=========


Searching with filter()
-----------------------

There are three search methods. The first, and the simplest, is ``filter()``. This method uses the Python standard library ``fnmatch`` (https://docs.python.org/library/fnmatch.html) module to search the filesystem.

This means you can search with the standard ``*.ext`` syntax. For example:

.. code:: python

	# prints the name of every file with a .txt extension
	for item in fs.filter("*.txt", recursive=True, files=True, dirs=False):
	    print(item.name)


Additionally, ``Directory.__getitem__`` is overloaded such that any string passed to ``__getitem__`` that contains a ``*`` character is passed to ``filter()``. For example:

.. code:: python

	# prints the name of every top-level file with a .txt extension
	for item in fs["*.txt"]:
	    print(item.name)


Using the ``fs["*.txt"]`` method affects the output of ``filter()`` in two ways: first, it won't do a recursive search, and second, it will not act like a generator - it will return a list object.

This is useful because when in an interactive interpreter, you can access files like so:

>>> firstSong = fs["some_directory"]["*.mp3"][0]

This is particularly useful when you are only expecting one file or directory back, for example to get track 12 from an album:

>>> track = fs["Some Artist"]["Some Album"]["12*"][0]


Searching with search()
-----------------------

The ``search()`` method uses the ``regex`` library (https://docs.python.org/library/re.html) to search via the supplied regular expression.

.. code:: python

	# prints all files with a txt extension
	for item in fs.search(r'(.*)\.txt', recursive=True, dirs=False):
	    print(item.name)


Searching with query()
----------------------

The ``query()`` method is by far the most flexible way to search. It takes a callback function as its first argument. The callback receives one argument - the file or directory object, and should return True if the file or directory matches the search, otherwise False. 

.. code:: python

	# print all files with a .txt extension
	for item in fs.query(lambda f: f.name.endswith(".txt"), recursive=True, dirs=False):
	    print(item.name)

	# print the absolute path and filesize (in MB) of all zip files larger than 128MB
	for item in fs.query(lambda f: f.name.endswith(".zip") and f.size > 2**27, recursive=True, dirs=False):
	    print(item.abspath, item.size // 2**20, "MB")

	# print the name and total size (in MB) of all top-level directories larger than 1GB
	for item in fs.query(lambda f: f.size > 2**30, files=False):
	    print(item.name, item.size // 2**20, "MB")


While a lambda is great for relatively simple searches, if you need something more complex, a standard function will work just as well. For example, this query will match zip files that contain txt files using the ``zipfile`` module in the standard library (https://docs.python.org/library/zipfile.html).

.. code:: python

	from zipfile import ZipFile

	def zipFilesContainingTextFiles(item):
	    if not item.name.endswith(".zip"):
	        return False
	    with ZipFile(item.abspath) as myzip:
	        for filename in myzip.namelist():
	            if filename.endswith(".txt"):
	                return True
	    return False

	for item in fs.query(zipFilesContainingTextFiles, recursive=True, dirs=False):
	    print(item.name)

