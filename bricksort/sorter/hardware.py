"""The machine's physical parts, as small swappable pieces.

The sorting logic only talks to these four things, so the virtual conveyor
(conveyor.py) and a real machine are interchangeable:

  Clock      what time it is (simulated or real)
  Camera     gives pictures of the belt; knows how many pixels are one millimetre
  Belt       moves at a known speed
  Diverter   sends the piece that arrives at the end of the belt at a given time to a bin

Real versions are at the bottom: a USB webcam (OpenCV) and a microcontroller such as
an Arduino driving the belt motor and the bin chute over USB (pyserial). The camera
test (camera_test.py) tries the webcam on its own, before there's a belt.
"""
import threading
import time


class Clock:
    def now(self):
        return time.monotonic()


class Camera:
    px_per_mm = 1.0          # calibration: how many pixels one millimetre on the belt is
    belt_direction = +1      # +1: pieces move left -> right in the picture, -1: right -> left

    def frame(self):
        """Latest picture of the belt as an (H, W, 3) RGB numpy array."""
        raise NotImplementedError

    def mm_from_camera_centre(self, x_px, width):
        """How far (mm, along the belt) a pixel column is past the middle of the picture."""
        return (x_px - width / 2) / self.px_per_mm * self.belt_direction


class Belt:
    speed_mm_s = 50.0
    camera_to_end_mm = 300.0  # from the middle of the camera picture to where pieces leave the belt

    def start(self):
        pass

    def stop(self):
        pass


class Diverter:
    def send(self, bin_name, arrive_at):
        """The piece reaching the end of the belt at time `arrive_at` must go to `bin_name`."""
        raise NotImplementedError


# ---------------------------------------------------------------- real hardware (for later)

class WebcamCamera(Camera):
    """A USB webcam or Raspberry Pi camera looking straight down at the belt.

    Calibrate px_per_mm once: put a ruler on the belt, take a picture, count pixels per mm.
    """

    def __init__(self, index=0, width=1280, height=720, px_per_mm=4.0, belt_direction=+1):
        import cv2
        self.cv2 = cv2
        import sys
        # DirectShow on Windows: opens in about a second (the default can take ten)
        self.cap = cv2.VideoCapture(index, cv2.CAP_DSHOW) if sys.platform == "win32" else cv2.VideoCapture(index)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        self.px_per_mm, self.belt_direction = px_per_mm, belt_direction

    def frame(self):
        ok, img = self.cap.read()
        if not ok:
            raise RuntimeError("Camera gave no picture")
        return self.cv2.cvtColor(img, self.cv2.COLOR_BGR2RGB)


class SerialMachine(Belt, Diverter):
    """Belt motor + bin flaps run by a microcontroller on a USB serial port.

    It sends simple text lines the microcontroller acts on:
      "BELT 50"   run the belt at 50 mm/s ("BELT 0" stops it)
      "BIN 3"     move the flap/arm for bin number 3 now
    The timing (when the piece reaches the flap) is handled here, so the
    microcontroller code can stay very simple.
    """

    def __init__(self, port="COM3", bins=(), speed_mm_s=50.0, camera_to_end_mm=300.0, baud=115200):
        import serial
        self.link = serial.Serial(port, baud, timeout=1)
        self.bin_numbers = {name: i for i, name in enumerate(bins)}
        self.speed_mm_s, self.camera_to_end_mm = speed_mm_s, camera_to_end_mm
        self.clock = Clock()

    def _say(self, line):
        self.link.write((line + "\n").encode())

    def start(self):
        self._say(f"BELT {self.speed_mm_s:g}")

    def stop(self):
        self._say("BELT 0")

    def send(self, bin_name, arrive_at):
        delay = max(0.0, arrive_at - self.clock.now() - 0.1)  # flap moves just before it arrives
        threading.Timer(delay, self._say, [f"BIN {self.bin_numbers.get(bin_name, len(self.bin_numbers) - 1)}"]).start()
