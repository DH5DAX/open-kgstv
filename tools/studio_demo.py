"""Real desktop documentation scenes, isolated sample data and Hamlib Dummy only.

python tools/studio_demo.py operating|editor|gallery|history|qso|setup --language en
All images are original generated project artwork. All contacts are sample data.
No real audio device, serial port or RF transmitter is opened.
"""
import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import tkinter as tk
import uuid
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from kgstv.gui import Application
from kgstv.hamlib import find_rigctld
from kgstv.image_document import Document, Layer, load_image
from screenshot_demo import test_card


def landscape():
    image = Image.new("RGB", (640, 480))
    draw = ImageDraw.Draw(image)
    for y in range(480):
        t = y/480
        draw.line((0,y,640,y),fill=(int(25+120*t),int(43+50*t),int(91+25*t)))
    draw.ellipse((440,100,545,205), fill="#f4c07a")
    draw.polygon([(0,330),(120,175),(260,355),(425,225),(640,365),(640,480),(0,480)], fill="#4a557b")
    draw.polygon([(65,247),(120,175),(176,247),(145,228),(121,236),(105,225)], fill="#b7c8d3")
    draw.polygon([(0,390),(190,275),(350,400),(540,290),(640,370),(640,480),(0,480)], fill="#273950")
    draw.polygon([(0,450),(160,390),(310,460),(530,370),(640,410),(640,480),(0,480)], fill="#162738")
    return image


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scene",choices=("operating","editor","gallery","history","qso","setup"))
    parser.add_argument("--language",choices=("en","de"),default="en")
    parser.add_argument("--compact",action="store_true")
    parser.add_argument("--waterfall",action="store_true",help="Show a paused synthetic MSK audio preview (no soundcard)")
    args=parser.parse_args()
    folder=ROOT/"outputs"/"studio-demo"/uuid.uuid4().hex
    folder.mkdir(parents=True)
    root=tk.Tk()
    app=Application(root,settings_path=folder/"settings.json",language=args.language)
    root.title("Open KG-STV | Studio documentation")
    if args.compact:
        root.geometry("940x640")
    app.callsign.set("TEST")
    app.rx_image=test_card()
    app.rx_summary={"callsign":"TEST2","good_blocks":300,"missing":[]}
    app._show(app.rx_preview,app.rx_image)
    doc=Document.from_image(landscape(),"Mountain evening")
    doc.add(Layer("text",text="CQ SSTV",x=105,y=37,size=32,shadow=True))
    doc.add(Layer("text",text="{MYCALL}",x=75,y=74,size=23,color="#f4c07a",shadow=True))
    doc.add(Layer("image",name="RX TEST2",image=load_image(test_card()),x=237,y=161,width=140,height=105,fit="contain"))
    doc.add(Layer("text",text="73 {HISCALL} de {MYCALL}",x=160,y=224,size=16,shadow=True))
    context={"MYCALL":"TEST","HISCALL":"TEST2"}
    app.set_tx_document(doc,context)
    app.library.add_image("Mountain evening",landscape())
    app.library.add_image("TEST2 · 300/300",test_card(),kind="rx")
    app.library.add_image("CQ · mountain template",doc.render(context),kind="template",document=doc)
    app.library.add_image("Reply to TEST2",doc.render(context),kind="tx",document=doc)
    for color, name in (("#182d41","Blue hour"),("#502830","CQ warm"),("#243c35","73 green")):
        template=Document(background=color)
        template.add(Layer("text",text="CQ CQ\n{MYCALL}",y=80,size=30,shadow=True))
        template.add(Layer("text",text="KG-STV · 73",y=197,size=21,color="#f4c07a"))
        app.library.add_image(name,template.render(context),kind="template",document=template)
    for n in range(24):
        text=("TEST2>CQ CQ de TEST2", "TEST>TEST2 de TEST - good evening!", "TEST2>Image received, RSV 595. Nice colours!", "TEST>Thanks for the QSO. 73!")[n%4]
        stamp=(datetime(2026,11,9,17,20,tzinfo=timezone.utc)+timedelta(minutes=n)).isoformat()
        app.library.add_message(text,"TX" if n%2 else "RX",created=stamp)
    app._recent_messages=list(reversed(app.library.messages(limit=200)))
    app._render_messages()
    app.message.insert(0,"TEST2 de TEST - ready for your next image")
    if args.waterfall:
        import numpy as np
        from kgstv.modem import modulate
        from kgstv.protocol import text_frame
        from kgstv.waterfall import HOP
        signal = modulate([text_frame("TEST>CQ CQ de TEST - KG-STV waterfall")], rate=12000)
        samples = np.resize(signal, HOP*80)*.12
        samples += np.random.default_rng(7).normal(0, .0002, len(samples))
        app.waterfall.consume([(n, samples[n*HOP:(n+1)*HOP], False) for n in range(80)])
    panel=app.radio_panel
    panel.connection.set("local");panel.model.set("1 · Hamlib Dummy");panel.device.set("")
    panel.baud.set("0");panel.civ.set("");panel.executable.set(find_rigctld());panel.ptt_method.set("hamlib")
    panel.activity_combo.current(0);panel.select_activity()

    def show():
        if panel.busy:
            root.after(100,show)
            return
        if args.scene=="editor":
            editor=app.open_editor();editor.selected=editor.document.layers[-1].id;editor.refresh()
            editor.notebook.select(editor.tab_frames["text_adjust"])
            if args.compact:editor.window.geometry("980x680")
        elif args.scene=="gallery":
            gallery=app.open_gallery();gallery.select(app.library.images(kind="template")[-1]["id"])
        elif args.scene=="history":app.open_history()
        elif args.scene=="qso":
            qso=app.open_logbook();qso.values["rst_sent"].set("595");qso.values["rst_received"].set("595")
            qso.values["comment"].set("KG-STV image exchange - sample contact")
        elif args.scene=="setup":app.open_setup()
        (folder/"ready.txt").write_text(args.scene,encoding="utf-8")

    def tune():
        if panel.busy:root.after(100,tune)
        else:
            if panel.connected:panel.tune_activity()
            root.after(150,show)
    root.after(200,panel.connect)
    root.after(350,tune)
    root.mainloop()


if __name__=="__main__":main()
