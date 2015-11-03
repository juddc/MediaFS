"""
MetaFS: A pure-Python filesystem caching system for easy searching and metadata storage

Author: Judd Cohen
License: MIT (See accompanying file LICENSE or copy at http://opensource.org/licenses/MIT)
"""
import os
import functools
import signal
import logging
import asyncio
from collections import namedtuple

from mediafs import (RootDirectory, CachedRootDirectory, Directory, mkRootDirectoryBaseClass)

try:
    import butter
except ImportError:
    print("===")
    print("Butter library not found (Linux-only, https://pypi.python.org/pypi/butter/0.11.1)")
    print("===")
    raise

from butter.asyncio.inotify import Inotify_async
from butter.inotify import (event_name, IN_ACCESS, IN_MODIFY, IN_ATTRIB,
    IN_CLOSE_WRITE, IN_CLOSE_NOWRITE, IN_OPEN, IN_MOVED_FROM, IN_MOVED_TO,
    IN_CREATE, IN_DELETE, IN_DELETE_SELF, IN_MOVE_SELF, IN_ONLYDIR,
    IN_DONT_FOLLOW, IN_EXCL_UNLINK, IN_MASK_ADD, IN_ISDIR, IN_ONESHOT,
    IN_ALL_EVENTS)

DIR_EVENTS = [IN_MODIFY, IN_MOVED_FROM, IN_MOVED_TO, IN_CREATE, IN_DELETE]
EVENT_NAMES = { k:v for k,v in event_name.items() if isinstance(k, str) and k != 'IN_ALL_EVENTS' }
DIR_FLAGS = 0
for evt in DIR_EVENTS:
    DIR_FLAGS |= evt


# FileEvent named tuple - the return value of the processFilesystemEvents coroutine is a list of these.
# The "type" field will be one of the following values:
#      "create", "modify", "delete", "movefrom", "moveto"
FileEvent = namedtuple("FileEvent", ["type", "parent", "name"])


def _flagsToStr(evt):
    """
    Helper function that converts the flags in an event to an array of strings
    for easier debugging.
    """
    flags = []
    for flagStr, flag in EVENT_NAMES.items():
        if evt.mask & flag:
            flags.append(flagStr)
    return flags



class SyncedDirectory(Directory):
    """
    A Directory object with helper methods to keep it in sync with the filesystem.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.root._inotifyRegister(self)


    def _inotifyCreate(self, evt, isDir):
        """
        Called when a file or directory is created inside this directory.
        """
        filename = evt.filename.decode()
        self.refresh(filename)


    def _inotifyModify(self, evt, isDir):
        """
        Called when a file or directory is modified inside this directory.
        """
        if not isDir:
            filename = evt.filename.decode()
            f = self[filename]
            # invalidate the hashes
            f._crc = None
            f._md5 = None
            f._fasthash = None


    def _inotifyMove(self, srcEvt, destEvt, destDir, isDir):
        """
        Called when a file or directory in this directory is moved somewhere
        """
        srcFilename = srcEvt.filename.decode()
        destFilename = destEvt.filename.decode()

        srcFile = self[srcFilename]

        logging.debug("_inotifyMove '%s' to '%s'" %
            (os.path.join(self.relpath, srcFilename),
            os.path.join(self.relpath, destFilename)))

        # simple rename operation?
        if self == destDir:
            logging.debug("RENAME METHOD")
            srcFile.rename(destFilename, syscall=False)

        # move the file object pointer directly if we have dicts available for both dirs
        elif self._contents is not None and destDir._contents is not None:
            logging.debug("DIRECT METHOD")
            self._pop(srcFile)
            destDir._push(srcFile)

        # otherwise just refresh both files on both sides to ensure they're in sync
        else:
            logging.debug("REFRESH_METHOD")
            self.refresh(srcFilename, destFilename)
            destDir.refresh(srcFilename, destFilename)


    def _inotifyDelete(self, evt, isDir):
        """
        Called when a file or directory is deleted inside this directory.
        """
        filename = evt.filename.decode()
        self.refresh(filename)
            

# make a CachedRootDirectory class that has SyncedDirectory as a subclass
SyncedCachedRootDir = mkRootDirectoryBaseClass(
    DirectoryCls=SyncedDirectory,
    RootDirectoryCls=CachedRootDirectory)


class SyncedRootDirectory(SyncedCachedRootDir):
    """
    A root directory object that can keep itself in sync with the filesystem.
    """
    DirectoryClass = SyncedDirectory


    def __init__(self, path, loop):
        super().__init__(path)
        self._inotify = Inotify_async(loop=loop)
        self._inotifyHandles = {}
        self._inotifyRegister(self)
        self._futureInotifyEvent = None


    def isSynced(self):
        """
        Returns True if the root directory object is completely in sync with the
        filesystem. Does an exhaustive search, and raises a RuntimeError if
        any files are not in sync.

        Because this is an exhaustive search that does not modify any data
        structures, this method is very slow compared to just calling
        ``refresh(recursive=True)``.

        This is primarily intended as a way to validate that the inotify events
        are being processed correctly.
        """
        allFiles = set()
        for item in self.all(recursive=True):
            allFiles.add(item.relpath)

        mirrorFiles = set()
        for item in RootDirectory(self.path).all(recursive=True):
            mirrorFiles.add(item.relpath)
            if item.relpath not in allFiles:
                raise RuntimeError("'%s' not in synced fs" % item.relpath)
                return False

        for item in allFiles:
            if item not in mirrorFiles:
                raise RuntimeError("'%s' in syncedFS but does not exist" % item.relpath)
                return False

        return True


    def _inotifyRegister(self, dirobj):
        """
        Because the butter library does not do any sort of recursive watching,
        this callback, which is called in the constructor of every directory
        object, will set up a watch for that directory.
        """
        handle = self._inotify.watch(dirobj.abspath, DIR_FLAGS)

        # allow lookups by either handle or relative path
        self._inotifyHandles[handle] = dirobj
        self._inotifyHandles[dirobj.relpath] = handle


    def _getInotifyEventDir(self, evt):
        """
        Takes an inotify event (the butter library object) and returns the inotify
        handle for it.
        """
        return self._inotifyHandles[evt.wd]


    @asyncio.coroutine
    def processFilesystemEvents(self):
        """
        Tries to get new events from the filesystem. If any events exist, more events will be
        retrieved with a timeout of 0.05 seconds until the timeout expires, at which time
        all of the retrieved events will be processed.

        Each event will be processed so that this object stays in sync with the filesystem.

        A list of all processed events will be returned in a list of ``FileEvent`` objects,
        which is a namedtuple containing 3 fields: ``type``, ``parent``, ``name``.

        | ``type`` is a string which will contain one of the following values: "create",
        | "modify", "delete", "movefrom", "moveto"
        | 
        | ``parent`` is a directory object that is the parent directory of the file or
        | directory that the event refers to.
        |
        | ``name`` is the name of the file or directory that the event refers to.

        Note that in the returned list of events, any time a "movefrom" event occurs, a
        "moveto" event is guaranteed to come after it.
        """
        if self._futureInotifyEvent is None:
            self._futureInotifyEvent = asyncio.ensure_future(self._inotify.get_event())

        results = []
        if self._futureInotifyEvent is not None and self._futureInotifyEvent.done():
            try:
                result = self._futureInotifyEvent.result()
                results.append(result)
            except asyncio.CancelledError:
                return []

            # see if more events will follow this one
            moreEvents = True
            while moreEvents:
                try:
                    nextResult = yield from asyncio.wait_for(self._inotify.get_event(), 0.05)
                    results.append(nextResult)
                except asyncio.TimeoutError:
                    moreEvents = False

            self._futureInotifyEvent = None

        # for every event, we're going to add a 3-tuple to this array representing the event
        returnValues = []

        # go through all the results and route them to helper methods on the Directory objects
        for i in range(len(results)):
            dirobj = None

            evt = results[i]

            # nextEvt is the event object following this one. we need this because
            # movefrom and moveto are different events and we need them as a pair
            if i < len(results) - 1:
                nextEvt = results[i + 1]
            else:
                nextEvt = None

            # is this a directory event?
            isDir = False
            if evt.is_dir_event:
                isDir = True

            # get the directory object we're going to route the event to
            dirobj = self._getInotifyEventDir(evt)

            # a file or directory was created
            if evt.create_event:
                dirobj._inotifyCreate(evt, isDir)
                returnValues.append(FileEvent("create", dirobj, evt.filename.decode()))

            # a file or directory was modified
            elif evt.modify_event:
                dirobj._inotifyModify(evt, isDir)
                returnValues.append(FileEvent("modify", dirobj, evt.filename.decode()))

            # a file or directory was deleted
            elif evt.delete_event:
                dirobj._inotifyDelete(evt, isDir)
                returnValues.append(FileEvent("delete", dirobj, evt.filename.decode()))

            # a file or directory was moved
            elif nextEvt is not None and (evt.moved_from_event or evt.moved_to_event):
                # we need to figure out the order. one event is movefrom and one event is moveto.
                evtFrom = None
                evtTo = None

                if evt.moved_from_event:
                    evtFrom = evt
                elif evt.moved_to_event:
                    evtTo = evt

                if nextEvt.moved_from_event:
                    evtFrom = nextEvt
                elif nextEvt.moved_to_event:
                    evtTo = nextEvt

                # make sure we actually get a movefrom/moveto pair
                if evtFrom is not None and evtTo is not None:
                    nextDirobj = self._getInotifyEventDir(nextEvt)
                    dirobj._inotifyMove(evt, nextEvt, nextDirobj, isDir)
                    # in our return values, movefrom and moveto will ALWAYS be a pair, and
                    # movefrom will ALWAYS come before moveto.
                    returnValues.append(FileEvent("movefrom", dirobj, evtFrom.filename.decode()))
                    returnValues.append(FileEvent("moveto", nextDirobj, evtTo.filename.decode()))

                # didn't get a pair, log an error
                else:
                    filename = os.path.join(dirobj.abspath, evt.filename.decode())
                    logging.error("Expected a MOVED_FROM and MOVED_TO pair, got %s and %s for file '%s'" % (
                        _flagsToStr(evt), _flagsToStr(nextEvt), filename))

        return returnValues



if __name__ == "__main__":
    if not os.path.exists("/tmp/mediafs_synctest"):
        os.mkdir("/tmp/mediafs_synctest")

    loop = asyncio.get_event_loop()
    fs = SyncedRootDirectory("/tmp/mediafs_synctest", loop)
    fs.refresh(recursive=True)

    @asyncio.coroutine
    def mainloop():
        while True:
            filesystemEvents = yield from fs.processFilesystemEvents()
            for evtType, evtObj, filename in filesystemEvents:
                print(evtType, evtObj, filename)
            yield from asyncio.sleep(1)

    loop.run_until_complete(mainloop())
