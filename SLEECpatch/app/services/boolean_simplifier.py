"""Small Boolean AST; comparison/arithmetic leaves retain their source spelling.

The serializer uses explicit parentheses, as required by the SLEEC grammar.
Negations count once (as Boolean operators), never twice.
"""
import re


def parse_expression(text):
    text = text.strip()
    if not text:
        return ('atom', 'true')
    if text.startswith('('):
        depth = 0
        for i, c in enumerate(text):
            depth += (c == '(') - (c == ')')
            if depth == 0:
                if i == len(text)-1:
                    return parse_expression(text[1:-1])
                break
    for op in ('or', 'and'):
        depth = 0
        for match in re.finditer(r'\(|\)|\b(?:and|or)\b', text):
            token = match.group()
            depth += (token == '(') - (token == ')')
            if depth == 0 and token == op:
                return (op, parse_expression(text[:match.start()]), parse_expression(text[match.end():]))
    if re.match(r'not\b', text):
        return ('not', parse_expression(text[3:]))
    # Relational expressions require parentheses in the concrete grammar.
    if re.search(r'[<>=]', text):
        text = '(' + text + ')'
    return ('atom', text)


def simplify(node):
    op = node[0]
    if op == 'atom': return node
    left = simplify(node[1])
    if op == 'not':
        if left[0] == 'not': return left[1]
        if left in [('atom', 'true'), ('atom', 'false')]:
            return ('atom', 'false' if left[1] == 'true' else 'true')
        return (op, left)
    right = simplify(node[2])
    identity = ('atom', 'true' if op == 'and' else 'false')
    absorbing = ('atom', 'false' if op == 'and' else 'true')
    if left == right: return left
    if left == identity: return right
    if right == identity: return left
    if left == absorbing or right == absorbing: return absorbing
    return (op, left, right)


def serialize(node):
    if node[0] == 'atom': return node[1]
    if node[0] == 'not': return '(not ' + serialize(node[1]) + ')'
    return '(' + serialize(node[1]) + ' ' + node[0] + ' ' + serialize(node[2]) + ')'


def simplify_expression(text):
    return serialize(simplify(parse_expression(text)))


def simplify_rule(text):
    # Rule/response syntax is left intact; only complete condition spans change.
    def trigger(m):
        return m[1] + simplify_expression(m[2]) + m[3]
    text = re.sub(r'(\bwhen\s+\w+\s+and\s+)(.*?)(\s+then\b)', trigger, text, flags=re.S)
    edits = []
    for match in re.finditer(r'\bunless\s+', text):
        start = match.end()
        if start >= len(text): continue
        opener = text[start]
        if opener in '({':
            closer = ')' if opener == '(' else '}'
            depth = 0
            end = start
            for end in range(start, len(text)):
                depth += (text[end] == opener) - (text[end] == closer)
                if depth == 0:
                    end += 1
                    break
        else:
            stop = re.search(r'\s+(?:then|unless)\b|\n|}', text[start:])
            end = start + stop.start() if stop else len(text)
        edits.append((start, end, simplify_expression(text[start:end])))
    for start, end, replacement in reversed(edits):
        text = text[:start] + replacement + text[end:]
    return text


def simplify_patch(patch):
    patch = dict(patch)
    patch['proposed_rule'] = simplify_rule(patch.get('proposed_rule', ''))
    if patch.get('new_rule'): patch['new_rule'] = simplify_rule(patch['new_rule'])
    return patch
