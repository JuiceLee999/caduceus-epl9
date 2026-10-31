#!/usr/bin/env bash
# Build GNU binutils 2.45 for mn10300-elf (assembler/linker/objdump for the camera CPU).
# Installs only under $PREFIX (default ~/ep7fw-toolchains). Verifies the GNU signature.
set -euo pipefail
PREFIX=${PREFIX:-$HOME/ep7fw-toolchains}
V=2.45
mkdir -p "$PREFIX/src" && cd "$PREFIX/src"
[ -f binutils-$V.tar.xz ] || curl -fsSLO https://ftp.gnu.org/gnu/binutils/binutils-$V.tar.xz
[ -f binutils-$V.tar.xz.sig ] || curl -fsSLO https://ftp.gnu.org/gnu/binutils/binutils-$V.tar.xz.sig
[ -f gnu-keyring.gpg ] || curl -fsSLO https://ftp.gnu.org/gnu/gnu-keyring.gpg
gpgv --keyring ./gnu-keyring.gpg binutils-$V.tar.xz.sig binutils-$V.tar.xz
[ -d binutils-$V ] || tar xf binutils-$V.tar.xz
rm -rf build-mn10300 && mkdir build-mn10300 && cd build-mn10300
../binutils-$V/configure --prefix="$PREFIX/mn10300" --target=mn10300-elf \
  --disable-nls --disable-werror --disable-gdb --disable-sim --disable-gprof \
  --disable-gold --disable-libctf --with-system-zlib --disable-shared >/dev/null
make -j"$(nproc)" all-gas all-ld all-binutils MAKEINFO=true >/dev/null
make install-gas install-ld install-binutils MAKEINFO=true >/dev/null
"$PREFIX/mn10300/bin/mn10300-elf-as" --version | head -1
echo "Add to PATH: $PREFIX/mn10300/bin"
