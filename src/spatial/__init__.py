"""Spatial geometry utilities for D&D combat positioning and AoE targeting."""

from .geometry import BoundingBox, Point3D, Vector3D
from .aoe import (
    AOEVolume,
    ConeVolume,
    CubeVolume,
    CylinderVolume,
    LineVolume,
    SphereVolume,
)

__all__ = [
    "Point3D",
    "Vector3D",
    "BoundingBox",
    "AOEVolume",
    "SphereVolume",
    "CylinderVolume",
    "ConeVolume",
    "CubeVolume",
    "LineVolume",
]
