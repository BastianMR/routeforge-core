"""Skill discovery and lookup."""

from __future__ import annotations

import importlib
import inspect
import pkgutil

from .base import Skill


class SkillRegistry:
    def __init__(self) -> None:
        self._skills: dict[str, Skill] = {}

    def register(self, skill: Skill) -> None:
        if not skill.name:
            raise ValueError("skill.name must be non-empty")
        self._skills[skill.name] = skill

    def get(self, name: str) -> Skill | None:
        return self._skills.get(name)

    def list(self) -> list[Skill]:
        return list(self._skills.values())

    def discover_builtin(self, package: str = "routeforge.skills.builtin") -> int:
        """Walk the package and register every Skill subclass found. Returns count."""
        pkg = importlib.import_module(package)
        count = 0
        for _finder, module_name, _is_pkg in pkgutil.walk_packages(pkg.__path__, prefix=f"{package}."):
            try:
                module = importlib.import_module(module_name)
            except Exception:
                continue
            for _name, obj in inspect.getmembers(module, inspect.isclass):
                if obj is Skill:
                    continue
                if not issubclass(obj, Skill):
                    continue
                if obj.__module__ != module.__name__:
                    continue
                try:
                    instance = obj()
                except Exception:
                    continue
                if instance.name:
                    self.register(instance)
                    count += 1
        return count
