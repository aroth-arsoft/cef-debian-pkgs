#!/usr/bin/python3
# -*- coding: utf-8 -*-
# kate: space-indent on; indent-width 4; mixedindent off; indent-mode python;
import sys
import argparse
import urllib.request
import errno
import shutil
import re
import os
import os.path
from zipfile import ZipFile, BadZipFile
import tarfile
from arsoft.utils import *
from arsoft.inifile import IniFile


def mkdir_p(path):
    try:
        os.makedirs(path)
    except OSError as exc:  # Python >2.5
        if exc.errno == errno.EEXIST and os.path.isdir(path):
            pass
        else:
            raise

def rmdir_p(path):
    return shutil.rmtree(path, ignore_errors=False, onerror=None)

def copytree(src, dst, symlinks=False, ignore=None, copy_function=shutil.copy2,
             ignore_dangling_symlinks=False, ignore_existing_dst=False):
    """Recursively copy a directory tree.

    The destination directory must not already exist.
    If exception(s) occur, an Error is raised with a list of reasons.

    If the optional symlinks flag is true, symbolic links in the
    source tree result in symbolic links in the destination tree; if
    it is false, the contents of the files pointed to by symbolic
    links are copied. If the file pointed by the symlink doesn't
    exist, an exception will be added in the list of errors raised in
    an Error exception at the end of the copy process.

    You can set the optional ignore_dangling_symlinks flag to true if you
    want to silence this exception. Notice that this has no effect on
    platforms that don't support os.symlink.

    The optional ignore argument is a callable. If given, it
    is called with the `src` parameter, which is the directory
    being visited by copytree(), and `names` which is the list of
    `src` contents, as returned by os.listdir():

        callable(src, names) -> ignored_names

    Since copytree() is called recursively, the callable will be
    called once for each directory that is copied. It returns a
    list of names relative to the `src` directory that should
    not be copied.

    The optional copy_function argument is a callable that will be used
    to copy each file. It will be called with the source path and the
    destination path as arguments. By default, copy2() is used, but any
    function that supports the same signature (like copy()) can be used.

    """
    names = os.listdir(src)
    if ignore is not None:
        ignored_names = ignore(src, names)
    else:
        ignored_names = set()

    if ignore_existing_dst:
        try:
            os.makedirs(dst)
        except OSError as exc:  # Python >2.5
            if exc.errno == errno.EEXIST and os.path.isdir(dst):
                pass
            else:
                raise
    else:
        os.makedirs(dst)
    errors = []
    for name in names:
        if name in ignored_names:
            continue
        srcname = os.path.join(src, name)
        dstname = os.path.join(dst, name)
        try:
            if os.path.islink(srcname):
                linkto = os.readlink(srcname)
                if symlinks:
                    # We can't just leave it to `copy_function` because legacy
                    # code with a custom `copy_function` may rely on copytree
                    # doing the right thing.
                    os.symlink(linkto, dstname)
                    shutil.copystat(srcname, dstname, follow_symlinks=not symlinks)
                else:
                    # ignore dangling symlink if the flag is on
                    if not os.path.exists(linkto) and ignore_dangling_symlinks:
                        continue
                    # otherwise let the copy occurs. copy2 will raise an error
                    if os.path.isdir(srcname):
                        copytree(srcname, dstname, symlinks, ignore,
                                 copy_function, ignore_existing_dst=ignore_existing_dst)
                    else:
                        copy_function(srcname, dstname)
            elif os.path.isdir(srcname):
                copytree(srcname, dstname, symlinks, ignore, copy_function, ignore_existing_dst=ignore_existing_dst)
            else:
                # Will raise a SpecialFileError for unsupported file types
                copy_function(srcname, dstname)
        # catch the Error from the recursive copytree so that we can
        # continue with other files
        except shutil.Error as err:
            errors.extend(err.args[0])
        except OSError as why:
            errors.append((srcname, dstname, str(why)))
    try:
        shutil.copystat(src, dst)
    except OSError as why:
        # Copying file access times may fail on Windows
        if getattr(why, 'winerror', None) is None:
            errors.append((src, dst, str(why)))
    if errors:
        raise shutil.Error(errors)
    return dst

def copy_and_overwrite(from_path, to_path):
    def _copy_and_overwrite(src, dst):
        shutil.copy2(src, dst)
    ret = False
    try:
        copytree(from_path, to_path, copy_function=_copy_and_overwrite, ignore_existing_dst=True)
        ret = True
    except shutil.Error as e:
        print('Copy failed: %s' % e, file=sys.stderr)

    remove_obsolete_files(from_path, to_path, ignore=shutil.ignore_patterns('debian', '.pc', '.git*'))
    return ret

def extract_archive(archive, dest_dir):
    ret = False
    b = os.path.basename(archive)
    b, last_ext = os.path.splitext(b)
    if last_ext == '.zip':
        try:
            with ZipFile(archive, 'r') as zipObj:
                # Extract all the contents of zip file in different directory
                zipObj.extractall(dest_dir)
            ret = True
        except BadZipFile as e:
            print('ZIP file %s error: %s' % (archive, e), file=sys.stderr)
    elif last_ext == '.gz' or last_ext == '.bz2' or last_ext == '.xz':
        b, second_ext = os.path.splitext(b)
        if second_ext == '.tar':
            try:
                with tarfile.open(archive, 'r') as tarObj:
                    # Extract all the contents of tar file in different directory
                    tarObj.extractall(dest_dir)
                ret = True
            except tarfile.TarError as e:
                print('Tar file %s error: %s' % (archive, e), file=sys.stderr)
    #print('extract_archive ret->%s %i' % (archive, ret))
    return ret


def get_spotify_builds(url, platform='linux64'):
    def extract_builds(data, platform):
        from lxml import html
        ret = []

        tree = html.fromstring(data)
        platform_table = tree.xpath('//table[@id="%s"]' % platform)
        if platform_table:
            all_versions = platform_table[0].xpath('tr[@class="toprow"]/@data-version')
            for e in all_versions:
                major, _ = e.split('.', 1)
                try:
                    major = int(major)
                except ValueError:
                    major = 0
                if major > 3:
                    ret.append( (major, e) )

        return ret

    hdr = {'User-Agent':'Mozilla/5.0', 'Accept': '*/*'}
    #print(url)
    req = urllib.request.Request(url, headers=hdr)
    try:
        response = urllib.request.urlopen(req)
        if response.status == 200:
            data = response.read()      # a `bytes` object
            text = data.decode('utf-8') # a `str`; this step can't be used if data is binary
            #print(text)
            return extract_builds(text, platform)
        #elif response.status == 302:
            #newurl = response.geturl()
            #print('new url %s' % newurl)
    except urllib.error.HTTPError as e:
        if self._verbose:
            print('HTTP Error %s: %s' % (url, e))
        pass
    return None


package_list = {
    'cef-78': {
        'version': 78,
        'site': 'spotify',
    },
    'cef-79': {
        'version': 79,
        'site': 'spotify',
        'disable': True,
    },
    }


site_list = {
    #http://opensource.spotify.com/cefbuilds/cef_binary_79.0.10%2Bge866a07%2Bchromium-79.0.3945.88_linux64.tar.bz2
    'spotify': {
        'archive': 'tar.bz2',
        'platform': 'linux64',
        'index': 'http://opensource.spotify.com/cefbuilds/index.html',
        'download': 'http://opensource.spotify.com/cefbuilds/cef_binary_${last_build}_${platform}.${archive}',
    },
}




class cef_package_update_app(object):
    def __init__(self):
        self._verbose = False
        self._packages = []

    def _get_latest_revisions(self):
        for name, details in site_list.items():
            index = details.get('index', None)
            if index is not None:
                builds = get_spotify_builds(index)
                #print(builds)
                if builds:
                    site_list[name]['builds'] = builds
        return True

    def _load_package_list(self):
        for name, details in package_list.items():
            if name not in self._packages:
                #if self._verbose:
                    #print('Skip package %s' % name)
                continue
            site = site_list.get(details.get('site', None), None)
            version = details.get('version', None)
            if site:
                site_download = site.get('download', None)
                site_builds = site.get('builds', None)
                site_platform = site.get('platform', None)
                site_archive = site.get('archive', None)
                builds = []
                last_build = None
                if site_builds is not None:
                    for (build_major, build_full_ver) in site_builds:
                        if build_major == version:
                            if last_build is None:
                                last_build = build_full_ver
                            builds.append(build_full_ver)
                package_list[name]['builds'] = builds
                package_list[name]['last_build'] = last_build


                if site_download is not None:
                    url = site_download
                    if url and site_platform is not None:
                        url = url.replace('${platform}', urllib.parse.quote_plus(str(site_platform)))
                    if url and site_archive is not None:
                        url = url.replace('${archive}', urllib.parse.quote_plus(str(site_archive)))
                    package_list[name]['site_download_url'] = url

    def _list(self):
        for name, details in site_list.items():
            print('Site %s' % name)
            site_download = details.get('download', None)
            if site_download:
                print('  Download: %s' % site_download)

        for name, details in package_list.items():
            if name not in self._packages:
                continue
            if details.get('disable', False):
                continue
            url = details.get('site_download_url')
            version = details.get('version', None)
            last_build = details.get('last_build', None)
            if url:
                if version is not None:
                    url = url.replace('${version}', urllib.parse.quote_plus(str(version)))
                if last_build is not None:
                    url = url.replace('${last_build}', urllib.parse.quote_plus(str(last_build)))

            print('%s' % name)
            print('  URL: %s' % url)
            #builds = details.get('builds', None)
            #print('  Builds:')
            #for b in builds:
            #    print('    %s' % b)
        return 0

    def _download_pkgs(self):
        ret = True
        mkdir_p(self._download_dir)
        for name, details in package_list.items():
            if name not in self._packages:
                continue
            if details.get('disable', False):
                continue
            print('%s' % name)
            site = site_list.get(details.get('site', None), None)
            if site:
                url = details.get('site_download_url')
                delete_files = details.get('delete-files', [])
                version = details.get('version', None)
                last_build = details.get('last_build', None)
                if url:
                    if version is not None:
                        url = url.replace('${version}', urllib.parse.quote_plus(str(version)))
                    if last_build is not None:
                        url = url.replace('${last_build}', urllib.parse.quote_plus(str(last_build)))
                site_download = site.get('download', None)
                site_archive = site.get('archive', None)
                if site_download is None:
                    download_ok = True
                else:
                    dest_format = 'zip'
                    if site_archive is None:
                        filename = name.lower()
                        filename += '.zip'
                    elif last_build is not None:
                        filename = name.lower() + '_%s.%s' % (last_build, site_archive)
                    else:
                        filename = name.lower() + '_%s.%s' % (version, site_archive)
                        dest_format = site_archive
                    download_ok = False

                    dest = os.path.join(self._download_dir, filename)
                    if os.path.isfile(dest):
                        if self._force:
                            os.unlink(dest)
                        else:
                            download_ok = True
                    if not download_ok:
                        if self._verbose:
                            print('Download %s...' % url)
                        try:
                            urllib.request.urlretrieve(url, dest)
                            download_ok = True
                        except urllib.error.HTTPError as ex:
                            print('HTTP error %s for %s' % (ex, url))
                    elif self._verbose:
                        print('Download file %s already exists.' % dest)

                if download_ok and site_archive and delete_files:
                    download_subdir = os.path.basename(url)
                    i = download_subdir.find(site_archive)
                    if i >= 0:
                        download_subdir = download_subdir[0:i]
                        if download_subdir[-1] == '.':
                            download_subdir = download_subdir[0:-1]

                    download_ok = False
                    pkg_download_tmp_dir = os.path.join(self._download_dir, name.lower() + '.tmp')
                    if self._verbose:
                        print('Extract to %s' % pkg_download_tmp_dir)
                    # extract to temp directory, delete the files and re-package
                    if extract_archive(dest, pkg_download_tmp_dir):
                        prefix = download_subdir
                        base_dir = os.path.join(pkg_download_tmp_dir, download_subdir)
                        for f in delete_files:
                            full = os.path.join(base_dir, f)
                            if os.path.exists(full):
                                try:
                                    os.unlink(full)
                                except IOError as e:
                                    print('Unable to delete %s: %s' % (full, e), file=sys.stderr)
                        download_ok = make_tarfile(base_dir, dest, prefix=prefix)
                        if not download_ok:
                            print('Failed to create tar archive %s from %s' % (dest, base_dir), file=sys.stderr)

                if site_download is None:
                    # No download required
                    pass
                elif download_ok:
                    pkg_download_dir = os.path.join(self._download_dir, name.lower())
                    pkg_download_tag_file = os.path.join(self._download_dir, '.' + name.lower() + '.tag')

                    # Extract all the contents of zip file in different directory
                    if not extract_archive(dest, pkg_download_dir):
                        print('Failed to extract %s to %s' % (dest, pkg_download_dir), file=sys.stderr)
                        ret = False

                    f = IniFile(pkg_download_tag_file)
                    if url is not None:
                        f.set(None, 'url', url)
                    if site_archive is not None:
                        f.set(None, 'archive', site_archive)
                    f.save(pkg_download_tag_file)
                    f.close()
                else:
                    print('Download failed %s' % (name), file=sys.stderr)
                    ret = False
        return ret


    def main(self):
        #=============================================================================================
        # process command line
        #=============================================================================================
        parser = argparse.ArgumentParser(description='update/generate CEF packages')
        parser.add_argument('-v', '--verbose', dest='verbose', action='store_true', help='enable verbose output of this script.')
        parser.add_argument('-f', '--force', dest='force', action='store_true', help='force re-download of packages.')
        parser.add_argument('-l', '--list', dest='list', action='store_true', help='show list of all packages.')
        parser.add_argument('-np', '--no-publish', dest='no_publish', action='store_true', help='do not publish packages.')
        parser.add_argument('-u', '--update', dest='update', action='store_true', help='update the package repositories.')
        parser.add_argument('-p', '--package', dest='packages', nargs='*', help='select packages to process (default all)')

        args = parser.parse_args()
        self._verbose = args.verbose
        self._force = args.force
        self._no_publish = args.no_publish

        base_dir = os.path.abspath(os.getcwd())
        self._download_dir = os.path.join(base_dir, 'download')
        if args.packages:
            self._packages = []
            available_packages = {}
            for name, details in package_list.items():
                available_packages[name.lower()] = name
                alias = details.get('alias', None)
                if alias is not None:
                    available_packages[alias.lower()] = name
            got_unknown_package = False
            for p in args.packages:
                pkg_name = p.lower()
                if pkg_name in available_packages:
                    real_name = available_packages[pkg_name]
                    self._packages.append(real_name)
                else:
                    got_unknown_package = True
                    print('Unknown package %s specified.' % p, file=sys.stderr)
            if got_unknown_package:
                return 1
        else:
            self._packages = package_list.keys()

        try:
            import debian
        except ImportError:
            print('Debian python extension not available. Please install python3-debian.', file=sys.stderr)
            return 2

        lsb_release = IniFile('/etc/lsb-release')
        self._distribution = lsb_release.get(None, 'DISTRIB_CODENAME', 'unstable')
        lsb_release.close()

        self._get_latest_revisions()
        self._load_package_list()

        if args.list:
            ret = self._list()
        elif args.update:
            if self._download_pkgs():
                if self._update_package_repo():
                    if self._no_publish:
                        ret = 0
                    else:
                        if self._ppa_publish():
                            ret = 0
                        else:
                            ret = 5
                else:
                    ret = 4
            else:
                ret = 3
        else:
            ret = 0

        return ret


if __name__ == "__main__":
    app = cef_package_update_app()
    sys.exit(app.main())
