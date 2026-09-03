"""CSV import and export may only name attributes their models actually have.

The standing half of the v3.3.0 CSV fix. Three importers and two exporters were
naming attributes that do not exist, and the fixed cases are covered by
round-trip tests elsewhere; this is the guard that catches the next one.

It is here because the bug class is invisible at every other layer:

- **Export** reads `record.premium` on a model whose column is
  `premium_amount`. Python raises `AttributeError` at request time, so the
  route 500s for any vehicle that has such a record and passes for every
  vehicle that does not.
- **Import** constructs `WarrantyRecord(coverage=...)`. SQLAlchemy's
  declarative constructor raises `TypeError`, which the enclosing
  `except Exception` turns into `add_error(row, "Invalid record data")`. The
  endpoint then returns **HTTP 200** with an error per row, so the response
  blames the user's CSV for an application bug. Nobody reports that.

Tax was the case both earlier hand-written enumerations missed, and it is the
one that shows why a standing guard beats a list: tax EXPORT was always fine,
so enumerating outward from the export bug could not reach it. Four nonexistent
kwargs meant no tax record had ever imported.

`test_the_enumerators_find_what_they_claim_to` is the guard on the guard. Both
walkers infer bindings from code shape, and a refactor that changed the shape
would make them return nothing and every assertion here pass vacuously.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm import RelationshipProperty

import app.models as models

EXPORT = Path("app/routes/export.py")
IMPORT = Path("app/routes/import_data.py")


def _mapped(name: str) -> type | None:
    """The mapped class exported under this name, or None."""
    cls = getattr(models, name, None)
    if cls is None:
        return None
    try:
        sa_inspect(cls)
    except Exception:
        return None
    return cls


def _attrs(cls: type) -> set[str]:
    """Every attribute the mapper knows: columns, relationships, synonyms.

    This is exactly the set SQLAlchemy's declarative constructor accepts, so a
    kwarg outside it is the `TypeError` the importer swallows.
    """
    return set(sa_inspect(cls).attrs.keys())


def _relationship_target(cls: type, attr: str) -> type | None:
    prop = sa_inspect(cls).attrs.get(attr)
    if isinstance(prop, RelationshipProperty):
        return prop.mapper.class_
    return None


def _functions(tree: ast.AST):
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            yield node


def _select_bindings(fn: ast.AST) -> dict[str, type]:
    """Variables holding rows of a model: `x = (await db.execute(select(M))).scalars().all()`.

    These are QUERY variables, not row variables. Reads on them (`result.scalars()`)
    are not model attribute reads, which is why the checker below looks only at
    loop targets.
    """
    bound: dict[str, type] = {}
    for node in ast.walk(fn):
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name):
            continue
        found: type | None = None
        for call in ast.walk(node.value):
            if (
                isinstance(call, ast.Call)
                and isinstance(call.func, ast.Name)
                and call.func.id == "select"
            ):
                for arg in call.args:
                    name = None
                    if isinstance(arg, ast.Name):
                        name = arg.id
                    elif isinstance(arg, ast.Attribute) and isinstance(arg.value, ast.Name):
                        name = arg.value.id
                    if name and (cls := _mapped(name)):
                        found = cls
        if found is not None:
            bound[target.id] = found
            continue
        for sub in ast.walk(node.value):
            if isinstance(sub, ast.Name) and sub.id in bound:
                bound[target.id] = bound[sub.id]
                break
    return bound


def _iterations(fn: ast.AST):
    """Every row-producing scope: `for` statements AND comprehensions.

    Comprehensions matter as much as statements. `export_vehicle_json` selects
    six models and contains no `for` STATEMENT at all, so a walker handling
    only `ast.For` would skip the largest handler in the file and report a
    clean run.

    Each is yielded with its OWN body, because bindings do not survive between
    them: `export_vehicle_json` reuses the name `r` for fuel, DEF and hours
    rows in three sibling comprehensions, and a per-function binding table
    resolves all of them to whichever came last.
    """
    for node in ast.walk(fn):
        if isinstance(node, ast.For):
            yield node.target, node.iter, node.body
        elif isinstance(node, ast.ListComp | ast.SetComp | ast.GeneratorExp | ast.DictComp):
            elts = [node.key, node.value] if isinstance(node, ast.DictComp) else [node.elt]
            for gen in node.generators:
                yield gen.target, gen.iter, elts + list(gen.ifs)


def export_attribute_reads() -> list[tuple[str, type, str]]:
    """Every `<row>.<attr>` an export handler reads, with the model it is on.

    A nested loop over a relationship (`for item in visit.line_items`) is bound
    to the RELATED model rather than the outer one. An earlier version of this
    walker treated it as the outer model and reported `export_service_records`
    as broken; the count went 3 to 2 when that was fixed, which is why the
    resolution is by relationship rather than by skipping nested loops.
    """
    tree = ast.parse(EXPORT.read_text())
    reads: list[tuple[str, type, str]] = []

    for fn in _functions(tree):
        queries = _select_bindings(fn)
        for target, iterable, body in _iterations(fn):
            if not isinstance(target, ast.Name):
                continue
            row_model: type | None = None
            if isinstance(iterable, ast.Name):
                row_model = queries.get(iterable.id)
            elif isinstance(iterable, ast.Attribute) and isinstance(iterable.value, ast.Name):
                outer = queries.get(iterable.value.id)
                # `for item in visit.line_items`: the outer name may itself be a
                # row variable rather than a query variable, so fall back to the
                # models any loop in this function binds.
                if outer is None:
                    for t2, it2, _b2 in _iterations(fn):
                        if (
                            isinstance(t2, ast.Name)
                            and t2.id == iterable.value.id
                            and isinstance(it2, ast.Name)
                        ):
                            outer = queries.get(it2.id)
                            break
                if outer is not None:
                    row_model = _relationship_target(outer, iterable.attr)
            if row_model is None:
                continue
            for stmt in body:
                for node in ast.walk(stmt):
                    if (
                        isinstance(node, ast.Attribute)
                        and isinstance(node.value, ast.Name)
                        and node.value.id == target.id
                    ):
                        reads.append((fn.name, row_model, node.attr))
    return reads


def import_constructions() -> list[tuple[int, type, list[str]]]:
    """Every `Model(...)` built by the importer, with its keyword names."""
    tree = ast.parse(IMPORT.read_text())
    built: list[tuple[int, type, list[str]]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            continue
        cls = _mapped(node.func.id)
        if cls is None:
            continue
        built.append((node.lineno, cls, [kw.arg for kw in node.keywords if kw.arg]))
    return built


def test_every_import_construction_uses_real_attributes():
    offenders = [
        f"{IMPORT.name}:{line} {cls.__name__} {sorted(set(kwargs) - _attrs(cls))}"
        for line, cls, kwargs in import_constructions()
        if set(kwargs) - _attrs(cls)
    ]
    assert offenders == [], (
        "These constructions name attributes their model does not have. "
        "SQLAlchemy raises TypeError, the importer's `except Exception` turns "
        "it into 'Invalid record data', and the endpoint answers 200 blaming "
        f"the user's file: {offenders}"
    )


def test_every_export_read_is_a_real_attribute():
    #: Read on a model instance but not mapped. `metadata` is SQLAlchemy's own
    #: and `_sa_instance_state` is internal; neither is a column, and neither is
    #: the defect this guards.
    # `hasattr`, not the mapper set. The export defect is an AttributeError at
    # request time, so a hybrid property or a plain `@property` on the model is
    # a perfectly good read even though it is not a mapped column.
    # `ServiceVisit.calculated_total_cost` is exactly that, and a mapper-only
    # check calls it broken.
    offenders = sorted(
        {
            f"{fn}: {cls.__name__}.{attr}"
            for fn, cls, attr in export_attribute_reads()
            if not hasattr(cls, attr)
        }
    )
    assert offenders == [], (
        "These export handlers read attributes their model does not have, "
        f"which is a 500 for any vehicle that has such a record: {offenders}"
    )


class TestTheEnumeratorsFindWhatTheyClaimTo:
    """Both walkers infer from code shape, so both can silently find nothing."""

    def test_the_export_walker_sees_a_known_read(self):
        reads = {(fn, cls.__name__, attr) for fn, cls, attr in export_attribute_reads()}
        assert ("export_warranties_csv", "WarrantyRecord", "policy_number") in reads

    def test_the_export_walker_sees_comprehensions_too(self):
        """`export_vehicle_json` has no `for` STATEMENT.

        It selects six models and reads them all inside list comprehensions, so
        a walker handling only `ast.For` would skip the biggest handler in the
        file while reporting a clean run.
        """
        names = {fn for fn, _c, _a in export_attribute_reads()}
        assert "export_vehicle_json" in names

    def test_the_export_walker_resolves_a_nested_relationship(self):
        """`for item in visit.line_items` is a ServiceLineItem, not a ServiceVisit.

        Binding it to the outer model produced a false positive that read as a
        third broken handler.
        """
        reads = {(cls.__name__, attr) for _f, cls, attr in export_attribute_reads()}
        assert any(cls == "ServiceLineItem" for cls, _ in reads), reads

    def test_the_import_walker_sees_a_known_construction(self):
        built = {
            (cls.__name__, tuple(sorted(kwargs))) for _l, cls, kwargs in import_constructions()
        }
        assert any(cls == "WarrantyRecord" for cls, _ in built), built

    @pytest.mark.parametrize("cls_name", ["WarrantyRecord", "InsurancePolicy", "TaxRecord"])
    def test_the_three_repaired_importers_are_still_walked(self, cls_name: str):
        """Named individually, because these are the three that were broken.

        A refactor that moved one of them out of `import_data.py` would take it
        out of this guard's reach, and the guard would keep passing.
        """
        assert any(cls.__name__ == cls_name for _l, cls, _k in import_constructions())
