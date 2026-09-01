#!/bin/bash

set -e

echo "=============================================="
echo "Running custom commands"

# -------------------------------------------------
# Existing W1700K custom files
# -------------------------------------------------

cp -f $DK_PROFILE/overview.js \
    feeds/luci/applications/luci-app-attendedsysupgrade/htdocs/luci-static/resources/view/attendedsysupgrade/overview.js

mkdir -p feeds/luci/modules/luci-mod-status/patches

cp -f $DK_PROFILE/patches/998-single-wiphy.patch \
    feeds/luci/modules/luci-mod-status/patches/998-single-wiphy.patch

if [ -d package/luci-app-wifi7 ] && [ -f $DK_PROFILE/patches/998-wifi7-i18n.patch ]; then
    patch -d package/luci-app-wifi7 -p1 --ignore-whitespace < $DK_PROFILE/patches/998-wifi7-i18n.patch
fi

if [ -d package/luci-app-w1700k-fancontrol ] && [ -f $DK_PROFILE/patches/998-fancontrol-i18n.patch ]; then
    patch -d package/luci-app-w1700k-fancontrol -p1 --ignore-whitespace < $DK_PROFILE/patches/998-fancontrol-i18n.patch
fi

if [ -d package/luci-app-airoha-npu ] && [ -f $DK_PROFILE/patches/998-npu-i18n.patch ]; then
    patch -d package/luci-app-airoha-npu -p1 --ignore-whitespace < $DK_PROFILE/patches/998-npu-i18n.patch
fi

if [ -d package/luci-app-airoha-flowsense ] && [ -f $DK_PROFILE/patches/998-flowsense-i18n.patch ]; then
    patch -d package/luci-app-airoha-flowsense -p1 --ignore-whitespace < $DK_PROFILE/patches/998-flowsense-i18n.patch
fi


# -------------------------------------------------
# Install latest Aurora LuCI theme
# -------------------------------------------------

echo "Installing latest Aurora LuCI theme..."

rm -rf package/luci-theme-aurora

if ! git clone \
    --depth=1 \
    https://github.com/eamonxg/luci-theme-aurora.git \
    package/luci-theme-aurora
then
    echo "ERROR: Failed to download Aurora theme!"
    exit 1
fi

if [ ! -f package/luci-theme-aurora/Makefile ]; then
    echo "ERROR: Aurora theme was downloaded, but Makefile is missing!"
    exit 1
fi

echo "Aurora theme installed successfully."


# -------------------------------------------------
# Install Aurora theme configuration app
# -------------------------------------------------

echo "Installing Aurora theme configuration app..."

rm -rf package/luci-app-aurora-config

if ! git clone \
    --depth=1 \
    https://github.com/eamonxg/luci-app-aurora-config.git \
    package/luci-app-aurora-config
then
    echo "ERROR: Failed to download Aurora theme configuration app!"
    exit 1
fi

if [ ! -f package/luci-app-aurora-config/Makefile ]; then
    echo "ERROR: Aurora theme configuration app was downloaded, but Makefile is missing!"
    exit 1
fi

echo "Aurora theme configuration app installed successfully."

# 修改 Aurora 菜单式样（默认侧边栏 + 小圆角）
TPL_DIR="package/luci-app-aurora-config/root/usr/share/aurora/"
if ls "$TPL_DIR"/*.template >/dev/null 2>&1; then
    sed -i "s/nav_type '.*'/nav_type 'sidebar'/g; s/struct_radius_base '.*'/struct_radius_base '0.125rem'/g" "$TPL_DIR"/*.template
    if grep -q "nav_type 'sidebar'" "$TPL_DIR"/*.template; then
        echo "theme-aurora nav preset applied!"
    else
        echo "theme-aurora nav preset failed; continuing!"
    fi
else
    echo "theme-aurora nav preset skipped (no templates); continuing!"
fi


# -------------------------------------------------
# Add Chinese translations for Airoha LuCI apps
# -------------------------------------------------

echo "Installing Chinese translations for Airoha LuCI apps..."

translation_targets=(
    "luci-app-airoha-flowsense|package/luci-app-airoha-flowsense"
    "luci-app-airoha-npu|package/luci-app-airoha-npu"
    "luci-app-w1700k-fancontrol|package/luci-app-w1700k-fancontrol"
    "luci-app-wifi7|package/luci-app-wifi7"
)

for translation_target in "${translation_targets[@]}"; do
    package_name="${translation_target%%|*}"
    target="${translation_target#*|}"
    translation="$DK_PROFILE/po/zh_Hans/${package_name}.po"

    if [ ! -d "$target" ]; then
        echo "ERROR: Translation target package is missing: $target"
        exit 1
    fi
    if [ ! -f "$translation" ]; then
        echo "ERROR: Translation file is missing: $translation"
        exit 1
    fi

    mkdir -p "$target/po/zh_Hans"
    cp -f "$translation" "$target/po/zh_Hans/${package_name}.po"
done

# luci-app-irqbalance ships its own complete zh_Hans translation in the
# OpenWrt luci feed (rewritten upstream UI), so no PO is copied from
# po/zh_Hans. The feed PO leaves the menu title "irqbalance" untranslated,
# so fix the msgstr in place for the Services menu.
IRQ_PO="feeds/luci/applications/luci-app-irqbalance/po/zh_Hans/irqbalance.po"
if [ -f "$IRQ_PO" ]; then
    sed -i '/^msgid "irqbalance"$/{n;s/^msgstr "irqbalance"$/msgstr "IRQ 平衡"/}' "$IRQ_PO"
    if grep -q 'msgstr "IRQ 平衡"' "$IRQ_PO"; then
        echo "irqbalance menu title localized (IRQ 平衡)"
    else
        echo "WARN: irqbalance zh_Hans msgid not found; skip"
    fi
else
    echo "WARN: irqbalance zh_Hans PO not found; skip"
fi

# The temperature & fan overview widget ships as 15_temperature.js inside
# luci-mod-status. Core modules translate via luci-base's "base" domain, so
# append its strings to the upstream base.po for the Chinese UI.
BASE_PO="feeds/luci/modules/luci-base/po/zh_Hans/base.po"
if [ -f "$BASE_PO" ] && [ -f $DK_PROFILE/po/zh_Hans/base-custom.po ]; then
    cat $DK_PROFILE/po/zh_Hans/base-custom.po >> "$BASE_PO"
fi

# The upstream menu titles omit the vendor prefix. Keep the user-facing
# application names explicit without changing application behavior.
if [ -f package/luci-app-airoha-npu/root/usr/share/luci/menu.d/luci-app-airoha-npu.json ]; then
    sed -i 's/"title": "SoC Status"/"title": "Airoha SoC 状态"/' \
        package/luci-app-airoha-npu/root/usr/share/luci/menu.d/luci-app-airoha-npu.json
fi
if [ -d package/luci-app-airoha-flowsense ]; then
    find package/luci-app-airoha-flowsense -type f \( -name '*.json' -o -name '*.js' \) -exec \
        sed -i -e 's/"title": "FlowSense"/"title": "Airoha 流量感知"/g' \
               -e 's/"title": "Airoha FlowSense"/"title": "Airoha 流量感知"/g' {} +
fi

# Move Airoha Fan Control from the System menu into the Status menu, between
# Airoha SoC Status (npu) and Airoha FlowSense. The dispatcher types menu
# order as int, so use consecutive integers: npu 15, fan 16, flowsense 17.
if [ -f package/luci-app-w1700k-fancontrol/root/usr/share/luci/menu.d/luci-app-w1700k-fancontrol.json ]; then
    sed -i -e 's#admin/system/fan#admin/status/fan#g' \
           -e 's#"order": 90#"order": 16#' \
        package/luci-app-w1700k-fancontrol/root/usr/share/luci/menu.d/luci-app-w1700k-fancontrol.json
fi
if [ -f package/luci-app-airoha-flowsense/root/usr/share/luci/menu.d/luci-app-airoha-flowsense.json ]; then
    sed -i 's#"order": 16#"order": 17#' \
        package/luci-app-airoha-flowsense/root/usr/share/luci/menu.d/luci-app-airoha-flowsense.json
fi

echo "Airoha LuCI translations installed successfully."

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
fi


# -------------------------------------------------
# Enable Chinese language
# -------------------------------------------------

echo "Enabling Chinese language..."

grep -qxF 'CONFIG_LUCI_LANG_zh_Hans=y' .config || \
    echo 'CONFIG_LUCI_LANG_zh_Hans=y' >> .config


# -------------------------------------------------
# Enable Aurora
# -------------------------------------------------

echo "Enabling Aurora theme..."

grep -qxF 'CONFIG_PACKAGE_luci-theme-aurora=y' .config || \
    echo 'CONFIG_PACKAGE_luci-theme-aurora=y' >> .config

grep -qxF 'CONFIG_PACKAGE_luci-app-aurora-config=y' .config || \
    echo 'CONFIG_PACKAGE_luci-app-aurora-config=y' >> .config


echo "=============================================="
echo "Custom commands completed"
