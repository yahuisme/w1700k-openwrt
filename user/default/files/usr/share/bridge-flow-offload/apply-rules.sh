#!/bin/sh
# Bridge flow offloading rule generator
# Called by the firewall4 script include and LAN hotplug.
# Apply directly: never reload firewall4 from inside its include.

BRIDGE="${1:-br-lan}"
RULES_DIR="/usr/share/nftables.d/ruleset-post"
RULES_FILE="${RULES_DIR}/30-bridge-offload.nft"
FLOWTABLE="br_offload"

detect_bridge_ports() {
    local brif_dir="/sys/class/net/${BRIDGE}/brif"
    [ -d "$brif_dir" ] || return 1
    local ports=""
    for port_dir in "$brif_dir"/*; do
        [ -d "$port_dir" ] || continue
        ports="${ports:+${ports}, }$(basename "$port_dir")"
    done
    [ -n "$ports" ] && echo "$ports"
}

main() {
    # Remove the persistent include left by older firmware.
    rm -f "$RULES_FILE"

    # Only use the NPU/hardware path when fw4 hardware offload is enabled.
    if [ "$(uci -q get firewall.@defaults[0].flow_offloading_hw)" != "1" ]; then
        nft delete table bridge fw4 >/dev/null 2>&1
        logger -t bridge-flow-offload "flow_offloading_hw not set, hardware offload disabled"
        return 0
    fi

    local devices
    devices=$(detect_bridge_ports)
    if [ -z "$devices" ]; then
        logger -t bridge-flow-offload "No bridge ports found for ${BRIDGE}, skipping"
        return 1
    fi

    nft -f - <<EOF
destroy table bridge fw4

table bridge fw4 {
    flowtable ${FLOWTABLE} {
        hook ingress priority 0; devices = { ${devices} }; flags offload;
    }

    chain forward {
        type filter hook forward priority 0; policy accept;
        meta l4proto { tcp, udp } flow offload @${FLOWTABLE}
    }
}
EOF

}

main
