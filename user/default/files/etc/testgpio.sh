#!/bin/sh

cd /sys/class/gpio

for i in $(seq 512 575); do
    echo -e "\nGPIO $i"

    if ! echo $i > export; then
        echo "Cannot export"
        continue
    fi

    if ! echo out > gpio$i/direction; then
        echo "Cannot set to output"
        echo $i > unexport
        continue
    fi

    echo 0 > gpio$i/value
    sleep 1
    if iw dev phy0.2-ap0 info >/dev/null; then
        echo "Wifi still responding"
    else
        echo "Wifi down ??"
    fi

    echo 1 > gpio$i/value
    sleep 1
    if iw dev phy0.2-ap0 info >/dev/null; then
        echo "Wifi still responding"
    else
        echo "Wifi down ??"
    fi

    echo $i > unexport
done

