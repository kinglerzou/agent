"""Capability-restricted arithmetic interpreter, NOT arbitrary-code isolation."""
import ast
import math
import operator

OPERATORS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
             ast.Div: operator.truediv, ast.Mod: operator.mod}


def calculate(expression):
    if not isinstance(expression, str) or not 1 <= len(expression) <= 200:
        raise ValueError('表达式长度必须为 1–200')
    tree = ast.parse(expression, mode='eval')
    if len(list(ast.walk(tree))) > 64:
        raise ValueError('表达式过于复杂')

    def visit(node):
        if isinstance(node, ast.Expression):
            return visit(node.body)
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            value = node.value
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            value = visit(node.operand) * (-1 if isinstance(node.op, ast.USub) else 1)
        elif isinstance(node, ast.BinOp) and type(node.op) in OPERATORS:
            value = OPERATORS[type(node.op)](visit(node.left), visit(node.right))
        else:
            raise ValueError('仅允许数字、括号、加减乘除和取余；禁止执行代码')
        if abs(value) > 1e12 or not math.isfinite(value):
            raise ValueError('结果超出预算')
        return value

    return str(visit(tree))
