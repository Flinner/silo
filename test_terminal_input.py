"""Check launch input mode without opening accounts or starting an agent."""
import ast
from pathlib import Path
from types import SimpleNamespace


def test_launch_input():
    tree = ast.parse(Path(__file__).with_name("silo").read_text())
    ui = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "TerminalUI")
    run = next(n for n in ui.body if isinstance(n, ast.FunctionDef) and n.name == "run")
    branch = next(n for n in ast.walk(run) if isinstance(n, ast.If)
                  and ast.unparse(n.test) == "selection.profile and selection.login")
    code = compile(ast.Module(body=branch.body, type_ignores=[]), "launch", "exec")
    for fail in (False, True):
        modes = []

        def launch(selection):
            assert modes == [-1], "launch menus must wait for input"
            if fail:
                raise RuntimeError("launch failed")

        ui = SimpleNamespace(screen=SimpleNamespace(timeout=modes.append), launch=launch)
        try:
            exec(code, {"self": ui, "selection": object()})
        except RuntimeError:
            assert fail
        assert modes == [-1, 150], "dashboard polling must resume after launch"


if __name__ == "__main__":
    test_launch_input()
    print("launch input checks passed")
