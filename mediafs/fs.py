"""
MetaFS: A pure-Python filesystem caching system for easy searching and metadata storage

Author: Judd Cohen
License: MIT (See accompanying file LICENSE or copy at http://opensource.org/licenses/MIT)
"""
import os
import re
import sys
import json
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



class FSObject(object):
    """
    Base class for all filesystem objects
    """
    # is this object a directory?
    isdir = False

    # what fields should be serialized when FSObject.serialize() is called?
    serializeFields = ('name', '_path', '_size', '_relpath', '_abspath')

    def __init__(self, path, parent=None):
        self.name = os.path.basename(path)
        self.parent = parent
        self._path = path

        # deferred values:
        self._metadata = None
        self._root = None
        self._size = None
        self._relpath = None
        self._abspath = None


    def serialize(self):
        """
        Returns a dict object containing the attributes of this object.
        Used for serializing the directory tree to a file.
        """
        mro = self.__class__.__mro__
        if File in mro:
            clsName = "File"
        elif Directory in mro:
            clsName = "Directory"
        elif FSObject in mro:
            clsName = "FSObject"
        else:
            raise TypeError("Don't know how to serialize a class that isn't derived "
                "from a FSObject (__mro__ == %s)" % mro)

        data = {'__fsobject': clsName}
        for attr in self.serializeFields:
            data[attr] = getattr(self, attr)
        return data


    @classmethod
    def deserialize(cls, attrs):
        """
        Takes a dict object and returns a new instance of this class with all attributes
        initialized to the values contained in the dict.
        """
        inst = cls.__new__(cls)
        for attr, val in attrs.items():
            if not attr.startswith("__"):
                setattr(inst, attr, val)
        inst.parent = None
        inst._metadata = None
        inst._root = None
        return inst


    def rename(self, newName, syscall=True):
        """
        Renames the file or directory. Raises a FileExistsError exception if the
        new name already exists.

        If the ``syscall`` argument is True, then ``os.rename()`` will be called
        on the underlying file or directory. Setting this to False is primarily
        useful for keeping things in sync if you know a rename occured and want
        to avoid the overhead of a refresh() call.
        """
        oldName = self.name
        oldAbsPath = self.abspath
        newPath = self.path[:-len(oldName)] + newName

        # if we have a parent directory, check that for the new filename:
        if self.parent is not None:
            if newName in self.parent:
                raise FileExistsError(newName)
        # if we don't have a parent, resort to an extra syscall:
        else:
            if os.path.exists(os.path.abspath(newPath)):
                raise FileExistsError(newName)

        # change the path and name values themselves
        self._path = newPath
        self.name = newName
        # clear cached values that probably contain the name
        self._relpath = None
        self._abspath = None

        # do the actual file rename if requested
        if syscall:
            os.rename(oldAbsPath, self.abspath)

        # inform the parent directory object that a rename occured so it can
        # update accordingly
        if self.parent is not None and self.parent.isdir:
            self.parent._itemRenamed(self, oldName, newName)


    def get(self, key, default=None):
        """
        Helper method for getting values from the metadata dict. Primarily
        useful for shortening ``Directory.query()`` lambda functions.

        *Example*:

            ``directory.query(lambda f: 'author' in f.metadata and f.metadata['author'] == "The Clash")``
            
            can be shortened to:

            ``directory.query(lambda f: f.get('author') == "The Clash")``

        The `default` argument is the value that will be returned if `key`
        is not a valid key in the metadata dict. This is useful if you
        are expecting a particular type and want to do some operation on
        that type. For example:

            ``directory.query(lambda f: f.get('year', default=0) > 1990))``
        """
        if key in self.metadata:
            return self.metadata[key]
        else:
            return default


    @property
    def size(self):
        """
        The size of the file or directory contents in bytes.
        Lazily evaluated and cached.
        """
        if self._size is None:
            self._size = os.path.getsize(self.path)
        return self._size


    @property
    def path(self):
        """
        The path to the file or directory.

        FSObject._path is set in the constructor, but if it is manually set to
        None, then this can reassemble it from the directory tree. Mostly useful
        for moving and renaming files.
        """
        if self._path is None:
            parts = [self.name]
            # go up the parent chain and figure out the path in reverse
            obj = self
            while obj is not None:
                if obj.parent is None:
                    break
                else:
                    parts.append(obj.parent.name)
                    obj = obj.parent
            # add on the location of the root directory itself
            parts.append(os.path.dirname(self.root.abspath))
            # reverse the array
            parts = parts[::-1]
            # reassemble the path
            self._path = os.path.join(*parts)
        return self._path


    @property
    def abspath(self):
        """
        The absolute path to the file or directory. Uses ``os.path.abspath()``.
        Lazily evaluated and cached.
        """
        if self._abspath is None:
            self._abspath = os.path.abspath(self.path)
        return self._abspath


    @property
    def metadata(self):
        """
        The metadata dict for this file or directory
        """
        if self._metadata is None:
            self._metadata = self.root._getMetadataForObject(self)
        return self._metadata


    @property
    def root(self):
        """
        A reference to the root directory object
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
        """
        if self._relpath is None:
            self._relpath = os.path.relpath(self.path, os.path.commonprefix([self.root.path, self.path]))
        return self._relpath


    def exists(self):
        """
        Does the file exist?
        Calls ``os.path.exists()`` on the file or directory and returns the result.
        """
        return os.path.exists(self.path)


    def stat(self):
        """
        Calls ``os.stat()`` on the file or directory and returns the result.
        """
        return os.stat(self.path)


    def atime(self):
        """
        Last access time as reported by the underlying filesystem.
        Calls ``os.path.getatime()`` on the file or directory and returns the result as a datetime object.
        """
        return datetime.fromtimestamp(os.path.getatime(self.path))


    def mtime(self):
        """
        Last modified time as reported by the underlying filesystem.
        Calls ``os.path.getmtime()`` on the file or directory and returns the result as a datetime object.
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
        Returns ``True`` if this file or directory is the same as another file or directory.
        Compares by hash, so ``file1.matches(file2) == True`` if ``file1`` and ``file2`` have
        identical contents.
        """
        return self.hash() == other.hash()


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

    # what fields should be serialized when FSObject.serialize() is called?
    serializeFields = FSObject.serializeFields + ('_crc', '_md5', '_fasthash')

    def __init__(self, path, parent=None):
        FSObject.__init__(self, path, parent)
        # deferred value storage:
        self._crc = None
        self._md5 = None
        self._fasthash = None


    def crc(self, refresh=False):
        """
        Calculate the CRC for this file. The result is cached, so subsequent calls
        do not result in calculating the CRC multiple times. If ``refresh`` is True,
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
        do not result in calculating the MD5 sum multiple times. If ``refresh`` is True,
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
        the hash multiple times. If ``refresh`` is True, then the result is recalculated.
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

    # what fields should be serialized when FSObject.serialize() is called?
    serializeFields = FSObject.serializeFields + ('_contents',)

    def __init__(self, path, parent=None):
        FSObject.__init__(self, path, parent)
        self._contents = None
        self._order = None


    @classmethod
    def deserialize(cls, attrs):
        """
        Takes a dict object, and returns a new instance of this class with all attributes
        initialized to the values contained in the dict.
        """
        inst = super(Directory, cls).deserialize(attrs)
        inst._order = None
        if inst._contents is not None:
            for key in inst._contents.keys():
                inst._contents[key].parent = inst
        return inst


    @property
    def size(self):
        """
        For directories, recursively calculate the size of the contents of the directory.
        This value is lazily evaluated and cached.
        """
        if self._size is None:
            total = 0
            for item in self.all(recursive=True):
                total += item.size
            self._size = total
        return self._size


    @property
    def contents(self):
        """
        The dict representing the contents of this directory. If this directory has not
        been refreshed yet, accessing this property will trigger a ``refresh(recursive=False)``
        before returning the dict.

        If you have code accessing a single specific file or directory object in an inner
        loop, a small optimization could be calling ``directory.contents[filename]``
        instead of ``directory[filename]``, due to the number of overloads in
        ``Directory.__getitem__``.
        """
        if self._contents is None:
            self.refresh(recursive=False)
        return self._contents


    @property
    def order(self):
        """
        A list representing the order of the items in this directory. Lazily evaluated
        and cached.

        Accessing this property will trigger ``refresh(recursive=False)`` if a refresh
        has never been run on this directory.
        """
        if self._order is None:
            if self._contents is None:
                self.refresh(recursive=False)
            else:
                self._order = self.root._orderDirectory(self._contents)
        return self._order


    def refresh(self, *files, **kwargs):
        """
        Rescans the filesystem and rebuilds the index for this directory. If any ``files`` are
        specified, then ``refresh()`` will only scan those files. Otherwise it will scan
        all files.

        If ``recursive=True`` is passed in, then ``refresh()`` will also be called on all subdirectories.
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
            # make sure the contents dict exists in case this is the first refresh called
            if self._contents is None:
                self._contents = {}

            # set up the files array to match the output format of dirlisting()
            f = []
            for item in files:
                itemPath = os.path.join(self.path, item)
                if os.path.exists(itemPath):
                    f.append( (item, os.path.isdir(itemPath), os.path.isfile(itemPath) ) )
                else:
                    f.append( (item, False, False) )
            files = f

            # if we're scanning specific files, we'll need to check if those files
            # still exist.
            checkRemoved = True

        # clear the directory size cache so that it will be recalculated next time it's requested
        self._size = None

        for filename, isdir, isfile in files:
            fullPath = os.path.join(self.path, filename)

            # should we skip this file?
            if self.root._ignorePath(filename, fullPath, isdir):
                continue

            # check if we need to remove an item from the directory
            if checkRemoved:
                # remove the key if the path doesn't exist
                if not isdir and not isfile and filename in self._contents:
                    # callback on deletions
                    self.root._pathDelete(self._contents[filename])
                    del self._contents[filename]
                    continue

            # create a new directory object
            if isdir:
                DirClass = self.root._getDirectoryClass(fullPath)
                item = DirClass(fullPath, parent=self)
                self._contents[filename] = item

                # callback on directory scans
                self.root._directoryRefresh(item)

                if recursive:
                    self._contents[filename].refresh(recursive=recursive)

            # create a new file object
            elif isfile:
                FileClass = self.root._getFileClass(fullPath)
                item = FileClass(fullPath, parent=self)
                self._contents[filename] = item

                # callback on file scans
                self.root._fileRefresh(item)

        # recalculate ordering
        self._order = self.root._orderDirectory(self._contents)


    def filter(self, pattern, recursive=False, dirs=True, files=True, ignoreCase=True):
        """
        Uses the Python stdlib ``fnmatch`` library to search the filesystem.

        If ``ignoreCase`` is True, then ``fnmatch.fnmatch()`` will be used, and filenames
        will be converted to lowercase before comparisons are made.

        If ``ignoreCase`` is False, then ``fnmatch.fnmatchcase()`` will be used.

        See https://docs.python.org/library/fnmatch.html for more information about the
        pattern syntax.

        ``recursive``, ``dirs``, and ``files`` arguments are passed to ``Directory.all()``.
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
        matching by default. Passes the value of the ``flags`` argument directly through
        to ``re.compile()``, so check out the docs on the ``regex`` module for how that works.

        The default value for ``flags`` is ``re.IGNORECASE``.

        ``recursive``, ``dirs``, and ``files`` arguments are passed to ``Directory.all()``.

        Example:
        ``directory.search(r'(.*)\.txt')``
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

        ``recursive``, ``dirs``, and ``files`` arguments are passed to ``Directory.all()``.

        *Examples*:

        All files that are named "file1.txt" or "file2.txt", recursively:
            >>> directory.query(lambda f: f.name in ("file1.txt", "file2.txt"), recursive=True)

        All files larger than 1024 bytes:
            >>> directory.query(lambda f: f.size > 1024, dirs=False)

        All files and directories that start with E:
            >>> directory.query(lambda f: f.name.startswith("E"))

        All files modified within the last 7 days:
            >>> from datetime import datetime, timedelta
            >>> directory.query(lambda f: f.mtime > (datetime.now() - timedelta(days=7)), dirs=False)

        All directories with more than 10 items:
            >>> directory.query(lambda d: len(d) > 10, recursive=True, files=False)

        All directories that contain a file called "asdf.txt":
            >>> directory.query(lambda d: "asdf.txt" in d, recursive=True, files=False)
        """
        for item in self.all(recursive=recursive, dirs=dirs, files=files):
            if query(item):
                yield item


    def all(self, recursive=False, reverse=False, dirs=True, files=True):
        """
        A generator that yields all files and subdirectories contained within this directory.

        * If ``recursive`` is True, then it will also yield all items contained in those subdirectories.
        * If ``reverse`` is True, then it will iterate in reverse order.
        * The ``dirs`` argument indicates whether or not directories should be yielded.
        * The ``files`` argument indicates whether or not files should be yielded.
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


    def _push(self, item):
        """
        Put a FSObject instance in this directory.
        Used for keeping directories in sync with filesystem changes.
        """
        if item.name in self.contents.keys():
            raise FileExistsError(item.name)
        self.contents[item.name] = item

        # reorder directory
        self._order = self.root._orderDirectory(self.contents)

        # set up file to be in this directory
        item.parent = self
        item._path = os.path.join(self.path, item.name)
        # clear cached data that is out of date now
        item._relpath = None
        item._abspath = None


    def _pop(self, item):
        """
        Remove a FSObject instance from this directory.
        Used for keeping directories in sync with filesystem changes.
        """
        if self._contents is not None:
            del self._contents[item.name]
            self._order = self.root._orderDirectory(self._contents)
        return item


    def _itemRenamed(self, item, oldName, newName):
        """
        Called by child file or directories when rename is called on them.
        """
        # no need to do anything if we haven't refreshed yet
        if self._contents is not None:
            # change the key for the item
            self._contents[newName] = self._contents[oldName]
            del self._contents[oldName]

            # recalculate ordering
            self._order = self.root._orderDirectory(self._contents)

        # if this is a directory, we need to update the paths of EVERY file inside
        if item.isdir:
            for f in item.all(recursive=True):
                f._path = None
                f._abspath = None
                f._relpath = None
                newPath = f.path # force the path var to update


    def __len__(self):
        """
        Return the number of files and directories in this directory
        """
        return len(self.contents)


    def __iter__(self):
        for key in self.order:
            yield self.contents[key]


    def __contains__(self, key):
        """
        Checks if a given file or directory name is contained in this directory
        """
        return (key in self.contents)


    def __getitem__(self, key):
        """
        Directory objects support a number of different indexing methods, all of which
        either return a single object or a list containing multiple objects, which is
        useful when you want to assign the results to a variable (as opposed to the
        searching methods ``filter()``, ``search()``, ``query()``, and ``all()``, which
        are generators).

        Directories support the following syntaxes for indexing:

        * An ellipsis object returns a list of all children, recursively.

            ``directory[...]``
                (same as ``list(directory.all(recursive=True))``)
        
        * An integer, which is treated as an index and returns one item based on the
          directory ordering. Because the ordering is precalculated, this is O(1).
          Returns exactly one item.

            ``directory[2]``

        * A slice, which is treated as a range of indices based on the directory ordering.

            ``directory[1:3]``

        * An empty slice, which returns a list of items in the directory.

            ``directory[:]``
                (same as ``list(directory.all(recursive=False))``)

        * A string key, which is treated as a file or directory name and uses a
          dict-based lookup for O(1) lookups. Returns exactly one item.

            ``directory["asdf.txt"]``

        * A string which contains either a ``*`` or a ``?``. This string is passed to the
          Python stdlib library ``fnmatch`` to support searches and returns a list of files
          or directories that match the pattern. See the documentation for the ``fnmatch``
          library for more information.

            ``directory["*.txt"]``
                (same as ``list(directory.filter("*.txt"))``)
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

    # what classes to use for file and directory objects?
    FileClass = File
    DirectoryClass = Directory

    def __init__(self, path):
        Directory.__init__(self, path, None)

        if not os.path.exists(path):
            raise FileNotFoundError(path)
        if not os.path.isdir(path):
            raise ValueError("Root path must be a directory (got '%s')" % path)
        self._md = self._readMetadata()
        self._contents, self._order = self._readTreeData()

        # make sure all direct child objects have the correct parent set
        if self._contents is not None:
            for item in self._contents.values():
                item.parent = self
                # may as well set the root attribute too
                item._root = self


    def rename(self, newName, syscall=True):
        # renaming the root directory would break things somewhat...
        raise OSError("You can't rename the root directory.")


    @property
    def root(self):
        # Normally the ``root`` property figures out what the root directory is and returns it.
        # This object IS the root, so just return self.
        return self


    def save(self):
        """
        Write all metadata to disk.
        """
        self._writeMetadata(self._md)
        self._writeTreeData(self._contents, self._order)


    def scrubMetadata(self, autoRefresh=True):
        """
        Removes metadata entries for files that no longer exist. Takes a while to run
        and deletes data, so it must be run manually.

        This method would be less useful if run using an out-of-date directory tree,
        so it will automatically call ``self.refresh(recursive=True)``. If you don't
        want this to happen for whatever reason (maybe you *just* ran a refresh and
        don't need a second one) then pass the argument ``autoRefresh=False`` to this
        method.
        """
        if autoRefresh:
            # we need to make sure we have the most current data first
            self.refresh(recursive=True)

        # built a set of all currently existing file and directory hashes
        hashes = set()
        for f in self.all(recursive=True):
            hashes.add(f.hash())

        # build a list of all hashes currently in self._md that are NOT in the
        # current set of hashes
        outdatedHashes = []
        for h in self._md.keys():
            if h not in hashes:
                outdatedHashes.append(h)

        # delete every entry in self._md that is outdated
        for h in outdatedHashes:
            del self._md[h]


    def _getFileClass(self, path):
        """
        Returns a Python class that will be used for File objects in the filesystem tree.

        If you want to set a new File class for all files, you can just set the FileClass
        attribute to your class. If you want to use multiple classes, you can override
        this method and place any logic for determining which class to use here.
        """
        return self.FileClass


    def _getDirectoryClass(self, path):
        """
        Returns a Python class that will be used for Directory objects in the filesystem tree.

        If you want to set a new Directory class for all directories, you can just set
        the ``DirectoryClass`` attribute to your class. If you want to use multiple
        classes, you can override this method and place any logic for determining which
        class to use here.
        """
        return self.DirectoryClass


    def _orderDirectory(self, contents):
        """
        From the ``contents`` argument, which is a dict with filenames as keys and
        File objects as values, return a list of keys that will represent the ordering
        of that dict.
        """
        order = list(contents.keys())
        order.sort()
        return order


    def _ignorePath(self, name, fullpath, isdir):
        """
        Based on a file or directory name and its full path, return True if a file or directory
        should be excluded from indexing. Otherwise return False.
        """
        return False


    def _directoryRefresh(self, item):
        """
        Called whenever a directory is refreshed.

        Override this in a subclass if you would like some code to be run whenever a
        directory is refreshed.
        """


    def _fileRefresh(self, item):
        """
        Called whenever a file is refreshed.

        Override this in a subclass if you would like some code to be run (for example,
        scanning the file to manipulate metadata) whenever any file is scanned.
        """


    def _pathDelete(self, item):
        """
        Called whenever a file or directory is about to be deleted. This happens
        when a refresh is triggered and a file or directory no longer exists.

        Override this in a subclass if you would like some code to run before the
        file or directory object reference is removed.

        *Note*: If a directory is refreshed with ``directory.refresh()``, its contents
        will be wiped and recreated, so this method will never be called. If ``refresh()``
        is called with arguments, eg. ``directory.refresh("asdf.txt", "asdf2.txt")``, only
        specific files are refreshed, and this method will be called if and when one of
        those files no longer exists.
        """


    def _readMetadata(self):
        """
        Retrieves and returns metadata for all files in the filesystem.

        The returned object should be a dict, with the keys being a unique identifier for
        files, and values being a dict or dict-like object containing the metadata
        associated with that key.

        By default, keys should be the output of ``FSObject.hash()``, but this can be
        changed by adding a custom implementation of ``RootDirectory._getMetadataForObject()``.

        The constructor will run ``self._md = self._readMetadata()``.

        Should be implemented in a subclass to allow reading in metadata from a file or database.
        """
        return {}


    def _writeMetadata(self, metadata):
        """
        The ``metadata`` argument is a dict containing metadata for the entire filesystem.
        The keys represent the output of ``FSObject.hash()``, and the values are dicts containing
        the metadata assocated with that hash.

        This method should write that metadata to a file or database so that it can be
        restored later with ``_readMetadata()``.
        """


    def _readTreeData(self):
        """
        Reads in the directory tree from a file.

        Should be implemented in a subclass to allow the contents of the filesystem
        to be cached.

        Should return a 2-tuple, with the first element being a dict (keys are filenames,
        values are of type ``FSObject``), and the second element being a list containing
        all keys in that dict which represents the ordering of those keys.

        The constructor will run ``self._contents, self._order = self._readTreeData()``.
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


    def _getMetadataForObject(self, obj):
        """
        Given a FSObject, return a dict or dict-like object representing the metadata
        for that file or directory.

        This method exists so that subclasses can override the default behavior.
        """
        # get the hash of the object and use it as a dict key for the metadata dict
        fshash = obj.hash()

        # no entry for this hash? make one first
        if fshash not in self._md:
            self._md[fshash] = {}

        return self._md[fshash]



class CachedRootDirectory(RootDirectory):
    """
    A root directory that uses the json module to cache the directory tree and metadata.

    The constructor adds two optional arguments, `metadataFile` and `treeFile`.
    They default to `.metadata.json` and `.tree.json`, respectively, and
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

    def __init__(self, path, metadataFile=".metadata.json", treeFile=".tree.json"):
        # Set the filenames of the metadata and tree files before calling the parent constructor.
        # The parent constructor will call _readMetadata and _readTreeData, so we need these values
        # to be available before that happens.
        self._mdFile = metadataFile
        if self._mdFile == ".metadata.json":
            # if the filename is the default one, put it at the root of the filesystem
            self._mdFile = os.path.join(path, metadataFile)

        self._treeFile = treeFile
        if self._treeFile == ".tree.json":
            # if the filename is the default one, put it at the root of the filesystem
            self._treeFile = os.path.join(path, treeFile)

        RootDirectory.__init__(self, path)


    def _ignorePath(self, name, fullpath, isdir):
        """
        A default implementation for ``_ignorePath`` that simply ignores the json files
        for metadata and the tree cache.
        """
        # Ignore the metadata and tree cache data when indexing
        if name == self._mdFile or name == self._treeFile:
            return True
        else:
            return False


    def _readMetadata(self):
        """
        Reads in metadata from a JSON file
        """
        if self._mdFile is not None and os.path.exists(self._mdFile):
            with open(self._mdFile, 'r') as fp:
                return json.load(fp)
        return {}


    def _writeMetadata(self, metadata):
        """
        Writes out all metadata to a JSON file
        """
        if self._mdFile is not None:
            with open(self._mdFile, 'w') as fp:
                json.dump(metadata, fp, indent=4)


    def _deserializeHandler(self, data):
        """
        When decoding the directory tree JSON file, this method is used for the
        ``object_hook`` argument of ``json.load()`` so that dicts can be
        transformed back into FSObjects.
        """
        if '__fsobject' in data:
            if data['__fsobject'] == 'File':
                return self._getFileClass(data['name']).deserialize(data)
            elif data['__fsobject'] == 'Directory':
                return self._getDirectoryClass(data['name']).deserialize(data)
        return data


    def _serializeHandler(self, obj):
        """
        When encoding the directory tree as JSON, this method is used for the
        ``default`` argument of ``json.dump()`` so that FSObjects can be transformed
        into dicts.
        """
        if isinstance(obj, (self._getFileClass(obj.name), self._getDirectoryClass(obj.name))):
            return obj.serialize()
        raise TypeError(str(type(obj)))


    def _readTreeData(self):
        """
        Reads the directory cache tree in from a JSON file
        """
        if self._treeFile is not None and os.path.exists(self._treeFile):
            with open(self._treeFile, 'r') as fp:
                data = json.load(fp, object_hook=self._deserializeHandler)
                return (data['contents'], data['order'])
        return (None, None)


    def _writeTreeData(self, tree, order):
        """
        Writes the directory tree cache out to a JSON file
        """
        if self._treeFile is not None:
            with open(self._treeFile, 'w') as fp:
                json.dump({'contents':tree, 'order':order}, fp, indent='\t', default=self._serializeHandler)



def mkRootDirectoryBaseClass(FileCls=File, DirectoryCls=Directory, RootDirectoryCls=RootDirectory):
    """
    Helper factory function that can generate a RootDirectory class
    with a different base class. Useful if you have a custom Directory
    class with features you also want to work with the root directory.

    ``FileCls``: a class that all file objects will derive from.
    ``DirectoryCls``: a class that all directories, including the root
        directory, will be derived from.
    ``RootDirectoryCls``: a class to copy existing methods from. This
        allows your custom base class to "inherit" methods from existing
        root directories, such as CachedRootDirectory.
    """
    # generate the new class
    class RootDir(DirectoryCls):
        FileClass = FileCls
        DirectoryClass = DirectoryCls

    # apply all of the root directory attributes to this new root directory class
    for name, obj in RootDirectory.__dict__.items():
        setattr(RootDir, name, obj)

    # if the specified root directory class isn't the default, also apply any extra
    # stuff from the specified one as well.
    if RootDirectoryCls != RootDirectory:
        if not RootDirectoryCls.__base__ == RootDirectory:
            raise Exception("The RootDirectoryCls argument must inherit directly from RootDirectory.")

        for name, obj in RootDirectoryCls.__dict__.items():
            setattr(RootDir, name, obj)

    return RootDir


