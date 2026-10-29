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

# Required patches share the applications' exact packages checkout.
PATCH_DIR="$PKG_REPO/w1700k-patches"
for file in \
    tree/target/linux/airoha/patches-6.18/745-net-pcs-airoha-extend-manual-rx-calib-to-E2-silicon.patch \
    tree/target/linux/airoha/patches-6.18/746-net-dsa-mt7530-pre-deassert-phy-reset-gpios-before-mdio-scan.patch \
    tree/target/linux/airoha/patches-6.18/940-pmdomain-airoha-cpu-pll-fallback.patch \
    tree/package/kernel/mt76/patches/911-mt76-mt7996-refresh-power-limits-on-txpower-changes.patch \
    tree/package/network/utils/iwinfo/patches/999-fix-txpower-list.patch; do
    [ -s "$PATCH_DIR/$file" ] || { echo "ERROR: Required patch missing: $file" >&2; exit 1; }
done
# Preserve buildroot ownership when copying the patch overlay.
cp -a --no-preserve=ownership "$PATCH_DIR/tree/." .
patch -p1 --fuzz=0 < "$PATCH_DIR/patches/002-w1700k-cpufreq-resources.patch"
# wifi-scripts installs directly from source; its Build/Prepare is empty.
patch -p1 --fuzz=0 < "$PATCH_DIR/patches/920-wifi-non-mlo-ap-txpower.patch"

# -------------------------------------------------
# Existing W1700K custom files
# -------------------------------------------------

mkdir -p feeds/luci/modules/luci-mod-status/patches
cp -f "$PATCH_DIR/patches/998-single-wiphy.patch" \
    feeds/luci/modules/luci-mod-status/patches/998-single-wiphy.patch

# Status LED colors: upgrade green, running white; keep native boot/failsafe.
DTS=target/linux/airoha/dts/an7581-w1700k-ubi.dts
for alias in 'boot red' 'failsafe blue' 'upgrade green' 'running white'; do
    read -r state color <<< "$alias"
    if [ "$state" = upgrade ]; then
        sed -i 's/led-upgrade = &led_status_blue;/led-upgrade = \&led_status_green;/' "$DTS"
    elif [ "$state" = running ]; then
        sed -i 's/led-running = &led_status_green;/led-running = \&led_status_white;/' "$DTS"
    fi
    grep -qF "led-$state = &led_status_$color;" "$DTS" || {
        echo "ERROR: LED alias mismatch: $state" >&2
        exit 1
    }
done
# End status LED colors

# -------------------------------------------------
# Preinstall the author's latest signed Aurora APKs, keys and update source.
# The helper uses this source tree; no Aurora templates are modified.
python3 /cache-scripts/external_packages.py prepare .

# The temperature & fan overview widget ships as 15_temperature.js inside
# luci-mod-status. Core modules translate via luci-base's "base" domain, so
# append its strings to the upstream base.po for the Chinese UI.
BASE_PO="feeds/luci/modules/luci-base/po/zh_Hans/base.po"
if [ -f "$BASE_PO" ] && [ -f "$DK_PROFILE/po/zh_Hans/base-custom.po" ]; then
    cat "$DK_PROFILE/po/zh_Hans/base-custom.po" >> "$BASE_PO"
fi

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
