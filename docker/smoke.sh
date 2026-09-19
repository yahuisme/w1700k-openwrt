#!/bin/bash
# No firmware, host-tool, toolchain, C or Go compilation is performed.
set -euo pipefail
export GOTOOLCHAIN=local GOENV=off
printf 'OS/architecture\n'
cat /etc/os-release
test "$(dpkg --print-architecture)" = arm64
test ! -e /bld/openwrt
printf 'Required commands\n'
for cmd in bash make gcc g++ ld ar patch diff find xargs cp seq grep getopt realpath stat gzip unzip bzip2 wget install perl python3 file which git rsync curl flock mountpoint tar cpio pkg-config swig bison flex gawk xz zstd msgfmt; do
    command -v "$cmd"
done
gcc -dumpfullversion
g++ -dumpfullversion
make --version
python3 --version
perl -MData::Dumper -MFindBin -MFile::Copy -MFile::Compare -MThread::Queue -MIPC::Cmd -MExtUtils::MakeMaker -e 'print "Perl modules OK\n"'
python3 -c 'import ntpath, ssl, bz2, lzma, sqlite3, ctypes, setuptools; print("Python modules OK")'
pkg-config --modversion openssl zlib libelf ncurses
python3-config --includes
for f in /usr/include/argp.h /usr/include/fts.h /usr/include/obstack.h /usr/include/libintl.h /usr/include/ncurses.h; do test -s "$f"; done
printf 'Go external bootstrap\n'
/usr/lib/go/bin/go version
/usr/lib/go/bin/go env GOROOT GOHOSTARCH GOHOSTOS GOTOOLCHAIN
/usr/lib/go/bin/go tool compile -V
/usr/lib/go/bin/go tool link -V
for d in bin pkg src; do test -d "/usr/lib/go/$d"; done
test "$(/usr/lib/go/bin/go env GOROOT)" = /usr/lib/go
test "$(/usr/lib/go/bin/go env GOVERSION)" = go1.26.8
printf 'Git and cache archive primitives\n'
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
cd "$tmp"
git init -q repo
git -C repo -c user.name=smoke -c user.email=smoke@invalid commit --allow-empty -qm smoke
git -C repo rev-parse --verify HEAD
mkdir input output
printf 'cache smoke\n' > input/payload
tar --format=pax -czf cache.tar.gz -C input .
flock lock tar -xzf cache.tar.gz -C output
cmp input/payload output/payload
getopt -o t --long test -- --test
printf 'SMOKE PASS (no compilation)\n'
