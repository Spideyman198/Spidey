"""Planar geometry helpers for the retrieval eval fixture."""

import math


def distance_between_points(a, b):
    """Return the Euclidean distance between two 2D points."""
    return math.hypot(a[0] - b[0], a[1] - b[1])


def polygon_area(vertices):
    """Compute the area of a simple polygon using the shoelace formula."""
    total = 0.0
    count = len(vertices)
    for index in range(count):
        x1, y1 = vertices[index]
        x2, y2 = vertices[(index + 1) % count]
        total += x1 * y2 - x2 * y1
    return abs(total) / 2.0
