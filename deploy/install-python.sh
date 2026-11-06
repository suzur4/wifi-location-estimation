#!/usr/bin/env bash
# Ubuntu 26.04: install the application interpreter in its own versioned prefix.
# Run as the operator. sudo is used for apt and for publishing the finished build.
set -euo pipefail
umask 022

version=3.13.18
archive=Python-$version.tar.xz
# SHA-256 of the XZ source release at https://www.python.org/downloads/release/python-31318/
sha256=abb0102e6d4ae027509bcb82327d9dd85515b44a3ba8ad538cfc5e9847029f68
parent=/opt/wifi-location-python
prefix=$parent/$version

# shellcheck source=/dev/null
. /etc/os-release
[[ $ID == ubuntu && $VERSION_ID == 26.04 && $EUID != 0 ]] || {
  echo 'Ubuntu 26.04の管理ユーザーから bash deploy/install-python.sh を実行してください。' >&2
  exit 1
}
if [[ -e $prefix || -L $prefix ]]; then
  echo "既存の $prefix を確認してください。使用するPythonはセットアップの --python で指定できます。" >&2
  exit 1
fi

sudo apt-get update -q
sudo apt-get install -y --no-install-recommends build-essential pkg-config ca-certificates curl xz-utils \
  libssl-dev zlib1g-dev libsqlite3-dev libffi-dev libbz2-dev liblzma-dev libreadline-dev libncurses-dev

work=$(mktemp -d)
staging=''
cleanup() {
  rm -rf -- "$work"
  if [[ -n $staging ]]; then sudo rm -rf -- "$staging"; fi
}
trap cleanup EXIT
cd "$work"
curl --fail --show-error --location --retry 2 --proto '=https' --proto-redir '=https' \
  "https://www.python.org/ftp/python/$version/$archive" -o "$archive"
printf '%s  %s\n' "$sha256" "$archive" | sha256sum --check --strict
tar -xf "$archive"
cd "Python-$version"
./configure --prefix="$prefix" --with-ensurepip=install
make -j4
make -j4 altinstall DESTDIR="$work/image"
# Check the modules needed for HTTPS, SQLite, binary wheels and isolated environments.
./python -I -c 'import bz2, ctypes, ensurepip, lzma, sqlite3, ssl, venv, zlib'

# Publish a complete, root-owned tree. A concurrent install must not replace a working runtime.
if [[ ! -e $parent && ! -L $parent ]]; then sudo mkdir -m 0755 -- "$parent"; fi
[[ -d $parent && ! -L $parent && $(stat -c %u "$parent") == 0 &&
   -z $(find "$parent" -maxdepth 0 -perm /022 -print) ]] || {
  echo "$parent の所有者と権限を確認してください（root管理・一般ユーザー書込不可）。" >&2
  exit 1
}
staging=$(sudo mktemp -d "$parent/.install-XXXXXXXX")
sudo cp -a --no-preserve=ownership -- "$work/image$prefix/." "$staging/"
sudo chmod -R go-w "$staging"
sudo chmod 0755 "$staging"
sudo mv -Tn -- "$staging" "$prefix"
[[ ! -e $staging ]] || { echo "既に $prefix があるため配置を中止しました。" >&2; exit 1; }
staging=''
"$prefix/bin/python3.13" -I -c 'import sqlite3, ssl, sys, venv; assert sys.version_info[:3] == (3, 13, 18); print(sys.executable, sys.version)'
