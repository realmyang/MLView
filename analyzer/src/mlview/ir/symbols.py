"""Import-alias resolution to canonical FQNs.

**No rule may match a bare attribute name.** Everything a rule matches comes
from here: `import torch.nn as nn` makes `nn.Linear` resolve to
`torch.nn.Linear`, and nothing else does.

Workspace-local imports resolve to a dotted *workspace* FQN
(`models.net.Net`), which the workspace registries then map to a `ClassIR` or
`FunctionIR`.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Set, Tuple

from ..knowledge import framework_for_module

__all__ = ["SymbolTable", "build_symbol_table", "dotted_name", "dotted_text"]


def dotted_name(node: ast.AST) -> Optional[str]:
    """`a.b.c` -> "a.b.c" for pure Name/Attribute chains, else None."""
    parts: List[str] = []
    cur = node
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr)
        cur = cur.value
    if isinstance(cur, ast.Name):
        parts.append(cur.id)
        return ".".join(reversed(parts))
    return None


def dotted_text(node: ast.AST) -> Optional[str]:
    """Source-ish dotted text, tolerating `self.x.y` and calls in the chain."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = dotted_text(node.value)
        return "%s.%s" % (base, node.attr) if base else None
    if isinstance(node, ast.Call):
        return dotted_text(node.func)
    return None


@dataclass
class SymbolTable:
    """Per-module alias map. Flow-insensitive by design."""

    module_dotted: str
    aliases: Dict[str, str] = field(default_factory=dict)
    star_imports: List[str] = field(default_factory=list)
    imported_modules: List[str] = field(default_factory=list)
    workspace_modules: Set[str] = field(default_factory=set)
    #: (module name as finally resolved, source line) for every import
    #: statement, so `build_workspace` can report the ones that resolved to
    #: nothing while a same-named module exists elsewhere in the workspace.
    import_sites: List[Tuple[str, int]] = field(default_factory=list)

    # -- resolution ---------------------------------------------------------
    def resolve_name(self, name: str) -> Optional[str]:
        return self.aliases.get(name)

    def resolve(self, node: ast.AST) -> Optional[str]:
        """Canonical FQN for a Name/Attribute expression, or None."""
        if isinstance(node, ast.Name):
            return self.aliases.get(node.id)
        if isinstance(node, ast.Attribute):
            base = self.resolve(node.value)
            if base is None:
                return None
            return "%s.%s" % (base, node.attr)
        return None

    def resolve_call(self, node: ast.Call) -> Optional[str]:
        return self.resolve(node.func)

    def is_workspace_fqn(self, fqn: Optional[str]) -> bool:
        if not fqn:
            return False
        head = fqn.split(".")
        for i in range(len(head), 0, -1):
            if ".".join(head[:i]) in self.workspace_modules:
                return True
        return False

    @property
    def frameworks(self) -> Tuple[str, ...]:
        found = []
        for mod in self.imported_modules:
            fw = framework_for_module(mod)
            if fw and fw not in found:
                found.append(fw)
        return tuple(found)


def _relative_base(module_dotted: str, level: int) -> str:
    """Package prefix for a relative import of `level` dots."""
    parts = module_dotted.split(".") if module_dotted else []
    # a module's own package is everything but its final component
    if parts:
        parts = parts[:-1]
    if level > 1:
        drop = level - 1
        parts = parts[:-drop] if drop <= len(parts) else []
    return ".".join(parts)


def _sibling_module(module: str, module_dotted: str,
                    workspace_modules: Set[str]) -> str:
    """`from model import X` inside `pkg/train.py` -> `pkg.model`.

    Python puts the *script's own directory* on `sys.path`, so a bare sibling
    import is the normal shape of `experiments/exp1/train.py` and of this
    repo's own `samples/` tree. Anchoring every module name at the analysis
    root instead made every sibling import resolve to nothing the moment the
    root was one directory higher than the scripts - silently, and with the
    graph and the issue list both changing.
    """
    if not module or not module_dotted or "." not in module_dotted:
        return module
    prefix = module_dotted.rpartition(".")[0]
    candidate = "%s.%s" % (prefix, module)
    if candidate in workspace_modules:
        return candidate
    below = candidate + "."
    if any(w.startswith(below) for w in workspace_modules):
        return candidate
    return module


def build_symbol_table(tree: ast.Module, module_dotted: str,
                       workspace_modules: Sequence[str] = ()) -> SymbolTable:
    """Collect every import in the module (including nested ones)."""
    known = set(workspace_modules)
    table = SymbolTable(module_dotted=module_dotted, workspace_modules=known)

    def sibling(module: str) -> str:
        return _sibling_module(module, module_dotted, known)

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                head = alias.name.split(".")[0]
                target = sibling(alias.name)
                if alias.asname:
                    table.aliases[alias.asname] = target
                else:
                    table.aliases.setdefault(head, target if target != alias.name
                                             else head)
                if head not in table.imported_modules:
                    table.imported_modules.append(head)
                table.import_sites.append((target, getattr(node, "lineno", 1)))
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = _relative_base(module_dotted, node.level)
                module = "%s.%s" % (base, node.module) if node.module else base
            else:
                module = sibling(node.module or "")
            if module and module.split(".")[0] not in table.imported_modules:
                table.imported_modules.append((node.module or module).split(".")[0])
            if module:
                table.import_sites.append((module, getattr(node, "lineno", 1)))
            for alias in node.names:
                if alias.name == "*":
                    if module:
                        table.star_imports.append(module)
                    continue
                local = alias.asname or alias.name
                table.aliases[local] = "%s.%s" % (module, alias.name) if module else alias.name
    return table
