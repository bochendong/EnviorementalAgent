"""Bounded integer arithmetic; no environment access, expression eval or hidden-rule fitting."""
import ast
import operator


def evaluate(expression: str) -> int:
    if len(expression) > 256:
        raise ValueError("expression must be at most 256 characters")
    tree = ast.parse(expression, mode="eval")
    if sum(1 for _ in ast.walk(tree)) > 64:
        raise ValueError("expression is too complex")
    binary = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
              ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod}

    def bounded(value):
        if type(value) is not int or abs(value) > 10**12:
            raise ValueError("use integers with magnitude at most 10^12")
        return value

    def visit(node):
        if isinstance(node, ast.Constant):
            return bounded(node.value)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            value = visit(node.operand)
            return value if isinstance(node.op, ast.UAdd) else -value
        if isinstance(node, ast.BinOp) and type(node.op) in binary:
            return bounded(binary[type(node.op)](visit(node.left), visit(node.right)))
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "inv"
                and len(node.args) == 2 and not node.keywords):
            value, modulus = (visit(arg) for arg in node.args)
            if not 2 <= modulus <= 10**9:
                raise ValueError("inverse modulus must be between 2 and 10^9")
            return bounded(pow(value, -1, modulus))
        raise ValueError("allowed: integers, parentheses, +, -, *, //, %, inv(integer, modulus)")

    return visit(tree.body)


def calculator_tool(session):
    from agents import function_tool

    @function_tool
    def calculate(expression: str) -> str:
        """Calculate integer arithmetic: +, -, *, //, %, parentheses; inv(n, m) is modular inverse.
        Free. E.g. '(12+7)%5' (syntax only). It only evaluates your expression, never probes or fits machines.
        """
        try:
            answer = evaluate(expression)
        except (ValueError, SyntaxError, ZeroDivisionError, RecursionError) as error:
            return session.log("calculate", {"expression": expression}, f"Rejected: arithmetic expression: {error}")
        return session.log("calculate", {"expression": expression}, f"{expression} = {answer}")

    return calculate
