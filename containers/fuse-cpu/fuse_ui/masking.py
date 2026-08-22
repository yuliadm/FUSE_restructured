"""Interactive 2D repair-mask helpers for FUSE Stage 0."""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path

import numpy as np
import plotly.graph_objects as go
from PIL import Image, ImageDraw


MASK_YELLOW = "rgb(255,215,40)"
VERTEX_MAGENTA = "rgb(255,77,157)"


def _normalised_vertices(vertices: list[list[float]] | np.ndarray) -> np.ndarray:
    array = np.asarray(vertices, dtype=np.float64)
    if array.size == 0:
        return np.empty((0, 2), dtype=np.float64)
    array = array.reshape(-1, 2)
    if not np.isfinite(array).all():
        raise ValueError("Mask vertices must be finite numbers.")
    if np.any(array < 0.0) or np.any(array > 1.0):
        raise ValueError("Mask vertices must use normalized coordinates in [0, 1].")
    return array


def vertices_to_pixels(
    vertices: list[list[float]] | np.ndarray,
    image_size: tuple[int, int],
) -> np.ndarray:
    normalized = _normalised_vertices(vertices)
    if not len(normalized):
        return normalized
    width, height = image_size
    scale = np.asarray([max(width - 1, 1), max(height - 1, 1)], dtype=np.float64)
    return normalized * scale


def polygon_mask(
    image_size: tuple[int, int],
    vertices: list[list[float]] | np.ndarray,
) -> Image.Image:
    pixels = vertices_to_pixels(vertices, image_size)
    if len(pixels) < 3:
        raise ValueError("At least three mask vertices are required.")
    mask = Image.new("L", image_size, 0)
    ImageDraw.Draw(mask).polygon(
        [tuple(np.rint(point).astype(int)) for point in pixels],
        fill=255,
    )
    return mask


def mask_overlay(source: Image.Image, mask: Image.Image) -> Image.Image:
    source_rgba = source.convert("RGBA")
    yellow = Image.new("RGBA", source.size, (255, 215, 40, 0))
    yellow.putalpha(mask.point(lambda value: 112 if value else 0))
    return Image.alpha_composite(source_rgba, yellow)


def image_png_bytes(image: Image.Image) -> bytes:
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def repair_specification(
    source: Image.Image,
    source_name: str,
    vertices: list[list[float]] | np.ndarray,
    repair_context: dict | None = None,
) -> dict:
    normalized = _normalised_vertices(vertices)
    source_png = image_png_bytes(source.convert("RGB"))
    return {
        "schema_version": "fuse.repair_mask.v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "authority": "user_defined_allowed_generation_region",
        "source": {
            "name": source_name,
            "canonical_png_sha256": sha256(source_png).hexdigest(),
            "size": list(source.size),
        },
        "repair": {} if repair_context is None else dict(repair_context),
        "mask": {
            "mode": "interactive_polygon",
            "vertices_normalized": normalized.tolist(),
            "vertices_pixel_xy": vertices_to_pixels(normalized, source.size).tolist(),
            "white_means_generate": True,
            "black_means_preserve": True,
        },
    }


def repair_spec_json_bytes(specification: dict) -> bytes:
    return (json.dumps(specification, indent=2) + "\n").encode("utf-8")


def _next_run_directory(data_root: Path) -> Path:
    parent = data_root / "flux_inputs" / "runs"
    parent.mkdir(parents=True, exist_ok=True)
    base = "repair_mask_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    candidate = parent / base
    suffix = 1
    while candidate.exists():
        candidate = parent / f"{base}_{suffix:02d}"
        suffix += 1
    candidate.mkdir(parents=False, exist_ok=False)
    return candidate


def save_repair_mask_run(
    data_root: Path,
    source: Image.Image,
    source_name: str,
    vertices: list[list[float]] | np.ndarray,
    repair_context: dict | None = None,
) -> Path:
    """Save one immutable mask-input run and return its directory."""
    mask = polygon_mask(source.size, vertices)
    overlay = mask_overlay(source, mask)
    specification = repair_specification(
        source,
        source_name,
        vertices,
        repair_context=repair_context,
    )
    run_dir = _next_run_directory(Path(data_root))

    source.convert("RGB").save(run_dir / "damaged_input.png")
    mask.save(run_dir / "restoration_mask_binary.png")
    overlay.save(run_dir / "mask_overlay.png")
    (run_dir / "repair_spec.json").write_bytes(
        repair_spec_json_bytes(specification)
    )
    return run_dir


def selected_image_point(
    event,
    image_size: tuple[int, int],
) -> np.ndarray | None:
    try:
        points = event.selection.points
    except (AttributeError, KeyError, TypeError):
        return None
    if not points:
        return None

    selected = points[-1]
    try:
        x = float(selected["x"])
        y = float(selected["y"])
    except (KeyError, TypeError, ValueError):
        return None
    if not np.isfinite([x, y]).all():
        return None

    width, height = image_size
    normalized = np.asarray(
        [x / max(width - 1, 1), y / max(height - 1, 1)],
        dtype=np.float64,
    )
    return np.clip(normalized, 0.0, 1.0)


def mask_editor_figure(
    source: Image.Image,
    vertices: list[list[float]] | np.ndarray,
    maximum_click_points: int = 45_000,
) -> go.Figure:
    """Display an image over a selectable point lattice and the current polygon."""
    image = source.convert("RGB")
    width, height = image.size
    normalized = _normalised_vertices(vertices)
    pixels = vertices_to_pixels(normalized, image.size)

    stride = max(1, int(np.ceil(np.sqrt(width * height / maximum_click_points))))
    x_values = np.arange(0, width, stride, dtype=np.float32)
    y_values = np.arange(0, height, stride, dtype=np.float32)
    grid_x, grid_y = np.meshgrid(x_values, y_values)
    flat_x = grid_x.reshape(-1)
    flat_y = grid_y.reshape(-1)

    figure = go.Figure()
    figure.add_layout_image(
        source=image,
        xref="x",
        yref="y",
        x=0,
        y=0,
        sizex=width,
        sizey=height,
        xanchor="left",
        yanchor="top",
        sizing="stretch",
        layer="below",
    )

    # Nearly invisible selectable points provide native Streamlit/Plotly click
    # events without a third-party canvas component.
    figure.add_trace(
        go.Scattergl(
            x=flat_x,
            y=flat_y,
            mode="markers",
            name="click surface",
            marker={
                "size": max(7, int(stride * 1.6)),
                "color": "rgba(0,0,0,0.004)",
                "line": {"width": 0},
            },
            customdata=np.column_stack(
                [
                    np.full(len(flat_x), "CANVAS", dtype=object),
                    flat_x.astype(object),
                    flat_y.astype(object),
                ]
            ),
            hovertemplate="x=%{x:.0f}, y=%{y:.0f}<extra></extra>",
            showlegend=False,
        )
    )

    if len(pixels):
        closed = np.vstack([pixels, pixels[0]]) if len(pixels) >= 3 else pixels
        figure.add_trace(
            go.Scatter(
                x=closed[:, 0],
                y=closed[:, 1],
                mode="lines+markers",
                name="allowed FLUX region",
                line={"color": MASK_YELLOW, "width": 4},
                marker={
                    "color": VERTEX_MAGENTA,
                    "size": 9,
                    "line": {"color": "white", "width": 1},
                },
                fill="toself" if len(pixels) >= 3 else None,
                fillcolor="rgba(255,215,40,0.28)",
                hovertemplate="vertex<br>x=%{x:.0f}, y=%{y:.0f}<extra></extra>",
            )
        )

    figure.update_layout(
        title={
            "text": "Click around the complete allowed generation region",
            "x": 0.02,
            "xanchor": "left",
        },
        height=max(560, min(850, int(760 * height / max(width, 1)))),
        margin={"l": 0, "r": 0, "b": 0, "t": 52},
        showlegend=False,
        dragmode="select",
        clickmode="event+select",
        xaxis={
            "range": [0, width],
            "visible": False,
            "fixedrange": True,
            "constrain": "domain",
        },
        yaxis={
            "range": [height, 0],
            "visible": False,
            "fixedrange": True,
            "scaleanchor": "x",
            "scaleratio": 1,
        },
        uirevision=f"fuse-mask-{width}-{height}-{len(normalized)}",
    )
    return figure
