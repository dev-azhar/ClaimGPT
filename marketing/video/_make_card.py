"""Generate a 1920x1080 brand card with title + subtitle, using PIL."""
import sys
from PIL import Image, ImageDraw, ImageFont

PNG, TITLE, SUBTITLE = sys.argv[1], sys.argv[2], sys.argv[3]

W, H = 1920, 1080
NAVY = (15, 76, 129)        # #0f4c81
TEAL = (13, 148, 136)       # #0d9488
TEAL_LIGHT = (167, 243, 208)  # #a7f3d0
INK = (15, 23, 42)          # #0f172a

# ── Background: vertical gradient navy → teal blend
img = Image.new("RGB", (W, H), NAVY)
top = Image.new("RGB", (W, H), NAVY)
bot = Image.new("RGB", (W, H), TEAL)
mask = Image.linear_gradient("L").resize((W, H))
img = Image.composite(bot, top, mask)

# ── Subtle radial vignette using a darker overlay
overlay = Image.new("RGBA", (W, H), (15, 23, 42, 0))
od = ImageDraw.Draw(overlay)
# Soft glow centered upper third
od.ellipse((W // 2 - 700, H // 2 - 600, W // 2 + 700, H // 2 + 200),
           fill=(94, 234, 212, 28))
img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")

# ── Fonts (fall back gracefully)
def load_font(size: int) -> ImageFont.FreeTypeFont:
    candidates = [
        "/System/Library/Fonts/SFNS.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/System/Library/Fonts/HelveticaNeue.ttc",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()

title_font = load_font(160)
sub_font = load_font(56)

draw = ImageDraw.Draw(img)

def draw_centered(text: str, font, y: int, fill):
    bbox = draw.textbbox((0, 0), text, font=font)
    w = bbox[2] - bbox[0]
    draw.text(((W - w) // 2, y), text, font=font, fill=fill)

# ── Subtle drop shadow behind title for depth
shadow_offset = 4
draw_centered(TITLE, title_font, H // 2 - 130 + shadow_offset, (0, 0, 0, 80))
draw_centered(TITLE, title_font, H // 2 - 130, (255, 255, 255))
draw_centered(SUBTITLE, sub_font, H // 2 + 80, TEAL_LIGHT)

# ── Tiny accent dot above title
dot_r = 14
draw.ellipse(
    (W // 2 - dot_r, H // 2 - 250 - dot_r, W // 2 + dot_r, H // 2 - 250 + dot_r),
    fill=TEAL_LIGHT,
)

img.save(PNG, "PNG", optimize=True)
print(f"  wrote {PNG}")
