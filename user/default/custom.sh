#!/bin/bash

set -e

echo "=============================================="
echo "Running custom commands"

# -------------------------------------------------
# Existing W1700K custom files
# -------------------------------------------------

mv files/overview.js \
    feeds/luci/applications/luci-app-attendedsysupgrade/htdocs/luci-static/resources/view/attendedsysupgrade/overview.js

mkdir -p feeds/luci/modules/luci-mod-status/patches

mv files/998-single-wiphy.patch \
    feeds/luci/modules/luci-mod-status/patches/998-single-wiphy.patch

if [ -d package/luci-app-wifi7 ] && [ -f files/998-wifi7-i18n.patch ]; then
    patch -d package/luci-app-wifi7 -p1 --ignore-whitespace < files/998-wifi7-i18n.patch
fi

if [ -d package/luci-app-w1700k-fancontrol ] && [ -f files/998-fancontrol-i18n.patch ]; then
    patch -d package/luci-app-w1700k-fancontrol -p1 --ignore-whitespace < files/998-fancontrol-i18n.patch
fi

if [ -d package/luci-app-airoha-npu ] && [ -f files/998-npu-i18n.patch ]; then
    patch -d package/luci-app-airoha-npu -p1 --ignore-whitespace < files/998-npu-i18n.patch
fi

if [ -d package/luci-app-airoha-flowsense ] && [ -f files/998-flowsense-i18n.patch ]; then
    patch -d package/luci-app-airoha-flowsense -p1 --ignore-whitespace < files/998-flowsense-i18n.patch
fi

if [ -d feeds/luci/applications/luci-app-irqbalance ] && [ -f files/998-irqbalance-i18n.patch ]; then
    patch -d feeds/luci/applications/luci-app-irqbalance -p1 --ignore-whitespace < files/998-irqbalance-i18n.patch
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
if find "package/luci-app-aurora-config/root/usr/share/aurora/" -type f -name '*.template' -exec \
    sed -i "s/nav_type '.*'/nav_type 'sidebar'/g; s/struct_radius_base '.*'/struct_radius_base '0.125rem'/g" {} +; then
    echo "theme-aurora nav preset applied!"
else
    echo "theme-aurora nav preset failed; continuing!"
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
    translation="files/po/zh_Hans/${package_name}.po"

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

# luci-app-irqbalance is a standard feed package (feeds/luci). Its upstream
# translation domain is "irqbalance" (the LUCI_BASENAME), so the PO must be
# named "irqbalance.po" rather than "luci-app-irqbalance.po".
if [ -d feeds/luci/applications/luci-app-irqbalance ]; then
    mkdir -p feeds/luci/applications/luci-app-irqbalance/po/zh_Hans
    cp -f files/po/zh_Hans/irqbalance.po \
        feeds/luci/applications/luci-app-irqbalance/po/zh_Hans/irqbalance.po
fi

# The upstream menu titles omit the vendor prefix. Keep the user-facing
# application names explicit without changing application behavior.
if [ -f package/luci-app-airoha-npu/root/usr/share/luci/menu.d/luci-app-airoha-npu.json ]; then
    sed -i 's/"title": "SoC Status"/"title": "Airoha SoC 状态"/' \
        package/luci-app-airoha-npu/root/usr/share/luci/menu.d/luci-app-airoha-npu.json
fi
if [ -d package/luci-app-airoha-flowsense ]; then
    find package/luci-app-airoha-flowsense -type f \( -name '*.json' -o -name '*.js' \) -exec \
        sed -i -e 's/"title": "FlowSense"/"title": "Airoha 流量传感器"/g' \
               -e 's/"title": "Airoha FlowSense"/"title": "Airoha 流量传感器"/g' {} +
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


# -------------------------------------------------
# Clean LuCI temporary files
# -------------------------------------------------

rm -rf /tmp/luci-*


echo "=============================================="
echo "Custom commands completed"
