"""Compute the three image-processing references."""
from pathlib import Path
import sys
root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
from PIL import Image
from verification.oracle import pixel,windows
image=Image.open(root/'assets/input_gray.png').convert('L');rows=[list(image.getdata())[i*image.width:(i+1)*image.width] for i in range(image.height)]
out=root/'outputs';out.mkdir(exist_ok=True)
for mode,name in enumerate(['sobel','gaussian','sharpen']):
 result=Image.new('L',image.size);result.putdata([pixel(w,mode) for w in windows(rows)]);result.save(out/(name+'.png'))
print(out)
