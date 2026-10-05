"""独立数值代入核验；不通过重新调用求解器来核验自身。"""
import ast
from fractions import Fraction
from .calculator import parse, bounded


def evaluate(node, x=None):
    if isinstance(node, ast.Constant):
        return node.exact
    if isinstance(node, ast.Name):
        if x is None:
            raise ValueError("缺少 x 的值")
        return x
    if isinstance(node, ast.UnaryOp):
        value = evaluate(node.operand, x)
        return -value if isinstance(node.op, ast.USub) else value
    left, right = evaluate(node.left, x), evaluate(node.right, x)
    if isinstance(node.op, ast.Add):
        value = left + right
    elif isinstance(node.op, ast.Sub):
        value = left - right
    elif isinstance(node.op, ast.Mult):
        value = left * right
    else:
        if not right:
            raise ValueError("不能除以零")
        value = left / right
    return bounded(value)


def verify(calculation):
    expression = calculation["expression"]
    result = Fraction(calculation["result"])
    if calculation["kind"] == "equation":
        left, right = expression.split("=")
        lhs, rhs = evaluate(parse(left), result), evaluate(parse(right), result)
    else:
        lhs, rhs = evaluate(parse(expression)), result
    return {"valid": lhs == rhs, "left": str(lhs), "right": str(rhs),
            "scope": "仅核验算式计算或方程代入，不证明列式符合题意"}
