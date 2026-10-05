"""精确四则运算和一元一次方程：AST 白名单 + Fraction，无 eval。"""
import ast
from fractions import Fraction


def bounded(value):
    if max(value.numerator.bit_length(), value.denominator.bit_length()) > 4096:
        raise ValueError("数值超出计算限制")
    return value


def parse(expression):
    if not isinstance(expression, str) or not expression.strip() or len(expression) > 256:
        raise ValueError("表达式必须为 1–256 字符")
    expression = expression.strip()
    try:
        tree = ast.parse(expression, mode="eval")
    except (SyntaxError, RecursionError) as exc:
        raise ValueError("表达式语法错误") from exc
    if sum(1 for _ in ast.walk(tree)) > 100:
        raise ValueError("表达式过于复杂")
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Expression, ast.BinOp, ast.UnaryOp, ast.Constant,
                                 ast.Name, ast.Load, ast.Add, ast.Sub, ast.Mult,
                                 ast.Div, ast.UAdd, ast.USub)):
            raise ValueError("仅支持数字、x、括号和 + - * /，不支持函数或幂")
        if isinstance(node, ast.Name) and node.id != "x":
            raise ValueError("唯一支持的未知数为 x")
        if isinstance(node, ast.Constant):
            if type(node.value) not in (int, float):
                raise ValueError("仅允许数字常量")
            raw = ast.get_source_segment(expression, node)
            # 限制指数后再构造 Fraction，避免极端指数耗尽资源。
            if "e" in raw.lower():
                if abs(int(raw.lower().split("e")[1])) > 100:
                    raise ValueError("科学计数法指数超限")
            node.exact = bounded(Fraction(raw))
    return tree.body


def linear(node):
    """返回 ax+b 的 (a,b)，拒绝非线性项和含未知数的分母。"""
    if isinstance(node, ast.Constant):
        return Fraction(0), node.exact
    if isinstance(node, ast.Name):
        return Fraction(1), Fraction(0)
    if isinstance(node, ast.UnaryOp):
        a, b = linear(node.operand)
        return (-a, -b) if isinstance(node.op, ast.USub) else (a, b)
    a, b = linear(node.left)
    c, d = linear(node.right)
    if isinstance(node.op, ast.Add):
        result = a+c, b+d
    elif isinstance(node.op, ast.Sub):
        result = a-c, b-d
    elif isinstance(node.op, ast.Mult):
        if a and c:
            raise ValueError("不支持非线性方程")
        result = a*d+b*c, b*d
    else:
        if c:
            raise ValueError("分母不能包含未知数")
        if not d:
            raise ValueError("不能除以零")
        result = a/d, b/d
    return tuple(bounded(v) for v in result)


def calculate(expression):
    """接收纯算式或等式，返回精确分数结果。百分比请写成 /100。"""
    if not isinstance(expression, str) or len(expression) > 256:
        raise ValueError("表达式长度超限")
    if "=" in expression:
        if expression.count("=") != 1:
            raise ValueError("仅支持一个等号")
        left, right = expression.split("=")
        a, b = linear(parse(left))
        c, d = linear(parse(right))
        if a == c:
            raise ValueError("方程无唯一解")
        value = bounded((d-b)/(a-c))
        kind = "equation"
    else:
        tree = parse(expression)
        if any(isinstance(n, ast.Name) for n in ast.walk(tree)):
            raise ValueError("含 x 时必须提供完整方程")
        _, value = linear(tree)
        kind = "expression"
    return {"expression": expression, "kind": kind, "result": str(value)}


def calculate_verified(expression):
    # 校验是强制后置步骤，不交由模型选择，不接收模型自报的结果。
    from .verifier import verify
    calculation = calculate(expression)
    verification = verify(calculation)
    if not verification["valid"]:
        raise ValueError("计算结果未通过代入校验")
    return {"calculation": calculation, "verification": verification}


def result_footer(result):
    calculation = result["calculation"]
    label = "x = " if calculation["kind"] == "equation" else ""
    return f"[工具核验结果] {calculation['expression']}；{label}{calculation['result']}"


from typing import Annotated
from pydantic import Field
from .base import ToolSpec

TOOL = ToolSpec(
    name="calculator",
    description=("精确四则运算和一元一次方程，计算任务应使用此工具。"
                 "参数为纯算式或方程字符串，未知数只能为 x；支持数字、小数、括号、+ - * / 和一个等号。"
                 "乘法显式写 *，百分比写 /100，例如 x*(1+20/100)*(1-20/100)=96。"
                 "不支持函数、幂、非线性、多未知数。自动核验计算/代入，但不证明列式符合题意。"),
    argument_type=Annotated[str, Field(min_length=1, max_length=256)],
    handler=calculate_verified, max_calls=2, require_success=True,
    result_footer=result_footer,
)
