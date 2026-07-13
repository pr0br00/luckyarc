"""Generate LuckyArc brand assets: avatar 400x400, banner 1500x500, og 1200x630."""
import cairosvg
from pathlib import Path

OUT = Path(__file__).parent

def clover(cx, cy, s, leaf="#4ade80", leaf2="#22c55e"):
    """4-leaf clover: heart-shaped leaves, tips meeting at center with gaps."""
    # heart with tip at (0, 0.08s), lobes up; drawn in unit space then scaled
    heart = (
        f"M 0 {0.08*s} "
        f"C {-0.42*s} {-0.30*s}, {-0.16*s} {-0.62*s}, 0 {-0.36*s} "
        f"C {0.16*s} {-0.62*s}, {0.42*s} {-0.30*s}, 0 {0.08*s} Z"
    )
    leaves = ""
    for i, angle in enumerate((0, 90, 180, 270)):
        col = leaf if i % 2 == 0 else leaf2
        leaves += f'''
        <g transform="translate({cx},{cy}) rotate({angle}) translate(0,{-0.16*s})">
          <path d="{heart}" fill="{col}"/>
        </g>'''
    stem = (
        f'<path d="M {cx + 0.04*s} {cy + 0.12*s} q {0.10*s} {0.42*s} {0.34*s} {0.54*s}" '
        f'stroke="{leaf2}" stroke-width="{0.075*s}" fill="none" stroke-linecap="round"/>'
    )
    return stem + leaves

def bg(w, h):
    return f'''
    <defs>
      <radialGradient id="g" cx="50%" cy="0%" r="120%">
        <stop offset="0%" stop-color="#1a2540"/>
        <stop offset="60%" stop-color="#0e1322"/>
        <stop offset="100%" stop-color="#0b0e14"/>
      </radialGradient>
    </defs>
    <rect width="{w}" height="{h}" fill="url(#g)"/>'''

# --- avatar 400x400 ---
svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="400" height="400">
{bg(400,400)}
{clover(200, 210, 150)}
</svg>'''
cairosvg.svg2png(bytestring=svg.encode(), write_to=str(OUT/"avatar.png"))

# --- banner 1500x500 ---
svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="1500" height="500">
{bg(1500,500)}
{clover(190, 250, 140)}
<text x="360" y="240" font-family="Helvetica, Arial, sans-serif" font-size="76" font-weight="800" fill="#e8ecf4">Lucky<tspan fill="#fbbf24">Arc</tspan></text>
<text x="363" y="305" font-family="Helvetica, Arial, sans-serif" font-size="34" fill="#8b94a8">No-loss prize savings on Arc</text>
<text x="363" y="360" font-family="Helvetica, Arial, sans-serif" font-size="26" fill="#4ade80">Deposit USDC · Withdraw anytime · Win the daily prize</text>
<text x="1480" y="470" text-anchor="end" font-family="Helvetica, Arial, sans-serif" font-size="24" fill="#5a6478">luckyarc.xyz</text>
</svg>'''
cairosvg.svg2png(bytestring=svg.encode(), write_to=str(OUT/"banner.png"))

# --- og image 1200x630 ---
svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="630">
{bg(1200,630)}
{clover(600, 200, 130)}
<text x="600" y="400" text-anchor="middle" font-family="Helvetica, Arial, sans-serif" font-size="64" font-weight="800" fill="#e8ecf4">Lucky<tspan fill="#fbbf24">Arc</tspan></text>
<text x="600" y="460" text-anchor="middle" font-family="Helvetica, Arial, sans-serif" font-size="30" fill="#8b94a8">Save USDC. Win the prize. Never lose your deposit.</text>
<text x="600" y="540" text-anchor="middle" font-family="Helvetica, Arial, sans-serif" font-size="26" fill="#4ade80">luckyarc.xyz — no-loss lottery on Arc</text>
</svg>'''
cairosvg.svg2png(bytestring=svg.encode(), write_to=str(OUT/"og.png"))

print("done:", [p.name for p in OUT.glob("*.png")])
