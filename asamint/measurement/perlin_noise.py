import math
import random


def gradient(h):
    """Generate random gradient vector."""
    return math.cos(h), math.sin(h)


def lerp(a, b, x):
    """Linear interpolation."""
    return a + x * (b - a)


def fade(t):
    """Smoothstep interpolation."""
    return t * t * t * (t * (t * 6 - 15) + 10)


def perlin(x, y, grid_size=8):
    """Compute Perlin noise for coordinates (x, y)."""
    x0, y0 = int(x // grid_size), int(y // grid_size)
    x1, y1 = x0 + 1, y0 + 1

    dx, dy = x / grid_size - x0, y / grid_size - y0

    random.seed(0)  # For reproducibility
    gradients = {}
    gradients[(x0, y0)] = gradient(random.random() * 2 * math.pi)
    gradients[(x1, y0)] = gradient(random.random() * 2 * math.pi)
    gradients[(x0, y1)] = gradient(random.random() * 2 * math.pi)
    gradients[(x1, y1)] = gradient(random.random() * 2 * math.pi)

    dot00, dot10 = (
        gradients[(x0, y0)][0] * dx + gradients[(x0, y0)][1] * dy,
        gradients[(x1, y0)][0] * (dx - 1) + gradients[(x1, y0)][1] * dy,
    )
    dot01, dot11 = (
        gradients[(x0, y1)][0] * dx + gradients[(x0, y1)][1] * (dy - 1),
        gradients[(x1, y1)][0] * (dx - 1) + gradients[(x1, y1)][1] * (dy - 1),
    )

    u, v = fade(dx), fade(dy)

    return lerp(lerp(dot00, dot10, u), lerp(dot01, dot11, u), v)
