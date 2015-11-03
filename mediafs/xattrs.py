import copy
import json
from json.decoder import JSONDecodeError

import xattr

from mediafs.fs import File, Directory, CachedRootDirectory


class XAttrMetadata(object):
    def __init__(self, path):
        self._path = path


    def _decodeVal(self, val):
        val = val.decode()
        try:
            return json.loads(val)
        except JSONDecodeError:
            return val


    def __getitem__(self, key):
        try:
            return self._decodeVal(xattr.get(self._path, key, namespace=xattr.NS_USER))
        except OSError:
            pass
        raise KeyError(key)


    def __setitem__(self, key, val):
        xattr.set(self._path, key, json.dumps(val), namespace=xattr.NS_USER)


    def __delitem__(self, key):
        xattr.remove(self._path, key, namespace=xattr.NS_USER)


    def __contains__(self, key):
        return key in self.keys()


    def __iter__(self):
        for val in self.values():
            yield val


    def __len__(self):
        return len(self.keys())


    def keys(self):
        return [ key.decode() for key in xattr.list(self._path, namespace=xattr.NS_USER) ]


    def values(self):
        return [ self[key] for key in self.keys() ]


    def items(self):
        allAttrs = xattr.get_all(self._path, namespace=xattr.NS_USER)
        return [ (key.decode(), self._decodeVal(val)) for key, val in allAttrs ]


    def pop(self, key):
        val = self[key]
        del self[key]
        return val


    def copy(self):
        return { k:v for k, v in self.items() }


    def deepcopy(self):
        return copy.deepcopy(self.copy())


    def __str__(self):
        return "{%s}" % ", ".join("%r: %r" % (key, val) for key, val in self.items())
    __repr__ = __str__



class XAttrRootDirectory(CachedRootDirectory):
    def __init__(self, path, treeFile=".tree.json"):
        CachedRootDirectory.__init__(self, path, metadataFile=None, treeFile=treeFile)


    def _getMetadataForObject(self, obj):
        return XAttrMetadata(obj.abspath)


    def _readMetadata(self):
        return {}


    def _writeMetadata(self, metadata):
        pass


