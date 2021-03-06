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
import copy
import tarfile
from arsoft.utils import *
from arsoft.inifile import IniFile



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

def remove_obsolete_files(src, dst, ignore=None):
    names = os.listdir(dst)
    if ignore is not None:
        ignored_names = ignore(dst, names)
    else:
        ignored_names = set()

    errors = []
    for name in names:
        if name in ignored_names:
            continue
        srcname = os.path.join(src, name)
        dstname = os.path.join(dst, name)
        try:
            if os.path.isdir(dstname):
                remove_obsolete_files(srcname, dstname, ignore)
            if not os.path.exists(srcname):
                print('remove %s' %dstname)
                if os.path.isfile(dstname):
                    os.unlink(dstname)
                else:
                    rmdir_p(dstname)
        # catch the Error from the recursive copytree so that we can
        # continue with other files
        except shutil.Error as err:
            errors.extend(err.args[0])
        except OSError as why:
            errors.append((srcname, dstname, str(why)))
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

def substVars(val, props, empty_vars=True):

    DELIM_START = "${";
    DELIM_STOP = "}"
    DELIM_START_LEN = len(DELIM_START)
    DELIM_STOP_LEN = len(DELIM_STOP)
    changed = False
    pattern = val
    i = 0

    while True:
        # Find opening paren of variable substitution.
        var_start = pattern.find(DELIM_START, i);
        if var_start < 0:
            dest = pattern;
            return changed, dest;

        # Find closing paren of variable substitution.
        var_end = pattern.find(DELIM_STOP, var_start);
        if var_end < 0:
            return False;

        key = pattern[var_start + DELIM_START_LEN: var_end]
        replacement = ''

        if key and key in props:
            replacement = str(props[key])

        if empty_vars or replacement:
            # Substitute the variable with its value in place.
            pattern = pattern[0:var_start] + replacement + pattern[var_end+DELIM_STOP_LEN:]
            changed = True
            # Move beyond the just substituted part.
            i = var_start + len(replacement)
        else:
            # Nothing has been substituted, just move beyond the unexpanded variable.
            i = var_end + DELIM_STOP_LEN
    return changed, pattern

def configure_file(src, dst, values={}, follow_symlinks=True, encoding='utf-8'):
    ret = True
    if not follow_symlinks and os.path.islink(src):
        os.symlink(os.readlink(src), dst)
    else:
        with open(src, 'rb') as fsrc, open(dst, 'wb') as fdst:

            for srcline in fsrc:
                changed, dstline = substVars(srcline.decode(encoding), props=values, empty_vars=False)
                if changed:
                    fdst.write(dstline.encode(encoding))
                else:
                    fdst.write(srcline)
            fsrc.close()
            fdst.close()
    return ret

def copy_and_configure(from_path, to_path, values={}, ignore=None):
    class _copy_and_configure:
        def __init__(self, values):
            self.values = values

        def __call__(self, src, dst):
            dstdir, dstbase = os.path.split(dst)
            dstchanged, dstbase = substVars(dstbase, props=values)
            if dstchanged:
                dst = os.path.join(dstdir, dstbase)

            configure_file(src, dst, values=self.values)
            shutil.copystat(src, dst)
    ret = False
    try:
        func = _copy_and_configure(values)
        copytree(from_path, to_path, copy_function=func, ignore_existing_dst=True, ignore=ignore)
        ret = True
    except shutil.Error as e:
        print('Copy failed: %s' % e, file=sys.stderr)
    return ret

def copyfile(src, dst):
    ret = False
    try:
        shutil.copy2(src, dst)
        ret = True
    except shutil.Error as e:
        print('Copy failed: %s' % e, file=sys.stderr)
    return ret

class MyTarFile(tarfile.TarFile):
    def extract(self, member, path="", set_attrs=True, *, numeric_owner=False, prefix=None):
        """Extract a member from the archive to the current working directory,
           using its full name. Its file information is extracted as accurately
           as possible. `member' may be a filename or a TarInfo object. You can
           specify a different directory using `path'. File attributes (owner,
           mtime, mode) are set unless `set_attrs' is False. If `numeric_owner`
           is True, only the numbers for user/group names are used and not
           the names.
        """
        self._check("r")

        if isinstance(member, str):
            tarinfo = self.getmember(member)
        else:
            tarinfo = member

        #print('extract %s prefix=%s' % (tarinfo, prefix))

        # Prepare the link target for makelink().
        if tarinfo.islnk():
            tarinfo._link_target = os.path.join(path, tarinfo.linkname)

        try:
            if prefix is None:
                dst = os.path.join(path, tarinfo.name)
            else:
                tname = tarinfo.name[len(prefix):]
                if tname and tname[0] == '/':
                    tname = tname[1:]
                dst = os.path.join(path, tname)
            self._extract_member(tarinfo, dst,
                                 set_attrs=set_attrs,
                                 numeric_owner=numeric_owner)
        except OSError as e:
            if self.errorlevel > 0:
                raise
            else:
                if e.filename is None:
                    self._dbg(1, "tarfile: %s" % e.strerror)
                else:
                    self._dbg(1, "tarfile: %s %r" % (e.strerror, e.filename))
        except tarfile.ExtractError as e:
            if self.errorlevel > 1:
                raise
            else:
                self._dbg(1, "tarfile: %s" % e)

    def extract_all_to(self, path=".", members=None, *, numeric_owner=False, prefix=None):
        """Extract all members from the archive to the current working
           directory and set owner, modification time and permissions on
           directories afterwards. `path' specifies a different directory
           to extract to. `members' is optional and must be a subset of the
           list returned by getmembers(). If `numeric_owner` is True, only
           the numbers for user/group names are used and not the names.
        """
        directories = []
        #print('extract_all_to prefix=%s' % prefix)

        if members is None:
            members = self

        for tarinfo in members:
            if prefix is not None:
                if not tarinfo.name.startswith(prefix):
                    continue
            if tarinfo.isdir():
                # Extract directories with a safe mode.
                directories.append(tarinfo)
                tarinfo = copy.copy(tarinfo)
                tarinfo.mode = 0o700
            # Do not set_attrs directories, as we will do that further down
            self.extract(tarinfo, path, set_attrs=not tarinfo.isdir(),
                         numeric_owner=numeric_owner, prefix=prefix)

        # Reverse sort directories.
        directories.sort(key=lambda a: a.name)
        directories.reverse()

        # Set correct owner, mtime and filemode on directories.
        for tarinfo in directories:
            dirpath = os.path.join(path, tarinfo.name)
            try:
                self.chown(tarinfo, dirpath, numeric_owner=numeric_owner)
                self.utime(tarinfo, dirpath)
                self.chmod(tarinfo, dirpath)
            except ExtractError as e:
                if self.errorlevel > 1:
                    raise
                else:
                    self._dbg(1, "tarfile: %s" % e)

def extract_archive(archive, dest_dir, prefix=None):
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
                with MyTarFile.open(archive, 'r') as tarObj:
                    #tarObj.open(archive, 'r')
                    # Extract all the contents of tar file in different directory
                    tarObj.extract_all_to(dest_dir, prefix=prefix)
                    ret = True
            except tarfile.TarError as e:
                print('Tar file %s error: %s' % (archive, e), file=sys.stderr)
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

re_cef_version_h = re.compile(r'#define CEF_VERSION\s*[\'"]([a-zA-Z0-9\.+-]+)[\'"]')
re_source_format = re.compile(r'([0-9]+.[0-9]+)\s*\((a-zA-Z)\)')


def increment_debian_revision(rev, strategy):
    e = rev.split('.')
    if strategy == 'minor':
        if len(e) < 2:
            e.append('0')
    try:
        num = int(e[-1]) + 1
    except ValueError:
        num = 0 if strategy != 'minor' else 1
    e[-1] = str(num)
    return '.'.join(e)

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

    def _download_pkgs(self, extract=False):
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
                    basename = urllib.parse.unquote(os.path.basename(url))
                else:
                    basename = None
                site_download = site.get('download', None)
                site_archive = site.get('archive', None)
                if site_download is None:
                    download_ok = True
                else:
                    if basename is None:
                        if site_archive is None:
                            filename = name.lower()
                            filename += '.zip'
                        elif last_build is not None:
                            filename = name.lower() + '_%s.%s' % (last_build, site_archive)
                        else:
                            filename = name.lower() + '_%s.%s' % (version, site_archive)
                    else:
                        filename = basename
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
                    if extract:
                        repo_dir = os.path.join(self._repo_dir, name.lower())

                        mkdir_p(repo_dir)

                        # Extract all the contents of zip file in different directory
                        prefix = basename
                        if site_archive and prefix.endswith(site_archive):
                            prefix = prefix[:-len(site_archive) - 1]
                        if self._verbose:
                            print('Extract %s to %s (prefix %s)' % (dest, repo_dir, prefix))

                        # Extract all the contents of zip file in different directory
                        if not extract_archive(dest, repo_dir, prefix=prefix):
                            print('Failed to extract %s to %s' % (dest, repo_dir), file=sys.stderr)
                            ret = False
                    else:
                        ret = True
                else:
                    print('Download failed %s' % (name), file=sys.stderr)
                    ret = False
        return ret

    def _update_package_repo(self):
        ret = True
        mkdir_p(self._repo_dir)
        for name, details in package_list.items():
            if name not in self._packages:
                continue
            if details.get('disable', False):
                continue
            site = site_list.get(details.get('site', None), None)
            url = details.get('site_download_url')
            version = details.get('version', None)
            last_build = details.get('last_build', None)
            if url:
                if version is not None:
                    url = url.replace('${version}', urllib.parse.quote_plus(str(version)))
                if last_build is not None:
                    url = url.replace('${last_build}', urllib.parse.quote_plus(str(last_build)))
                basename = urllib.parse.unquote(os.path.basename(url))
            else:
                basename = None
            site_download = site.get('download', None)
            site_archive = site.get('archive', None)

            repo_dir = os.path.join(self._repo_dir, name.lower())
            repo_ok = os.path.isdir(repo_dir)

            repo_debian_dir = os.path.join(repo_dir, 'debian')

            values = { 'cef:ABI': version }

            copy_and_configure(self._debian_dir, repo_debian_dir, values=values, ignore=shutil.ignore_patterns('changelog', '.git*'))

            if basename is None:
                if site_archive is None:
                    filename = name.lower()
                    filename += '.zip'
                elif last_build is not None:
                    filename = name.lower() + '_%s.%s' % (last_build, site_archive)
                else:
                    filename = name.lower() + '_%s.%s' % (version, site_archive)
            else:
                filename = basename
            download_file = os.path.join(self._download_dir, filename)
            download_ok = os.path.isfile(download_file)

            if not download_ok:
                print('Download file %s is missing' % (download_file), file=sys.stderr)

            elif repo_ok:
                print('Repository %s ok' % repo_dir)
                download_subdir = details.get('repo_subdir', name.lower())

                debian_package_name = 'cef%i' % version

                orig_file = os.path.join(repo_dir, '../%s_%s.orig.%s' % (debian_package_name, last_build, site_archive) )
                if self._verbose:
                    print('Use orig archive file: %s' % orig_file)

                if not os.path.isfile(orig_file):
                    if self._verbose:
                        print('Copy %s to %s' % (download_file, orig_file))
                    if not copyfile(download_file, orig_file):
                        print('Failed to copy file %s to %s' % (download_file, orig_file), file=sys.stderr)
                        repo_ok = False
                    else:
                        # Extract all the contents of zip file in different directory
                        prefix = basename
                        if site_archive and prefix.endswith(site_archive):
                            prefix = prefix[:-len(site_archive) - 1]
                        if self._verbose:
                            print('Extract %s to %s (prefix %s)' % (orig_file, repo_dir, prefix))
                        if not extract_archive(orig_file, repo_dir, prefix=prefix):
                            print('Failed to extract %s to %s' % (orig_file, repo_dir), file=sys.stderr)
                            repo_ok = False

                if repo_ok:
                    print('Prepare build of %s' % (name.lower()))

                    pc_dir = os.path.join(repo_dir, '.pc')
                    if os.path.isdir(pc_dir):
                        if self._verbose:
                            print('Delete directory %s' % (pc_dir))
                        rmdir_p(pc_dir)

                    debian_package_version = None
                    debian_package_orig_version = None
                    debian_package_update_ok = False
                    debian_revision = None
                    cef_version = None
                    cef_version_h = os.path.join(repo_dir, 'include/cef_version.h')
                    try:
                        f = open(cef_version_h, 'r')
                        for line in f:
                            m = re_cef_version_h.search(line)
                            if m:
                                cef_version = m.group(1)
                                break
                        f.close()
                    except IOError as e:
                        print('Unable to open %s: %s' % (cef_version_h, e), file=sys.stderr)
                        pass

                    if cef_version:

                        commit_msg = 'Automatic update %s' % cef_version

                        source_format = None
                        source_format_version = None
                        source_format_filename = os.path.join(repo_dir, 'debian/source/format')
                        try:
                            f = open(source_format_filename, 'r')
                            line = f.readline().strip()
                            m = re_source_format.search(line)
                            if m:
                                source_format_version = m.group(1)
                                source_format = m.group(2)
                                break
                            f.close()
                        except IOError as e:
                            print('Unable to open %s: %s' % (source_format_filename, e), file=sys.stderr)
                            pass

                        dch_filename = os.path.join(repo_dir, 'debian/changelog')
                        dch_version = None
                        try:
                            import debian.changelog
                            from textwrap import TextWrapper
                            f = open(dch_filename, 'r')
                            dch = debian.changelog.Changelog(f)
                            f.close()
                            old_version = str(dch.version)
                            debian_package_orig_version = cef_version
                            new_version = debian_package_orig_version + '-'
                            #print('old_version %s' % old_version)
                            #print('new_version %s' % new_version)
                            if old_version.startswith(new_version):
                                i = old_version.rfind('-')
                                if i:
                                    debian_revision = old_version[i+1:] if i else 0
                            else:
                                debian_revision = '0'

                            debian_revision = increment_debian_revision(debian_revision, strategy=details.get('debian-revision', 'major'))
                            #print('debian_revision %s' % debian_revision)
                            new_version = new_version + debian_revision
                            #print('new_version %s' % new_version)

                            debian_package_version = new_version
                            dch.new_block(
                                package=debian_package_name,
                                version=debian_package_version,
                                distributions=self._distribution,
                                urgency=dch.urgency,
                                author="%s <%s>" % debian.changelog.get_maintainer(),
                                date=debian.changelog.format_date()
                            )
                            wrapper = TextWrapper()
                            wrapper.initial_indent    = "  * "
                            wrapper.subsequent_indent = "    "
                            dch.add_change('')
                            for l in wrapper.wrap(commit_msg):
                                dch.add_change(l)
                            dch.add_change('')
                            f = open(dch_filename, 'w')
                            f.write(str(dch))
                            #print(dch)
                            f.close()
                            debian_package_update_ok = True
                        except IOError as e:
                            print('Unable to open %s: %s' % (dch_filename, e), file=sys.stderr)
                            pass
                    else:
                        print('Failed to get version from %s.' % setup_py, file=sys.stderr)
                        ret = False

                else:
                    print('Download directory %s missing' % pkg_download_dir, file=sys.stderr)
            else:
                print('Repository %s failed' % repo_dir, file=sys.stderr)
                ret = False
        return ret

    def _ppa_publish(self, no_upload=True):
        ret = True
        for name, details in package_list.items():
            if name not in self._packages:
                continue
            if details.get('disable', False):
                continue

            repo_dir = os.path.join(self._repo_dir, name.lower())
            repo_ok = os.path.isdir(repo_dir)
            if repo_ok:
                print('Publish package on PPA from %s' % repo_dir)
                args = ['ppa_publish']
                if no_upload:
                    args.append('--noput')
                try:
                    (sts, stdoutdata, stderrdata) = runcmdAndGetData(args=args, stdin=sys.stdin, stdout=sys.stdout, stderr=sys.stderr, cwd=repo_dir)
                    if sts != 0:
                        print('ppa_publish failed:\n%s' % stderrdata, file=sys.stderr)
                except FileNotFoundError as ex:
                    print('Cannot execute ppa_publish.', file=sys.stderr)
                    ret = False

        return ret

    def main(self):
        #=============================================================================================
        # process command line
        #=============================================================================================
        parser = argparse.ArgumentParser(description='update/generate CEF packages')
        parser.add_argument('-v', '--verbose', dest='verbose', action='store_true', help='enable verbose output of this script.')
        parser.add_argument('-f', '--force', dest='force', action='store_true', help='force re-download of packages.')
        parser.add_argument('-fe', '--force-extract', dest='force_extract', action='store_true', help='force override local source with downloaded package.')
        parser.add_argument('-l', '--list', dest='list', action='store_true', help='show list of all packages.')
        parser.add_argument('-np', '--no-publish', dest='no_publish', action='store_true', help='do not publish packages.')
        parser.add_argument('-d', '--download', dest='download', action='store_true', help='downloads the latest CEF binary packages.')
        parser.add_argument('-u', '--update', dest='update', action='store_true', help='update the package repositories.')
        parser.add_argument('-p', '--package', dest='packages', nargs='*', help='select packages to process (default all)')

        args = parser.parse_args()
        self._verbose = args.verbose
        self._force = args.force
        self._force_extract = args.force_extract
        self._no_publish = args.no_publish

        base_dir = os.path.abspath(os.getcwd())
        self._download_dir = os.path.join(base_dir, 'download')
        self._repo_dir = os.path.join(base_dir, 'repo')
        self._debian_dir = os.path.join(base_dir, 'debian')
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
        elif args.download:
            if self._download_pkgs(extract=self._force_extract):
                ret = 0
            else:
                ret = 1
        elif args.update:
            if self._download_pkgs(extract=self._force_extract):
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
