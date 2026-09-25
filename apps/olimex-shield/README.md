# apps/olimex-shield — the board, and the sketch that runs on it

`eeg_stream/eeg_stream.ino` is the Arduino sketch flashed to the board. It reads two analog pins
250 times a second and prints each reading as a CSV line over USB serial. The bridge
(`apps/server`) reads those lines. That is the entire contract between hardware and software.

**It was checked against a live board on 2026-09-14.** Read straight off the serial port at
115200 baud, the banner and the `t_us,ch0,ch1` cadence matched this source exactly, so this file
is what was flashed. It compiles for `arduino:avr:uno` in 2124 bytes of flash and 226 bytes of
RAM (arduino-cli 1.5.1, AVR core 1.8.8).

## What you need

| Part | Notes |
|---|---|
| Arduino UNO R3, or a pin-compatible 5 V board | The rig here reports as `arduino:avr:uno`. |
| Olimex **SHIELD-EKG-EMG** | One shield = one differential channel. |
| An electrode cable for the shield | Olimex sells matching passive cables (snap / disposable-gel leads). |
| Disposable gel electrodes, or cup electrodes + conductive paste | **Not ultrasound gel.** It couples sound, not current, and the drift it causes looks like biology. |
| USB cable | Data-capable, not charge-only. |
| A laptop you can run **on battery** | See Safety. It also removes most mains hum. |

## Wiring

1. Seat the shield on the Arduino headers. Check that every pin is in its socket and nothing is
   offset by a row.
2. Plug the electrode cable into the shield's input connector.
3. Leave the shield's jumpers at their single-shield defaults. **This sketch reads the shield
   output on `A0`** (and also prints `A1`). If your shield's channel-select jumper routes it to
   another analog pin, change `CH0_PIN` in the sketch.
   - The jumper names and defaults are in Olimex's SHIELD-EKG-EMG user manual, and deliberately
     not repeated here. A copied jumper table that is wrong is worse than a pointer to the right
     one.
4. Connect USB to the laptop.

**`ch1` (`A1`) is printed but not shown to be a second input.**
- On the one rig measured, with the leads floating, ch1 correlated +0.89 with ch0. That is what a
  floating pin picking up the same room looks like.
- The cheapest check: touch or short one channel's leads and see which column responds
  (`apps/server/RIG.md`).

## Flashing

With [arduino-cli](https://arduino.github.io/arduino-cli/):

```bash
arduino-cli core install arduino:avr
arduino-cli board list                       # find the port: /dev/cu.usbmodemXXXX, /dev/ttyACM0, COM3
arduino-cli compile --fqbn arduino:avr:uno apps/olimex-shield/eeg_stream
arduino-cli upload  --fqbn arduino:avr:uno -p <port> apps/olimex-shield/eeg_stream
```

Or in the Arduino IDE: open `eeg_stream/eeg_stream.ino`, choose **Arduino UNO** and the port, and
press Upload.

**Stop the bridge first.** Only one program can hold a serial port. If the workbench's bridge has
it open, the upload fails with a busy-port error.

## Check that it is streaming

```bash
arduino-cli monitor -p <port> -c baudrate=115200
```

```
# ArduinoEKG ready
# t_us,ch0,ch1
4004,523,458
8004,410,425
```

- `t_us` should step about 4000 µs apart.
- With nothing attached, values sit near mid-scale (~510).
- Lines starting with `#` are comments, and the bridge skips them.
- Opening the port resets the Arduino, so the first sample arrives about 1.6 s later.

## The contract, and what breaks it silently

| Setting | Value | If you change it |
|---|---|---|
| `BAUD` | 115200 | The bridge must match (`/open` takes `baud`). |
| `SAMPLE_RATE` | 250 Hz | **Silent.** The bridge labels samples at its declared rate, so change `NOMINAL_RATE_HZ` in `apps/server/rig.py` too. |
| CSV columns | `t_us,ch0,ch1` | **Silent.** The bridge picks the channel by column index (`channelCol`, default 1 = ch0). |
| Banner text | `# ArduinoEKG ready` | Safe. Only a human reads it. |

**The board's clock is not exact.**
- The sketch schedules samples off the board's own `micros()`, so `t_us` always agrees with itself
  and cannot reveal a clock error.
- Against a computer's clock, one board ran at 249.83 Hz (about −680 ppm), and that figure moved
  by 41 ppm within a day.
- The bridge measures the real rate against the host clock (`apps/server/timebase.py`). Any
  lock-in analysis must use that measured rate.
- `t_us` is a 32-bit `micros()`, so it wraps every 71.6 minutes.

## Versioning

This file is the version. If you change it:

1. edit it here and commit;
2. re-flash;
3. repeat the streaming check above, and confirm the board shows the change before trusting a
   recording against it;
4. add a line to the repository `CHANGELOG.md` saying what changed on the board.

## Safety

This is a hobby amplifier, not a medically isolated device.
- Run it from a battery-powered laptop unplugged from mains.
- Never connect anyone with an implanted pacemaker or other active implant.

The full list is in the repository README, and in the workbench, which shows it before every
connection.
