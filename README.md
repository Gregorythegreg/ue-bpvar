# bpvar

Create **typed** Blueprint member variables from Unreal Python.

Stock UE5. No third-party plugins. One file.

## The problem

`unreal.BlueprintEditorLibrary.add_member_variable(bp, name, pin_type)` wants an
`unreal.EdGraphPinType`. Every obvious way to build one fails:

```python
t = unreal.EdGraphPinType()
t.PinCategory = "int"                          # AttributeError
t.set_editor_property("PinCategory", "int")    # also fails
dir(t)                                         # reports no fields at all
```

`PinCategory` is a **protected** UPROPERTY, so Python cannot assign it.

The trap is that the failure is silent. Hand `add_member_variable` a blank
`EdGraphPinType()` and it **succeeds** — you get a variable with no type. It
appears in the Blueprint, looks fine in the editor, and its Get/Set nodes will
not compile.

## The fix

`EdGraphPinType` inherits `import_text`, so the type can be built from its text
form:

```python
t = unreal.EdGraphPinType()
t.import_text('(PinCategory="int",PinSubCategory="",'
              'PinSubCategoryObject=None,ContainerType=None)')
```

That round-trips for every scalar category and for Array/Set/Map containers.
This module builds that string, uses it, then **re-reads the live type** to
prove the variable landed.

## Install

Drop `bpvar.py` anywhere on your project's Python path — typically
`YourProject/Content/Python/`.

Requires UE5 with **Python Editor Script Plugin** and **Editor Scripting
Utilities** enabled.

## Usage

From the editor's Python console (Output Log → Cmd → Python):

```python
import bpvar

BP = "/Game/MyProject/BP_PlayerState"

bpvar.add(BP, "Gold", "int")
bpvar.add(BP, "Speed", "float")                                    # -> real/double
bpvar.add(BP, "HasSeenIntro", "bool")
bpvar.add(BP, "StashItemIds", "string", container="Array")
bpvar.add(BP, "ItemsTable", "object", sub_object="/Script/Engine.DataTable")
```

`add()` compiles and saves, reloads the asset from disk, and raises `Drift` if
the live type does not match what you asked for. It does not report success
from a return code — every write is read back.

## Gotcha: use `"real"` for floats, not `"float"`

UE5 renamed float pins. A Blueprint float is `PinCategory="real"` with
`PinSubCategory="double"`.

Creating one as `"float"` or `"double"` **succeeds** and produces a variable —
but the resulting pin will not link to anything, and the failed connection is
reported as success. This costs an afternoon to find.

`bpvar` rewrites `"float"`/`"double"` to `real`/`double` for you. Pass an
explicit `sub_category` if you really want the legacy form.

## Categories

`bool` `byte` `int` `int64` `real` `float` `double` `name` `string` `text`
`object` `class` `struct` `enum`

Containers: `None` `Array` `Set` `Map`

## Checks

```bash
python bpvar.py --check      # pure Python, no editor needed
```

```
py bpvar.py --selftest       # in the editor: creates a throwaway
                             # Blueprint, adds every type, deletes it
```

## Status

`--check` (the pin-type string logic) is verified and passing.

`--selftest` needs a running editor. The technique it uses came out of a
production UE5.4 project, but this standalone module is a rewrite of that code
to drop a plugin dependency, and the editor path has not been re-run since the
rewrite. If it breaks on your engine version, please open an issue with the
output — that is the most useful bug report you can file here.

`get_member_variable_type` is missing from some 5.x builds. Where it is absent,
`add()` confirms the variable landed but prints a warning that the *type* was
not verified, rather than claiming a check it did not perform.

## License

MIT
