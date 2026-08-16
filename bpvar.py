"""bpvar — create *typed* Blueprint member variables from Unreal Python.

The problem
-----------
`unreal.BlueprintEditorLibrary.add_member_variable(bp, name, pin_type)` needs an
`unreal.EdGraphPinType`. The obvious way to build one does not work::

    t = unreal.EdGraphPinType()
    t.PinCategory = "int"        # AttributeError
    t.set_editor_property("PinCategory", "int")   # also fails

`EdGraphPinType.PinCategory` is a **protected** UPROPERTY, so it cannot be assigned
from Python, and `dir(t)` reports no fields at all — which makes the struct look
inert. Hand `add_member_variable` a blank `EdGraphPinType()` and it still succeeds:
you get a variable with **no type**. It shows up in the Blueprint, and its Get/Set
nodes will not compile.

The fix
-------
`EdGraphPinType` inherits `import_text`, so the type can be built from its *text*
form instead::

    t = unreal.EdGraphPinType()
    t.import_text('(PinCategory="int",PinSubCategory="",'
                  'PinSubCategoryObject=None,ContainerType=None)')

That round-trips correctly for every scalar category and for Array/Set/Map
containers. `pin_text()` below builds that string; `add()` uses it and then
re-reads the live type to prove the variable actually landed.

Floats: use "real", not "float"
-------------------------------
UE5 renamed float pins. A Blueprint float is `PinCategory="real"` with
`PinSubCategory="double"`. Creating one as `"float"` or `"double"` *succeeds* and
produces a variable — but its pin will not link to anything, and the failed
connection is reported as success. Always use::

    bpvar.add(bp, "Speed", "real", sub_category="double")

...or just `bpvar.add(bp, "Speed", "float")`, which this module rewrites to the
above for you.

Usage
-----
Run inside the Unreal Editor's Python (Output Log > Cmd > Python, or `py`)::

    import bpvar
    BP = "/Game/MyProject/BP_PlayerState"
    bpvar.add(BP, "Gold", "int")
    bpvar.add(BP, "Speed", "float")                       # -> real/double
    bpvar.add(BP, "StashItemIds", "string", container="Array")
    bpvar.add(BP, "ItemsTable", "object", sub_object="/Script/Engine.DataTable")

Self-test (creates a throwaway asset, then deletes it)::

    py bpvar.py --selftest

Requires: Unreal Engine 5 with the Python Editor Script Plugin and Editor
Scripting Utilities enabled. No third-party plugins.
"""

from __future__ import annotations

import argparse
import sys

__all__ = ["Drift", "CATEGORIES", "CONTAINERS", "pin_text", "add", "selftest"]
__version__ = "0.1.0"


class Drift(Exception):
    """Live editor state disagreed with what we just wrote."""


# PinCategory strings accepted by EdGraphPinType.
CATEGORIES = {
    "bool", "byte", "int", "int64", "real", "double", "float",
    "name", "string", "text", "object", "class", "struct", "enum",
}
CONTAINERS = {"None", "Array", "Set", "Map"}


def pin_text(category: str, *, sub_object: str = "", container: str = "None",
             sub_category: str = "") -> str:
    """Build the text form of an EdGraphPinType.

    This is the only way to construct one from Python — see the module docstring.

    "float"/"double" are rewritten to UE5's real/double pair unless an explicit
    `sub_category` is given, because a variable made as a bare "float" creates a
    pin that silently refuses to connect.

    >>> pin_text("int")
    '(PinCategory="int",PinSubCategory="",PinSubCategoryObject=None,ContainerType=None)'
    >>> pin_text("float")
    '(PinCategory="real",PinSubCategory="double",PinSubCategoryObject=None,ContainerType=None)'
    """
    if category not in CATEGORIES:
        raise ValueError(f"unknown PinCategory {category!r}; expected one of {sorted(CATEGORIES)}")
    if container not in CONTAINERS:
        raise ValueError(f"unknown ContainerType {container!r}; expected one of {sorted(CONTAINERS)}")

    if category in ("float", "double") and not sub_category:
        category, sub_category = "real", "double"

    obj = f'"{sub_object}"' if sub_object else "None"
    return (f'(PinCategory="{category}",PinSubCategory="{sub_category}",'
            f'PinSubCategoryObject={obj},ContainerType={container})')


def add(bp: str, name: str, category: str, *, sub_object: str = "",
        container: str = "None", sub_category: str = "") -> None:
    """Add a typed member variable to a Blueprint, then verify it by readback.

    Compiles and saves afterwards — Unreal does not list a new member in the
    action database until the Blueprint is recompiled, so a variable added
    without this step looks like it was never created.

    Raises Drift if the live type does not match what was requested.
    """
    import unreal  # deferred: pin_text() and its tests run without the editor

    text = pin_text(category, sub_object=sub_object, container=container,
                    sub_category=sub_category)
    bel, eal = unreal.BlueprintEditorLibrary, unreal.EditorAssetLibrary

    asset = eal.load_asset(bp)
    if asset is None:
        raise Drift(f"{bp}: no such asset")

    pin = unreal.EdGraphPinType()
    pin.import_text(text)

    if name not in list(bel.list_member_variable_names(asset)):
        bel.add_member_variable(asset, name, pin)
    bel.compile_blueprint(asset)
    eal.save_asset(bp)

    # Re-load from disk: an in-memory object can report a write that never
    # persisted. Everything below is read from the reloaded asset.
    asset = eal.load_asset(bp)
    bel.compile_blueprint(asset)

    names = list(bel.list_member_variable_names(asset))
    if name not in names:
        raise Drift(f"{bp}: variable {name!r} did not land (have {names})")

    # get_member_variable_type is not present on every 5.x; when it is missing we
    # can still prove the name landed, just not the type. Say so rather than
    # reporting a verification that did not happen.
    getter = getattr(bel, "get_member_variable_type", None)
    if getter is None:
        print(f"  ! {bp}.{name}: created, but this engine build has no "
              f"get_member_variable_type — type NOT verified")
        return

    live = getter(asset, name)
    live = live.export_text() if live else ""
    want_cat = "real" if category in ("float", "double") and not sub_category else category
    if f'PinCategory="{want_cat}"' not in live:
        raise Drift(f"{bp}.{name}: wanted PinCategory {want_cat!r}, live type is {live[:160]}")
    if f"ContainerType={container}" not in live:
        raise Drift(f"{bp}.{name}: wanted ContainerType {container!r}, live type is {live[:160]}")


# ─── checks ──────────────────────────────────────────────────────────────────

SCRATCH = "/Game/_BpvarSelfTest"

CASES = [
    ("Gold", "int", {}),
    ("Speed", "float", {}),
    ("HasSeenIntro", "bool", {}),
    ("HubDisplayName", "text", {}),
    ("StashItemIds", "string", {"container": "Array"}),
    ("ItemsTable", "object", {"sub_object": "/Script/Engine.DataTable"}),
]


def check_pin_text() -> None:
    """Pure-Python check — runs without Unreal. The string form is the whole trick."""
    assert pin_text("int") == (
        '(PinCategory="int",PinSubCategory="",PinSubCategoryObject=None,ContainerType=None)')
    # float/double must be rewritten to real/double or the pin will not connect.
    assert pin_text("float") == pin_text("real", sub_category="double")
    assert pin_text("double") == pin_text("real", sub_category="double")
    # ...unless the caller was explicit.
    assert 'PinCategory="float"' in pin_text("float", sub_category="float")
    assert "ContainerType=Array" in pin_text("string", container="Array")
    assert 'PinSubCategoryObject="/Script/Engine.DataTable"' in pin_text(
        "object", sub_object="/Script/Engine.DataTable")
    for bad in (("nope", {}), ("int", {"container": "Bag"})):
        try:
            pin_text(bad[0], **bad[1])
        except ValueError:
            pass
        else:
            raise AssertionError(f"pin_text should have rejected {bad}")
    print("pin_text: ok")


def selftest() -> int:
    """Create a throwaway Blueprint, add every case, verify, delete. Needs the editor."""
    check_pin_text()
    import unreal

    eal = unreal.EditorAssetLibrary
    bp = f"{SCRATCH}/BP_BpvarSelfTest"
    print(f"self-test on {bp}\n")

    factory = unreal.BlueprintFactory()
    factory.set_editor_property("parent_class", unreal.SaveGame)
    unreal.AssetToolsHelpers.get_asset_tools().create_asset(
        bp.rsplit("/", 1)[1], SCRATCH, None, factory)
    if not eal.does_asset_exist(bp):
        print("FAILED: could not create the scratch Blueprint")
        return 1

    fails: list[str] = []
    try:
        for name, cat, kw in CASES:
            try:
                add(bp, name, cat, **kw)
                suffix = "[]" if kw.get("container") == "Array" else ""
                print(f"  ok   {name:16s} {cat}{suffix}")
            except Exception as e:  # Drift, or anything the editor raises
                fails.append(f"{name}: {e}")
                print(f"  FAIL {name:16s} {e}")
    finally:
        for asset in eal.list_assets(SCRATCH, recursive=True):
            eal.delete_asset(asset.split(".")[0])
        eal.delete_directory(SCRATCH)
        print("\n  cleanup: scratch deleted")

    if fails:
        print(f"\n{len(fails)} FAILURE(S):")
        for f in fails:
            print(f"  - {f}")
        return 1
    print("\nall cases passed — typed Blueprint variables are scriptable")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--selftest", action="store_true",
                   help="create a throwaway Blueprint and prove every type lands (needs the editor)")
    p.add_argument("--check", action="store_true",
                   help="run the pure-Python pin_text checks only (no editor needed)")
    args = p.parse_args()
    if args.selftest:
        return selftest()
    if args.check:
        check_pin_text()
        return 0
    p.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
