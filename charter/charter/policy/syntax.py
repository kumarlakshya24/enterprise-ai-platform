"""Lexer and parser for the Cedar subset Charter evaluates.

The subset is permit/forbid, an optional when-clause, ==, !=, in, &&, ||, and !.
There is no entity hierarchy, no arithmetic, and no arbitrary functions.
A file that uses syntax outside the subset is a parse error, not a silent allow.
"""

from __future__ import annotations

from dataclasses import dataclass


class PolicySyntaxError(Exception):
    def __init__(self, message: str, line: int, filename: str = "") -> None:
        self.line = line
        self.filename = filename
        where = f"{filename}:{line}" if filename else f"line {line}"
        super().__init__(f"{where}: {message}")


@dataclass(frozen=True)
class EntityRef:
    type_name: str
    id: str


@dataclass(frozen=True)
class Slot:
    name: str
    entity: EntityRef | None


@dataclass(frozen=True)
class FieldPath:
    """A dotted name in a when-clause. Not a filesystem path."""

    parts: tuple[str, ...]

    def dotted(self) -> str:
        return ".".join(self.parts)


@dataclass(frozen=True)
class Lit:
    value: str | bool


@dataclass(frozen=True)
class ListLit:
    values: tuple[str, ...]


@dataclass(frozen=True)
class PathVal:
    path: FieldPath


type Value = Lit | ListLit | PathVal
type Expr = Not | Bin | Compare


@dataclass(frozen=True)
class Not:
    expr: Expr


@dataclass(frozen=True)
class Bin:
    op: str
    left: Expr
    right: Expr


@dataclass(frozen=True)
class Compare:
    path: FieldPath
    op: str
    right: Value


@dataclass(frozen=True)
class Statement:
    effect: str
    principal: Slot
    action: Slot
    resource: Slot
    when: Expr | None
    rule_id: str
    controls: tuple[str, ...]
    filename: str
    line: int
    end_line: int
    excerpt: str


@dataclass(frozen=True)
class Bundle:
    statements: tuple[Statement, ...]
    files: tuple[tuple[str, str], ...]
    digest: str

    def rule_ids(self) -> tuple[str, ...]:
        return tuple(statement.rule_id for statement in self.statements)


@dataclass(frozen=True)
class _Tok:
    kind: str
    value: str
    line: int


@dataclass(frozen=True)
class _Ann:
    line: int
    key: str
    value: str


_TWO = ("==", "!=", "&&", "||", "::")
_SINGLE = set("(){};,.[]!")


def _tokenize(text: str, filename: str) -> tuple[list[_Tok], list[_Ann]]:
    tokens: list[_Tok] = []
    annotations: list[_Ann] = []
    i = 0
    line = 1
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == "\n":
            line += 1
            i += 1
            continue
        if ch.isspace():
            i += 1
            continue
        if ch == "/" and i + 1 < n and text[i + 1] == "/":
            end = text.find("\n", i)
            if end < 0:
                end = n
            body = text[i + 2 : end].strip()
            if body.startswith("@"):
                key, _, rest = body[1:].partition(" ")
                annotations.append(_Ann(line, key.strip(), rest.strip()))
            i = end
            continue
        two = text[i : i + 2]
        if two in _TWO:
            tokens.append(_Tok(two, two, line))
            i += 2
            continue
        if ch in _SINGLE:
            tokens.append(_Tok(ch, ch, line))
            i += 1
            continue
        if ch == '"':
            j = i + 1
            chars: list[str] = []
            while j < n and text[j] != '"':
                if text[j] == "\\":
                    j += 1
                    if j >= n:
                        raise PolicySyntaxError("unterminated escape", line, filename)
                    chars.append(text[j])
                    j += 1
                    continue
                if text[j] == "\n":
                    raise PolicySyntaxError("unterminated string", line, filename)
                chars.append(text[j])
                j += 1
            if j >= n or text[j] != '"':
                raise PolicySyntaxError("unterminated string", line, filename)
            tokens.append(_Tok("STRING", "".join(chars), line))
            i = j + 1
            continue
        if ch.isalpha() or ch == "_":
            j = i + 1
            while j < n and (text[j].isalnum() or text[j] == "_"):
                j += 1
            tokens.append(_Tok("IDENT", text[i:j], line))
            i = j
            continue
        raise PolicySyntaxError(f"unexpected {ch!r}", line, filename)
    tokens.append(_Tok("EOF", "", line))
    return tokens, annotations


class _Parser:
    def __init__(self, tokens: list[_Tok], filename: str) -> None:
        self.tokens = tokens
        self.filename = filename
        self.i = 0

    def peek(self) -> _Tok:
        return self.tokens[self.i]

    def _error(self, message: str) -> PolicySyntaxError:
        return PolicySyntaxError(message, self.peek().line, self.filename)

    def _eat_kind(self, kind: str) -> _Tok:
        tok = self.peek()
        if tok.kind != kind:
            raise self._error(f"expected {kind}, found {tok.value or tok.kind}")
        self.i += 1
        return tok

    def _eat_word(self, word: str) -> _Tok:
        tok = self.peek()
        if tok.kind != "IDENT" or tok.value != word:
            raise self._error(f"expected {word}")
        self.i += 1
        return tok

    def _ident(self) -> _Tok:
        tok = self.peek()
        if tok.kind != "IDENT":
            raise self._error("expected an identifier")
        self.i += 1
        return tok

    def parse_statements(self) -> list[tuple[Statement, int, int]]:
        found: list[tuple[Statement, int, int]] = []
        while self.peek().kind != "EOF":
            found.append(self._statement())
        return found

    def _statement(self) -> tuple[Statement, int, int]:
        effect_tok = self.peek()
        if effect_tok.kind != "IDENT" or effect_tok.value not in ("permit", "forbid"):
            raise self._error("expected permit or forbid")
        effect = effect_tok.value
        self.i += 1
        self._eat_kind("(")
        principal = self._slot()
        self._eat_kind(",")
        action = self._slot()
        self._eat_kind(",")
        resource = self._slot()
        self._eat_kind(")")
        when: Expr | None = None
        if self.peek().kind == "IDENT" and self.peek().value == "when":
            self.i += 1
            self._eat_kind("{")
            when = self._or()
            self._eat_kind("}")
        end = self._eat_kind(";")
        placeholder = Statement(
            effect=effect,
            principal=principal,
            action=action,
            resource=resource,
            when=when,
            rule_id="",
            controls=(),
            filename=self.filename,
            line=effect_tok.line,
            end_line=end.line,
            excerpt="",
        )
        return placeholder, effect_tok.line, end.line

    def _slot(self) -> Slot:
        tok = self.peek()
        if tok.kind != "IDENT" or tok.value not in ("principal", "action", "resource"):
            raise self._error("expected principal, action, or resource")
        name = tok.value
        self.i += 1
        if self.peek().kind == "==":
            self.i += 1
            return Slot(name, self._entity())
        return Slot(name, None)

    def _entity(self) -> EntityRef:
        type_tok = self._ident()
        self._eat_kind("::")
        literal = self._eat_kind("STRING")
        return EntityRef(type_tok.value, literal.value)

    def _or(self) -> Expr:
        left = self._and()
        while self.peek().kind == "||":
            self.i += 1
            left = Bin("||", left, self._and())
        return left

    def _and(self) -> Expr:
        left = self._unary()
        while self.peek().kind == "&&":
            self.i += 1
            left = Bin("&&", left, self._unary())
        return left

    def _unary(self) -> Expr:
        if self.peek().kind == "!":
            self.i += 1
            return Not(self._unary())
        return self._primary()

    def _primary(self) -> Expr:
        if self.peek().kind == "(":
            self.i += 1
            expr = self._or()
            self._eat_kind(")")
            return expr
        return self._compare()

    def _compare(self) -> Compare:
        path = self._path()
        op_tok = self.peek()
        if op_tok.kind in ("==", "!="):
            op = op_tok.kind
            self.i += 1
        elif op_tok.kind == "IDENT" and op_tok.value == "in":
            op = "in"
            self.i += 1
        else:
            raise self._error("expected ==, !=, or in")
        return Compare(path, op, self._value())

    def _path(self) -> FieldPath:
        first = self._ident()
        parts = [first.value]
        while self.peek().kind == ".":
            self.i += 1
            parts.append(self._ident().value)
        return FieldPath(tuple(parts))

    def _value(self) -> Value:
        tok = self.peek()
        if tok.kind == "STRING":
            self.i += 1
            return Lit(tok.value)
        if tok.kind == "[":
            return self._list()
        if tok.kind == "IDENT" and tok.value in ("true", "false"):
            self.i += 1
            return Lit(tok.value == "true")
        if tok.kind == "IDENT":
            return PathVal(self._path())
        raise self._error("expected a value")

    def _list(self) -> ListLit:
        self._eat_kind("[")
        values: list[str] = []
        if self.peek().kind != "]":
            values.append(self._eat_kind("STRING").value)
            while self.peek().kind == ",":
                self.i += 1
                if self.peek().kind == "]":
                    break
                values.append(self._eat_kind("STRING").value)
        self._eat_kind("]")
        return ListLit(tuple(values))


def _controls(raw: str) -> tuple[str, ...]:
    parts = [part.strip() for part in raw.split(",")]
    return tuple(part for part in parts if part)


def _attach(
    text: str,
    filename: str,
    parsed: list[tuple[Statement, int, int]],
    annotations: list[_Ann],
) -> list[Statement]:
    lines = text.splitlines()
    statements: list[Statement] = []
    prev = 0
    unnamed = 0
    for statement, start, end in parsed:
        mine = [ann for ann in annotations if prev < ann.line < start]
        prev = end
        rule_id = ""
        controls: tuple[str, ...] = ()
        for ann in mine:
            if ann.key == "id":
                rule_id = ann.value
            elif ann.key == "controls":
                controls = _controls(ann.value)
        if not rule_id:
            unnamed += 1
            rule_id = f"R-UNNAMED-{filename}-{unnamed}"
        excerpt_from = mine[0].line if mine else start
        excerpt = "\n".join(lines[excerpt_from - 1 : end])
        statements.append(
            Statement(
                effect=statement.effect,
                principal=statement.principal,
                action=statement.action,
                resource=statement.resource,
                when=statement.when,
                rule_id=rule_id,
                controls=controls,
                filename=filename,
                line=start,
                end_line=end,
                excerpt=excerpt,
            )
        )
    return statements


def parse_file(filename: str, text: str) -> list[Statement]:
    tokens, annotations = _tokenize(text, filename)
    parsed = _Parser(tokens, filename).parse_statements()
    return _attach(text, filename, parsed, annotations)


def parse_policies(files: dict[str, str]) -> tuple[Statement, ...]:
    statements: list[Statement] = []
    for name in sorted(files):
        statements.extend(parse_file(name, files[name]))
    return tuple(statements)
