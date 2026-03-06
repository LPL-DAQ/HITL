import time
import smbus2

BUS = 1
ADDRS = [0x4C, 0x4A]

def soft_reset(bus, addr):
    # Command 0111xxxx = software reset; default reset mode uses DB15 DB14 = 0 0
    # Datasheet shows "software reset (default) same as POR". :contentReference[oaicite:2]{index=2}
    bus.write_i2c_block_data(addr, 0x70, [0x00, 0x00])

def write_update(bus, addr, ch, code, bits=12):
    # Command 0011 = write input reg + update DAC reg, access bits = channel (A=0..H=7)
    # Table 6: 0 0 1 1 ... Write to DAC input register channel n, and update DAC register channel n :contentReference[oaicite:3]{index=3}
    ca = 0x30 | (ch & 0x0F)

    # Data packing differs for 10-bit vs 12-bit (Table 14) :contentReference[oaicite:4]{index=4}
    shift = 16 - bits  # 12-bit -> 4, 10-bit -> 6
    code = max(0, min(code, (1 << bits) - 1))
    word = code << shift
    bus.write_i2c_block_data(addr, ca, [(word >> 8) & 0xFF, word & 0xFF])

bus = smbus2.SMBus(BUS)

for a in ADDRS:
    soft_reset(bus, a)

time.sleep(0.05)

print("Setting OUT0 to full-scale (12-bit) for 2s, then 0V…")
for a in ADDRS:
    write_update(bus, a, ch=0, code=409, bits=10)
    write_update(bus, a, ch=1, code=409, bits=10)


time.sleep(2)

for a in ADDRS:
    write_update(bus, a, ch=0, code=0, bits=10)
    write_update(bus, a, ch=1, code=409, bits=10)


print("Done.")
