"""Independent checks of the facts/rules/cost contract. Run unittest discover -s tests."""
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from engine import parse_document, generate_tasks, estimate_quote

ROOT = Path(__file__).resolve().parents[1]


def part(**updates):
    value = {"id": "WOOD-01", "name": "侧板", "category": "wood", "material": "多层板",
             "length": 1000, "width": 500, "thickness": 18, "quantity": 2, "unit": "mm",
             "finish": "白色烤漆", "source": {"file": "drawing.csv", "reference": "row2", "revision": "A"},
             "review_status": "pending", "issues": []}
    value.update(updates)
    return value


def dxf(entity_pairs, insunits=4):
    header = [(0, "SECTION"), (2, "HEADER")]
    if insunits is not None:
        header += [(9, "$INSUNITS"), (70, insunits)]
    pairs = header + [(0, "ENDSEC"), (0, "SECTION"), (2, "ENTITIES")] + entity_pairs + [(0, "ENDSEC"), (0, "EOF")]
    return "\n".join(f"{c}\n{v}" for c, v in pairs).encode()


def rectangle(metadata=None, handle="AB", layer="0", width=10, height=20, bulge=False):
    pairs = [(0, "LWPOLYLINE"), (5, handle), (8, layer), (90, 4), (70, 1)]
    for x, y in [(0, 0), (width, 0), (width, height), (0, height)]:
        pairs += [(10, x), (20, y)]
    if bulge:
        pairs += [(42, .5)]
    if metadata is not None:
        pairs += [(1001, "CABINET_PART"), (1000, json.dumps(metadata))]
    return pairs


class ImportTests(unittest.TestCase):
    def test_csv_chinese_headers_and_explicit_quantity(self):
        data = "编号,名称,类别,材料,长度,宽度,厚度,数量,单位,表面处理\nW1,侧板,木工,多层板,100,50,1.8,2,cm,烤漆\n".encode()
        result = parse_document("test.csv", data)
        self.assertEqual(result["status"], "parsed")
        p = result["parts"][0]
        self.assertEqual((p["length"], p["width"], p["thickness"]), (1000, 500, 18))
        self.assertEqual(p["quantity"], 2)
        self.assertEqual(p["review_status"], "pending")
        self.assertIn("2", p["source"]["reference"])

    def test_csv_mm_aliases_and_model_sources(self):
        result = parse_document("bridge.csv", b"id,name,category,material,length_mm,width_mm,thickness_mm,quantity,finish,source_file,source_reference,revision\nA,Panel,wood,Plywood,100,50,18,2,unpainted,source.SLDPRT,Default,B\n")
        p = result["parts"][0]
        self.assertEqual(p["length"], 100)
        self.assertEqual(p["source"]["model_file"], "source.SLDPRT")
        self.assertEqual(p["source"]["model_reference"], "Default")
        self.assertEqual(p["source"]["revision"], "B")
        self.assertEqual(p["source"]["part_number"], "A")

    def test_generated_id_is_not_claimed_as_a_source_part_number(self):
        result = parse_document("no-id.csv", b"name,category,material,quantity\nLight,electrical,LED,1\n")
        self.assertTrue(result["parts"][0]["id"].startswith("P-"))
        self.assertNotIn("part_number", result["parts"][0]["source"])

    def test_json_units_and_missing_never_filled(self):
        result = parse_document("test.json", json.dumps({"unit": "in", "parts": [{"name": "panel", "category": "wood", "length": 10}]}).encode())
        p = result["parts"][0]
        self.assertEqual(p["length"], 254)
        self.assertIsNone(p["quantity"])
        self.assertIsNone(p["width"])
        self.assertIsNone(p["thickness"])
        self.assertEqual(p["material"], "")
        self.assertGreater(len(p["issues"]), 3)
        self.assertEqual(result["status"], "needs_review")

    def test_unstated_dimension_units_are_not_mm(self):
        result = parse_document("unit.csv", b"name,category,material,length,width,thickness,quantity\npanel,wood,plywood,10,20,1,2\n")
        self.assertIsNone(result["parts"][0]["length"])
        self.assertTrue(any("单位" in issue for issue in result["parts"][0]["issues"]))

    def test_zero_negative_nan_and_fractional_quantity(self):
        payload = [part(length=0, width=-1, thickness="NaN", quantity=0), part(id="B", quantity=1.5)]
        result = parse_document("x.json", json.dumps(payload).encode())
        p = result["parts"][0]
        self.assertIsNone(p["length"])
        self.assertIsNone(p["width"])
        self.assertIsNone(p["thickness"])
        self.assertIsNone(p["quantity"])
        self.assertTrue(any("整数" in x for x in result["parts"][1]["issues"]))

    def test_identical_ids_keep_every_bom_row_pending_without_merging_quantity(self):
        result = parse_document("x.json", json.dumps([part(), part()]).encode())
        self.assertEqual(len(result["parts"]), 2)
        self.assertEqual([p["quantity"] for p in result["parts"]], [2, 2])
        self.assertEqual(len({p["id"] for p in result["parts"]}), 2)
        self.assertTrue(all(any("重复编号需确认" in x for x in p["issues"]) for p in result["parts"]))
        self.assertTrue(all(p["review_status"] == "pending" for p in result["parts"]))
        self.assertTrue(any("未自动累加或去重" in x for x in result["warnings"]))

    def test_conflicting_ids_are_kept_flagged_with_unique_internal_ids(self):
        result = parse_document("x.json", json.dumps([part(), part(width=600)]).encode())
        self.assertEqual(len(result["parts"]), 2)
        self.assertNotEqual(result["parts"][0]["id"], result["parts"][1]["id"])
        self.assertTrue(all(any("重复" in x for x in p["issues"]) for p in result["parts"]))

    def test_unknown_material_does_not_guess_trade(self):
        result = parse_document("x.json", json.dumps([{"name": "unknown", "material": "钢化玻璃", "quantity": 1}]).encode())
        self.assertIsNone(result["parts"][0]["category"])
        self.assertEqual(generate_tasks(result["parts"]), [])

    def test_bad_csv_and_json_fail_explicitly(self):
        for filename, content in [("x.json", b"bad"), ("x.json", b'{"parts": "not-list"}'),
                                  ("x.csv", b"name,name\nA,B"), ("x.csv", b"name,category\nA,wood,extra"), ("x.csv", b"")]:
            with self.subTest(filename=filename, content=content):
                result = parse_document(filename, content)
                self.assertEqual(result["status"], "error")
                self.assertEqual(result["parts"], [])

    def test_native_formats_and_binary_dxf_require_conversion(self):
        for filename, content in [("x.SLDPRT", b"CAD"), ("x.SLDASM", b"CAD"), ("x.DWG", b"CAD"),
                                  ("x.STEP", b"ISO-10303"), ("x.pdf", b"%PDF"), ("x.dxf", b"AutoCAD Binary DXF\r\n")]:
            with self.subTest(filename=filename):
                result = parse_document(filename, content)
                self.assertEqual(result["status"], "needs_conversion")
                self.assertEqual(result["parts"], [])


class DxfTests(unittest.TestCase):
    def test_xdata_rectangle_dimensions_units_and_evidence(self):
        metadata = {"id": "A", "name": "Panel", "category": "wood", "material": "Plywood", "thickness": .5, "quantity": 2, "finish": "paint"}
        result = parse_document("panel.dxf", dxf(rectangle(metadata), insunits=1))
        p = result["parts"][0]
        self.assertEqual((p["length"], p["width"], p["thickness"]), (254, 508, 12.7))
        self.assertEqual(p["source"]["handle"], "AB")
        self.assertEqual(result["geometry"][0]["points"][2], [254, 508])

    def test_explicit_cut_properties_override_view_dimensions(self):
        metadata = {"name": "Panel", "category": "wood", "material": "Plywood", "length_mm": 1200, "width_mm": 450, "thickness_mm": 18, "quantity": 1, "finish": "paint"}
        result = parse_document("view.dxf", dxf(rectangle(metadata, width=1200, height=18)))
        self.assertEqual(result["parts"][0]["width"], 450)

    def test_partial_explicit_dimension_alias_is_not_overridden(self):
        metadata = {"name": "Panel", "category": "wood", "material": "Plywood", "length_mm": 1200, "thickness_mm": 18, "quantity": 1, "finish": "paint"}
        result = parse_document("view.dxf", dxf(rectangle(metadata, width=10, height=450)))
        self.assertEqual(result["parts"][0]["length"], 1200)
        self.assertEqual(result["parts"][0]["width"], 450)

    def test_unknown_units_never_promote_geometry_to_mm(self):
        metadata = {"name": "Panel", "category": "wood", "material": "Plywood", "thickness": 18, "quantity": 2}
        result = parse_document("unitless.dxf", dxf(rectangle(metadata), insunits=0))
        p = result["parts"][0]
        self.assertIsNone(p["length"])
        self.assertIsNone(p["width"])
        self.assertEqual(result["geometry"][0]["units"], "drawing")
        self.assertTrue(any("INSUNITS" in x for x in result["warnings"]))

    def test_no_attributes_means_geometry_only(self):
        result = parse_document("bare.dxf", dxf(rectangle()))
        self.assertEqual(len(result["geometry"]), 1)
        self.assertEqual(result["parts"], [])
        self.assertTrue(any("未提供" in x for x in result["warnings"]))

    def test_layer_contract_requires_explicit_quantity(self):
        result = parse_document("layer.dxf", dxf(rectangle(layer="CABINET::wood::Side::Plywood::18::paint")))
        self.assertIsNone(result["parts"][0]["quantity"])
        result2 = parse_document("layer.dxf", dxf(rectangle(layer="CABINET::wood::Side::Plywood::18::paint::4")))
        self.assertEqual(result2["parts"][0]["quantity"], 4)

    def test_curved_polygon_is_not_rectangular_cut_size(self):
        result = parse_document("curve.dxf", dxf(rectangle({"name": "Panel", "category": "wood", "quantity": 1}, bulge=True)))
        self.assertIsNone(result["parts"][0]["length"])
        self.assertTrue(result["geometry"][0]["approximate"])

    def test_insert_attributes_retain_handle_without_fake_geometry(self):
        entities = [(0, "INSERT"), (5, "C5"), (8, "WOOD"), (2, "CAB_PANEL"), (10, 10), (20, 20)]
        for key, value in {"name": "Panel", "category": "wood", "material": "Plywood", "quantity": 3, "length": 1200, "width": 450, "thickness": 18, "finish": "paint"}.items():
            entities += [(0, "ATTRIB"), (2, "CABINET_" + key.upper()), (1, value)]
        entities += [(0, "SEQEND")]
        result = parse_document("block.dxf", dxf(entities))
        self.assertEqual(result["parts"][0]["quantity"], 3)
        self.assertEqual(result["parts"][0]["source"]["handle"], "C5")
        self.assertEqual(result["geometry"][0]["type"], "insert")
        self.assertNotIn("points", result["geometry"][0])
        self.assertTrue(any("不展开" in x for x in result["warnings"]))

    def test_legacy_polyline(self):
        entity = [(0, "POLYLINE"), (5, "E1"), (8, "CABINET::glass::Shelf::Glass::8::polished::2"), (70, 1)]
        for x, y in [(0, 0), (100, 0), (100, 50), (0, 50)]:
            entity += [(0, "VERTEX"), (10, x), (20, y)]
        entity += [(0, "SEQEND")]
        result = parse_document("legacy.dxf", dxf(entity))
        self.assertEqual(result["parts"][0]["length"], 100)
        self.assertEqual(result["parts"][0]["width"], 50)

    def test_malformed_dxf_does_not_produce_a_bom(self):
        result = parse_document("bad.dxf", b"0\nSECTION\n2")
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["parts"], [])


class TaskTests(unittest.TestCase):
    def test_dependency_graph_covers_every_terminal_and_is_acyclic(self):
        parts = [part(id=category, category=category) for category in ["wood", "metal", "glass", "electrical", "hardware"]]
        tasks = generate_tasks(parts)
        by_id = {task["id"]: task for task in tasks}
        self.assertEqual(len(by_id), len(tasks))
        seen = set()
        for task in tasks:
            self.assertTrue(set(task["dependencies"]) <= seen)
            seen.add(task["id"])
            self.assertEqual(task["status"], "draft")
            self.assertIsNone(task["assignee"])
            self.assertTrue(task["rule_id"])
        terminal_ids = {next(t["id"] for t in reversed(tasks) if t["part_id"] == p["id"]) for p in parts}
        self.assertEqual(set(by_id["T-FINAL-assembly"]["dependencies"]), terminal_ids)
        self.assertEqual(by_id["T-FINAL-electrical"]["dependencies"], ["T-FINAL-assembly"])
        self.assertEqual(by_id["T-FINAL-electrical"]["trade"], "电工")
        self.assertEqual(by_id["T-FINAL-quality"]["dependencies"], ["T-FINAL-electrical"])
        self.assertEqual(by_id["T-FINAL-pack"]["dependencies"], ["T-FINAL-quality"])

    def test_quantity_scales_component_hours_once(self):
        one = generate_tasks([part(quantity=1)])
        four = generate_tasks([part(quantity=4)])
        for a, b in zip(one, four):
            self.assertEqual(b["hours"], a["hours"] * 4 if a["part_id"] else a["hours"])

    def test_paint_only_when_explicitly_applicable(self):
        self.assertFalse(any(t["trade"] == "油漆" for t in generate_tasks([part(finish="饰面板免漆")])) )
        self.assertTrue(any(t["trade"] == "油漆" for t in generate_tasks([part(finish="喷粉")])) )

    def test_missing_quantity_means_unknown_hours(self):
        self.assertTrue(all(t["hours"] is None for t in generate_tasks([part(quantity=None)])))

    def test_no_electrical_parts_skip_final_electrical_operation(self):
        tasks = generate_tasks([part()])
        by_id = {t["id"]: t for t in tasks}
        self.assertNotIn("T-FINAL-electrical", by_id)
        self.assertEqual(by_id["T-FINAL-quality"]["dependencies"], ["T-FINAL-assembly"])

    def test_duplicate_id_cannot_create_colliding_dependencies(self):
        with self.assertRaises(ValueError):
            generate_tasks([part(), part()])


class QuoteTests(unittest.TestCase):
    def test_known_quote_uses_area_count_loss_overhead_and_true_margin(self):
        p = part()
        tasks = [{"id": "T", "part_id": p["id"], "title": "cut", "trade": "木工", "hours": 2}]
        settings = {"material_rates": {"多层板": {"unit_price": 100, "pricing_unit": "m2"}},
                    "hourly_rates": {"木工": 50}, "loss_rate": .1, "overhead_rate": .2,
                    "outsourcing_cost": 30, "margin_rate": .25}
        q = estimate_quote([p], tasks, settings)
        self.assertTrue(q["complete"])
        self.assertEqual(q["material_cost"], 100) # 1m × .5m × 2pcs
        self.assertEqual(q["labor_cost"], 100)
        self.assertEqual(q["waste_cost"], 10)
        self.assertEqual(q["overhead_cost"], 48) # (100+100+10+30) × .2
        self.assertEqual(q["total_cost"], 288)
        self.assertEqual(q["suggested_price"], 384) # 288 / (1-.25), not ×1.25

    def test_unpriced_material_or_labor_never_gives_complete_zero_quote(self):
        q = estimate_quote([part()], generate_tasks([part()]), {})
        self.assertFalse(q["complete"])
        self.assertIsNone(q["suggested_price"])
        self.assertIsNone(q["total_cost"])
        self.assertGreater(len(q["missing"]), 1)
        self.assertTrue(all(line["amount"] is None for line in q["lines"]))

    def test_piece_volume_meter_and_weight_do_not_use_wrong_dimensions(self):
        for unit, expected, updates in [("piece", 20, {}), ("meter", 20, {}), ("m2", 10, {}),
                                         ("m3", .18, {}), ("kg", 50, {"weight_kg": 2.5})]:
            with self.subTest(unit=unit):
                p = part(**updates)
                q = estimate_quote([p], [{"id": "T", "part_id": p["id"], "title": "x", "trade": "木工", "hours": 1}],
                                   {"material_rates": {"wood": {"unit_price": 10, "pricing_unit": unit}}, "hourly_rates": {"木工": 0}})
                self.assertEqual(q["material_cost"], expected)
                self.assertTrue(q["complete"])

    def test_kg_cost_requires_real_weight_not_assumed_density(self):
        p = part(category="metal")
        q = estimate_quote([p], generate_tasks([p]), {"material_rates": {"metal": {"unit_price": 20, "pricing_unit": "kg"}}})
        self.assertFalse(q["complete"])
        self.assertTrue(any("weight_kg" in x for x in q["missing"]))

    def test_invalid_margin_and_negative_rates_cannot_produce_price(self):
        for margin in (1, -1, "NaN"):
            q = estimate_quote([part()], generate_tasks([part()]), {"margin_rate": margin, "outsourcing_cost": -10})
            self.assertFalse(q["complete"])
            self.assertIsNone(q["suggested_price"])

    def test_unknown_part_route_cannot_disappear_from_quote(self):
        p = part(category=None)
        q = estimate_quote([p], [], {"material_rates": {"多层板": {"unit_price": 100, "pricing_unit": "m2"}}})
        self.assertFalse(q["complete"])
        self.assertEqual(q["material_cost"], 100)
        self.assertIsNone(q["total_cost"])

    def test_empty_quote_is_incomplete(self):
        self.assertFalse(estimate_quote([], [], {})["complete"])


class SampleTests(unittest.TestCase):
    def test_supplied_bom_end_to_end(self):
        result = parse_document("showcase-bom.csv", (ROOT / "samples/showcase-bom.csv").read_bytes())
        self.assertEqual(len(result["parts"]), 8)
        self.assertEqual(result["status"], "parsed")
        tasks = generate_tasks(result["parts"])
        settings = json.loads((ROOT / "samples/demo-quote-settings.json").read_text())
        quote = estimate_quote(result["parts"], tasks, settings)
        self.assertTrue(quote["complete"], quote["missing"])
        self.assertGreater(quote["suggested_price"], quote["total_cost"])
        self.assertEqual({t["trade"] for t in tasks}, {"木工", "五金", "油漆", "玻璃", "电工", "装配", "质检", "包装"})

    def test_supplied_dxf_is_true_geometry_and_explicitly_schematic(self):
        result = parse_document("showcase-front-demo.dxf", (ROOT / "samples/showcase-front-demo.dxf").read_bytes())
        self.assertEqual(len(result["parts"]), 5)
        self.assertGreaterEqual(len(result["geometry"]), 10)
        self.assertEqual(result["status"], "needs_review")
        self.assertTrue(all(any("示意" in x for x in p["issues"]) for p in result["parts"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
