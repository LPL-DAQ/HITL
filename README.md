## Instructions for setting up HITL Testbed

# Install Packages on Raspberry Pi
('sudo' for MacOS installation bypass)

```bash

sudo apt update -y && sudo apt upgrade -y

sudo raspi-config nonint do_i2c 0   # enable i2c

sudo apt install -y python3-pip python3-venv i2c-tools protobuf-compiler

pip3 install --break-system-packages smbus2 protobuf rich

protoc --python_out=. clover.proto     # run inside of the folder containing clover.proto

```


# Wiring

1. Jumper wires connecting 3.3V, GND, GPIO2 (SDA), GPIO3 (SLC) from rpi to breadboard
2. Wire both DACs VCC, GND, SDA, and SCL pins on breadboard
3. XLR connector pins:
    * Pin 1 -> GND (top row)
    * Pin 2 -> DAC output
        - XLR 1 -> DAC 1 Pin 0
        - XLR 2 -> DAC 1 Pin 1
        - XLR 3 -> DAC 2 Pin 0
        - XLR 4 -> DAC 2 Pin 
    * Pin 3 -> GND (top row)

We can also only use 1 DAC for just 4 sensor inputs


# SSH
How to SSH into RPi5 on Windows

power rpi5 with usb-c
connect ethernet to your laptop 
go to Network Connections in control panel
ethernet -> properties -> sharing -> allow other network users
open powershell

Before continueing, ensure the rpi has been on ~60 seconds

Get-NetNeighbor -AddressFamily IPv4 | Where-Object {$_.IPAddress -like "192.168.137.*"} | Format-Table IPAddress,LinkLayerAddress,State
copy the IP (for me it was 192.168.137.22)
ssh <hostname>@192.168.137.<final IP number>
host name is currently "hitl"
enter the password, currently LPLhitl


Trouble shooting:

Are you connected to USC Secure Wireless?
Reflash the OS with raspberry pi imager. Make sure the SSID is USC Secure Wireless, select "Open Network", make sure you are using the hostname you set up
if net neighbor shows "unreachable," turn off network sharing, turn it back on, power cycle rpi


# Running
sudo ip addr add 169.254.88.88/16 dev lo

cd HITL/hitl
python3 gnc-testbed.py --csv <csv name>.csv

if you get "address already in use"
pkill -f gnc-testbed.py

power another PS, ssh again,
cd HITL
source .venv/bin/activate
cd hitl
python3 client-new.py

if you get "address already in use"
pkill -f client-new.py