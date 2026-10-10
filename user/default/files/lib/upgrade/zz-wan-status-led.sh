# Stage2 calls this before killing processes; leave the native upgrade alias.
indicate_upgrade() {
    if [ "$(cat /tmp/sysinfo/board_name 2>/dev/null)" = gemtek,w1700k-ubi ]; then
        touch /tmp/wan-status-led-upgrade
        echo 0 > /sys/class/leds/red:status/brightness
    fi
    . /etc/diag.sh
    set_state upgrade
}
