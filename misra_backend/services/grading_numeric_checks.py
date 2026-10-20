"""Bounded arithmetic from literal student text; never marks or repairs.

This is not algebra, OCR, physics validation or a rubric. Unsupported expressions
stay unchecked. Different lines are never assumed to be equivalent.
"""
import ast
import math
import re

VERSION = 'literal_arithmetic_v1'
MAX_EXPRESSION = 200
MAX_VALUE = 1_000_000_000
MAX_CHECKS = 32
_TOKEN = re.compile(r'sqrt|(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d{1,3})?|\*\*|[()+*/^\-]')


def evaluate_numeric_expression(expression):
    """Evaluate a small arithmetic grammar, without eval or name lookup."""
    if not isinstance(expression, str) or not expression.strip():
        return {'status':'unsupported'}
    if len(expression) > MAX_EXPRESSION:
        return {'status':'limit_exceeded'}
    text = expression.strip().replace('−','-').replace('×','*').replace('÷','/')
    text = text.replace('²','^2').replace('³','^3')
    text = re.sub(r'\s*m/s\s*$', '', text)
    tokens, offset = [], 0
    while offset < len(text):
        if text[offset].isspace():
            offset += 1
            continue
        match = _TOKEN.match(text, offset)
        if not match:
            return {'status':'unsupported'}
        tokens.append(match[0])
        offset = match.end()
    expanded = []
    for token in tokens:
        previous_number = bool(expanded) and (expanded[-1][0].isdigit() or expanded[-1].startswith('.'))
        if previous_number and (token[0].isdigit() or token.startswith('.')):
            return {'status':'unsupported'}  # Never turn "2 7" into 27.
        if token == '(' and expanded and (expanded[-1] == ')' or previous_number):
            expanded.append('*')  # Explicit numeric juxtaposition: 2(3), (2)(3).
        expanded.append('**' if token == '^' else token)
    normalized = ''.join(expanded)
    try:
        tree = ast.parse(normalized, mode='eval')
        if sum(1 for _ in ast.walk(tree)) > 64:
            return {'status':'limit_exceeded'}

        def calculate(node):
            if isinstance(node,ast.Constant) and type(node.value) in (int,float):
                value = node.value
            elif isinstance(node,ast.UnaryOp) and isinstance(node.op,(ast.UAdd,ast.USub)):
                value = calculate(node.operand) * (-1 if isinstance(node.op,ast.USub) else 1)
            elif isinstance(node,ast.BinOp) and isinstance(node.op,(ast.Add,ast.Sub,ast.Mult,ast.Div,ast.Pow)):
                left, right = calculate(node.left), calculate(node.right)
                if isinstance(node.op,ast.Add): value = left + right
                elif isinstance(node.op,ast.Sub): value = left - right
                elif isinstance(node.op,ast.Mult): value = left * right
                elif isinstance(node.op,ast.Div): value = left / right
                else:
                    if abs(right) > 8:
                        raise OverflowError()
                    value = left ** right
            elif (isinstance(node,ast.Call) and isinstance(node.func,ast.Name)
                  and node.func.id == 'sqrt' and len(node.args) == 1 and not node.keywords):
                value = math.sqrt(calculate(node.args[0]))
            else:
                raise TypeError()
            if type(value) not in (int,float) or not math.isfinite(value) or abs(value) > MAX_VALUE:
                raise OverflowError()
            return value

        value = calculate(tree.body)
    except (SyntaxError,TypeError):
        return {'status':'unsupported'}
    except (ZeroDivisionError,ValueError):
        return {'status':'domain_error'}
    except (OverflowError,RecursionError):
        return {'status':'limit_exceeded'}
    return {'status':'computed','normalized_expression':normalized,'value':float(value)}


def numeric_context(evidence):
    """Locate RHS arithmetic; never compare a key or infer links between lines.

    Spans refer to unchanged evidence text (end exclusive). Bounded coverage is
    explicit. There is deliberately no score, correctness or tolerance field.
    """
    checks, limited = [], False
    segments = [item for item in evidence if item.get('kind') == 'ocr_segment']
    if not segments:
        segments = [item for item in evidence if item.get('kind') == 'combined_ocr']
    if len(segments) > 16:
        limited = True
    for item in segments[:16]:
        original = item.get('text') or ''
        if not isinstance(original,str):
            continue
        if len(original) > 20000:
            limited = True
        for match in re.finditer(r'=(?!=)([^=;\n]*)',original[:20000]):
            raw = match[1]
            # A prose label for the next assignment is not part of this RHS.
            # Require a colon-delimited label; do not guess where algebra ends.
            boundary = re.search(r'\s+[A-Za-z][A-Za-z _]*:\s*(?:[A-Za-z][A-Za-z0-9_]*)?\s*$',raw)
            if boundary:
                raw = raw[:boundary.start()]
            sentence_end = re.search(r'(?<=\))\.\s*$',raw)
            if sentence_end:
                raw = raw[:sentence_end.start()]
            if not raw.strip():
                continue
            if len(checks) >= MAX_CHECKS:
                limited = True
                break
            start = match.start(1) + len(raw) - len(raw.lstrip())
            end = match.start(1) + len(raw.rstrip())
            expression = original[start:end]
            checks.append({'evidence_ref':item['id'],'text_span':{'start':start,'end':end},
                           'literal_expression':expression[:MAX_EXPRESSION],
                           **evaluate_numeric_expression(expression)})
    return {'version':VERSION,'authority':'Literal arithmetic only; no source confirmation or grading authority',
            'coverage_limited':limited,'checks':checks}
