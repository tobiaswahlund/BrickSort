"""A small 3D view of a part that you can spin with the mouse.

Drag with the left mouse button to turn it, use the mouse wheel to zoom.
Used instead of the flat reference picture in the review window and the
sorting machine. Pieces without a 3D model (your custom pieces) show a photo.
"""
import tkinter as tk

import mujoco
import numpy as np
from PIL import Image, ImageTk

from .scene import _fmt, close_renderer

BACKGROUND = (0.16, 0.17, 0.19)


class PartViewer(tk.Label):
    def __init__(self, master, lib, part_id, rgb=(160, 165, 169), size=160, fallback=None):
        super().__init__(master, bg="#292b30", cursor="fleur")
        self.size = size
        self.renderer = None
        try:
            verts, faces = lib.part_mesh(part_id)
        except Exception:
            # no 3D model: show the picture we have instead
            if fallback is not None:
                self._show(fallback.resize((size, size)))
            self.configure(cursor="")
            return
        if min(rgb) > 200:
            rgb = (165, 170, 175)   # white would vanish in the light; show it light grey
        elif max(rgb) < 45:
            rgb = (110, 112, 108)
        b = " ".join(f"{c:.3f}" for c in BACKGROUND)
        xml = f"""
<mujoco>
  <visual>
    <global offwidth="{size}" offheight="{size}"/>
    <headlight ambient="0.35 0.35 0.35" diffuse="0.55 0.55 0.55" specular="0.15 0.15 0.15"/>
    <map znear="0.01"/>
    <quality offsamples="4"/>
  </visual>
  <asset>
    <texture name="sky" type="skybox" builtin="flat" rgb1="{b}" rgb2="{b}" width="16" height="16"/>
    <material name="plastic" specular="0.4" shininess="0.85"/>
    <mesh name="part" vertex="{_fmt(verts)}" face="{_fmt(faces)}"/>
  </asset>
  <worldbody>
    <light directional="true" dir="-0.4 0.5 -0.75" diffuse="0.35 0.35 0.35" specular="0.3 0.3 0.3"/>
    <geom type="mesh" mesh="part" material="plastic" rgba="{rgb[0] / 255:.3f} {rgb[1] / 255:.3f} {rgb[2] / 255:.3f} 1"/>
  </worldbody>
</mujoco>"""
        self.model = mujoco.MjModel.from_xml_string(xml)
        self.data = mujoco.MjData(self.model)
        mujoco.mj_forward(self.model, self.data)
        self.renderer = mujoco.Renderer(self.model, size, size)
        self.cam = mujoco.MjvCamera()
        self.cam.type = mujoco.mjtCamera.mjCAMERA_FREE
        self.cam.lookat[:] = 0
        self.radius = float(np.linalg.norm(verts.max(0) - verts.min(0)) / 2)
        self.cam.distance = self.radius * 3.2
        self.cam.azimuth, self.cam.elevation = 30.0, -35.0
        self.bind("<ButtonPress-1>", self._press)
        self.bind("<B1-Motion>", self._drag)
        self.bind("<MouseWheel>", self._zoom)
        self.bind("<Destroy>", self._close)
        self.render()

    def _show(self, img):
        self.photo = ImageTk.PhotoImage(img)
        self.configure(image=self.photo)

    def render(self):
        self.renderer.update_scene(self.data, camera=self.cam)
        self._show(Image.fromarray(self.renderer.render()))

    def _press(self, e):
        self.last = (e.x, e.y)

    def _drag(self, e):
        dx, dy = e.x - self.last[0], e.y - self.last[1]
        self.last = (e.x, e.y)
        self.cam.azimuth -= dx * 0.8
        self.cam.elevation = float(np.clip(self.cam.elevation - dy * 0.8, -89, 89))
        self.render()

    def _zoom(self, e):
        self.cam.distance = float(np.clip(self.cam.distance * (0.9 if e.delta > 0 else 1.1),
                                          self.radius * 1.2, self.radius * 8))
        self.render()
        return "break"

    def _close(self, e):
        if e.widget is self and self.renderer is not None:
            close_renderer(self.renderer)
            self.renderer = None
