"""Small allowlisted utility tools; no model can directly access storage."""

import ast
import operator
from collections.abc import Callable

from langchain_core.tools import tool

_SAFE_OPERATORS: dict[type[ast.operator] | type[ast.unaryop], Callable[..., float]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


@tool
def search_knowledge(query: str) -> str:
    """Reject direct search; callers must use the citation-validating retrieval service."""
    del query
    return "Chỉ dịch vụ retrieval có kiểm chứng nguồn mới được phép trả kết quả kiến thức."


@tool
def calculate(expression: str) -> str:
    """Evaluate a numeric expression with a strict AST/operator allowlist."""
    try:
        return str(_eval_node(ast.parse(expression, mode="eval").body))
    except (SyntaxError, ValueError, TypeError, ZeroDivisionError) as exc:
        return f"Biểu thức không hợp lệ: {exc}"


def _eval_node(node: ast.AST) -> float:
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return float(node.value)
        raise ValueError("Unsupported constant")
    if isinstance(node, ast.UnaryOp):
        operation = _SAFE_OPERATORS.get(type(node.op))
        if operation is None:
            raise ValueError("Unsupported unary operator")
        return float(operation(_eval_node(node.operand)))
    if isinstance(node, ast.BinOp):
        operation = _SAFE_OPERATORS.get(type(node.op))
        if operation is None:
            raise ValueError("Unsupported binary operator")
        return float(operation(_eval_node(node.left), _eval_node(node.right)))
    raise ValueError("Unsupported expression")
