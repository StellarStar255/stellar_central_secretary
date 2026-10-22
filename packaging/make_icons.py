"""Regenerate the existing eight-ray brand mark (requires Pillow)."""
import math
from pathlib import Path
from PIL import Image, ImageDraw

root = Path(__file__).resolve().parent.parent/'secretary/static/icons'
root.mkdir(parents=True, exist_ok=True)
def mark(size, color, background=False):
    scale=4
    canvas=Image.new('RGBA',(size*scale,size*scale))
    draw=ImageDraw.Draw(canvas)
    n=size*scale
    if background:
        draw.rounded_rectangle((n*.04,n*.04,n*.96,n*.96),radius=n*.21,fill='#242323')
    center=n/2
    radius=n*(.29 if background else .41)
    inner=n*(.055 if background else .065)
    width=max(1,round(n*(.029 if background else .045)))
    for i in range(8):
        angle=i*math.pi/4
        start=(center+math.cos(angle)*inner,center+math.sin(angle)*inner)
        end=(center+math.cos(angle)*radius,center+math.sin(angle)*radius)
        draw.line((start,end),fill=color,width=width)
        for x,y in (start,end):draw.ellipse((x-width/2,y-width/2,x+width/2,y+width/2),fill=color)
    return canvas.resize((size,size),Image.Resampling.LANCZOS)
app=mark(1024,'#ef9b62',True)
app.save(root/'app.png')
app.save(root/'app.icns')
app.save(root/'app.ico',sizes=[(16,16),(32,32),(48,48),(64,64),(128,128),(256,256)])
for name,color in {'ready':'#72ba96','busy':'#efab59','error':'#ef756f','starting':'#a0a0a0'}.items():
    mark(72,color).save(root/f'tray-{name}.png')
