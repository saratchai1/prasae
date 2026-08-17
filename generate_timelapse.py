import os
import json
from PIL import Image, ImageDraw, ImageFont

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
TIMELAPSE_DIR = os.path.join(DATA_DIR, "timelapse")
os.makedirs(TIMELAPSE_DIR, exist_ok=True)

with open(os.path.join(DATA_DIR, "timeseries.json"), "r", encoding="utf-8") as f:
    stats = json.load(f)

def create_gif(mode="rgb", output_name="timelapse_rgb.gif", fps=2):
    frames = []
    
    # Try to load a clean font or default
    try:
        font_large = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Bold.ttf", 22)
        font_small = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 15)
    except:
        font_large = ImageFont.load_default()
        font_small = ImageFont.load_default()
        
    for entry in stats:
        if mode == "rgb":
            img_path = os.path.join(BASE_DIR, entry["rgb_file"])
        elif mode == "false_color":
            img_path = os.path.join(BASE_DIR, entry["fc_file"])
        else:
            img_path = os.path.join(BASE_DIR, entry["ndvi_file"])
            
        if not os.path.exists(img_path):
            continue
            
        im = Image.open(img_path).convert("RGBA")
        W, H = im.size
        
        # Create a clean banner at the top and bottom
        overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        
        # Top banner background (semi-transparent dark)
        draw.rectangle([(0, 0), (W, 42)], fill=(15, 23, 42, 210))
        
        # Month Year Text
        month_label = f"{entry['month_name'][:3]} {entry['year']}"
        draw.text((12, 8), month_label, fill=(255, 255, 255, 255), font=font_large)
        
        # Mode Tag
        mode_label = "Sentinel-2 True Color" if mode == "rgb" else ("Color Infrared (CIR)" if mode == "false_color" else "NDVI Index Heatmap")
        draw.text((W - 190, 12), mode_label, fill=(148, 163, 184, 255), font=font_small)
        
        # Bottom HUD
        draw.rectangle([(0, H - 36), (W, H)], fill=(15, 23, 42, 200))
        stats_text = f"Mean NDVI: {entry['mean_ndvi_plot']:.3f}  |  Veg Cover: {entry['veg_coverage_pct']:.1f}%"
        draw.text((12, H - 28), stats_text, fill=(52, 211, 153, 255), font=font_small)
        
        # Merge
        frame = Image.alpha_composite(im, overlay).convert("RGB")
        frames.append(frame)
        
    if frames:
        out_path = os.path.join(TIMELAPSE_DIR, output_name)
        # 500ms per frame = 2 fps
        duration = int(1000 / fps)
        frames[0].save(
            out_path,
            save_all=True,
            append_images=frames[1:],
            duration=duration,
            loop=0,
            optimize=True
        )
        print(f"Generated {out_path} ({len(frames)} frames)")

if __name__ == "__main__":
    print("Generating Timelapses...")
    create_gif("rgb", "timelapse_true_color.gif", fps=2)
    create_gif("false_color", "timelapse_false_color.gif", fps=2)
    create_gif("ndvi", "timelapse_ndvi.gif", fps=2)
    print("All timelapses created successfully!")
