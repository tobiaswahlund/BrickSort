// BrickSort machine: an Arduino (Uno or Nano) runs the belt and the bin chute.
//
// The PC (bricksort/sorter/hardware.py, SerialMachine) sends one line per command over USB, 115200 baud:
//   BELT 50     run the belt at 50 mm/s (BELT 0 stops it)
//   BIN 3       turn the chute to bin 3 (0 = the first bin)
//   PING        answers PONG (the PC checks the Arduino is there)
// Every command is answered with OK (or ERR and why), so the PC can tell it arrived.
// The PC does the timing (when a piece reaches the chute), so this stays simple.
//
// Wiring (see docs/MACHINE.md):
//   stepper driver (A4988 or TMC2208): STEP -> pin 3, DIR -> pin 4, EN -> pin 5
//   chute servo signal -> pin 9 (servo power from a separate 5 V supply, grounds joined)
// Upload with the free Arduino IDE: open this file, choose your board and port, press Upload.

#include <Servo.h>

// ---- change these to match your build ----
const int STEP_PIN = 3, DIR_PIN = 4, ENABLE_PIN = 5, SERVO_PIN = 9;
const float STEPS_PER_TURN = 200.0;   // a NEMA 17 motor: 200 full steps per turn
const float MICROSTEPS = 16.0;        // as set on the driver (A4988: MS1-3 high = 16)
const float ROLLER_MM = 25.0;         // diameter of the roller that drives the belt
const bool BELT_REVERSED = false;     // true if the belt runs the wrong way
const int BIN_COUNT = 6;              // bins around the chute, rest bin included
const int FIRST_ANGLE = 30, LAST_ANGLE = 150;   // chute angle for the first and last bin
// --------------------------------------------

const float STEPS_PER_MM = STEPS_PER_TURN * MICROSTEPS / (PI * ROLLER_MM);
Servo chute;
unsigned long stepEveryUs = 0;   // 0: belt stopped
unsigned long lastStepUs = 0;
String line;

int angleFor(int bin) {
  if (BIN_COUNT < 2) return (FIRST_ANGLE + LAST_ANGLE) / 2;
  return FIRST_ANGLE + (long)(LAST_ANGLE - FIRST_ANGLE) * bin / (BIN_COUNT - 1);
}

void setBelt(float mmPerS) {
  if (mmPerS <= 0) {
    stepEveryUs = 0;
    digitalWrite(ENABLE_PIN, HIGH);   // driver off: the motor doesn't hum or heat up while stopped
    return;
  }
  digitalWrite(ENABLE_PIN, LOW);
  stepEveryUs = (unsigned long)(1000000.0 / (mmPerS * STEPS_PER_MM));
}

void handle(String cmd) {
  cmd.trim();
  int space = cmd.indexOf(' ');
  String verb = space < 0 ? cmd : cmd.substring(0, space);
  String arg = space < 0 ? "" : cmd.substring(space + 1);
  verb.toUpperCase();
  if (verb == "PING") {
    Serial.println("PONG");
  } else if (verb == "BELT") {
    setBelt(arg.toFloat());
    Serial.println("OK");
  } else if (verb == "BIN") {
    int bin = arg.toInt();
    if (bin < 0 || bin >= BIN_COUNT) {
      Serial.println("ERR no such bin");
      return;
    }
    chute.write(angleFor(bin));
    Serial.println("OK");
  } else if (verb.length()) {
    Serial.println("ERR unknown command");
  }
}

void setup() {
  pinMode(STEP_PIN, OUTPUT);
  pinMode(DIR_PIN, OUTPUT);
  pinMode(ENABLE_PIN, OUTPUT);
  digitalWrite(DIR_PIN, BELT_REVERSED ? HIGH : LOW);
  setBelt(0);
  chute.attach(SERVO_PIN);
  chute.write(angleFor(BIN_COUNT - 1));   // start pointing at the last bin (the rest bin)
  Serial.begin(115200);
  Serial.println("BRICKSORT READY");
}

void loop() {
  // the belt: one step every stepEveryUs microseconds (checked as often as possible)
  if (stepEveryUs) {
    unsigned long now = micros();
    if (now - lastStepUs >= stepEveryUs) {
      lastStepUs += stepEveryUs;
      if (now - lastStepUs > 100000) lastStepUs = now;   // fell far behind (just started): don't rush
      digitalWrite(STEP_PIN, HIGH);
      delayMicroseconds(2);
      digitalWrite(STEP_PIN, LOW);
    }
  }
  // commands from the PC, one line at a time
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n') {
      handle(line);
      line = "";
    } else if (c != '\r' && line.length() < 40) {
      line += c;
    }
  }
}
