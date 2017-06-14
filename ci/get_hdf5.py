# -*- coding: utf-8 -*-

from os import environ, makedirs, walk, listdir, getcwd, chdir
from os.path import join as pjoin, exists
from tempfile import TemporaryFile, TemporaryDirectory
from sys import exit, stderr, platform
from shutil import copyfileobj, copy
from glob import glob
from subprocess import run, PIPE, STDOUT
from zipfile import ZipFile
from tarfile import TarFile
from gzip import GzipFile
from pathlib import Path
import requests

HDF5_18_URL = "https://www.hdfgroup.org/ftp/HDF5/releases/hdf5-1.8/hdf5-{version}/src/"
HDF5_110_URL = "https://www.hdfgroup.org/ftp/HDF5/releases/hdf5-1.10/hdf5-{version}/src/"
if platform.startswith('win'):
    HDF5_18_FILE = HDF5_18_URL + "hdf5-{version}.zip"
    HDF5_110_FILE = HDF5_110_URL + "hdf5-{version}.zip"
else:
    HDF5_18_FILE = HDF5_18_URL + "hdf5-{version}.gzip"
    HDF5_110_FILE = HDF5_110_URL + "hdf5-{version}.tar.gz"


CMAKE_CONFIGURE_CMD = [
    "cmake", "-DBUILD_SHARED_LIBS:BOOL=ON", "-DCMAKE_BUILD_TYPE:STRING=RELEASE",
    "-DHDF5_BUILD_CPP_LIB=OFF", "-DHDF5_BUILD_HL_LIB=ON",
    "-DHDF5_BUILD_TOOLS:BOOL=ON",
]
CMAKE_BUILD_CMD = ["cmake", "--build"]
CMAKE_INSTALL_ARG = ["--target", "install", '--config', 'Release']
CMAKE_INSTALL_PATH_ARG = "-DCMAKE_INSTALL_PREFIX={install_path}"
CMAKE_HDF5_LIBRARY_PREFIX = ["-DHDF5_EXTERNAL_LIB_PREFIX=h5py_"]
REL_PATH_TO_UNPACKED_DIR = "hdf5-{version}"
DEFAULT_VERSION = '1.8.17'
VSVERSION_TO_GENERATOR = {
    "9": "Visual Studio 9 2008",
    "10": "Visual Studio 10 2010",
    "14": "Visual Studio 14 2015",
    "9-64": "Visual Studio 9 2008 Win64",
    "10-64": "Visual Studio 10 2010 Win64",
    "14-64": "Visual Studio 14 2015 Win64",
}


def download_hdf5(version, outfile):
    if version.split(".")[:2] == ["1", "10"]:
        file = HDF5_110_FILE.format(version=version)
    else:
        file = HDF5_18_FILE.format(version=version)

    print("Downloading " + file, file=stderr)
    r = requests.get(file, stream=True)
    try:
        r.raise_for_status()
        copyfileobj(r.raw, outfile)
    except requests.HTTPError:
        print("Failed to download hdf5 version {version}, exiting".format(
            version=version
        ), file=stderr)
        exit(1)


def build_hdf5(
    version, hdf5_file, install_path, cmake_generator, use_prefix, with_mpi
):
    if platform.startswith('win'):
        build_system = "cmake"
    else:
        build_system = "autotools"

    with TemporaryDirectory() as hdf5_extract_path:
        if platform.startswith('win'):
            with ZipFile(hdf5_file) as z:
                z.extractall(hdf5_extract_path)
        else:
            with GzipFile(fileobj=hdf5_file) as z:
                with TarFile(fileobj=z) as t:
                    t.extractall(hdf5_extract_path)

        if build_system == "cmake":
            cfg_cmd, build_cmds = get_cmake_cmds(
                version, install_path, cmake_generator, use_prefix
            )
        elif build_system == "autotools":
            cfg_cmd, build_cmds = get_autotools_cmds(install_path, with_mpi)
        else:
            raise RuntimeError("Unknown build system")

        old_dir = getcwd()
        with TemporaryDirectory() as cmake_work_dir:
            if build_system == "cmake":
                chdir(cmake_work_dir)
            elif build_system == "autotools":
                cwd = Path(get_unpacked_path(version, hdf5_extract_path))
                chdir(cwd)
                p = run(["chmod", "+x", "autogen.sh"])
                p.check_returncode()
                p = run(["./autogen.sh"], cwd=cwd)
                p.check_returncode()
            else:
                raise RuntimeError("Unknown build system")

            print("Configuring HDF5 version {version}...".format(version=version), file=stderr)
            print(' '.join(cfg_cmd), file=stderr)
            p = run(cfg_cmd, stdout=PIPE, stderr=STDOUT, universal_newlines=True)
            print(p.stdout)
            p.check_returncode()
            print("Building HDF5 version {version}...".format(version=version), file=stderr)
            for cmd in build_cmds:
                print(' '.join(cmd), file=stderr)
                p = run(cmd,
                        universal_newlines=True, shell=True)
                p.check_returncode()
                print(p.stdout)
            print("Installed HDF5 version {version} to {install_path}".format(
                version=version, install_path=install_path,
            ), file=stderr)

            chdir(old_dir)

    if platform.startswith('win'):
        print("Copying HDF5 dlls", file=stderr)
        for f in glob(pjoin(install_path, 'bin/*.dll')):
            copy(f, pjoin(install_path, 'lib'))


def get_autotools_cmds(install_path, with_mpi):
    parallel_args = ["--enable-parallel"] if with_mpi else []

    cfg_cmd = ["./configure", "--prefix", install_path] + parallel_args

    build_cmds = (["make"], ["make", "install"])

    return cfg_cmd, build_cmds


def get_cmake_cmds(
    version, install_path, cmake_generator, use_prefix, hdf5_extract_path
):
    generator_args = (
        ["-G", cmake_generator] if cmake_generator is not None else []
    )
    prefix_args = CMAKE_HDF5_LIBRARY_PREFIX if use_prefix else []

    cfg_cmd = CMAKE_CONFIGURE_CMD + [
        get_cmake_install_path(install_path),
        get_unpacked_path(version, hdf5_extract_path),
    ] + generator_args + prefix_args

    build_cmd = CMAKE_BUILD_CMD + ['.'] + CMAKE_INSTALL_ARG

    return cfg_cmd, (build_cmd, )


def get_unpacked_path(version, extract_point):
    return pjoin(extract_point, REL_PATH_TO_UNPACKED_DIR.format(version=version))


def get_cmake_install_path(install_path):
    if install_path is not None:
        return CMAKE_INSTALL_PATH_ARG.format(install_path=install_path)
    return ' '


def hdf5_cached(install_path):
    if exists(pjoin(install_path, "lib", "hdf5.dll")):
        return True
    return False


def main():
    install_path = environ.get("HDF5_DIR")
    version = environ.get("HDF5_VERSION", DEFAULT_VERSION)
    vs_version = environ.get("HDF5_VSVERSION")
    use_prefix = True if environ.get("H5PY_USE_PREFIX") is not None else False
    with_mpi = environ.get('HDF5_MPI') == "ON"

    if install_path is not None:
        if not exists(install_path):
            makedirs(install_path)
    if vs_version is not None:
        cmake_generator = VSVERSION_TO_GENERATOR[vs_version]
        if vs_version == '9-64':
            # Needed for
            # http://help.appveyor.com/discussions/kb/38-visual-studio-2008-64-bit-builds
            run("ci\\appveyor\\vs2008_patch\\setup_x64.bat")
    else:
        cmake_generator = None

    if not hdf5_cached(install_path):
        with TemporaryFile() as f:
            download_hdf5(version, f)
            f.seek(0)
            build_hdf5(version, f, install_path, cmake_generator, use_prefix, with_mpi)
    else:
        print("using cached hdf5", file=stderr)
    if install_path is not None:
        print("hdf5 files: ", file=stderr)
        for dirpath, dirnames, filenames in walk(install_path):
            for file in filenames:
                print(" * " + pjoin(dirpath, file))


if __name__ == '__main__':
    main()
