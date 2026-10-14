"""The sorting machine: camera -> spot a piece -> recognise it -> choose a bin -> send it there.

hardware.py   the parts of the machine (camera, belt, diverter) as swappable pieces:
              a virtual version now, real camera / motors later
detector.py   notices objects on the belt in the camera picture, counts them
rules.py      your bin rules (bins.json)
properties.py size, flatness, category... of each part, for the rules
machine.py    ties it together
"""
