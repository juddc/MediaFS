import os
import functools
import signal
import logging
import asyncio

from mediafs import (RootDirectory, CachedRootDirectory, Directory, mkRootDirectoryBaseClass)

try:
    import butter
except ImportError:
    print("===")
    print("Butter library not found (Linux-only, https://pypi.python.org/pypi/butter/0.11.1)")
    print("===")

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
    DirectoryClass=SyncedDirectory,
    RootDirectoryClass=CachedRootDirectory)


class SyncedRootDirectory(SyncedCachedRootDir):
    """
    A root directory object that can keep itself in sync with the filesystem.
    """

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
        handle = self._inotify.watch(dirobj.abspath, DIR_FLAGS)
        self._inotifyHandles[handle] = dirobj
        self._inotifyHandles[dirobj.relpath] = handle


    def _getInotifyEventDir(self, evt):
        return self._inotifyHandles[evt.wd]


    def _getDirectoryClass(self):
        return SyncedDirectory


    @asyncio.coroutine
    def handleInotifyEvents(self):
        if self._futureInotifyEvent is None:
            self._futureInotifyEvent = asyncio.ensure_future(self._inotify.get_event())

        results = []
        if self._futureInotifyEvent is not None and self._futureInotifyEvent.done():
            try:
                result = self._futureInotifyEvent.result()
                results.append(result)
            except asyncio.CancelledError:
                pass

            # see if more events will follow this one
            moreEvents = True
            while moreEvents:
                try:
                    nextResult = yield from asyncio.wait_for(self._inotify.get_event(), 0.05)
                    results.append(nextResult)
                except asyncio.TimeoutError:
                    moreEvents = False

            self._futureInotifyEvent = None

        returnValues = []

        for i in range(len(results)):
            dirobj = None

            evt = results[i]

            if i < len(results) - 1:
                nextEvt = results[i + 1]
            else:
                nextEvt = None

            isDir = False
            if evt.is_dir_event:
                isDir = True

            dirobj = self._getInotifyEventDir(evt)

            if evt.create_event:
                dirobj._inotifyCreate(evt, isDir)
                returnValues.append(("create", dirobj, evt.filename.decode()))

            elif evt.modify_event:
                dirobj._inotifyModify(evt, isDir)
                returnValues.append(("modify", dirobj, evt.filename.decode()))

            elif evt.delete_event:
                dirobj._inotifyDelete(evt, isDir)
                returnValues.append(("delete", dirobj, evt.filename.decode()))

            elif nextEvt is not None and (evt.moved_from_event or evt.moved_to_event):
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

                if evtFrom is None or evtTo is None:
                    filename = os.path.join(dirobj.abspath, evt.filename.decode())
                    logging.error("Expected a MOVED_FROM and MOVED_TO pair, got %s and %s for file '%s'" % (
                        _flagsToStr(evt), _flagsToStr(nextEvt), filename))
                else:
                    nextDirobj = self._getInotifyEventDir(nextEvt)
                    dirobj._inotifyMove(evt, nextEvt, nextDirobj, isDir)
                    returnValues.append(("movefrom", dirobj, evtFrom.filename.decode()))
                    returnValues.append(("moveto", nextDirobj, evtTo.filename.decode()))

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
            filesystemEvents = yield from fs.handleInotifyEvents()
            for evtType, evtObj, filename in filesystemEvents:
                print(evtType, evtObj, filename)
            yield from asyncio.sleep(1)

    loop.run_until_complete(mainloop())
