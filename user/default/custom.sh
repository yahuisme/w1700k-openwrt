#!/bin/bash

set -e

echo "=============================================="
echo "Running custom commands"

# -------------------------------------------------
# Fetch W1700K LuCI apps from user's packages repo
# -------------------------------------------------
# luci-app-wifi7 / luci-app-airoha-npu /
# luci-app-airoha-flowsense / luci-app-airoha-fancontrol
# are maintained in yahuisme/packages with native LuCI UI,
# built-in 100% i18n, and strict platform safety checks.
PKG_REPO=/tmp/yahuisme-packages
if ! git clone --depth=1 https://github.com/yahuisme/packages.git "$PKG_REPO"; then
    echo "ERROR: Failed to clone user packages repo!"
    exit 1
fi
cp -r "$PKG_REPO/luci-app-wifi7" "$PKG_REPO/luci-app-airoha-npu" \
      "$PKG_REPO/luci-app-airoha-flowsense" \
      "$PKG_REPO/luci-app-airoha-fancontrol" \
      "$PKG_REPO/luci-app-firmwareupgrade" package/

# -------------------------------------------------
# Existing W1700K custom files
# -------------------------------------------------

mkdir -p feeds/luci/modules/luci-mod-status/patches
cp -f "$DK_PROFILE/patches/998-single-wiphy.patch" \
    feeds/luci/modules/luci-mod-status/patches/998-single-wiphy.patch


# -------------------------------------------------
# Install latest Aurora LuCI theme
# -------------------------------------------------

for pkg in luci-theme-aurora luci-app-aurora-config; do
    echo "Installing $pkg..."
    rm -rf "package/$pkg"
    if ! git clone --depth=1 "https://github.com/eamonxg/$pkg.git" "package/$pkg"; then
        echo "ERROR: Failed to download $pkg!"
        exit 1
    fi
    if [ ! -f "package/$pkg/Makefile" ]; then
        echo "ERROR: $pkg was downloaded, but Makefile is missing!"
        exit 1
    fi
    echo "$pkg installed successfully."
done

# 修改 Aurora 菜单式样（默认侧边栏 + 小圆角）
TPL_DIR="package/luci-app-aurora-config/root/usr/share/aurora"
if [ -d "$TPL_DIR" ]; then
    sed -i "s/nav_type '.*'/nav_type 'sidebar'/g; s/struct_radius_base '.*'/struct_radius_base '0.125rem'/g" "$TPL_DIR"/*.template 2>/dev/null || true
    echo "theme-aurora nav preset applied!"
fi


# The temperature & fan overview widget ships as 15_temperature.js inside
# luci-mod-status. Core modules translate via luci-base's "base" domain, so
# append its strings to the upstream base.po for the Chinese UI.
BASE_PO="feeds/luci/modules/luci-base/po/zh_Hans/base.po"
if [ -f "$BASE_PO" ] && [ -f "$DK_PROFILE/po/zh_Hans/base-custom.po" ]; then
    cat "$DK_PROFILE/po/zh_Hans/base-custom.po" >> "$BASE_PO"
fi

echo "Airoha LuCI configuration completed."

# The package index is generated during feeds install, before these
# translation files existed. Drop the cached index so make defconfig
# rescans and registers the new luci-i18n-*-zh-cn packages.
rm -rf tmp/info 2>/dev/null || true
rm -f tmp/.packageinfo 2>/dev/null || true


# -------------------------------------------------
# Wireless regdb power boost (quilt-applied, after fork 555)
# 556 CN 2.4G/5.2G + US 5.2G/5.5G to 30dBm
# -------------------------------------------------
mkdir -p package/firmware/wireless-regdb/patches

if [ -f "$DK_PROFILE/patches/610-w1700k-cn-us-power-30.patch" ]; then
    cp -f "$DK_PROFILE/patches/610-w1700k-cn-us-power-30.patch" package/firmware/wireless-regdb/patches/
    echo "regdb patch: 610-w1700k-cn-us-power-30.patch"
else
    echo "ERROR: regdb patch missing: 610-w1700k-cn-us-power-30.patch" >&2
    exit 1
fi

echo "=============================================="
echo "Custom commands completed"
