import os
import random
import shutil
import tempfile
import unittest
from zipfile import ZipFile

from fs import *


class TestMetaFS(unittest.TestCase):

    def _getFS(self, Cls=RootDirectory, clean=True):
        """
        Helper function that extracts the contents of a zip file to a temp directory
        and uses that path as a testing filesystem, then creates an object for that
        filesystem and returns it.

        If clean == True, then any existing temp filesystem is deleted and a new one
        is extracted.
        """
        basedir = os.path.join(tempfile.gettempdir(), "mediafs_tests")

        # do we need to clean up first and create a fresh FS?
        if clean:
            zipFilename = "./testfs.zip"
            testdataPath = os.path.abspath(zipFilename)

            if not os.path.exists(testdataPath):
                raise FileNotFoundError(testdataPath)

            if not os.path.exists(basedir):
                os.mkdir(basedir)

            # remove any existing files
            destpath = os.path.join(basedir, "testfs")
            if os.path.exists(destpath):
                shutil.rmtree(destpath)

            # extract the test fs zip file
            with ZipFile(testdataPath) as testdata:
                testdata.extractall(path=basedir)

        # return a new root directory representing the test filesystem
        return Cls(os.path.join(basedir, "testfs"))


    def test_length(self):
        """
        Test that we get the number of files we expect to in various directories
        """
        fs = self._getFS()
        
        self.assertEqual(len(fs), 7) # 7 items in the toplevel dir

        # syntax for getting all top-level files
        self.assertEqual(len(fs[:]), 7)

        # test splicing
        self.assertEqual(len(fs[1:3]), 2)

        # 3 files in /def/azerty
        self.assertEqual(len(fs['def']['azerty']), 3)

        # only 5 directories
        self.assertEqual(len(list(fs.all(recursive=True, files=False, dirs=True))), 5)

        # 11 files
        self.assertEqual(len(list(fs.all(recursive=True, files=True, dirs=False))), 11)

        # 16 total files and directories
        self.assertEqual(len(list(fs.all(recursive=True, files=True, dirs=True))), 16)

        # another syntax for getting all files
        self.assertEqual(len(fs[...]), 16)


    def test_file_exists(self):
        """
        Make sure we can easily test if a file exists
        """
        fs = self._getFS()

        # do these folders exist?
        self.assertTrue("abc" in fs)
        self.assertTrue("def" in fs)

        # these ARE folders, right?
        self.assertTrue(fs['abc'].isdir == True)
        self.assertTrue(fs['def'].isdir == True)

        # check a file inside a folder
        self.assertTrue("qwerty" in fs["abc"])

        # do these top-level files exist?
        self.assertTrue("test.txt" in fs)
        self.assertTrue("test1.txt" in fs)
        self.assertTrue("test2.txt" in fs)
        self.assertTrue("test3.txt" in fs)
        self.assertTrue("some_other_test.txt" in fs)

        # this file should not exist
        with self.assertRaises(KeyError):
            fs['abcdefg.txt']


    def test_search(self):
        """
        Test searching the filesystem via various methods
        """
        fs = self._getFS()

        # number of files matching /abc/qwerty/stuff/thing*.txt
        self.assertEqual(len(fs['abc']['qwerty']['stuff']['thing*.txt']), 2)

        # number of top-level files with a .txt extension
        self.assertEqual(len(fs['*.txt']), 5)

        # same thing, more explict syntax
        self.assertEqual(len(list(fs.filter("*.txt"))), 5)

        # number of top-level files
        self.assertEqual(len(fs['*']), 7)

        # files with a name containing the string "j1"
        self.assertEqual(len(list(fs.search("j1", recursive=True))), 1)
        j1 = list(fs.search("j1", recursive=True))[0]
        self.assertEqual(j1.name, "j1.txt")
        self.assertEqual(j1.size, 4995)

        # number of files with a filesize greater than 2048 bytes
        self.assertEqual(len(list(fs.query(lambda f: f.size > 2048, files=True, dirs=False))), 5)

        #
        # search metadata
        #

        # add a dummy "author" metadata entry to all files (but not directories)
        for item in fs.all(dirs=False, recursive=True):
            item.metadata['author'] = ""

        # set an actual author value to some files
        fs['test2.txt'].metadata['author'] = "Some Dude"
        fs['test3.txt'].metadata['author'] = "Some Other Dude"
        fs['abc']['qwerty']['qwerty.txt'].metadata['author'] = "Some Dude"

        # count files with "Some Dude" author
        count = 0
        for item in fs.query(lambda f: f.metadata['author'] == "Some Dude", dirs=False, recursive=True):
            count += 1
        self.assertEqual(count, 2)

        # count files with "Some Other Dude" author
        count = 0
        for item in fs.query(lambda f: f.metadata['author'] == "Some Other Dude", dirs=False, recursive=True):
            count += 1
        self.assertEqual(count, 1)


    def test_duplicate_files(self):
        """
        Test working with duplicate files
        """
        fs = self._getFS()

        duplicates = []
        for item1 in fs.all(recursive=True):
            for item2 in fs.all(recursive=True):
                if item1.abspath != item2.abspath and item1.matches(item2) and (item2, item1) not in duplicates:
                    duplicates.append((item1, item2))

        self.assertEqual(len(duplicates), 2)
        self.assertEqual(duplicates, [
            (fs['abc']['qwerty']['stuff']['thing1.txt'], fs['test.txt']),
            (fs['abc']['qwerty']['stuff']['thing2.txt'], fs['test1.txt']),
        ])

        # test metadata with copies of the same file
        fs['test.txt'].metadata['author'] = "Some Dude"
        count = 0
        for item in fs.query(lambda f: "author" in f.metadata and f.metadata['author'] == "Some Dude", recursive=True):
            count += 1
        # this results in TWO files, not one, because "test.txt" and "thing1.txt" have identical hashes
        self.assertEqual(count, 2)


    def test_refresh(self):
        """
        Test refreshing
        """
        fs = self._getFS()
        fs.refresh()

        fs = self._getFS()
        fs.refresh(recursive=True)

        fs = self._getFS()
        fs['abc'] # will raise keyerror if it can't be found
        fs.refresh('abc', recursive=True)


    def test_lazy_refresh(self):
        """
        Test lazy evaluation of refresh()
        """
        fs = self._getFS()

        # folder _contents start out as None
        self.assertEqual(fs['def']['azerty']._contents, None)

        # then the folder is accessed
        item = fs['def']['azerty']['j1.txt']

        # then _contents is populated
        self.assertTrue(isinstance(fs['def']['azerty']._contents, dict))
        self.assertEqual(len(fs['def']['azerty']._contents), 3)

        # test lazy evaluation of other properties:
        self.assertEqual(item._abspath, None)
        itemPath = item.abspath
        self.assertEqual(item._abspath, itemPath)

        self.assertEqual(item._crc, None)
        crcValue = item.crc()
        self.assertEqual(item._crc, crcValue)

        self.assertEqual(item._md5, None)
        md5Value = item.md5()
        self.assertEqual(item._md5, md5Value)

        self.assertEqual(item._root, None)
        rootValue = item.root
        self.assertEqual(item._root, rootValue)

        # try root again after save and reload
        fs.save()
        fs = self._getFS(clean=False)
        
        item = fs['def']['azerty']['j1.txt']

        self.assertEqual(item._root, None)
        rootValue = item.root
        self.assertEqual(item._root, rootValue)


    def test_metadata_cache(self):
        fs = self._getFS(CachedRootDirectory)
        fs.refresh(recursive=True)

        # store some metadata on a file
        file1 = fs['abc']['qwerty']['stuff']['thing1.txt']
        file1.metadata['author'] = "Some Dude"
        file1.metadata['year'] = 2015
        file1.metadata['month'] = 10
        file1.metadata['day'] = 22

        # store some metadata on another file
        file2 = fs['test2.txt']
        file2.metadata['author'] = "Some Other Dude"
        file2.metadata['year'] = 2015
        file2.metadata['month'] = 10
        file2.metadata['day'] = 12

        # write out metadata
        fs.save()

        # recreate filesystem object and reload caches
        del fs
        fs = self._getFS(CachedRootDirectory, clean=False)

        # look up the two files we put metadata on
        file1 = fs['abc']['qwerty']['stuff']['thing1.txt']
        file2 = fs['test2.txt']

        # check that all the keys are there
        for f in (file1, file2):
            for key in ("author", "year", "month", "day"):
                self.assertTrue(key in f.metadata)

        # check that all the values are correct for both files
        self.assertEqual(file1.metadata['author'], "Some Dude")
        self.assertEqual(file1.metadata['year'], 2015)
        self.assertEqual(file1.metadata['month'], 10)
        self.assertEqual(file1.metadata['day'], 22)
        self.assertEqual(file2.metadata['author'], "Some Other Dude")
        self.assertEqual(file2.metadata['year'], 2015)
        self.assertEqual(file2.metadata['month'], 10)
        self.assertEqual(file2.metadata['day'], 12)

        # check that some other key isn't in the metadata
        self.assertFalse("asdf" in file2.metadata)

        # check that some random key isn't in a different file's metadata
        self.assertFalse("asdf" in fs['test.txt'].metadata)


    def test_filesystem_cache(self):
        fs = self._getFS(CachedRootDirectory)
        fs.refresh(recursive=True)

        numFiles = len(fs)

        fs.save()

        # recreate the filesystem object and reload caches
        del fs
        fs = self._getFS(CachedRootDirectory, clean=False)

        self.assertEqual(len(fs), numFiles)

        # will raise exception if cache is broken because we never did a refresh
        someFile = fs['test2.txt']

        with self.assertRaises(KeyError):
            fs['non-existant-file.asdf']



if __name__ == '__main__':
    unittest.main()

