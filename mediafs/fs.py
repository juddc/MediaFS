"""
MetaFS: A pure-Python filesystem caching system for easy searching and metadata storage
"""
import os
import re
import sys
import json
import pickle
import fnmatch
import hashlib
import binascii
from datetime import datetime

# Python 3.5 has scandir built-in, so grab that if it's available
if hasattr(os, 'scandir'):
    scandir = os.scandir
else:
    # Try importing scandir from the pypi library
    try:
        from scandir import scandir
    except ImportError:
        # give up and use os.listdir if we can't find scandir anywhere
        scandir = None


# Provide the same interface for both scandir and listdir so we can use scandir if available
if scandir is None:
    def dirlisting(path):
        for item in os.listdir(path):
            itemPath = os.path.join(path, item)
            yield (item, os.path.isdir(itemPath), os.path.isfile(itemPath))
else:
    def dirlisting(path):
        try:
            for item in scandir(path):
                yield (item.name, item.is_dir(), item.is_file())
        except:
            return


def _md5(path):
    """
    Returns the MD5 sum of a file. Will raise MemoryError on large files.
    Just intended for use as a helper for calculating a version number for
    the module so we can avoid unpickling data from older versions.
    """
    h = hashlib.md5()
    with open(path, 'r') as fp:
        # python2 yells at you for calling encode() here
        if sys.version_info.major <= 2:
            h.update(fp.read())
        else:
            h.update(fp.read().encode())
    return h.hexdigest()

# precalculate the version number at import time so we don't have to calculate
# it every time a file tree cache is loaded
_VERSION = _md5(os.path.abspath(__file__))



class FSObject(object):
    """
    Base class for all filesystem objects
    """
    isdir = False

    def __init__(self, path, parent=None):
        self.path = path
        self.name = os.path.basename(path)
        self.parent = parent

        # deferred values:
        self._metadata = None
        self._root = None
        self._size = None
        self._relpath = None
        self._abspath = None


    @property
    def size(self):
        """
        The size of the file or directory contents in bytes.
        This value is cached after the first call.
        """
        if self._size is None:
            self._size = os.path.getsize(self.path)
        return self._size


    @property
    def abspath(self):
        """
        The absolute path to the file or directory
        This value is cached after the first call.
        """
        if self._abspath is None:
            self._abspath = os.path.abspath(self.path)
        return self._abspath


    @property
    def metadata(self):
        """
        The metadata dict for the file or directory
        """
        if self._metadata is None:
            self._metadata = self.root._getMetadataForObject(self.hash())
        return self._metadata


    @property
    def root(self):
        """
        The root directory object
        """
        if self._root is None:
            # go up the parent chain and get the root directory, stopping when parent == None
            obj = self
            while obj is not None:
                if obj.parent is None:
                    break
                else:
                    obj = obj.parent
            self._root = obj
        return self._root


    @property
    def relpath(self):
        """
        The file or directory path relative to the root directory.
        This value is cached after the first call.
        """
        if self._relpath is None:
            self._relpath = os.path.relpath(self.path, os.path.commonprefix([self.root.path, self.path]))
        return self._relpath


    def exists(self):
        """
        Does the file exist? This value is not cached.
        """
        return os.path.exists(self.path)


    def stat(self):
        """
        Calls `os.stat()` on the file and returns the result.
        """
        return os.stat(self.path)


    @property
    def atime(self):
        """
        Returns the last access time for the file or directory as a datetime object.
        This value is not cached.
        """
        return datetime.fromtimestamp(os.path.getatime(self.path))


    @property
    def mtime(self):
        """
        Returns the last modified time for the file or directory as a datetime object.
        This value is not cached.
        """
        return datetime.fromtimestamp(os.path.getmtime(self.path))


    def hash(self):
        """
        Return a hash suitable for storing the metadata dict for this object. This
        should be unique among all files and directories in the RootDirectory object.
        For directories, its best to use the relative path. For files, we can hash
        the file and use that, which means that moving or renaming the file won't
        lose track of data.
        """
        return self.relpath


    def matches(self, other):
        """
        Returns True if this file or directory is the same as another file or directory.
        Compares by hash, so `file1.matches(file2) == True` if `file1` and `file2` have
        identical contents.
        """
        return self.hash() == other.hash()


    def __getstate__(self):
        # When pickling, the metadata is stored in a separate file, so ignore _metadata here.
        # Additionally, the root directory object is not pickled
        excludeKeys = ["_metadata", "_root"]
        return { key:val for (key, val) in self.__dict__.items() if key not in excludeKeys }


    def __setstate__(self, state):
        # restore everything (which won't include the metadata and root object)
        for key, val in state.items():
            self.__dict__[key] = val
        # then make sure we have _metadata and _root attributes
        self._metadata = None
        self._root = None


    # All FSObjects should have some kind of implementation for __len__, __iter__,
    # __contains__, and __getitem__ to elegantly support Directory.query().
    # The default implementations here assumes the object has NO contents at all.


    def __len__(self):
        return 0


    def __iter__(self):
        # This is an empty generator - see http://stackoverflow.com/a/13243870
        return
        yield


    def __contains__(self, key):
        return False


    def __getitem__(self, val):
        raise KeyError(val)


    def __str__(self):
        return "<%s: %s>" % (self.__class__.__name__, self.name)
    __repr__ = __str__



class File(FSObject):
    """
    Object that represents a file in the filesystem
    """
    isdir = False

    def __init__(self, path, parent=None):
        FSObject.__init__(self, path, parent)
        # deferred value storage:
        self._crc = None
        self._md5 = None
        self._fasthash = None


    def crc(self, refresh=False):
        """
        Calculate the CRC for this file. The result is cached, so subsequent calls
        do not result in calculating the CRC multiple times. If `refresh` is True,
        then the result is recalculated.
        """
        if refresh or self._crc is None:
            c = 0
            with open(self.path, 'rb') as fp:
                chunk = fp.read(1024)
                while chunk:
                    c = binascii.crc32(chunk, c)
                    chunk = fp.read(1024)
            self._crc = c
        return self._crc


    def md5(self, refresh=False):
        """
        Calculate the MD5 sum for this file. The result is cached, so subsequent calls
        do not result in calculating the MD5 sum multiple times. If `refresh` is True,
        then the result is recalculated.
        """
        if refresh or self._md5 is None:
            h = hashlib.md5()
            with open(self.path, 'rb') as fp:
                chunk = fp.read(2048)
                while chunk:
                    h.update(chunk)
                    chunk = fp.read(2048)
            self._md5 = h.hexdigest()
        return self._md5


    def fasthash(self, refresh=False):
        """
        Calculate a hash for this file that works well on larger files but is optimized
        for speed. The result is cached, so subsequent calls do not result in calculating
        the hash multiple times. If `refresh` is True, then the result is recalculated.
        """
        if refresh or self._fasthash is None:
            # only get the size once to avoid excess syscalls
            size = self.size

            # for small files, just use the md5 of the whole file
            if size < 2**19:
                self._fasthash = self.md5()

            # for larger files, hash some bits at the beginning, some bits
            # at the end, and the size of the file. that gives reasonable results.
            else:
                h = hashlib.md5()
                with open(self.path, 'rb') as fp:
                    fp.seek(1024 * 8)
                    h.update(fp.read(2048))
                    fp.seek(-4096, 2) # 4k before the end of the file
                    h.update(fp.read(2048))

                # factor in the filesize so that very similar files can still be
                # easily distinguished
                h.update(str(size).encode())
                self._fasthash = h.hexdigest()

        return self._fasthash


    def hash(self):
        """
        For files, instead of returning the relative path of the file, return the
        hash, so that if a file is moved or renamed the metadata will remain
        associated with it. This will also result in duplicate files having the
        same metadata (which is the intended behavior).
        """
        return self.fasthash()



class Directory(FSObject):
    """
    Object that represents a directory in the filesystem
    """
    isdir = True

    def __init__(self, path, parent=None):
        FSObject.__init__(self, path, parent)
        self._contents = None
        self._order = None


    @property
    def size(self):
        """
        For directories, recursively calculate the size of the contents of the directory
        """
        if self._size is None:
            total = 0
            for item in self.all(recursive=True):
                total += item.size
            self._size = total
        return self._size


    @property
    def contents(self):
        if self._contents is None:
            self.refresh()
        return self._contents


    @property
    def order(self):
        if self._order is None:
            self.refresh()
        return self._order


    def refresh(self, *files, **kwargs):
        """
        Rescans the filesystem and rebuilds the index for this directory. If any `files` are
        specified, then `refresh()` will only scan those files. Otherwise it will scan
        all files.

        If `recursive=True` is passed in, then `refresh()` will also be called on all subdirectories.
        """
        # extract the recursive argument from kwargs
        recursive = False
        if 'recursive' in kwargs:
            recursive = kwargs['recursive']

        # if no files are specified, then we're going to rescan all files. clearing
        # the dict will have the result of removing any files that no longer exist.
        if len(files) == 0:
            files = dirlisting(self.path)
            self._contents = {}

            # because we cleared the _contents dict anyway, theres no need to check
            # if a file still exists.
            checkRemoved = False

        else:
            # set up the files array to match the output format of dirlisting()
            f = []
            for item in files:
                itemPath = os.path.join(self.path, item)
                if os.path.exists(itemPath):
                    f.append( (item, os.path.isdir(itemPath), os.path.isfile(itemPath) ) )
                else:
                    f.append( (item, False, False) )
            files = f

            if self._contents is None:
                self._contents = {}

            # if we're scanning specific files, we'll need to check if those files
            # still exist.
            checkRemoved = True

        # clear the directory size cache so that it will be recalculated next time it's requested
        self._size = None

        # figure out what file and directory classes we're going to use when indexing
        DirClass = self.root._getDirectoryClass()
        FileClass = self.root._getFileClass()

        for filename, isdir, isfile in files:
            fullPath = os.path.join(self.path, filename)

            # should we skip this file?
            if self.root._ignoreFile(filename, fullPath, isdir):
                continue

            # check if we need to remove an item from the directory
            if checkRemoved:
                # remove the key if the path doesn't exist
                if not isdir and not isfile and filename in self._contents:
                    del self._contents[filename]
                    continue

            # create a new directory object
            if isdir:
                item = DirClass(fullPath, parent=self)
                self._contents[filename] = item

                # callback on directory scans
                self.root._directoryRefresh(item)

                if recursive:
                    self._contents[filename].refresh(recursive=recursive)

            # create a new file object
            elif isfile:
                item = FileClass(fullPath, parent=self)
                self._contents[filename] = item

                # callback on file scans
                self.root._fileRefresh(item)

        # recalculate ordering
        self._order = self.root._orderDirectory(self._contents)


    def filter(self, pattern, recursive=False, dirs=True, files=True, ignoreCase=True):
        """
        Uses the Python stdlib `fnmatch` library to search the filesystem.
        """
        if ignoreCase:
            # fnmatch() uses case-sensitive searching on case-sensitive filesystems,
            # so we have to lowercase everything ourselves
            pattern = pattern.lower()
            for item in self.all(recursive=recursive, dirs=dirs, files=files):
                if fnmatch.fnmatch(item.name.lower(), pattern):
                    yield item

        # use fnmatch.fnmatchcase for case-sensitive searching regardless of OS
        else:
            for item in self.all(recursive=recursive, dirs=dirs, files=files):
                if fnmatch.fnmatchcase(item.name, pattern):
                    yield item


    def search(self, regex, recursive=False, dirs=True, files=True, flags=re.IGNORECASE):
        """
        Uses a regex as a query string to search the filesystem. Uses case-insensitive
        matching by default. Passes the value of the `flags` argument directly through
        to `re.compile()`, so check out the docs on the `regex` module for how that works.
        """
        check = re.compile(regex, flags=flags)
        for item in self.all(recursive=recursive, dirs=dirs, files=files):
            if check.search(item.name):
                yield item


    def query(self, query, recursive=False, dirs=True, files=True):
        """
        Uses a custom function to search the filesystem. That function is passed a single
        argument, an FSObject, and should return a boolean that determines if the file
        matches.

        Examples:
            # all files that are named "file1.txt" or "file2.txt", recursively
            directory.query(lambda f: f.name == "file1.txt" or f.name == "file2.txt", recursive=True)

            # all files larger than 1024 bytes
            directory.query(lambda f: f.size > 1024, dirs=False)

            # all files and directories that start with E
            directory.query(lambda f: f.name.startswith("E"))

            # all files modified within the last 7 days
            from datetime import datetime, timedelta
            directory.query(lambda f: f.mtime > (datetime.now() - timedelta(days=7)), files=True, dirs=False)

            # all directories with more than 10 items
            directory.query(lambda d: len(d) > 10, recursive=True, files=False, dirs=True)

            # all directories that contain a file called "asdf.txt"
            directory.query(lambda d: "asdf.txt" in d, recursive=True, files=False, dirs=True)
        """
        for item in self.all(recursive=recursive, dirs=dirs, files=files):
            if query(item):
                yield item


    def get(self, filename):
        """
        Returns a single file if that file is contained anywhere in this directory.
        Case-sensitive.
        """
        for item in self.all(recursive=True, dirs=True, files=True):
            if item.name == filename:
                return item
        raise FileNotFoundError(filename)


    def all(self, recursive=False, reverse=False, dirs=True, files=True):
        """
        A generator that yields all files and subdirectories contained within this directory.

        * If `recursive` is True, then it will also yield all items contained in those subdirectories.
        * If `reverse` is True, then it will iterate in reverse order.
        * The `dirs` argument indicates whether or not directories should be yielded.
        * The `files` argument indicates whether or not files should be yielded.
        """
        if dirs == False and files == False:
            raise ValueError("If both dirs and files are both False, no results will ever be generated.")

        if reverse:
            ordering = reversed(self.order)
        else:
            ordering = self.order

        for key in ordering:
            item = self.contents[key]

            if dirs and item.isdir:
                yield item

            elif files and not item.isdir:
                yield item

            if recursive and item.isdir:
                for subitem in item.all(recursive=recursive, reverse=reverse, dirs=dirs, files=files):
                    yield subitem


    def __len__(self):
        """
        Return the number of files and directories in this directory
        """
        return len(self.contents)


    def __iter__(self):
        for key in self.order:
            yield self.contents[key]


    def __contains__(self, key):
        return (key in self.contents)


    def __getitem__(self, key):
        """
        Directory objects support a number of different indexing methods, all of which
        either return a single object, or a list containing multiple objects (as opposed
        to the searching methods `filter()`, `search()`, `query()`, and `all()`, which
        are generators).

        Directories support the following syntaxes for indexing:
            * An ellipsis object (Python 3 only), returns a list of all children, recursively.
                    directory[...]    # same as list(directory.all(recursive=True))
            
            * An integer, which is treated as an index and returns one item based on the
              directory ordering. Because the ordering is precalculated, this is O(1).
              Returns exactly one item.
                    directory[2]

            * A slice, which is treated as a range of indices based on the directory ordering.
                    directory[1:3]

            * A string key, which is treated as a filename and uses a dict-based lookup for O(1)
              lookups. Returns exactly one item.
                    directory["asdf.txt"]

            * A string which contains either a `*` or a `?`. This string is passed to the
              Python stdlib library fnmatch to support searches and returns a list of files
              or directories that match the pattern. See the documentation for the `fnmatch`
              library for more information.
                    directory["*.txt"]       # same as list(directory.filter("*.txt"))
        """
        # python 3 ellipsis as a shortcut for all files and directories, recursively
        if key == Ellipsis:
            return list(self.all(recursive=True))

        # allow indexing by integer using the directory order
        elif isinstance(key, int):
            return self.contents[self.order[key]]

        # allow standard slice syntax by passing the slice directly to the ordering list
        elif isinstance(key, slice):
            return [ self.contents[item] for item in self.order[key] ]

        # look up the key in the contents dict
        # this lookup needs to be done BEFORE the filter check just in case there are files
        # that contain a '*' or '?'
        elif key in self.contents:
            return self.contents[key]

        # return the results of a filter so we can support cool search-based keys
        elif '*' in key or '?' in key:
            return list(self.filter(key))

        # if none of those previous key syntaxes matched, then raise an exception
        else:
            raise KeyError(key)



class RootDirectory(Directory):
    """
    The filesystem root directory
    """
    def __init__(self, path):
        Directory.__init__(self, path, None)

        if not os.path.exists(path):
            raise FileNotFoundError(path)
        if not os.path.isdir(path):
            raise ValueError("Root path must be a directory (got '%s')" % path)
        self._md = self._readMetadata()
        self._contents, self._order = self._readTreeData()


    @property
    def root(self):
        # Normally the `root` property figures out what the root directory is and returns it.
        # This object IS the root, so just return self.
        return self


    def save(self):
        """
        Write all metadata to disk.
        """
        self._writeMetadata(self._md)
        self._writeTreeData(self._contents, self._order)


    def scrubMetadata(self):
        """
        Removes metadata entries for files that no longer exist. Takes a while to run
        and deletes data, so it must be run manually.
        """
        self.refresh(recursive=True)

        hashes = set()
        outdatedHashes = []

        for f in self.all(recursive=True):
            hashes.add(f.hash())

        for h in self._md.keys():
            if h not in hashes:
                outdatedHashes.append(h)

        for h in outdatedHashes:
            del self._md[h]


    def _getFileClass(self):
        """
        Returns a Python class that will be used for File objects in the filesystem
        tree. Used to allow subclasses of the File object.
        """
        return File


    def _getDirectoryClass(self):
        """
        Returns a Python class that will be used for Directory objects in the filesystem
        tree. Used to allow subclasses of the Directory object.
        """
        return Directory


    def _orderDirectory(self, contents):
        """
        From the `contents` argument, which is a dict with filenames as keys and
        File objects as values, return a list of keys that will represent the ordering
        of that dict.
        """
        order = list(contents.keys())
        order.sort()
        return order


    def _ignoreFile(self, name, fullpath, isdir):
        """
        Based on a filename and its full path, return True if a file or directory
        should be excluded from indexing. Otherwise return False.
        """
        return False


    def _directoryRefresh(self, item):
        """
        Callback whenever a directory is refreshed.

        Override this in subclasses if you would like some code to be run whenever
        any directory is refreshed.
        """


    def _fileRefresh(self, item):
        """
        Callback whenever a directory is refreshed.

        Override this in subclasses if you would like some code to be run (for example,
        scanning the file to manipulate metadata) whenever any file is scanned.
        """


    def _readMetadata(self):
        """
        Returns metadata for all files in the filesystem.

        The returned object should be a dict, with keys being the output of FSObject.hash(),
        and values being a dict containing the metadata associated with that hash.

        Should be implemented in a subclass to allow storing metadata in a file or database.
        """
        return {}


    def _writeMetadata(self, metadata):
        """
        The `metadata` argument is a dict containing metadata for the entire filesystem.
        The keys represent the output of FSObject.hash(), and the values are dicts containing
        the metadata assocated with that hash.

        This method should write that metadata to a file or database so that it can be
        restored later with _readMetadata.
        """


    def _readTreeData(self):
        """
        Reads in the directory tree from a file.

        Should be implemented in a subclass to allow the contents of the filesystem
        to be cached.

        Should return a 2-tuple, with the first element being a dict (keys are filenames,
        values are of type `FSObject`), and the second element being a list containing
        all keys in that dict which represents the ordering of those keys.
        """
        return (None, None)


    def _writeTreeData(self, tree, ordering):
        """
        Writes out the directory tree to a file.

        Should be implemented in a subclass to allow the contents of the filesystem
        to be cached.

        Takes the root directory tree and the ordering of the keys in that tree,
        and writes them to a file or database so that a full rescan of the filesystem
        can be avoided.
        """


    def _getMetadataForObject(self, fshash):
        """
        Given the hash of a file (which are generated by FSObject.hash()), return a
        dict representing the metadata for that file.

        This method exists so that subclasses can override default behavior.
        """
        if fshash not in self._md:
            self._md[fshash] = {}
        return self._md[fshash]



class CachedRootDirectory(RootDirectory):
    """
    A root directory that uses the pickle module to cache the directory tree,
    and the json module to serialize the metadata.

    The constructor adds two optional arguments, `metadataFile` and `treeFile`.
    They default to `.metadata.json` and `.tree.pickle`, respectively, and
    can be used to specify the paths to the metadata storage for this filesystem.

    If `metadataFile=None` is passed to the constructor, metadata will not be
    saved or restored.

    If `treeFile=None` is passed to the constructor, the filesystem tree cache
    will not be saved or restored.

    If `metadataFile` or `treeFile` are left at their default values, they will be
    created inside the root directory. Otherwise the values will be treated as
    paths to the metadata files, so it is up to the user to put them in a
    reasonable place.
    """

    def __init__(self, path, metadataFile=".metadata.json", treeFile=".tree.pickle"):
        # Set the filenames of the metadata and tree files before calling the parent constructor.
        # The parent constructor will call _readMetadata and _readTreeData, so we need these values
        # to be available before that happens.
        self._mdFile = metadataFile
        if self._mdFile == ".metadata.json":
            # if the filename is the default one, put it at the root of the filesystem
            self._mdFile = os.path.join(path, metadataFile)

        self._treeFile = treeFile
        if self._treeFile == ".tree.pickle":
            # if the filename is the default one, put it at the root of the filesystem
            self._treeFile = os.path.join(path, treeFile)

        RootDirectory.__init__(self, path)


    def _ignoreFile(self, name, fullpath, isdir):
        # Ignore the metadata and tree cache data when indexing
        if name == self._mdFile or name == self._treeFile:
            return True
        else:
            return False


    def _readMetadata(self):
        if self._mdFile is not None and os.path.exists(self._mdFile):
            with open(self._mdFile, 'r') as fp:
                return json.load(fp)
        return {}


    def _writeMetadata(self, metadata):
        if self._mdFile is not None:
            with open(self._mdFile, 'w') as fp:
                json.dump(metadata, fp, indent=4)


    def _readTreeData(self):
        if self._treeFile is not None and os.path.exists(self._treeFile):
            with open(self._treeFile, 'rb') as fp:
                try:
                    tree, order, version = pickle.load(fp)
                except:
                    # don't load this cache, it wasn't parsed correctly
                    return (None, None)
                else:
                    # make sure the version matches
                    if version == _VERSION:
                        return (tree, order)
        return (None, None)


    def _writeTreeData(self, tree, order):
        if self._treeFile is not None:
            with open(self._treeFile, 'wb') as fp:
                pickle.dump((tree, order, _VERSION), fp)


