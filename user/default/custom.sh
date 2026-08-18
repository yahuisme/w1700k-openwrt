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
# Install Aurora LuCI theme
# -------------------------------------------------

echo "Installing Aurora LuCI theme..."

rm -rf package/luci-theme-aurora

git clone \
    --depth=1 \
    --branch v1.2.0 \
    https://github.com/eamonxg/luci-theme-aurora.git \
    package/luci-theme-aurora


# -------------------------------------------------
# Enable packages
# -------------------------------------------------

echo "Enabling Chinese language..."

grep -qxF 'CONFIG_PACKAGE_luci-i18n-base-zh-cn=y' .config || \
    echo 'CONFIG_PACKAGE_luci-i18n-base-zh-cn=y' >> .config

echo "Enabling Aurora theme..."

grep -qxF 'CONFIG_PACKAGE_luci-theme-aurora=y' .config || \
    echo 'CONFIG_PACKAGE_luci-theme-aurora=y' >> .config


# -------------------------------------------------
# Clean LuCI temporary files
# -------------------------------------------------

rm -rf /tmp/luci-*


echo "=============================================="
echo "Custom commands completed"
