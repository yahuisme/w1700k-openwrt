#!/bin/sh
# OpenWrt /bin/sh is BusyBox ash; local variables are intentional.
# shellcheck disable=SC3043
set -e

rc=0
STAGE="preflight"
trap '
  rc=$?
  trap - EXIT
  if [ "$rc" -ne 0 ]; then
    printf "[installer] ERROR: stage=%s exit=%s. Stop; preserve the serial log.\n" "$STAGE" "$rc" >&2
    if [ "$STAGE" = "read factory data" ]; then
      printf "[installer] If calibration data is damaged, recovery requires an original backup from this device; calibration cannot be recreated without it.\n" >&2
    fi
  fi
  exit "$rc"
' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
stage() { STAGE="$*"; log "Stage: $STAGE"; }

INSTALLER_DIR="/installer"
RECOVERY_IMAGE="${INSTALLER_DIR}/openwrt-airoha-an7581-gemtek_w1700k-ubi-initramfs-recovery.itb"
SYSUPGRADE_IMAGE="${INSTALLER_DIR}/openwrt-airoha-an7581-gemtek_w1700k-ubi-squashfs-sysupgrade.itb"
FACTORY_BIN="${INSTALLER_DIR}/factory.bin"

# ---- Factory layout offsets ----
FACTORY_BASE_OFF=$((0x00401000))
EEPROM_REL_OFF=$((0x4000))
EEPROM_LEN=$((0x1e00))
EEPROM_ABS_OFF=$((FACTORY_BASE_OFF + EEPROM_REL_OFF))
DSD_OFF=$((0x00400000))
DSD_LEN=$((0x00001000))

# ---- Temp paths ----
FACTORY_TMP="/tmp/factory-build"
EEPROM_DUMP="${FACTORY_TMP}/eeprom.bin"
DSD_BIN="${FACTORY_TMP}/dsd.bin"
DSD_STR="${FACTORY_TMP}/dsd.strings"
FACTORY_BLOB="${FACTORY_TMP}/factory.bin"

log() {
  printf '[installer] %s\n' "$*"
}

die() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

require_file() {
  if [ ! -f "$1" ]; then
    die "Missing required file: $1"
  fi
  [ -s "$1" ] || die "Empty required file: $1"
}

check_mtd() {
  local node="/sys/class/mtd/$1"
  local name size offset

  name="$(cat "$node/name")" || die "Unsupported MTD layout: $1"
  size="$(cat "$node/size")" || die "Unsupported MTD layout: $1"
  offset="$(cat "$node/offset")" || die "Unsupported MTD layout: $1"
  case "$size" in
    ''|*[!0-9]*) die "Unsupported MTD layout: $1";;
  esac
  case "$offset" in
    ''|*[!0-9]*) die "Unsupported MTD layout: $1";;
  esac
  # Sysfs and the expected constants are canonical decimal strings. Numeric
  # tests can overflow in BusyBox and fail open inside this OR condition.
  if [ "$name" != "$2" ] || [ "$size" != "$3" ] || [ "$offset" != "$4" ]; then
    die "Unsupported MTD layout: $1"
  fi
}

validate_layout() {
  # OpenWrt target/linux/airoha/dts/an7581-w1700k-ubi.dts.
  # Validate the running installer DT, not existing UBI volume health.
  tr '\000' '\n' < /proc/device-tree/compatible | grep -qx 'gemtek,w1700k-ubi' || die "Unsupported board"
  check_mtd mtd0 vendor $((0x600000)) 0
  check_mtd mtd1 chainloader $((0x100000)) $((0x600000))
  check_mtd mtd2 ubi $((0x1b700000)) $((0x700000))
  if [ -d /sys/class/ubi/ubi0 ]; then
    [ "$(cat /sys/class/ubi/ubi0/mtd_num)" = 2 ] || die "ubi0 is not attached to mtd2"
  fi
}

prompt_confirm() {
  # A failed ubinfo probe cannot distinguish first install from damaged UBI.
  if ubinfo /dev/ubi0 >/dev/null 2>&1; then
    log "Existing UBI layout detected."
  else
    log "UBI is absent, unattached or unreadable; existing data may remain."
  fi
  printf 'Initialize/reinstall UBI2 on mtd2 and erase its contents? (yes/no)\n'
  read -r answer
  [ "$answer" = "yes" ]
}

ubi_mknod() {
  local dev="$1"
  dev="${dev##*/}"

  # If device node already exists, no need to create it
  [ -e "/dev/$dev" ] && return 0

  [ -e "/sys/class/ubi/$dev/uevent" ] || return 2
  # Runtime UBI uevent files are device-provided and cannot be statically followed.
  # shellcheck disable=SC1090
  . "/sys/class/ubi/$dev/uevent"
  mknod "/dev/$dev" c "$MAJOR" "$MINOR"
}

mac_valid() {
  echo "$1" | grep -Eq '^[0-9A-Fa-f]{2}(:[0-9A-Fa-f]{2}){5}$'
}

mac_to_hex() {
  echo "$1" | tr -d :
}

str_to_hex() {
  # ASCII string to hex (no separators)
  printf '%s' "$1" | hexdump -v -e '1/1 "%02x"'
}

hex_to_bytes() {
  # hex string -> binary bytes
  echo "$1" | sed 's/../\\x&/g'
}

write_hex() {
  local bytes
  # Check conversion separately: printf with a command substitution hides errors.
  bytes="$(hex_to_bytes "$1")" || die "Factory hex conversion failed"
  printf '%b' "$bytes" > "$FACTORY_TMP/field.bin"
  dd if="$FACTORY_TMP/field.bin" of="$FACTORY_BLOB" bs=1 seek="$2" conv=notrunc 2>/dev/null
}

get_dsd_value() {
  key="$1"
  src="$2"
  grep -m1 "^${key}=" "$src" | cut -d= -f2-
}

get_factory_eeprom() {
  local init_off="$1"
  local eeprom_len="$2"
  local magic="$3"
  local eeprom_dump="$4"
  local ebs
  local off
  local found

  [ -d "$FACTORY_TMP" ] || mkdir -p "$FACTORY_TMP"

  ebs="$(cat "/sys/class/mtd/$(basename /dev/mtd0)/erasesize")"
  case "$ebs" in ""|*[!0-9]*) die "Invalid erase size";; esac
  [ "$ebs" -gt 0 ] || die "Invalid erase size"
  [ $((init_off + 3 * ebs + eeprom_len)) -le $((0x600000)) ] || die "EEPROM search exceeds vendor boundary"
  off="$init_off"

  while [ $((off)) -lt $((init_off + 4 * ebs)) ]; do
    magic_read="$(hexdump -v -s "$off" -n 2 -e '1/1 "%02x"' /dev/mtd0)"
    if [ "$magic_read" = "$magic" ]; then
      found=1
      break
    fi
    off=$((off + ebs))
  done

  if [ "$found" != "1" ]; then
    die "factory partition not found on raw flash offset"
  fi

  log "found factory partition at offset $(printf %08x $((off)))"
  dd if=/dev/mtd0 bs=1 skip="$off" count="$eeprom_len" of="$eeprom_dump"
}

get_factory_macs() {
  local dsd_off="$1"
  local dsd_len="$2"

  [ -d "$FACTORY_TMP" ] || mkdir -p "$FACTORY_TMP"

  dd if=/dev/mtd0 of="$DSD_BIN" bs=1 skip="$dsd_off" count="$dsd_len" 2>/dev/null
  [ "$(wc -c < "$DSD_BIN")" -eq "$dsd_len" ] || die "DSD length mismatch"
  strings "$DSD_BIN" > "$DSD_STR"

  WAN_MAC="$(get_dsd_value wan_mac "$DSD_STR")"
  LAN_MAC="$(get_dsd_value lan_mac "$DSD_STR")"
  FAN_ID="$(get_dsd_value fan_id "$DSD_STR")"
  SERIAL_NUMBER="$(get_dsd_value serial_number "$DSD_STR")"
}

build_factory_volume() {
  local eeprom_bin="$1"
  local factory_bin_path="$2"
  local eeprom_size

  log "Rebuild factory volume as UBI"

  # ---- New factory blob layout ----
  FACTORY_SIZE=$((0x10000))
  EEPROM_DST_OFF=$((0x0))
  WAN_MAC_OFF=$((0x5000))
  LAN_MAC_OFF=$((0x6000))
  FAN_ID_OFF=$((0x7000))
  SERIAL_OFF=$((0x8000))

  require_file "$eeprom_bin"

  [ -n "$WAN_MAC" ] || die "wan_mac missing"
  [ -n "$LAN_MAC" ] || die "lan_mac missing"
  [ -n "$FAN_ID" ] || die "fan_id missing"
  [ -n "$SERIAL_NUMBER" ] || die "serial_number missing"

  mac_valid "$WAN_MAC" || die "wan_mac invalid: $WAN_MAC"
  mac_valid "$LAN_MAC" || die "lan_mac invalid: $LAN_MAC"

  log "DSD validation OK:"
  log "  wan_mac       = $WAN_MAC"
  log "  lan_mac       = $LAN_MAC"
  log "  fan_id        = $FAN_ID"
  log "  serial_number = $SERIAL_NUMBER"

  eeprom_size="$(wc -c < "$eeprom_bin")"
  [ "$eeprom_size" -eq "$EEPROM_LEN" ] || die "EEPROM length must be $EEPROM_LEN bytes"
  # MT7996 chip ID 0x7990 is stored little-endian: bytes 90 79.
  [ "$(hexdump -v -n 2 -e '1/1 "%02x"' "$eeprom_bin")" = "9079" ] || die "EEPROM magic mismatch"

  log "Creating empty factory blob (${FACTORY_SIZE} bytes)..."
  dd if=/dev/zero of="$FACTORY_BLOB" bs=1 count="$FACTORY_SIZE" 2>/dev/null

  log "Copying EEPROM (len 0x$(printf %x "$eeprom_size")) -> blob @0x0..."
  dd if="$eeprom_bin" of="$FACTORY_BLOB" bs=1 seek="$EEPROM_DST_OFF" count="$eeprom_size" conv=notrunc 2>/dev/null

  log "Writing WAN/LAN MACs as hex bytes..."
  WAN_HEX="$(mac_to_hex "$WAN_MAC")"
  LAN_HEX="$(mac_to_hex "$LAN_MAC")"
  write_hex "$WAN_HEX" "$WAN_MAC_OFF"
  write_hex "$LAN_HEX" "$LAN_MAC_OFF"

  log "Writing fan_id and serial_number as hex bytes..."
  FAN_HEX="$(str_to_hex "$FAN_ID")"
  SER_HEX="$(str_to_hex "$SERIAL_NUMBER")"
  write_hex "$FAN_HEX" "$FAN_ID_OFF"
  write_hex "$SER_HEX" "$SERIAL_OFF"

  log "Factory volume built at $FACTORY_BLOB ."
  cp "$FACTORY_BLOB" "$factory_bin_path"
}

install_prepare_ubi() {
  mtddev="$1"

  log "Formatting NAND and creating UBI volumes on $mtddev..."
  [ -e /sys/class/ubi/ubi0 ] && ubidetach -p "$mtddev"

  # The installer already obtained explicit consent, including damaged UBI.
  ubiformat "$mtddev" -y
  ubiattach -p "$mtddev"
  sync
  sleep 1

  [ -e /dev/ubi0 ] || ubi_mknod ubi0

  ubimkvol /dev/ubi0 -n 0 -s 126976 -N ubootenv
  ubi_mknod ubi0_0
  ubimkvol /dev/ubi0 -n 1 -s 126976 -N ubootenv2
  ubi_mknod ubi0_1
}

verify_volume() {
  local image="$1" dev="$2" length
  length="$(wc -c < "$image")"
  [ "$length" -gt 0 ] || die "Empty image: $image"
  log "Readback verification: $dev ($length bytes)"
  # Dynamic UBI volumes are LEB-rounded; compare only the written bytes.
  head -c "$length" "$dev" > "$FACTORY_TMP/readback.bin"
  cmp -s "$image" "$FACTORY_TMP/readback.bin" || die "UBI readback mismatch: $dev"
  rm -f "$FACTORY_TMP/readback.bin"
}

install_write_factory() {
  local factory_bin_path="$1"

  ubimkvol /dev/ubi0 -n 2 -t static -s "$(wc -c < "$factory_bin_path")" -N factory
  ubi_mknod ubi0_2
  ubiupdatevol /dev/ubi0_2 "$factory_bin_path"
  verify_volume "$factory_bin_path" /dev/ubi0_2
  sync
  sleep 1
}

install_write_recovery() {
  local recovery_image="$1"

  ubimkvol /dev/ubi0 -n 3 -s "$(wc -c < "$recovery_image")" -N recovery
  ubi_mknod ubi0_3
  ubiupdatevol /dev/ubi0_3 "$recovery_image"
  verify_volume "$recovery_image" /dev/ubi0_3
  sync
  sleep 1
}

install_write_openwrt() {
  ubimkvol /dev/ubi0 -n 4 -s 126976 -N fit
  ubi_mknod ubi0_4

  # Load OpenWrt upgrade helpers only when needed
  . /lib/functions.sh
  . /lib/upgrade/common.sh
  . /lib/upgrade/nand.sh
  . /lib/upgrade/fit.sh

  export CI_KERNPART=fit CI_UBIPART=ubi

  log "Installing sysupgrade image via nand_upgrade_fit..."
  nand_upgrade_fit "$1" cat
  local fit_volume
  fit_volume="$(nand_find_volume ubi0 fit)"
  [ -n "$fit_volume" ] || die "FIT volume missing after upgrade"
  verify_volume "$1" "/dev/$fit_volume"
}

stage "validate layout"
validate_layout
require_file "$RECOVERY_IMAGE"
require_file "$SYSUPGRADE_IMAGE"

if ! prompt_confirm; then
  log "User aborted."
  exit 0
fi

stage "read factory data"
log "Generating factory.bin on device..."
get_factory_eeprom "$EEPROM_ABS_OFF" "$EEPROM_LEN" "9079" "$EEPROM_DUMP"
get_factory_macs "$DSD_OFF" "$DSD_LEN"
build_factory_volume "$EEPROM_DUMP" "$FACTORY_BIN"
require_file "$FACTORY_BIN"

stage "prepare UBI"
install_prepare_ubi /dev/mtd2
stage "write factory"
install_write_factory "$FACTORY_BIN"
stage "write recovery"
install_write_recovery "$RECOVERY_IMAGE"
stage "write fit"
install_write_openwrt "$SYSUPGRADE_IMAGE"

stage "final sync"
log "Sync starting; do not power off."
sync
log "Sync complete; all three images passed readback verification."
sleep 5

log "Install complete. Rebooting..."
stage "reboot"
reboot
sleep 5
die "reboot returned but the system is still running; no automatic retry or reflash"
