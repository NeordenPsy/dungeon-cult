"""Read-only GLB mesh audit. Run in a fresh background Blender, never in a GUI scene."""

import argparse
import json
import math
from pathlib import Path
import sys

import bmesh
import bpy


def analyze_mesh(mesh):
    """Analyze base mesh topology without welding UV splits or applying modifiers."""
    mesh.calc_loop_triangles()
    bm = bmesh.new()
    try:
        bm.from_mesh(mesh)
        bm.verts.ensure_lookup_table()
        bm.verts.index_update()
        unseen = set(range(len(bm.verts)))
        sizes = []
        while unseen:
            seed = unseen.pop()
            stack = [seed]
            size = 0
            while stack:
                current = bm.verts[stack.pop()]
                size += 1
                for edge in current.link_edges:
                    neighbor = edge.other_vert(current).index
                    if neighbor in unseen:
                        unseen.remove(neighbor)
                        stack.append(neighbor)
            sizes.append(size)
        coords = [v.co for v in bm.verts]
        diagonal_sq = sum(
            (max(v[i] for v in coords) - min(v[i] for v in coords)) ** 2
            for i in range(3)
        ) if coords else 0.0
        area_epsilon = diagonal_sq * 1e-14
        return {
            "vertices": len(bm.verts),
            "edges": len(bm.edges),
            "faces": len(bm.faces),
            "triangles": len(mesh.loop_triangles),
            "boundary_edges": sum(e.is_boundary for e in bm.edges),
            "wire_edges": sum(e.is_wire for e in bm.edges),
            "edges_with_more_than_two_faces": sum(len(e.link_faces) > 2 for e in bm.edges),
            "non_manifold_edges_including_boundary": sum(not e.is_manifold for e in bm.edges),
            "inconsistent_winding_edges": sum(e.is_manifold and not e.is_contiguous for e in bm.edges),
            "near_zero_area_faces": sum(f.calc_area() <= area_epsilon for f in bm.faces),
            "non_finite_vertices": sum(not all(math.isfinite(c) for c in v.co) for v in bm.verts),
            "connected_components": len(sizes),
            "largest_component_vertices": max(sizes, default=0),
            "uv_layers": len(mesh.uv_layers),
            "area_epsilon_local_units_squared": area_epsilon,
        }
    finally:
        bm.free()


def audit_file(input_path, output_path):
    if not bpy.app.background:
        raise RuntimeError("Use a fresh background Blender; this tool must not clear a GUI scene.")
    source = Path(input_path).resolve()
    target = Path(output_path).resolve()
    if source.suffix.lower() != ".glb" or not source.is_file():
        raise ValueError("Input must be an existing .glb file")
    if source == target or target.exists():
        raise FileExistsError("Output must be a new file, never the input or an existing report")
    if target.suffix.lower() != ".json":
        raise ValueError("Output must have a .json extension")
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(source))
    objects = []
    for obj in sorted(bpy.context.scene.objects, key=lambda item: item.name):
        if obj.type == "MESH":
            objects.append({
                "object": obj.name,
                "world_dimensions_blender_units": list(obj.dimensions),
                "material_slots": len(obj.material_slots),
                **analyze_mesh(obj.data),
            })
    if not objects:
        raise ValueError("No mesh objects found in GLB")
    report = {
        "schema_version": 1,
        "input_name": source.name,
        "blender_version": bpy.app.version_string,
        "scope": "Imported base meshes; no welding, modifiers, deformation or repairs",
        "limitations": [
            "Boundary edges can be UV/normal splits, not necessarily visible holes",
            "Disconnected components can be intentional",
            "Does not test self-intersections, appearance, rigging or printability",
            "Triangle total counts mesh object instances, not unique shared mesh data",
        ],
        "total_triangles": sum(obj["triangles"] for obj in objects),
        "mesh_objects": objects,
        "images": [{"name": im.name, "width": im.size[0], "height": im.size[1]}
                   for im in bpy.data.images if im.type == "IMAGE"],
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])
    report = audit_file(args.input, args.output)
    print(f"Audit saved: {len(report['mesh_objects'])} mesh objects, {report['total_triangles']} triangles")


if __name__ == "__main__":
    main()
