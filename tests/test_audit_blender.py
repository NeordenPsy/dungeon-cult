"""Run with Blender --background --factory-startup --python-exit-code 1 --python this_file."""

import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

import bmesh
import bpy

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("audit_glb", ROOT / "skills/local-image-to-3d/scripts/audit_glb.py")
AUDIT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUDIT)


class MeshTests(unittest.TestCase):
    def setUp(self):
        bpy.ops.wm.read_factory_settings(use_empty=True)

    def test_closed_cube(self):
        bpy.ops.mesh.primitive_cube_add()
        result = AUDIT.analyze_mesh(bpy.context.object.data)
        self.assertEqual(result["triangles"], 12)
        self.assertEqual(result["boundary_edges"], 0)
        self.assertEqual(result["non_manifold_edges_including_boundary"], 0)
        self.assertEqual(result["connected_components"], 1)

    def test_open_plane(self):
        bpy.ops.mesh.primitive_plane_add()
        result = AUDIT.analyze_mesh(bpy.context.object.data)
        self.assertEqual(result["triangles"], 2)
        self.assertEqual(result["boundary_edges"], 4)

    def test_disconnected_cubes(self):
        mesh = bpy.data.meshes.new("two_cubes")
        bm = bmesh.new()
        bmesh.ops.create_cube(bm, size=1)
        second = bmesh.ops.create_cube(bm, size=1)["verts"]
        bmesh.ops.translate(bm, vec=(3, 0, 0), verts=second)
        bm.to_mesh(mesh)
        bm.free()
        result = AUDIT.analyze_mesh(mesh)
        self.assertEqual(result["connected_components"], 2)
        self.assertEqual(result["largest_component_vertices"], 8)
        self.assertEqual(result["triangles"], 24)

    def test_wire_and_isolated_vertex(self):
        mesh = bpy.data.meshes.new("wire")
        mesh.from_pydata([(0, 0, 0), (1, 0, 0), (3, 0, 0)], [(0, 1)], [])
        result = AUDIT.analyze_mesh(mesh)
        self.assertEqual(result["wire_edges"], 1)
        self.assertEqual(result["connected_components"], 2)
        self.assertEqual(result["triangles"], 0)

    def test_empty_mesh(self):
        result = AUDIT.analyze_mesh(bpy.data.meshes.new("empty"))
        self.assertEqual(result["connected_components"], 0)
        self.assertEqual(result["triangles"], 0)

    def test_three_faces_sharing_edge(self):
        mesh = bpy.data.meshes.new("non_manifold")
        mesh.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0),
                          (0, -1, 0), (0, 0, 1)], [],
                         [(0, 1, 2), (1, 0, 3), (0, 1, 4)])
        self.assertEqual(AUDIT.analyze_mesh(mesh)["edges_with_more_than_two_faces"], 1)

    def test_degenerate_triangle(self):
        mesh = bpy.data.meshes.new("flat_triangle")
        mesh.from_pydata([(0, 0, 0), (1, 0, 0), (2, 0, 0)], [], [(0, 1, 2)])
        self.assertEqual(AUDIT.analyze_mesh(mesh)["near_zero_area_faces"], 1)

    def test_glb_roundtrip_and_no_overwrite(self):
        with tempfile.TemporaryDirectory(prefix="dungeon-cult-audit-") as tmp:
            source = Path(tmp) / "cube.glb"
            output = Path(tmp) / "audit.json"
            bpy.ops.mesh.primitive_cube_add()
            bpy.ops.export_scene.gltf(filepath=str(source), export_format="GLB")
            before = hashlib.sha256(source.read_bytes()).hexdigest()
            result = AUDIT.audit_file(source, output)
            self.assertEqual(result["total_triangles"], 12)
            self.assertEqual(json.loads(output.read_text(encoding="utf-8"))["input_name"], "cube.glb")
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), before)
            with self.assertRaises(FileExistsError):
                AUDIT.audit_file(source, output)
            with self.assertRaises(FileExistsError):
                AUDIT.audit_file(source, source)


suite = unittest.defaultTestLoader.loadTestsFromTestCase(MeshTests)
result = unittest.TextTestRunner(verbosity=2).run(suite)
if not result.wasSuccessful():
    raise RuntimeError("Mesh audit tests failed")
