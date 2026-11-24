"""Walk a layout and expand block references with their full transformation.

AutoCAD rules that matter for a correct takeoff are applied here:

* entities on layer ``0`` inside a block take the layer of the block reference,
  BYBLOCK linetype/colour take the reference's values;
* a block reference on a *frozen* layer hides everything inside it, one on an
  *off* layer hides only its layer-0 content;
* MINSERT arrays are expanded into every row x column instance;
* nested blocks are expanded recursively with the chained transformation.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass

from ezdxf.document import Drawing
from ezdxf.entities import DXFGraphic, Insert
from ezdxf.lldxf.const import DXFTableEntryError
from ezdxf.math import Matrix44


@dataclass(frozen=True)
class Props:
    """Effective properties of one entity occurrence."""

    matrix: Matrix44 | None  # block coordinates -> layout coordinates; None at top level
    layer: str
    linetype: str
    color: str  # ACI number as text ("1".."255") or "#RRGGBB"
    depth: int  # 0 = directly in the layout
    hidden: bool  # on a frozen/off layer, or inside a reference on a frozen layer
    in_frozen: bool = False  # inside a block reference on a frozen layer


class Walker:
    """Iterates over a layout, yielding ``(entity, Props)`` for every occurrence."""

    def __init__(self, doc: Drawing, *, include_hidden: bool = False, descend: bool = True) -> None:
        self.doc = doc
        self.include_hidden = include_hidden
        self.descend = descend
        self.notes: set[str] = set()
        self._layers: dict[str, tuple[bool, bool, str, str]] = {}
        self._names: dict[str, str] = {}

    def layer_info(self, name: str) -> tuple[bool, bool, str, str]:
        """(frozen, off, linetype, colour) of a layer; unknown layers are visible."""
        key = name.upper()
        info = self._layers.get(key)
        if info is None:
            try:
                layer = self.doc.layers.get(name)
            except DXFTableEntryError:
                info = (False, False, "Continuous", "7")
            else:
                color = f"#{layer.dxf.true_color:06X}" if layer.dxf.hasattr("true_color") else str(abs(layer.dxf.color))
                info = (layer.is_frozen(), layer.is_off(), layer.dxf.get("linetype", "Continuous"), color)
            self._layers[key] = info
        return info

    def walk(self, entities: Iterable[DXFGraphic], parent: Props | None = None,
             stack: tuple[str, ...] = ()) -> Iterator[tuple[DXFGraphic, Props]]:
        """Yield every entity, descending into block references when enabled."""
        for entity in entities:
            if entity.dxf.get("invisible", 0):
                continue
            props = self._props(entity, parent)
            yield entity, props
            if self.descend and entity.dxftype() == "INSERT":
                yield from self._expand(entity, props, stack)

    def _props(self, e: DXFGraphic, parent: Props | None) -> Props:
        layer = e.dxf.get("layer", "0") or "0"
        if parent is not None and layer == "0":
            layer = parent.layer
        frozen, off, layer_linetype, layer_color = self.layer_info(layer)
        linetype = e.dxf.get("linetype", "BYLAYER") or "BYLAYER"
        if linetype.upper() == "BYLAYER":
            linetype = layer_linetype
        elif linetype.upper() == "BYBLOCK":
            linetype = parent.linetype if parent else "Continuous"
        aci = e.dxf.get("color", 256)
        if e.dxf.hasattr("true_color"):
            color = f"#{e.dxf.true_color:06X}"
        elif aci == 256:  # BYLAYER
            color = layer_color
        elif aci == 0:  # BYBLOCK
            color = parent.color if parent else "7"
        else:
            color = str(abs(aci))
        in_frozen = parent.in_frozen if parent else False
        return Props(
            matrix=parent.matrix if parent else None,
            layer=layer,
            linetype=linetype,
            color=color,
            depth=parent.depth if parent else 0,
            hidden=in_frozen or frozen or off,
            in_frozen=in_frozen,
        )

    def _expand(self, insert: Insert, props: Props, stack: tuple[str, ...]) -> Iterator[tuple[DXFGraphic, Props]]:
        name = insert.dxf.name
        block = self.doc.blocks.get(name)
        if block is None:
            self.notes.add(f"Block definition {name!r} is missing; its references were counted but not measured.")
            return
        if block.block_record.is_xref:
            self.notes.add(f"External reference {name!r} is not loaded; its geometry was not measured.")
            return
        if name.upper() in stack:
            self.notes.add(f"Block {name!r} references itself; the circular reference was skipped.")
            return
        frozen = props.in_frozen or self.layer_info(props.layer)[0]
        if frozen and not self.include_hidden:
            return
        instances = insert.multi_insert() if insert.mcount > 1 else (insert,)
        for instance in instances:
            matrix = instance.matrix44()
            if props.matrix is not None:
                matrix = matrix @ props.matrix
            context = Props(matrix, props.layer, props.linetype, props.color, props.depth + 1, frozen, frozen)
            yield from self.walk(block, context, stack + (name.upper(),))

    def block_name(self, insert: Insert) -> str:
        """Effective block name: anonymous dynamic-block copies (``*U12``) resolve to the
        name of the dynamic block they were made from."""
        name = insert.dxf.name
        effective = self._names.get(name)
        if effective is None:
            effective = name
            block = self.doc.blocks.get(name) if name.startswith("*") else None
            if block is not None and block.block_record.has_xdata("AcDbBlockRepBTag"):
                for code, value in block.block_record.get_xdata("AcDbBlockRepBTag"):
                    if code == 1005:
                        original = self.doc.entitydb.get(value)
                        if original is not None and original.dxftype() == "BLOCK_RECORD":
                            effective = original.dxf.name
            self._names[name] = effective
        return effective

    def attribs(self, insert: Insert) -> dict[str, str]:
        """Attribute values of a block reference by upper-case tag, incl. constant ATTDEFs."""
        values: dict[str, str] = {}
        block = self.doc.blocks.get(insert.dxf.name)
        if block is not None:
            for attdef in block.get_const_attdefs():
                values[attdef.dxf.tag.upper()] = attdef.dxf.text
        for attrib in insert.attribs:
            values[attrib.dxf.tag.upper()] = attrib.dxf.text
        return values
