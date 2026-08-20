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
# Install HomeProxy and sing-box 1.14-compatible packages
# -------------------------------------------------
# ImmortalWrt HomeProxy master still generates legacy inbound fields that
# sing-box 1.13+ rejects. Import the paired, 1.14-compatible packages from
# VIKINGYFY/packages and remove the upstream sing-box recipe to avoid a
# duplicate package definition.

echo "Installing HomeProxy and sing-box 1.14-compatible packages..."

rm -rf \
    package/luci-app-homeproxy \
    package/sing-box \
    feeds/packages/net/sing-box \
    /tmp/viking-packages

if ! git clone \
    --depth=1 \
    --single-branch \
    https://github.com/VIKINGYFY/packages.git \
    /tmp/viking-packages
then
    echo "ERROR: Failed to download VIKINGYFY/packages!"
    exit 1
fi

for package_name in luci-app-homeproxy sing-box; do
    if [ ! -f "/tmp/viking-packages/$package_name/Makefile" ]; then
        echo "ERROR: $package_name is missing from VIKINGYFY/packages!"
        exit 1
    fi

    cp -a "/tmp/viking-packages/$package_name" "package/$package_name"
done

rm -rf /tmp/viking-packages

echo "HomeProxy and sing-box 1.14-compatible packages installed successfully."


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
