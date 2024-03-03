from __future__ import annotations

from typing import List, Any, Union
from collections import defaultdict
from dataclasses import dataclass

import torch

from ..envoy import Envoy
from ..util import fetch_and_set, fetch_attr


class Edit:

    def __init__(self, 
        parent: str, 
        target: str, 
        key: str, 
        replacement: torch.nn.Module,
    ) -> None:
        self.parent = parent
        self.target = target
        self.key = key
        self.replacement = replacement

    def __str__ (self):
        return f"{self.parent}.{self.target} -> {self.key}"
    
    def __repr__(self) -> str:
        return f"{self.parent}.{self.target} -> {self.key}"

class Compiler: 

    def __init__(
        self,
        edits: List[Edit]
    ):
        self.edits = edits
        self.edit_branches = None

    def compile_edits(self, obj):
        self.group_edit_branches()

        print(self.edit_branches)

        for branch in self.edit_branches:
            targets = []
            wrapper_names = []
            wrapper_modules = []

            for edit in self.edit_branches[branch]:
                targets.append(edit.target)
                wrapper_names.append(edit.key)
                wrapper_modules.append(edit.replacement)
                mod = fetch_attr(obj, edit.parent)
                setattr(mod, edit.key, edit.replacement)

            wrapper_dict = dict(zip(wrapper_names, wrapper_modules))
            target_dict = dict(zip(targets, wrapper_names))

            backend = self.get_backend(target_dict, wrapper_dict)    

            parent_module = fetch_attr(obj, branch)        
            edited_module = torch.compile(parent_module, backend=backend, dynamic=True)
            fetch_and_set(obj, branch, edited_module)

    def decompile_edits(self, obj):
        for branch in self.edit_branches:
            fetch_and_set(obj, branch, fetch_attr(obj, branch)._orig_mod)

    def group_edit_branches(self):
        # Normalize attribute strings and group by their root branch
        branches = defaultdict(list)
        for edit in self.edits:
            attr_path = edit.parent
            # Remove leading dot or split[0] is ""
            normalized_attr = attr_path.lstrip('.')
            parts = normalized_attr.split('.')
            root = parts[0] if parts else ""
            branches[root].append(edit)
        
        self.edit_branches = branches

    def get_backend(
        self, 
        target_dict: dict[str, str],
        wrapper_dict: dict[str, torch.nn.Module]
    ):  
        unseen = set(list(target_dict.keys()))

        def edited_backend(gm: torch.fx.GraphModule, _: List[torch.Tensor]):

            for wrapper_name in wrapper_dict.keys():
                gm.add_submodule(wrapper_name, wrapper_dict[wrapper_name])

            for node in gm.graph.nodes:    
                arg_names = [arg.name for arg in node.args if hasattr(arg, "name")]

                for target in target_dict.keys():
                    if target in arg_names and target in unseen:
                        arg_index = arg_names.index(target)
                        
                        with gm.graph.inserting_after(node):
                            wrapper_args = (node.args[arg_index], )
                            wrapper_node = gm.graph.call_module(target_dict[target], args=wrapper_args)
                            node = wrapper_node

                        unseen.remove(target)
                        continue

                if not unseen:
                    break
                    
            gm.recompile()

            print(gm)

            return gm.forward

        return edited_backend

class Editor:
    def __init__(self, obj: object, edits: List[Edit]) -> None:
        self.obj = obj
        self.compiler = Compiler(edits)

    def __enter__(self) -> Editor:
        self.compiler.compile_edits(self.obj)

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.compiler.decompile_edits(self.obj)