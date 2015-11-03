#!/usr/bin/env python
"""
This is a utility script that lets you use MediaFS for searching from the command line.

Due to Python interpreter startup time, this probably won't replace standard OS
commands for searching a filesystem such as `find` or `locate`, however this *is*
useful for searching by serialized metadata that has been saved by some other program
or script using MediaFS.

For example, if you stored ID3 tag information from some MP3 files as metadata for
a directory, you could use this script to search by metadata:
    $ metasearch.py --query="f.get('author') == 'The Beatles'"
"""
import os
import sys
import argparse

from mediafs import CachedRootDirectory


def getargs():
    parser = argparse.ArgumentParser(description="Search the filesystem with MediaFS")

    searchgroup = parser.add_mutually_exclusive_group()
    searchgroup.add_argument("--query", "-q", type=str, nargs=1, dest='query',
        help="Search the filesystem with a function (eg. --query=\"'qwerty' in f.name\") "
        "Equivalent to fs.query(lambda f: (QUERY))")
    searchgroup.add_argument("--filter", "-f", type=str, nargs=1, dest='filter',
        help="Search the filesystem with a glob (eg. --filter=\"*qwerty*\")")
    searchgroup.add_argument("--search", "-s", type=str, nargs=1, dest='search',
        help="Search the filesystem with a regex (eg. --query=\"(.*)qwerty(.*)\")")

    parser.add_argument("--refresh", "-r", action="store_true", dest="refresh",
        help="Refresh the directory tree cache")

    parser.add_argument("--refresh-metadata", "-m", action="store_true", dest="refreshMetadata",
        help="When refreshing the directory tree cache, also compute metadata hashes for faster subsequent searching")

    parser.add_argument("--write", "-w", action="store_true", dest="write",
        help="Writes out the updated cache before exiting (speeds subsequent runs)")

    parser.add_argument("--non-recursive", "-n", action="store_true", dest="nonrecursive",
        help="Do not search recursively")

    parser.add_argument("--exclude-dirs", "-d", action="store_true", dest="nodirs",
        help="Exclude directories from the search (files only)")

    parser.add_argument("--exclude-files", "-x", action="store_true", dest="nofiles",
        help="Exclude files from the search (directories only)")

    parser.add_argument("--exec", "-e", type=str, nargs=1, dest="resultExec", default="print(f.abspath)",
        help="A line of Python code that is run for each search result. "
        "Defaults to \"print(f.abspath)\" if not specified")

    return parser.parse_args()


def main():
    args = getargs()

    fs = CachedRootDirectory(os.getcwd())

    if args.refresh:
        if args.refreshMetadata:
            for item in fs.all(recursive=True):
                item.metadata
        else:
            fs.refresh(recursive=True)

    recursive = not args.nonrecursive
    dirs = not args.nodirs
    files = not args.nofiles
    resultExec = args.resultExec
    if isinstance(resultExec, list):
        resultExec = resultExec[0]

    if not dirs and not files:
        print("Excluding both files and directories will lead to zero results")
        sys.exit(2)

    if args.query:
        query = args.query[0]
        if not query.startswith("lambda"):
            query = "lambda f: (%s)" % query
            try:
                queryFunc = eval(query)
            except Exception as e:
                print("Error compiling query: %s" % e)
                sys.exit(2)

            for f in fs.query(queryFunc, recursive=recursive, dirs=dirs, files=files):
                exec(resultExec)

    elif args.filter:
        for f in fs.filter(args.filter[0], recursive=recursive, dirs=dirs, files=files):
            exec(resultExec)

    elif args.search:
        for f in fs.search(args.search[0], recursive=recursive, dirs=dirs, files=files):
            exec(resultExec)

    if args.write:
        fs.save()


if __name__ == "__main__":
    main()

