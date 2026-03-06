## Instructions for setting up HITL Testbed

# Install Packages on Raspberry Pi
('sudo' for MacOS installation bypass)

```bash

sudo apt update -y && sudo apt upgrade -y

sudo raspi-config nonint do_i2c 0   # enable i2c

sudo apt install -y python3-pip python3-venv i2c-tools protobuf-compiler

pip3 install --break-system-packages smbus2 protobuf rich

protoc --python_out=. clover.proto --proto_path=api     # protobuf bindings

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