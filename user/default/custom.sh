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


# -------------------------------------------------
# Install Momo and its compatible sing-box core
# -------------------------------------------------
# Momo is shipped disabled by default. Import only its two application
# packages plus the paired sing-box recipe needed by Momo's >= 1.12 core
# requirement; remove any pre-existing sing-box recipe to avoid duplicates.

echo "Installing Momo and compatible sing-box packages..."

rm -rf \
    package/momo \
    package/luci-app-momo \
    package/sing-box \
    feeds/packages/net/sing-box \
    /tmp/openwrt-momo \
    /tmp/viking-packages

if ! git clone \
    --depth=1 \
    --single-branch \
    https://github.com/nikkinikki-org/OpenWrt-momo.git \
    /tmp/openwrt-momo
then
    echo "ERROR: Failed to download OpenWrt-momo!"
    exit 1
fi

for package_name in momo luci-app-momo; do
    if [ ! -f "/tmp/openwrt-momo/$package_name/Makefile" ]; then
        echo "ERROR: $package_name is missing from OpenWrt-momo!"
        exit 1
    fi

    cp -a "/tmp/openwrt-momo/$package_name" "package/$package_name"
done

if ! git clone \
    --depth=1 \
    --single-branch \
    https://github.com/VIKINGYFY/packages.git \
    /tmp/viking-packages
then
    echo "ERROR: Failed to download VIKINGYFY/packages!"
    exit 1
fi

if [ ! -f /tmp/viking-packages/sing-box/Makefile ]; then
    echo "ERROR: sing-box is missing from VIKINGYFY/packages!"
    exit 1
fi

cp -a /tmp/viking-packages/sing-box package/sing-box
rm -rf /tmp/openwrt-momo /tmp/viking-packages

echo "Momo and compatible sing-box packages installed successfully."


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
