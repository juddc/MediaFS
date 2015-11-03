"""
MetaFS: A pure-Python filesystem caching system for easy searching and metadata storage

Author: Judd Cohen
License: MIT (See accompanying file LICENSE or copy at http://opensource.org/licenses/MIT)
"""
import json
from json.decoder import JSONDecodeError

try:
    import xattr
except ImportError:
    print("===")
    print("pyxattr library not found (https://pypi.python.org/pypi/pyxattr)")
    print("===")
    raise

from mediafs.fs import File, Directory, CachedRootDirectory


class XAttrMetadata(object):
    """
    A dict-like class that uses the ``xattr`` module to reflect key/value pairs from
    extended filesystem attributes.

    Keys must be strings.

    Values are fed through the ``json`` module for better type support.

    No caching is done, which means that all values will reflect the status of the file
    at the time of the call. This is useful if you have multiple applications operating
    on the same attribute data.

    If you are utilizing this metadata with tools other than this library, be aware that
    all attribute keys are in the user namespace.

    For example:

    >>> fs['asdf2.txt'].metadata['author'] = "John Smith"
    >>> fs['asdf2.txt'].metadata['year'] = 2007

    ::

        $ getfattr -n user.author asdf2.txt
        # file: asdf2.txt
        user.author="\"John Smith\""
        
        $ getfattr -n user.year asdf2.txt
        # file: asdf2.txt
        user.year="2007"
    """

    def __init__(self, path):
        self._path = path


    def _decodeVal(self, val):
        """
        Helper function for decoding values we get from ``xattr.get()``.
        Converts the value to a string, then passes it through ``json.loads()`` for type conversion.
        """
        val = val.decode()
        try:
            return json.loads(val)
        except JSONDecodeError:
            return val


    def __getitem__(self, key):
        """
        Retrieves an extended filesystem attribute. Raises ``KeyError`` if the file does not
        have an attribute with that name.
        """
        try:
            return self._decodeVal(xattr.get(self._path, key, namespace=xattr.NS_USER))
        except OSError:
            pass
        raise KeyError(key)


    def __setitem__(self, key, val):
        """
        Sets a filesystem attribute
        """
        xattr.set(self._path, key, json.dumps(val), namespace=xattr.NS_USER)


    def __delitem__(self, key):
        """
        Removes a filesystem attribute
        """
        xattr.remove(self._path, key, namespace=xattr.NS_USER)


    def __contains__(self, key):
        """
        Checks if a filesystem attribute exists on this file
        """
        return key in self.keys()


    def __iter__(self):
        """
        An interator on all values stored in filesystem attributes
        """
        for val in self.values():
            yield val


    def __len__(self):
        """
        Returns the number of attributes stored
        """
        return len(self.keys())


    def keys(self):
        """
        Returns a list of all filesystem attributes
        """
        return [ key.decode() for key in xattr.list(self._path, namespace=xattr.NS_USER) ]


    def values(self):
        """
        Returns a list of all filesystem attribute values
        """
        return [ self[key] for key in self.keys() ]


    def items(self):
        """
        Returns a list of key/value pairs for all filesystem attributes
        """
        allAttrs = xattr.get_all(self._path, namespace=xattr.NS_USER)
        return [ (key.decode(), self._decodeVal(val)) for key, val in allAttrs ]


    def pop(self, key):
        """
        Removes a filesystem attribute by its name and returns its value
        """
        val = self[key]
        del self[key]
        return val


    def copy(self):
        """
        Returns a dict with all filesystem attributes as key/value pairs
        """
        return { k:v for k, v in self.items() }


    def __str__(self):
        return "{%s}" % ", ".join("%r: %r" % (key, val) for key, val in self.items())
    __repr__ = __str__



class XAttrRootDirectory(CachedRootDirectory):
    """
    A RootDirectory object that stores file and directory metadata as extended filesystem
    attributes on Linux systems. Depends on the ``pyxattrs`` Python module.

    This class is derived from ``CachedRootDirectory``, so you will still need to call
    ``save()`` to write the directory tree cache. If you do not need this functionality
    at all, pass ``treeFile=None`` as an argument to the constructor.

    Using extended filesystem attributes for metadata can situationally be faster than
    using a single JSON file to store all metadata because it doesn't have the overhead
    of hashing (even partially) files before doing the metadata lookup. It also has the
    advantage of working on the filesystem attributes directly - calling
    ``file.metadata['asdf'] = 5`` immediately serializes the value, which is then available
    to other applications without needing to call ``save()`` first.

    The primary disadvantage is portability. Many system tools such as ``cp`` and ``rsync``
    will ignore extended attributes and you can lose metadata this way. It can also be tricky
    to get your data out if you move it to another system.

    If you have issues using this class, try using the command line tools ``attr``,
    ``getfattr``, and ``setfattr``. Please note that this class uses the "user" namespace,
    which means that if you set a metadata key called ``title``, then the actual key name
    will be ``user.title`` when using the command line tools.

    If the command line tools do not work for you, then there is probably something wrong
    with your OS configuration. Some filesystems (like ``tmpfs``) do not support extended
    attributes at all, and others may need to have particular mount options to work correctly.
    """

    def __init__(self, path, treeFile=".tree.json"):
        CachedRootDirectory.__init__(self, path, metadataFile=None, treeFile=treeFile)


    def _getMetadataForObject(self, obj):
        """
        Return a XAttrMetadata object, which is a dict-like object which wraps the
        ``xattr`` python module for metadata access.
        """
        return XAttrMetadata(obj.abspath)

