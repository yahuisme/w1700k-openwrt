#!/bin/bash

set -e

echo "=============================================="
echo "Running custom commands"

# Keep the official OpenWrt version templates and machine version fields.

# -------------------------------------------------
# Keep native reset/upgrade reconnect defaults aligned with 99-w1700k-defaults.
FLASH_JS="feeds/luci/modules/luci-mod-system/htdocs/luci-static/resources/view/system/flash.js"
if [ ! -f "$FLASH_JS" ]; then
    echo "ERROR: LuCI flash.js not found" >&2
    exit 1
fi
FLASH_OLD=$(grep -oF "'192.168.1.1'" "$FLASH_JS" | wc -l)
FLASH_NEW=$(grep -oF "'192.168.8.1'" "$FLASH_JS" | wc -l)
if [ "$FLASH_OLD:$FLASH_NEW" != "3:0" ] && [ "$FLASH_OLD:$FLASH_NEW" != "0:3" ]; then
    echo "ERROR: LuCI reconnect defaults changed; review flash.js" >&2
    exit 1
fi
sed -i "s/'192\.168\.1\.1'/'192.168.8.1'/g" "$FLASH_JS"
[ "$(grep -oF "'192.168.8.1'" "$FLASH_JS" | wc -l)" -eq 3 ] || exit 1

# -------------------------------------------------
# Fetch W1700K LuCI apps from user's packages repo
# -------------------------------------------------
# luci-app-wifi7 / luci-app-airoha-npu /
# luci-app-airoha-flowsense / luci-app-airoha-fancontrol
# are maintained in yahuisme/packages with native LuCI UI,
# built-in 100% i18n, and strict platform safety checks.
PKG_REPO=$(mktemp -d)
trap 'rm -rf "$PKG_REPO"' EXIT

if ! git clone --depth=1 https://github.com/yahuisme/packages.git "$PKG_REPO"; then
    echo "ERROR: Failed to clone user packages repo!"
    exit 1
fi
PKG_SHA=$(git -C "$PKG_REPO" rev-parse HEAD)
printf 'yahuisme/packages\t%s\t%s\n' "$(git -C "$PKG_REPO" remote get-url origin)" "$PKG_SHA" > .custom-revisions.tsv
echo "yahuisme/packages: $PKG_SHA"
cp -r "$PKG_REPO/luci-app-wifi7" "$PKG_REPO/luci-app-airoha-npu" \
      "$PKG_REPO/luci-app-airoha-flowsense" \
      "$PKG_REPO/luci-app-airoha-fancontrol" package/

# Required patches are versioned with the firmware workflow.
PATCH_DIR="$DK_USER/w1700k-patches"
for file in \
    patches/002-w1700k-cpufreq-resources.patch \
    patches/920-wifi-non-mlo-ap-txpower.patch \
    patches/610-w1700k-power-30.patch \
    patches/998-single-wiphy.patch \
    patches/110-run-libuv-loop.patch \
    tree/target/linux/airoha/patches-6.18/745-net-pcs-airoha-extend-manual-rx-calib-to-E2-silicon.patch \
    tree/target/linux/airoha/patches-6.18/746-net-dsa-mt7530-pre-deassert-phy-reset-gpios-before-mdio-scan.patch \
    tree/target/linux/airoha/patches-6.18/940-pmdomain-airoha-cpu-pll-fallback.patch \
    tree/package/kernel/mt76/patches/911-mt76-mt7996-refresh-power-limits-on-txpower-changes.patch \
    tree/package/kernel/mt76/patches/913-mt76-mt7996-clean-up-truncated-txfree.patch \
    tree/package/kernel/mt76/patches/914-mt76-mt7996-free-rro-drop-buffers.patch \
    tree/package/network/utils/iwinfo/patches/998-fix-multi-radio-scan.patch \
    tree/package/network/utils/iwinfo/patches/999-fix-txpower-list.patch \
    tree/package/system/procd/patches/001-watchdog-reconcile-timeout.patch; do
    [ -s "$PATCH_DIR/$file" ] || { echo "ERROR: Required patch missing or empty: $file" >&2; exit 1; }
done
# Backport the reviewed ttyd event loop fix.
TTYD_RECIPE=feeds/packages/utils/ttyd
TTYD_PATCH=110-run-libuv-loop.patch
TTYD_TARGET="$TTYD_RECIPE/patches/$TTYD_PATCH"
if ! grep -Fxq 'PKG_VERSION:=1.7.7' "$TTYD_RECIPE/Makefile" ||
   ! grep -Fxq 'PKG_HASH:=039dd995229377caee919898b7bd54484accec3bba49c118e2d5cd6ec51e3650' "$TTYD_RECIPE/Makefile"; then
    echo 'ERROR: unreviewed ttyd source; check libwebsockets compatibility' >&2
    exit 1
fi
if [ -L "$TTYD_TARGET" ] || { [ -e "$TTYD_TARGET" ] && ! cmp -s "$PATCH_DIR/patches/$TTYD_PATCH" "$TTYD_TARGET"; }; then
    echo 'ERROR: conflicting ttyd compatibility patch in package feed' >&2
    exit 1
fi
# APK requires integer revisions. Do not stack on a changed upstream release.
case "$(grep -E '^[[:space:]]*PKG_RELEASE[[:space:]]*[:+?]?=' "$TTYD_RECIPE/Makefile" || true)" in
    PKG_RELEASE:=1)
        [ -e "$TTYD_TARGET" ] || install -D -m 644 "$PATCH_DIR/patches/$TTYD_PATCH" "$TTYD_TARGET"
        sed -i 's/^PKG_RELEASE:=1$/PKG_RELEASE:=2/' "$TTYD_RECIPE/Makefile"
        ;;
    PKG_RELEASE:=2)
        [ -f "$TTYD_TARGET" ] || { echo 'ERROR: unreviewed ttyd package release' >&2; exit 1; }
        ;;
    *) echo 'ERROR: unreviewed ttyd package release' >&2; exit 1 ;;
esac
# Preserve buildroot ownership when copying the patch overlay.
cp -a --no-preserve=ownership "$PATCH_DIR/tree/." .
patch -p1 --fuzz=0 --no-backup-if-mismatch < "$PATCH_DIR/patches/002-w1700k-cpufreq-resources.patch"
# wifi-scripts installs directly from source; its Build/Prepare is empty.
patch -p1 --fuzz=0 --no-backup-if-mismatch < "$PATCH_DIR/patches/920-wifi-non-mlo-ap-txpower.patch"

# -------------------------------------------------
# Existing W1700K custom files
# -------------------------------------------------

mkdir -p feeds/luci/modules/luci-mod-status/patches
cp -f "$PATCH_DIR/patches/998-single-wiphy.patch" \
    feeds/luci/modules/luci-mod-status/patches/998-single-wiphy.patch

# Status LED colors: upgrade green, running white; keep native boot/failsafe.
DTS=target/linux/airoha/dts/an7581-w1700k-ubi.dts
LED_SOURCE=$DTS
if grep -Fxq '#include "an7581-gemtek-common.dtsi"' "$DTS"; then
    LED_SOURCE=${DTS%/*}/an7581-gemtek-common.dtsi
fi
[ -f "$LED_SOURCE" ] || { echo "ERROR: LED alias source missing: $LED_SOURCE" >&2; exit 1; }
for alias in 'boot red red' 'failsafe blue blue' 'upgrade blue green' 'running green white'; do
    read -r state native preset <<< "$alias"
    property="^[[:space:]]*led-${state}[[:space:]]*="
    colors=$native
    [ "$LED_SOURCE" != "$DTS" ] || colors="$native|$preset"
    if [ "$(grep -Ec "$property" "$LED_SOURCE")" -ne 1 ] ||
       ! grep -Eq "${property}[[:space:]]*&led_status_($colors);[[:space:]]*$" "$LED_SOURCE"; then
        echo "ERROR: LED alias mismatch: $state" >&2
        exit 1
    fi
done
if [ "$LED_SOURCE" = "$DTS" ]; then
    sed -Ei 's/^([[:space:]]*led-upgrade[[:space:]]*=[[:space:]]*&led_status_)blue;/\1green;/;
             s/^([[:space:]]*led-running[[:space:]]*=[[:space:]]*&led_status_)green;/\1white;/' "$DTS"
else
    # The common DTSI also serves other boards. Override only on W1700K.
    # Match property names regardless of line breaks or inline overrides.
    properties='led-(boot|failsafe|upgrade|running)'
    local_aliases=$(grep -Eow "$properties" "$DTS" || [ "$?" -eq 1 ])
    override=$'\n&{/aliases} {\n\tled-upgrade = &led_status_green;\n\tled-running = &led_status_white;\n};'
    if [ -z "$local_aliases" ]; then
        printf '%s\n' "$override" >> "$DTS"
    elif [ "$(tail -n 5 "$DTS")" != "$override" ] ||
         [ "$local_aliases" != "$(grep -Eow "$properties" <<< "$override")" ]; then
        echo 'ERROR: LED alias mismatch: W1700K override' >&2
        exit 1
    fi
fi
# End status LED colors

# -------------------------------------------------
# Preinstall the author's latest signed Aurora APKs, keys and update source.
# The helper uses this source tree; no Aurora templates are modified.
python3 /cache-scripts/external_packages.py prepare .

# The temperature & fan overview widget ships as 15_temperature.js inside
# luci-mod-status. Core modules translate via luci-base's "base" domain, so
# append its strings to the upstream base.po for the Chinese UI.
BASE_PO="feeds/luci/modules/luci-base/po/zh_Hans/base.po"
CUSTOM_PO="$DK_PROFILE/po/zh_Hans/base-custom.po"
for PO in "$BASE_PO" "$CUSTOM_PO"; do
    [ -f "$PO" ] || { echo "ERROR: Required Chinese dictionary missing: $PO" >&2; exit 1; }
done
# gettext is already a builder dependency. Parse both inputs, prefer project
# translations on duplicate msgids, then replace only a validated merged PO.
PO_WORK=$(mktemp -d)
MERGED_PO="$PO_WORK/merged.po"
# Reuse the exact upstream header metadata for the headerless project fragment.
msggrep --force-po --msgid -e '^$' "$BASE_PO" -o "$PO_WORK/custom.po"
printf '\n' >> "$PO_WORK/custom.po"
cat "$CUSTOM_PO" >> "$PO_WORK/custom.po"
if ! { msgfmt -o /dev/null "$BASE_PO" && msgfmt -o /dev/null "$PO_WORK/custom.po" &&
       msgcat --use-first --no-wrap "$PO_WORK/custom.po" "$BASE_PO" -o "$MERGED_PO" &&
       msgfmt -o /dev/null "$MERGED_PO"; }; then
    rm -rf "$PO_WORK"
    echo "ERROR: Chinese dictionary validation/merge failed" >&2
    exit 1
fi
chmod --reference="$BASE_PO" "$MERGED_PO"
mv "$MERGED_PO" "$BASE_PO"
rm -rf "$PO_WORK"

echo "Airoha LuCI configuration completed."

# Refresh the feeds-install index so make defconfig discovers the
# newly imported applications and themes.
rm -rf tmp/info 2>/dev/null || true
rm -f tmp/.packageinfo 2>/dev/null || true


# -------------------------------------------------
# Shared regdb customization follows the official 500 patch.
# -------------------------------------------------
mkdir -p package/firmware/wireless-regdb/patches

cp -f "$PATCH_DIR/patches/610-w1700k-power-30.patch" package/firmware/wireless-regdb/patches/
echo "regdb patch: 610-w1700k-power-30.patch"

echo "=============================================="
echo "Custom commands completed"
