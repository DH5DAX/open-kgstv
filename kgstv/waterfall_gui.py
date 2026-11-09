"""Compact receive-audio waterfall. All rendering runs on Tk's UI thread."""
import tkinter as tk

import numpy as np
from PIL import Image, ImageTk

from . import theme
from .waterfall import SpectrumAnalyzer, FREQUENCIES, FLOOR_DB, CEILING_DB, palette


class Waterfall(tk.Canvas):
    ROWS = 80  # 8 s at 10 rows/s; newest audio is at the top.

    def __init__(self, parent, *, tr, sans, mono):
        super().__init__(parent, width=340, height=146, bg=theme.WELL,
                         highlightthickness=1, highlightbackground=theme.BORDER)
        self.tr, self.sans, self.mono = tr, sans, mono
        self.colors = palette()
        self.history = np.zeros((self.ROWS, len(FREQUENCIES), 3), dtype=np.uint8)
        self.running = False
        self.has_audio = False
        self.peak_db = -240.0
        self.clipped = False
        self.hover_x = None
        self.analyzer = SpectrumAnalyzer()
        self.photo = None
        self.bind("<Configure>", lambda event: self.redraw())
        self.bind("<Motion>", self._hover)
        self.bind("<Button-1>", self._hover)
        self.bind("<Leave>", lambda event: self._hover(None))
        self.reset()

    def reset(self):
        self.analyzer = SpectrumAnalyzer()
        self.history[:] = self.colors[0]
        self.has_audio = self.clipped = False
        self.peak_db = -240.0
        self.redraw()

    def set_running(self, running):
        if self.running != running:
            self.running = running
            self.redraw()

    def consume(self, chunks):
        rows = self.analyzer.feed(chunks)
        for row in rows:
            self.history[1:] = self.history[:-1].copy()
            if row is None:
                self.history[0] = (80, 82, 94)
                continue
            indices = np.clip((row.db - FLOOR_DB) * 255 / (CEILING_DB - FLOOR_DB), 0, 255).astype(np.uint8)
            self.history[0] = self.colors[indices]
            self.peak_db, self.clipped = row.peak_db, row.clipped
            self.has_audio = True
        if rows:
            self.redraw()

    def _hover(self, event):
        self.hover_x = event.x if event is not None and 39 <= event.y < self.winfo_height()-24 else None
        self._draw_cursor()

    def _draw_cursor(self):
        self.delete("cursor")
        width, height = self.winfo_width(), self.winfo_height()
        if self.hover_x is None or width < 50:
            return
        x = min(width-9, max(9, self.hover_x))
        frequency = round((x-9) / (width-18) * 3000)
        self.create_line(x, 39, x, height-24, fill=theme.MUTED, dash=(2, 3), tags="cursor")
        self.create_text(width/2, 13, text=f"{frequency} Hz", fill=theme.TEXT,
                         font=(self.mono, 8), tags="cursor")

    def redraw(self):
        width, height = self.winfo_width(), self.winfo_height()
        if width < 50 or height < 80:
            return
        self.delete("all")
        left, right, top, bottom = 9, width-9, 39, height-24
        image = Image.fromarray(self.history).resize((right-left+1, bottom-top), Image.Resampling.NEAREST)
        self.photo = ImageTk.PhotoImage(image, master=self)
        self.create_image(left, top, anchor="nw", image=self.photo)
        self.create_text(left, 13, anchor="w", text=self.tr("waterfall"), fill=theme.TEXT,
                         font=(self.sans, 9, "bold"))
        state = "wf_live" if self.running and self.has_audio else "wf_wait" if self.running else "wf_paused"
        self.create_text(right, 13, anchor="e", text=self.tr(state),
                         fill=theme.BLUE if self.running else theme.DIM, font=(self.sans, 8))
        for hz in range(0, 3001, 500):
            x = left + (right-left) * hz / 3000
            label = f"{hz/1000:g}".replace(".", self.tr("wf_decimal"))
            if hz == 3000:
                label += " kHz"
            self.create_text(x, 29, text=label, anchor="w" if hz == 0 else "e" if hz == 3000 else "center",
                             font=(self.mono, 8), fill=theme.MUTED)
            self.create_line(x, 35, x, 39, fill=theme.DIM)
        if not self.has_audio:
            self.create_text(width/2, (top+bottom)/2, text=self.tr("wf_wait" if self.running else "wf_start"),
                             font=(self.sans, 9), fill=theme.DIM)
        self.create_text(left, height-11, anchor="w", text=self.tr("wf_time"),
                         font=(self.sans, 8), fill=theme.DIM)
        # Fixed colour scale, independent of gain/decoder settings.
        legend_x = width/2-20
        self.create_text(legend_x-4, height-11, anchor="e", text="−95", font=(self.mono, 7), fill=theme.DIM)
        for n in range(40):
            color = "#%02x%02x%02x" % tuple(self.colors[round(n*255/39)])
            self.create_line(legend_x+n, height-14, legend_x+n, height-8, fill=color)
        self.create_text(legend_x+44, height-11, anchor="w", text="−15", font=(self.mono, 7), fill=theme.DIM)
        level = self.tr("wf_clip") if self.clipped else f"{self.peak_db:.0f} dBFS" if self.has_audio and self.peak_db > -120 else "−∞ dBFS"
        self.create_text(right, height-11, anchor="e", text=level,
                         fill=theme.TINT if self.clipped else theme.MUTED, font=(self.mono, 8))
        self._draw_cursor()
