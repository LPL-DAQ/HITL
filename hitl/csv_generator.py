import csv

output_file = "test_data.csv"

header = [
    "time",
    "data_queue_size",
    "fuel_valve_setpoint",
    "fuel_valve_internal_pos",
    "fuel_valve_encoder_pos",
    "fuel_valve_velocity",
    "fuel_valve_acceleration",
    "fuel_valve_nsec_per_pulse",
    "lox_valve_setpoint",
    "lox_valve_internal_pos",
    "lox_valve_encoder_pos",
    "lox_valve_velocity",
    "lox_valve_acceleration",
    "lox_valve_nsec_per_pulse",
    "pt102",
    "pt103",
    "pto401",
    "pt202",
    "pt203",
    "ptf401",
    "ptc401",
    "ptc402",
]

num_lines = 6000

with open(output_file, "w", newline="") as f:
    writer = csv.writer(f)
    writer.writerow(header)

    for i in range(num_lines):
        row = [
            0,    # time
            0,    # data_queue_size
            0,    # fuel_valve_setpoint
            0,    # fuel_valve_internal_pos
            0,    # fuel_valve_encoder_pos
            0,    # fuel_valve_velocity
            0,    # fuel_valve_acceleration
            0,    # fuel_valve_nsec_per_pulse
            0,    # lox_valve_setpoint
            0,    # lox_valve_internal_pos
            0,    # lox_valve_encoder_pos
            0,    # lox_valve_velocity
            0,    # lox_valve_acceleration
            0,    # lox_valve_nsec_per_pulse
            200,  # pt102
            0,    # pt103
            0,    # pto401
            200,  # pt202
            0,    # pt203
            200,  # ptf401
            200,  # ptc401
            0,    # ptc402
        ]
        writer.writerow(row)

print(f"Created {output_file} with {num_lines} data rows.")