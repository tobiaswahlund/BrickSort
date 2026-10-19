"""The PC side of the real machine (bricksort/sorter/hardware.py, SerialMachine), talking to a pretend
Arduino that answers like firmware/bricksort_machine/bricksort_machine.ino does."""
import sys
import time
import types

import pytest


class PretendArduino:
    """Stands in for serial.Serial: keeps what the firmware would do, answers what it would answer."""
    bins = 5   # as set in the firmware (BIN_COUNT): here the five bins below

    def __init__(self, port, baud, timeout=1):
        self.port, self.baud = port, baud
        self.answers = [b"BRICKSORT READY\r\n"]   # what it says after restarting
        self.belt_mm_s, self.chute_bin, self.heard = 0.0, self.bins - 1, []

    def readline(self):
        return self.answers.pop(0) if self.answers else b""

    def reset_input_buffer(self):
        self.answers = []

    def write(self, data):
        verb, _, arg = data.decode().strip().partition(" ")
        self.heard.append(data.decode().strip())
        if verb == "PING":
            self.answers.append(b"PONG\r\n")
        elif verb == "BELT":
            self.belt_mm_s = float(arg)
            self.answers.append(b"OK\r\n")
        elif verb == "BIN" and 0 <= int(arg) < self.bins:
            self.chute_bin = int(arg)
            self.answers.append(b"OK\r\n")
        else:
            self.answers.append(b"ERR\r\n")

    def close(self):
        pass


@pytest.fixture
def machine(monkeypatch):
    monkeypatch.setitem(sys.modules, "serial", types.SimpleNamespace(Serial=PretendArduino))
    from bricksort.sorter.hardware import SerialMachine
    m = SerialMachine("COM7", bins=["Red", "Technic", "Other Lego", "Not Lego", "Rest"], speed_mm_s=40,
                      chute_lead_s=0.0)
    return m


def test_it_finds_the_arduino_and_runs_the_belt(machine):
    assert machine.ping()
    machine.start()
    assert machine.link.belt_mm_s == 40
    machine.stop()
    assert machine.link.belt_mm_s == 0


def test_a_piece_turns_the_chute_to_its_bin_in_time(machine):
    machine.send("Technic", arrive_at=machine.clock.now() + 0.05)
    assert machine.link.chute_bin == 4          # not yet: it starts pointing at the last bin
    time.sleep(0.3)
    assert machine.link.chute_bin == 1          # "Technic" is the second bin


def test_an_unknown_bin_goes_to_the_rest_bin(machine):
    machine.send("No such bin", arrive_at=machine.clock.now())
    time.sleep(0.2)
    assert machine.link.chute_bin == 4


def test_close_stops_the_belt(machine):
    machine.start()
    machine.close()
    assert machine.link.heard[-1] == "BELT 0"
