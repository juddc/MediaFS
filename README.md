MediaFS - A Python File/Directory API with Metadata
===

MediaFS is a Python API that makes it easy to search a directory tree. It has
support for custom metadata as well as caching for faster searching.

The primary design goal for MediaFS is to be a backend for managing media
collections, such as for music or video, but the implementation is
filetype-agnostic and can be used for working with any type of data.


Examples:
```
from mediafs import CachedRootDirectory

fs = CachedRootDirectory("/some/directory")

# prints number of top-level files and directories
print(len(fs))

# prints file size of a file in bytes
print(fs['some_file.txt'].size)

# prints the name of every file with a .txt extension
for item in fs.filter("*.txt", recursive=True, files=True, dirs=False):
	print(item.name)

# print the absolute path and filesize (in MB) of all zip files larger than 128MB
for item in fs.query(lambda f: f.name.endswith(".zip") and f.size > 2**27, recursive=True, dirs=False):
	print(item.abspath, item.size // 2**20, "MB")

# print the name and filesize (in MB) of all top-level directories larger than 1GB
for item in fs.query(lambda f: f.size > 2**30, files=False):
	print(item.name, item.size // 2**20, "MB")

```

