"""
Py  —  LLVM-backed implementation
=================================

Pipeline:   source -> Lexer -> Parser -> AST -> CodeGen (LLVM IR) -> MCJIT -> native code

What changed versus the tree-walking version
  * §6-§8  Environment / PyFunction / Interpreter  ->  CodeGen + Backend (llvmlite)
  * Every Py function becomes a native LLVM function; top-level code becomes `py_main_N`.
  * Values are tagged structs  %Val = { i32 tag, i64 payload }.
      - int / float / bool / None are handled *inline* in machine code
        (overflow-checked int arithmetic, float arithmetic, comparisons).
      - str / list live on a Python-side heap; payload = handle.  Slow paths
        (str concat, list ops, '/', '//', '%', '**', builtins, methods) call back
        into a small Python runtime through ctypes.
  * Global variables live in a persistent slot table, so the REPL can compile each
    input as a new LLVM module and still share state.
  * Runtime errors set a flag; generated code checks it after every fallible call
    and unwinds, so errors surface as normal PyRuntimeError (REPL keeps working).

Two ways to run
  python py_llvm.py script.ep                   JIT: compile in memory and run (also the REPL)
  python py_llvm.py --compile script.ep -o app  AOT: emit a standalone native executable
      (LLVM object file + the embedded C runtime, linked with cc/gcc/clang; needs a C compiler)

Known limitations (by design, to keep the backend small)
  * Compiled executables treat strings as UTF-8 bytes (len/indexing/upper/lower are byte-wise).
  * Only *named* functions can be called (no calling a function stored in a variable).
  * Nested `def`s do not capture enclosing locals (they see globals only).
  * Ints are 64-bit; overflow raises OverflowError instead of promoting to bigint.
  * str/list objects are never freed (no GC).
"""

from __future__ import annotations
import sys, os, struct, ctypes
from enum import Enum
from dataclasses import dataclass, field
from typing import Any, List, Optional

import llvmlite.ir as ir
import llvmlite.binding as llvm


# ══════════════════════════════════════════════════════════════════════════════
# §1  ERRORS
# ══════════════════════════════════════════════════════════════════════════════


class PyError(Exception):
    """Base class for all Py errors."""

    def __init__(self, message: str, line: int = None):
        self.message = message
        self.line = line
        super().__init__(str(self))

    def __str__(self) -> str:
        loc = f" [line {self.line}]" if self.line else ""
        label = f"\033[91m{type(self).__name__}\033[0m"
        return f"{label}: {self.message}{loc}"

    def plain(self) -> str:
        loc = f" [line {self.line}]" if self.line else ""
        return f"{type(self).__name__}: {self.message}{loc}"


class LexerError(PyError):
    """Illegal character or unterminated literal."""


class ParseError(PyError):
    """Token stream violates the grammar."""


class PyRuntimeError(PyError):
    """Type error, undefined name, wrong arity, etc."""


# ══════════════════════════════════════════════════════════════════════════════
# §2  TOKENS
# ══════════════════════════════════════════════════════════════════════════════


class TT(Enum):
    INTEGER = "INTEGER"
    FLOAT = "FLOAT"
    STRING = "STRING"
    IF = "if"
    ELIF = "elif"
    ELSE = "else"
    WHILE = "while"
    FOR = "for"
    IN = "in"
    DEF = "def"
    RETURN = "return"
    AND = "and"
    OR = "or"
    NOT = "not"
    TRUE = "True"
    FALSE = "False"
    NONE = "None"
    NAME = "NAME"
    PLUS = "+"
    MINUS = "-"
    STAR = "*"
    SLASH = "/"
    PERCENT = "%"
    DOUBLESLASH = "//"
    DOUBLESTAR = "**"
    EQEQUAL = "=="
    NOTEQUAL = "!="
    LESS = "<"
    LESSEQUAL = "<="
    GREATER = ">"
    GREATEREQUAL = ">="
    EQUAL = "="
    PLUSEQUAL = "+="
    MINEQUAL = "-="
    STAREQUAL = "*="
    SLASHEQUAL = "/="
    LPAREN = "("
    RPAREN = ")"
    LBRACKET = "["
    RBRACKET = "]"
    COLON = ":"
    COMMA = ","
    DOT = "."
    NEWLINE = "NEWLINE"
    INDENT = "INDENT"
    DEDENT = "DEDENT"
    EOF = "EOF"


KEYWORDS: dict = {
    "if": TT.IF,
    "elif": TT.ELIF,
    "else": TT.ELSE,
    "while": TT.WHILE,
    "for": TT.FOR,
    "in": TT.IN,
    "def": TT.DEF,
    "return": TT.RETURN,
    "and": TT.AND,
    "or": TT.OR,
    "not": TT.NOT,
    "True": TT.TRUE,
    "False": TT.FALSE,
    "None": TT.NONE,
}

_TWO_CHAR = {
    "**": TT.DOUBLESTAR,
    "//": TT.DOUBLESLASH,
    "==": TT.EQEQUAL,
    "!=": TT.NOTEQUAL,
    "<=": TT.LESSEQUAL,
    ">=": TT.GREATEREQUAL,
    "+=": TT.PLUSEQUAL,
    "-=": TT.MINEQUAL,
    "*=": TT.STAREQUAL,
    "/=": TT.SLASHEQUAL,
}
_ONE_CHAR = {
    "+": TT.PLUS,
    "-": TT.MINUS,
    "*": TT.STAR,
    "/": TT.SLASH,
    "%": TT.PERCENT,
    "=": TT.EQUAL,
    "<": TT.LESS,
    ">": TT.GREATER,
    "(": TT.LPAREN,
    ")": TT.RPAREN,
    "[": TT.LBRACKET,
    "]": TT.RBRACKET,
    ":": TT.COLON,
    ",": TT.COMMA,
    ".": TT.DOT,
}


@dataclass
class Token:
    type: TT
    value: Any
    line: int
    col: int

    def __repr__(self):
        return f"Token({self.type.name}, {self.value!r}, {self.line}:{self.col})"


# ══════════════════════════════════════════════════════════════════════════════
# §3  LEXER
# ══════════════════════════════════════════════════════════════════════════════


class Lexer:
    """Single-pass tokeniser with INDENT/DEDENT and implicit continuation in ()/[]."""

    _ESCAPES = {
        "n": "\n",
        "t": "\t",
        "r": "\r",
        "\\": "\\",
        "'": "'",
        '"': '"',
        "0": "\0",
        "a": "\a",
        "b": "\b",
    }

    def __init__(self, source: str):
        self.source = source
        self.pos = 0
        self.line = 1
        self.col = 1
        self.tokens: list = []
        self.indent_stack = [0]
        self.at_line_start = True
        self.paren_depth = 0

    def tokenize(self) -> List[Token]:
        while self.pos < len(self.source):
            self._next_token()
        self._close_all_indents()
        if self.tokens and self.tokens[-1].type not in (TT.NEWLINE, TT.DEDENT):
            self.tokens.append(Token(TT.NEWLINE, "\n", self.line, self.col))
        self.tokens.append(Token(TT.EOF, None, self.line, self.col))
        return self.tokens

    def _cur(self) -> str:
        return self.source[self.pos] if self.pos < len(self.source) else "\0"

    def _peek(self, n: int = 1) -> str:
        idx = self.pos + n
        return self.source[idx] if idx < len(self.source) else "\0"

    def _here(self) -> tuple:
        return self.line, self.col

    def _advance(self) -> str:
        ch = self.source[self.pos]
        self.pos += 1
        if ch == "\n":
            self.line += 1
            self.col = 1
        else:
            self.col += 1
        return ch

    def _err(self, msg):
        raise LexerError(msg, self.line)

    def _close_all_indents(self):
        while len(self.indent_stack) > 1:
            self.indent_stack.pop()
            self.tokens.append(Token(TT.DEDENT, None, self.line, self.col))

    def _next_token(self):
        if self.at_line_start and self.paren_depth == 0:
            self._handle_indentation()
            return
        ch = self._cur()
        if ch in (" ", "\t"):
            self._advance()
        elif ch == "\n":
            ln, cl = self._here()
            self._advance()
            if self.paren_depth == 0:
                self.tokens.append(Token(TT.NEWLINE, "\n", ln, cl))
                self.at_line_start = True
        elif ch == "\r":
            self._advance()
        elif ch == "#":
            while self._cur() not in ("\n", "\0"):
                self._advance()
        elif ch in ('"', "'"):
            self._read_string()
        elif ch.isdigit():
            self._read_number()
        elif ch.isalpha() or ch == "_":
            self._read_name()
        else:
            self._read_operator()

    def _handle_indentation(self):
        indent = 0
        while self._cur() in (" ", "\t"):
            indent = (indent // 8 + 1) * 8 if self._cur() == "\t" else indent + 1
            self._advance()
        ch = self._cur()
        if ch in ("\n", "\r", "\0") or ch == "#":
            if ch == "#":
                while self._cur() not in ("\n", "\0"):
                    self._advance()
            if self._cur() == "\n":
                self._advance()
            return
        self.at_line_start = False
        current = self.indent_stack[-1]
        if indent > current:
            self.indent_stack.append(indent)
            self.tokens.append(Token(TT.INDENT, indent, self.line, 1))
        elif indent < current:
            while len(self.indent_stack) > 1 and self.indent_stack[-1] > indent:
                self.indent_stack.pop()
                self.tokens.append(Token(TT.DEDENT, indent, self.line, 1))
            if self.indent_stack[-1] != indent:
                self._err(
                    "IndentationError: unindent does not match any outer indentation level"
                )

    def _read_string(self):
        ln, cl = self._here()
        q = self._advance()
        if self._cur() == q and self._peek() == q:
            self._advance()
            self._advance()
            buf = []
            while True:
                ch = self._cur()
                if ch == "\0":
                    self._err("SyntaxError: EOF in triple-quoted string")
                if ch == q and self._peek() == q and self._peek(2) == q:
                    self._advance()
                    self._advance()
                    self._advance()
                    break
                buf.append(
                    self._advance()
                    if ch != "\\"
                    else self._ESCAPES.get(self._advance(), "")
                )
            self.tokens.append(Token(TT.STRING, "".join(buf), ln, cl))
            return
        buf = []
        while True:
            ch = self._cur()
            if ch == "\0":
                self._err("SyntaxError: unterminated string")
            if ch == "\n":
                self._err("SyntaxError: EOL in string")
            if ch == q:
                self._advance()
                break
            if ch == "\\":
                self._advance()
                buf.append(self._ESCAPES.get(self._advance(), ""))
            else:
                buf.append(self._advance())
        self.tokens.append(Token(TT.STRING, "".join(buf), ln, cl))

    def _read_number(self):
        ln, cl = self._here()
        digits = []
        is_float = False
        while self._cur().isdigit():
            digits.append(self._advance())
        if self._cur() == "." and self._peek().isdigit():
            is_float = True
            digits.append(self._advance())
            while self._cur().isdigit():
                digits.append(self._advance())
        if self._cur() in ("e", "E"):
            is_float = True
            digits.append(self._advance())
            if self._cur() in ("+", "-"):
                digits.append(self._advance())
            if not self._cur().isdigit():
                self._err("SyntaxError: invalid numeric literal")
            while self._cur().isdigit():
                digits.append(self._advance())
        text = "".join(digits)
        self.tokens.append(
            Token(
                TT.FLOAT if is_float else TT.INTEGER,
                float(text) if is_float else int(text),
                ln,
                cl,
            )
        )

    def _read_name(self):
        ln, cl = self._here()
        buf = []
        while self._cur().isalnum() or self._cur() == "_":
            buf.append(self._advance())
        name = "".join(buf)
        self.tokens.append(Token(KEYWORDS.get(name, TT.NAME), name, ln, cl))

    def _read_operator(self):
        ln, cl = self._here()
        ch = self._advance()
        two = ch + self._cur()
        if two in _TWO_CHAR:
            self._advance()
            self.tokens.append(Token(_TWO_CHAR[two], two, ln, cl))
            return
        if ch in _ONE_CHAR:
            if ch in "([":
                self.paren_depth += 1
            elif ch in ")]":
                self.paren_depth = max(0, self.paren_depth - 1)
            self.tokens.append(Token(_ONE_CHAR[ch], ch, ln, cl))
            return
        if ch == "!":
            self._err("SyntaxError: '!' must be followed by '='")
        self._err(f"SyntaxError: unexpected character {ch!r}")


# ══════════════════════════════════════════════════════════════════════════════
# §4  AST NODES
# ══════════════════════════════════════════════════════════════════════════════


@dataclass
class ASTNode:
    line: int = 0


@dataclass
class Program(ASTNode):
    body: List[ASTNode] = field(default_factory=list)


@dataclass
class IntLiteral(ASTNode):
    value: int = 0


@dataclass
class FloatLiteral(ASTNode):
    value: float = 0.0


@dataclass
class StringLiteral(ASTNode):
    value: str = ""


@dataclass
class BoolLiteral(ASTNode):
    value: bool = True


@dataclass
class NoneLiteral(ASTNode):
    pass


@dataclass
class Name(ASTNode):
    id: str = ""


@dataclass
class ListLiteral(ASTNode):
    elts: List[ASTNode] = field(default_factory=list)


@dataclass
class Subscript(ASTNode):
    value: ASTNode = None
    index: ASTNode = None


@dataclass
class BinOp(ASTNode):
    left: ASTNode = None
    op: str = ""
    right: ASTNode = None


@dataclass
class UnaryOp(ASTNode):
    op: str = ""
    operand: ASTNode = None


@dataclass
class Compare(ASTNode):
    left: ASTNode = None
    op: str = ""
    right: ASTNode = None


@dataclass
class BoolOp(ASTNode):
    op: str = ""
    values: List[ASTNode] = field(default_factory=list)


@dataclass
class Call(ASTNode):
    func: ASTNode = None
    args: List[ASTNode] = field(default_factory=list)


@dataclass
class MethodCall(ASTNode):
    obj: ASTNode = None
    method: str = ""
    args: List[ASTNode] = field(default_factory=list)


@dataclass
class Assign(ASTNode):
    target: str = ""
    value: ASTNode = None


@dataclass
class AugAssign(ASTNode):
    target: str = ""
    op: str = ""
    value: ASTNode = None


@dataclass
class ExprStmt(ASTNode):
    expr: ASTNode = None


@dataclass
class Return(ASTNode):
    value: Optional[ASTNode] = None


@dataclass
class If(ASTNode):
    test: ASTNode = None
    body: List[ASTNode] = field(default_factory=list)
    orelse: List[ASTNode] = field(default_factory=list)


@dataclass
class While(ASTNode):
    test: ASTNode = None
    body: List[ASTNode] = field(default_factory=list)


@dataclass
class For(ASTNode):
    target: str = ""
    iter: ASTNode = None
    body: List[ASTNode] = field(default_factory=list)


@dataclass
class FuncDef(ASTNode):
    name: str = ""
    params: List[str] = field(default_factory=list)
    body: List[ASTNode] = field(default_factory=list)


# ══════════════════════════════════════════════════════════════════════════════
# §5  PARSER  (unchanged: recursive descent)
# ══════════════════════════════════════════════════════════════════════════════


class Parser:
    def __init__(self, tokens: List[Token]):
        self.tokens = tokens
        self.pos = 0

    def _cur(self) -> Token:
        return self.tokens[min(self.pos, len(self.tokens) - 1)]

    def _peek(self, n=1) -> Token:
        return self.tokens[min(self.pos + n, len(self.tokens) - 1)]

    def _prev(self) -> Token:
        return self.tokens[max(self.pos - 1, 0)]

    def _advance(self) -> Token:
        tok = self._cur()
        if self.pos < len(self.tokens) - 1:
            self.pos += 1
        return tok

    def _check(self, *types: TT) -> bool:
        return self._cur().type in types

    def _match(self, *types: TT) -> bool:
        if self._check(*types):
            self._advance()
            return True
        return False

    def _expect(self, tt: TT, msg: str = "") -> Token:
        if not self._check(tt):
            got = self._cur()
            desc = (
                msg or f"expected '{tt.value}', got '{got.type.value}' ({got.value!r})"
            )
            raise ParseError(f"SyntaxError: {desc}", got.line)
        return self._advance()

    def _err(self, msg: str):
        raise ParseError(f"SyntaxError: {msg}", self._cur().line)

    def _skip_newlines(self):
        while self._check(TT.NEWLINE):
            self._advance()

    def parse(self) -> Program:
        stmts = self._stmt_list()
        self._expect(TT.EOF, "expected end of file")
        return Program(body=stmts, line=1)

    def _stmt_list(self) -> List[ASTNode]:
        stmts = []
        while True:
            self._skip_newlines()
            if self._check(TT.EOF, TT.DEDENT):
                break
            stmts.append(self._stmt())
        return stmts

    def _stmt(self) -> ASTNode:
        self._skip_newlines()
        if self._match(TT.DEF):
            return self._func_def()
        if self._match(TT.IF):
            return self._if_stmt()
        if self._match(TT.WHILE):
            return self._while_stmt()
        if self._match(TT.FOR):
            return self._for_stmt()
        return self._simple_stmt()

    def _simple_stmt(self) -> ASTNode:
        if self._check(TT.RETURN):
            self._advance()
            node = self._return_stmt()
        elif self._check(TT.NAME) and self._peek(1).type == TT.EQUAL:
            node = self._assign()
        elif self._check(TT.NAME) and self._peek(1).type in (
            TT.PLUSEQUAL,
            TT.MINEQUAL,
            TT.STAREQUAL,
            TT.SLASHEQUAL,
        ):
            node = self._aug_assign()
        else:
            node = ExprStmt(expr=self._expr(), line=self._cur().line)
        if self._check(TT.NEWLINE):
            self._advance()
        elif not self._check(TT.EOF, TT.DEDENT):
            self._err(
                f"expected newline after statement, got {self._cur().type.value!r}"
            )
        return node

    def _assign(self) -> Assign:
        t = self._expect(TT.NAME)
        self._expect(TT.EQUAL)
        return Assign(target=t.value, value=self._expr(), line=t.line)

    def _aug_assign(self) -> AugAssign:
        t = self._advance()
        op = self._advance()
        return AugAssign(target=t.value, op=op.value, value=self._expr(), line=t.line)

    def _return_stmt(self) -> Return:
        ln = self._prev().line
        if self._check(TT.NEWLINE, TT.EOF, TT.DEDENT):
            return Return(value=None, line=ln)
        return Return(value=self._expr(), line=ln)

    def _func_def(self) -> FuncDef:
        ln = self._prev().line
        name = self._expect(TT.NAME, "expected function name")
        self._expect(TT.LPAREN, "expected '(' after function name")
        params = []
        if self._check(TT.NAME):
            params.append(self._advance().value)
            while self._match(TT.COMMA):
                if not self._check(TT.NAME):
                    self._err("expected parameter name")
                params.append(self._advance().value)
        self._expect(TT.RPAREN, "expected ')'")
        self._expect(TT.COLON, "expected ':' after function signature")
        body = self._block()
        return FuncDef(name=name.value, params=params, body=body, line=ln)

    def _if_stmt(self) -> If:
        ln = self._prev().line
        test = self._expr()
        self._expect(TT.COLON, "expected ':' after if-condition")
        body = self._block()
        orelse = self._elif_or_else()
        return If(test=test, body=body, orelse=orelse, line=ln)

    def _elif_or_else(self) -> List[ASTNode]:
        self._skip_newlines()
        if self._match(TT.ELIF):
            ln = self._prev().line
            test = self._expr()
            self._expect(TT.COLON, "expected ':' after elif")
            body = self._block()
            orelse = self._elif_or_else()
            return [If(test=test, body=body, orelse=orelse, line=ln)]
        if self._match(TT.ELSE):
            self._expect(TT.COLON, "expected ':' after else")
            return self._block()
        return []

    def _while_stmt(self) -> While:
        ln = self._prev().line
        test = self._expr()
        self._expect(TT.COLON, "expected ':' after while")
        return While(test=test, body=self._block(), line=ln)

    def _for_stmt(self) -> For:
        ln = self._prev().line
        var = self._expect(TT.NAME, "expected loop variable")
        self._expect(TT.IN, "expected 'in'")
        itr = self._expr()
        self._expect(TT.COLON, "expected ':' after for-clause")
        return For(target=var.value, iter=itr, body=self._block(), line=ln)

    def _block(self) -> List[ASTNode]:
        self._expect(TT.NEWLINE, "expected newline before block")
        self._expect(TT.INDENT, "expected indented block")
        stmts = self._stmt_list()
        if not stmts:
            self._err("empty block")
        self._expect(TT.DEDENT, "expected dedent after block")
        return stmts

    def _expr(self) -> ASTNode:
        return self._or_expr()

    def _or_expr(self) -> ASTNode:
        node = self._and_expr()
        if self._check(TT.OR):
            vals = [node]
            while self._match(TT.OR):
                vals.append(self._and_expr())
            return BoolOp(op="or", values=vals, line=node.line)
        return node

    def _and_expr(self) -> ASTNode:
        node = self._not_expr()
        if self._check(TT.AND):
            vals = [node]
            while self._match(TT.AND):
                vals.append(self._not_expr())
            return BoolOp(op="and", values=vals, line=node.line)
        return node

    def _not_expr(self) -> ASTNode:
        if self._match(TT.NOT):
            ln = self._prev().line
            return UnaryOp(op="not", operand=self._not_expr(), line=ln)
        return self._comparison()

    def _comparison(self) -> ASTNode:
        node = self._sum()
        while self._check(
            TT.EQEQUAL, TT.NOTEQUAL, TT.LESS, TT.LESSEQUAL, TT.GREATER, TT.GREATEREQUAL
        ):
            op = self._advance()
            right = self._sum()
            node = Compare(left=node, op=op.value, right=right, line=node.line)
        return node

    def _sum(self) -> ASTNode:
        node = self._term()
        while self._check(TT.PLUS, TT.MINUS):
            op = self._advance().value
            right = self._term()
            node = BinOp(left=node, op=op, right=right, line=node.line)
        return node

    def _term(self) -> ASTNode:
        node = self._factor()
        while self._check(TT.STAR, TT.SLASH, TT.DOUBLESLASH, TT.PERCENT):
            op = self._advance().value
            right = self._factor()
            node = BinOp(left=node, op=op, right=right, line=node.line)
        return node

    def _factor(self) -> ASTNode:
        if self._check(TT.PLUS, TT.MINUS):
            op = self._advance()
            return UnaryOp(op=op.value, operand=self._factor(), line=op.line)
        return self._power()

    def _power(self) -> ASTNode:
        base = self._primary()
        if self._match(TT.DOUBLESTAR):
            ln = self._prev().line
            return BinOp(left=base, op="**", right=self._factor(), line=ln)
        return base

    def _primary(self) -> ASTNode:
        node = self._atom()
        while True:
            if self._check(TT.LPAREN):
                self._advance()
                ln = self._prev().line
                args = self._call_args()
                self._expect(TT.RPAREN, "expected ')' after arguments")
                node = Call(func=node, args=args, line=ln)
            elif self._check(TT.LBRACKET):
                self._advance()
                ln = self._prev().line
                idx = self._expr()
                self._expect(TT.RBRACKET, "expected ']' after index")
                node = Subscript(value=node, index=idx, line=ln)
            elif self._check(TT.DOT):
                self._advance()
                ln = self._prev().line
                name_tok = self._expect(
                    TT.NAME, "expected attribute/method name after '.'"
                )
                if not self._check(TT.LPAREN):
                    self._err(
                        f"attribute access without a call is not supported: '.{name_tok.value}'"
                    )
                self._advance()
                args = self._call_args()
                self._expect(TT.RPAREN, "expected ')' after method arguments")
                node = MethodCall(obj=node, method=name_tok.value, args=args, line=ln)
            else:
                break
        return node

    def _call_args(self) -> List[ASTNode]:
        args = []
        if not self._check(TT.RPAREN):
            args.append(self._expr())
            while self._match(TT.COMMA):
                if self._check(TT.RPAREN):
                    break
                args.append(self._expr())
        return args

    def _atom(self) -> ASTNode:
        tok = self._cur()
        if self._match(TT.INTEGER):
            return IntLiteral(value=tok.value, line=tok.line)
        if self._match(TT.FLOAT):
            return FloatLiteral(value=tok.value, line=tok.line)
        if self._match(TT.STRING):
            return StringLiteral(value=tok.value, line=tok.line)
        if self._match(TT.TRUE):
            return BoolLiteral(value=True, line=tok.line)
        if self._match(TT.FALSE):
            return BoolLiteral(value=False, line=tok.line)
        if self._match(TT.NONE):
            return NoneLiteral(line=tok.line)
        if self._match(TT.NAME):
            return Name(id=tok.value, line=tok.line)
        if self._match(TT.LBRACKET):
            elts = []
            if not self._check(TT.RBRACKET):
                elts.append(self._expr())
                while self._match(TT.COMMA):
                    if self._check(TT.RBRACKET):
                        break
                    elts.append(self._expr())
            self._expect(TT.RBRACKET, "expected ']'")
            return ListLiteral(elts=elts, line=tok.line)
        if self._match(TT.LPAREN):
            node = self._expr()
            self._expect(TT.RPAREN, "expected ')'")
            return node
        self._err(f"unexpected token {tok.type.value!r} ({tok.value!r})")


# ══════════════════════════════════════════════════════════════════════════════
# §6  VALUE MODEL  (tagged values shared by generated code and the runtime)
# ══════════════════════════════════════════════════════════════════════════════

T_NONE, T_BOOL, T_INT, T_FLOAT, T_STR, T_LIST, T_BUILTIN, T_FUNC, T_UNDEF = (
    0,
    1,
    2,
    3,
    4,
    5,
    6,
    7,
    15,
)


class CVal(ctypes.Structure):
    """Mirror of LLVM's %Val = { i32, i64 } (16 bytes, same layout)."""

    _fields_ = [("tag", ctypes.c_int32), ("pay", ctypes.c_int64)]


class FuncRef:
    """Value that stands for a user function (functions are called statically)."""

    def __init__(self, name):
        self.name = name

    def __repr__(self):
        return f"<function {self.name}>"

    __str__ = __repr__


class Heap:
    """Object table: str / list / builtin / FuncRef live here; payload = index."""

    def __init__(self):
        self.objs: list = []
        self.by_id: dict = {}

    def handle(self, obj) -> int:
        h = self.by_id.get(id(obj))
        if h is None:
            h = len(self.objs)
            self.objs.append(obj)  # keeps obj alive -> id() stays unique
            self.by_id[id(obj)] = h
        return h

    def get(self, h: int):
        return self.objs[h]


HEAP = Heap()
INT_MIN, INT_MAX = -(2**63), 2**63 - 1


def encode(v, line=None):
    if v is None:
        return T_NONE, 0
    if isinstance(v, bool):
        return T_BOOL, int(v)
    if isinstance(v, int):
        if not INT_MIN <= v <= INT_MAX:
            raise PyRuntimeError(
                "OverflowError: integer does not fit in 64 bits (LLVM backend)", line
            )
        return T_INT, v
    if isinstance(v, float):
        return T_FLOAT, struct.unpack("<q", struct.pack("<d", v))[0]
    if isinstance(v, str):
        return T_STR, HEAP.handle(v)
    if isinstance(v, list):
        return T_LIST, HEAP.handle(v)
    if isinstance(v, FuncRef):
        return T_FUNC, HEAP.handle(v)
    if callable(v):
        return T_BUILTIN, HEAP.handle(v)
    raise PyRuntimeError(f"InternalError: cannot encode {type(v).__name__}")


def decode(tag: int, pay: int):
    if tag == T_NONE:
        return None
    if tag == T_BOOL:
        return bool(pay)
    if tag == T_INT:
        return pay
    if tag == T_FLOAT:
        return struct.unpack("<d", struct.pack("<q", pay))[0]
    if tag in (T_STR, T_LIST, T_BUILTIN, T_FUNC):
        return HEAP.get(pay)
    raise PyRuntimeError("InternalError: bad value tag")


def put(out, v, line=None):
    t, p = encode(v, line)
    out[0].tag = t
    out[0].pay = p


# ── value helpers ─────────────────────────────────────────────────────────────


def _ep_str(v) -> str:
    if v is None:
        return "None"
    if isinstance(v, bool):
        return "True" if v else "False"
    if isinstance(v, list):
        return "[" + ", ".join(_ep_str(x) for x in v) + "]"
    if isinstance(v, FuncRef):
        return repr(v)
    if callable(v):
        return f"<built-in function {v.__name__.replace('_builtin_', '')}>"
    return str(v)


def _ep_bool(v) -> bool:
    if v is None:
        return False
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return v != 0
    if isinstance(v, (str, list)):
        return len(v) > 0
    return True


def _type_name(v) -> str:
    if v is None:
        return "NoneType"
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, int):
        return "int"
    if isinstance(v, float):
        return "float"
    if isinstance(v, str):
        return "str"
    if isinstance(v, list):
        return "list"
    if isinstance(v, FuncRef):
        return "function"
    if callable(v):
        return "builtin_function"
    return type(v).__name__


# ══════════════════════════════════════════════════════════════════════════════
# §7  BUILTINS  (run in the Python runtime; called from native code)
# ══════════════════════════════════════════════════════════════════════════════


def _builtin_print(args):
    print(*(_ep_str(a) for a in args))
    return None


def _builtin_len(args):
    if len(args) != 1:
        raise PyRuntimeError("TypeError: len() takes exactly 1 argument")
    v = args[0]
    if isinstance(v, (str, list)):
        return len(v)
    raise PyRuntimeError(f"TypeError: object of type '{_type_name(v)}' has no len()")


def _builtin_range(args):
    if not (1 <= len(args) <= 3):
        raise PyRuntimeError("TypeError: range() takes 1–3 arguments")
    iargs = []
    for a in args:
        if not isinstance(a, (int, float)):
            raise PyRuntimeError("TypeError: range() arguments must be integers")
        iargs.append(int(a))
    return list(range(*iargs))


def _builtin_int(args):
    if len(args) != 1:
        raise PyRuntimeError("TypeError: int() takes 1 argument")
    v = args[0]
    if isinstance(v, (bool, int, float)):
        return int(v)
    if isinstance(v, str):
        s = v.strip()
        if s.lstrip("-+").isdigit():
            return int(s)
        raise PyRuntimeError(f"ValueError: invalid literal for int(): {v!r}")
    raise PyRuntimeError(
        f"TypeError: int() argument must be a string or number, not '{_type_name(v)}'"
    )


def _builtin_float(args):
    if len(args) != 1:
        raise PyRuntimeError("TypeError: float() takes 1 argument")
    v = args[0]
    if isinstance(v, (bool, int, float)):
        return float(v)
    if isinstance(v, str) and v.strip():
        try:
            return float(v.strip())
        except ValueError:
            raise PyRuntimeError(
                f"ValueError: could not convert string to float: {v!r}"
            )
    raise PyRuntimeError(
        f"TypeError: float() argument must be a string or number, not '{_type_name(v)}'"
    )


def _builtin_str(args):
    if len(args) != 1:
        raise PyRuntimeError("TypeError: str() takes 1 argument")
    return _ep_str(args[0])


def _builtin_bool(args):
    if len(args) != 1:
        raise PyRuntimeError("TypeError: bool() takes 1 argument")
    return _ep_bool(args[0])


def _builtin_input(args):
    return input(_ep_str(args[0]) if args else "")


def _builtin_abs(args):
    if len(args) != 1:
        raise PyRuntimeError("TypeError: abs() takes 1 argument")
    v = args[0]
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return abs(v)
    raise PyRuntimeError(f"TypeError: bad operand type for abs(): '{_type_name(v)}'")


def _builtin_max(args):
    if not args:
        raise PyRuntimeError("TypeError: max() expected at least 1 argument")
    items = args[0] if len(args) == 1 and isinstance(args[0], list) else args
    if not items:
        raise PyRuntimeError("ValueError: max() arg is an empty sequence")
    try:
        return max(items)
    except TypeError as e:
        raise PyRuntimeError(f"TypeError: {e}")


def _builtin_min(args):
    if not args:
        raise PyRuntimeError("TypeError: min() expected at least 1 argument")
    items = args[0] if len(args) == 1 and isinstance(args[0], list) else args
    if not items:
        raise PyRuntimeError("ValueError: min() arg is an empty sequence")
    try:
        return min(items)
    except TypeError as e:
        raise PyRuntimeError(f"TypeError: {e}")


def _builtin_type(args):
    if len(args) != 1:
        raise PyRuntimeError("TypeError: type() takes 1 argument")
    return f"<class '{_type_name(args[0])}'>"


def _builtin_append(args):
    if len(args) != 2:
        raise PyRuntimeError("TypeError: append() takes 2 arguments")
    lst, val = args
    if not isinstance(lst, list):
        raise PyRuntimeError("TypeError: first argument must be a list")
    lst.append(val)
    return None


def _builtin_pop(args):
    if len(args) not in (1, 2):
        raise PyRuntimeError("TypeError: pop() takes 1 or 2 arguments")
    lst = args[0]
    if not isinstance(lst, list):
        raise PyRuntimeError("TypeError: first argument must be a list")
    idx = int(args[1]) if len(args) == 2 else -1
    if not lst:
        raise PyRuntimeError("IndexError: pop from empty list")
    return lst.pop(idx)


BUILTINS = {
    "print": _builtin_print,
    "len": _builtin_len,
    "range": _builtin_range,
    "int": _builtin_int,
    "float": _builtin_float,
    "str": _builtin_str,
    "bool": _builtin_bool,
    "input": _builtin_input,
    "abs": _builtin_abs,
    "max": _builtin_max,
    "min": _builtin_min,
    "type": _builtin_type,
    "append": _builtin_append,
    "pop": _builtin_pop,
}


# ── slow-path operators (used when the inline fast path doesn't apply) ────────

OPS = ["+", "-", "*", "/", "//", "%", "**", "==", "!=", "<", "<=", ">", ">="]
CMP_OPS = {"==", "!=", "<", "<=", ">", ">="}


def apply_binop(op: str, left: Any, right: Any, line: int) -> Any:
    if op == "+" and isinstance(left, str) and isinstance(right, str):
        return left + right
    if op == "*" and isinstance(left, str) and isinstance(right, (int, float)):
        return left * int(right)
    if op == "*" and isinstance(left, (int, float)) and isinstance(right, str):
        return right * int(left)
    if op == "+" and isinstance(left, list) and isinstance(right, list):
        return left + right
    if op == "*" and isinstance(left, list) and isinstance(right, (int, float)):
        return left * int(right)
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        if op == "+":
            return left + right
        if op == "-":
            return left - right
        if op == "*":
            return left * right
        if op == "**":
            try:
                return left**right
            except ZeroDivisionError:
                raise PyRuntimeError(
                    "ZeroDivisionError: 0 cannot be raised to a negative power", line
                )
            except OverflowError:
                raise PyRuntimeError("OverflowError: result too large", line)
        if op == "%":
            if right == 0:
                raise PyRuntimeError("ZeroDivisionError: modulo by zero", line)
            return left % right
        if op == "/":
            if right == 0:
                raise PyRuntimeError("ZeroDivisionError: division by zero", line)
            return left / right
        if op == "//":
            if right == 0:
                raise PyRuntimeError(
                    "ZeroDivisionError: integer division by zero", line
                )
            return int(left // right)
    raise PyRuntimeError(
        f"TypeError: unsupported operand type(s) for '{op}': "
        f"'{_type_name(left)}' and '{_type_name(right)}'",
        line,
    )


def apply_compare(op: str, left: Any, right: Any, line: int) -> bool:
    if op == "==":
        return left == right
    if op == "!=":
        return left != right
    for v in (left, right):
        if not isinstance(v, (int, float, str)):
            raise PyRuntimeError(
                f"TypeError: '{op}' not supported between '{_type_name(left)}' and '{_type_name(right)}'",
                line,
            )
    try:
        return {
            "<": left < right,
            "<=": left <= right,
            ">": left > right,
            ">=": left >= right,
        }[op]
    except TypeError:
        raise PyRuntimeError(
            f"TypeError: '{op}' not supported between '{_type_name(left)}' and '{_type_name(right)}'",
            line,
        )


# ══════════════════════════════════════════════════════════════════════════════
# §8  RUNTIME  (Python functions exported to LLVM code through ctypes)
# ══════════════════════════════════════════════════════════════════════════════

_CT = {
    "void": None,
    "i32": ctypes.c_int32,
    "i64": ctypes.c_int64,
    "P": ctypes.POINTER(CVal),
}

#            name              (return, [argument types])
RT_SIGS = {
    "rt_binop": ("void", ["i32", "i32", "i64", "i32", "i64", "P", "i32"]),
    "rt_unary": ("void", ["i32", "i32", "i64", "P", "i32"]),
    "rt_truthy": ("i32", ["i32", "i64"]),
    "rt_list_new": ("void", ["i32", "P", "P"]),
    "rt_subscript": ("void", ["i32", "i64", "i32", "i64", "P", "i32"]),
    "rt_call_builtin": ("void", ["i64", "i32", "P", "P", "i32"]),
    "rt_method": ("void", ["i32", "i64", "i64", "i32", "P", "P", "i32"]),
    "rt_iter_len": ("i64", ["i32", "i64", "i32"]),
    "rt_iter_get": ("void", ["i32", "i64", "i64", "P", "i32"]),
    "rt_raise": ("void", ["i64", "i32"]),
}


class Runtime:
    NSLOTS = 8192
    MAX_DEPTH = 4000

    def __init__(self):
        self.err = (ctypes.c_int32 * 1)()  # error flag polled by generated code
        self.depth = (ctypes.c_int32 * 1)()  # call depth counter
        self.error: Optional[PyError] = None
        self.slots = (CVal * self.NSLOTS)()  # global variable storage
        self.slot_idx: dict = {}
        self._callbacks = []
        for name, (ret, args) in RT_SIGS.items():
            impl = getattr(self, "_" + name)
            cb = ctypes.CFUNCTYPE(_CT[ret], *[_CT[a] for a in args])(
                self._guard(impl, ret != "void")
            )
            self._callbacks.append(cb)
            llvm.add_symbol(name, ctypes.cast(cb, ctypes.c_void_p).value)

    # ── globals ───────────────────────────────────────────────────────────────
    def has_slot(self, name) -> bool:
        return name in self.slot_idx

    def slot_addr(self, name) -> int:
        i = self.slot_idx.get(name)
        if i is None:
            i = len(self.slot_idx)
            if i >= self.NSLOTS:
                raise PyRuntimeError("InternalError: too many global variables")
            self.slot_idx[name] = i
            self.slots[i].tag = T_UNDEF
        return ctypes.addressof(self.slots) + i * ctypes.sizeof(CVal)

    # ── error plumbing ────────────────────────────────────────────────────────
    def _fail(self, e: PyError):
        if not self.err[0]:
            self.error = e
            self.err[0] = 1

    def _guard(self, fn, returns):
        def wrapper(*a):
            try:
                return fn(*a)
            except PyError as e:
                self._fail(e)
            except RecursionError:
                self._fail(
                    PyRuntimeError("RecursionError: maximum recursion depth exceeded")
                )
            except Exception as e:  # noqa
                self._fail(PyRuntimeError(f"InternalError: {e}"))
            return 0 if returns else None

        return wrapper

    def take_error(self):
        e, self.error = self.error, None
        self.err[0] = 0
        self.depth[0] = 0
        return e

    # ── callbacks ─────────────────────────────────────────────────────────────
    def _rt_binop(self, op, lt, lp, rt_, rp, out, line):
        l, r, name = decode(lt, lp), decode(rt_, rp), OPS[op]
        v = (
            apply_compare(name, l, r, line)
            if name in CMP_OPS
            else apply_binop(name, l, r, line)
        )
        put(out, v, line)

    def _rt_unary(self, op, t, p, out, line):
        v = decode(t, p)
        sym = "-" if op == 0 else "+"
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            put(out, -v if op == 0 else +v, line)
        else:
            raise PyRuntimeError(
                f"TypeError: bad operand type for unary '{sym}': '{_type_name(v)}'",
                line,
            )

    def _rt_truthy(self, t, p):
        return 1 if _ep_bool(decode(t, p)) else 0

    def _rt_list_new(self, n, arr, out):
        put(out, [decode(arr[i].tag, arr[i].pay) for i in range(n)])

    def _rt_subscript(self, ot, op_, it, ip, out, line):
        obj, idx = decode(ot, op_), decode(it, ip)
        if not isinstance(obj, (list, str)):
            raise PyRuntimeError(
                f"TypeError: '{_type_name(obj)}' object is not subscriptable", line
            )
        if not isinstance(idx, (int, float)):
            raise PyRuntimeError(
                f"TypeError: indices must be integers, not '{_type_name(idx)}'", line
            )
        idx = int(idx)
        if idx < -len(obj) or idx >= len(obj):
            raise PyRuntimeError(
                f"IndexError: index {idx} out of range (length {len(obj)})", line
            )
        put(out, obj[idx], line)

    def _rt_call_builtin(self, name_h, n, args, out, line):
        fn = BUILTINS[HEAP.get(name_h)]
        try:
            put(out, fn([decode(args[i].tag, args[i].pay) for i in range(n)]), line)
        except PyRuntimeError as e:
            if e.line is None:
                e.line = line
            raise

    def _rt_method(self, ot, op_, name_h, n, args, out, line):
        obj, method = decode(ot, op_), HEAP.get(name_h)
        a = [decode(args[i].tag, args[i].pay) for i in range(n)]
        if isinstance(obj, str) and method in ("lower", "upper"):
            if a:
                raise PyRuntimeError(f"TypeError: {method}() takes no arguments", line)
            put(out, getattr(obj, method)(), line)
            return
        raise PyRuntimeError(
            f"AttributeError: '{_type_name(obj)}' object has no attribute '{method}'",
            line,
        )

    def _rt_iter_len(self, t, p, line):
        obj = decode(t, p)
        if not isinstance(obj, (list, str)):
            raise PyRuntimeError(
                f"TypeError: '{_type_name(obj)}' object is not iterable", line
            )
        return len(obj)

    def _rt_iter_get(self, t, p, i, out, line):
        put(out, decode(t, p)[i], line)

    def _rt_raise(self, msg_h, line):
        raise PyRuntimeError(HEAP.get(msg_h), line)


# ══════════════════════════════════════════════════════════════════════════════
# §9  CODE GENERATOR  (AST -> LLVM IR)
# ══════════════════════════════════════════════════════════════════════════════

I1, I32, I64, DBL, VOID = (
    ir.IntType(1),
    ir.IntType(32),
    ir.IntType(64),
    ir.DoubleType(),
    ir.VoidType(),
)
VAL = ir.LiteralStructType([I32, I64])
VALP = ir.PointerType(VAL)
_IRT = {"void": VOID, "i32": I32, "i64": I64, "P": VALP}


def c32(n):
    return ir.Constant(I32, n)


def c64(n):
    return ir.Constant(I64, n)


def const_val(tag: int, pay: int = 0) -> ir.Constant:
    return ir.Constant(VAL, [c32(tag), c64(pay)])


NONE_C, UNDEF_C = const_val(T_NONE), const_val(T_UNDEF)


def _scan(stmts):
    """
    Collect (assigned names, augmented names, nested FuncDefs) of a statement list,
    without descending into function bodies.
    """
    assigned, aug, defs = set(), set(), []

    def walk(ss):
        for s in ss:
            if isinstance(s, Assign):
                assigned.add(s.target)
            elif isinstance(s, AugAssign):
                aug.add(s.target)
            elif isinstance(s, For):
                assigned.add(s.target)
                walk(s.body)
            elif isinstance(s, While):
                walk(s.body)
            elif isinstance(s, If):
                walk(s.body)
                walk(s.orelse)
            elif isinstance(s, FuncDef):
                defs.append(s)

    walk(stmts)
    return assigned, aug, defs


class CodeGen:
    """Lowers one Program into one LLVM module."""

    ARITH = {"+": "sadd", "-": "ssub", "*": "smul"}
    FARITH = {"+": "fadd", "-": "fsub", "*": "fmul"}

    def __init__(self, backend: "Backend"):
        self.be = backend
        self.mod = ir.Module("py_module")
        self.mod.triple = llvm.get_default_triple()
        self.mod.data_layout = str(backend.target_machine.target_data)
        self.fns: dict = {}  # mangled name -> ir.Function (this module)
        self.global_names: set = set()
        # per-function state
        self.fn = self.b = self.eb = self.body_block = None
        self.locals: dict = {}
        self.is_main = False
        self._unwind = None
        self.err_ptr, self.depth_ptr = backend.flag_ptrs(self)

    # ── module-level driver ──────────────────────────────────────────────────
    def compile(self, program: Program):
        assigned, aug, defs = _scan(program.body)
        self.global_names = set(assigned) | set(aug)

        infos, pending = [], list(defs)
        while pending:
            fd = pending.pop(0)
            a, g, nested = _scan(fd.body)
            locs = list(dict.fromkeys(list(fd.params) + sorted(a)))
            self.global_names.add(fd.name)
            self.global_names |= g - set(locs)
            mangled = self.be.mangle(fd.name)
            self.be.funcs[fd.name] = (mangled, len(fd.params))
            infos.append((fd, mangled, locs))
            pending.extend(nested)

        main_name = self.be.mangle("main")
        main = ir.Function(self.mod, ir.FunctionType(VOID, []), main_name)
        self.begin(main, [], [], is_main=True)
        self.stmts(program.body)
        self.finish()

        for fd, mangled, locs in infos:
            fn = self.get_fn(mangled, len(fd.params))
            self.begin(fn, list(fd.params), locs, is_main=False, line=fd.line)
            self.stmts(fd.body)
            self.finish()
        return self.mod, main_name

    def get_fn(self, mangled: str, arity: int) -> ir.Function:
        fn = self.fns.get(mangled)
        if fn is None:
            fn = ir.Function(self.mod, ir.FunctionType(VAL, [VAL] * arity), mangled)
            self.fns[mangled] = fn
        return fn

    def rtfn(self, name: str) -> ir.Function:
        fn = self.fns.get(name)
        if fn is None:
            ret, args = RT_SIGS[name]
            fn = ir.Function(
                self.mod, ir.FunctionType(_IRT[ret], [_IRT[a] for a in args]), name
            )
            self.fns[name] = fn
        return fn

    def call_rt(self, name, args):
        return self.b.call(self.rtfn(name), args)

    # ── function scaffolding ─────────────────────────────────────────────────
    def begin(self, fn, params, local_names, is_main, line=0):
        self.fn, self.is_main, self._unwind = fn, is_main, None
        entry = fn.append_basic_block("entry")
        self.body_block = fn.append_basic_block("body")
        self.eb = ir.IRBuilder(entry)  # entry block: only allocas live here
        self.b = ir.IRBuilder(self.body_block)
        self.locals = {}
        for n in local_names:
            p = self.eb.alloca(VAL, name=n)
            self.eb.store(UNDEF_C, p)
            self.locals[n] = p
        for arg, n in zip(fn.args, params):
            self.eb.store(arg, self.locals[n])
        if not is_main:  # recursion guard
            d = self.b.add(self.b.load(self.depth_ptr), c32(1))
            self.b.store(d, self.depth_ptr)
            over, ok = self._new("deep"), self._new("shallow")
            self.b.cbranch(self.b.icmp_signed(">", d, c32(self.be.max_depth)), over, ok)
            self.b.position_at_end(over)
            self.call_rt(
                "rt_raise",
                [
                    self.be.str_handle(
                        self, "RecursionError: maximum recursion depth exceeded"
                    ),
                    c32(line),
                ],
            )
            self.b.branch(self.unwind())
            self.b.position_at_end(ok)

    def finish(self):
        if not self.b.block.is_terminated:
            self.emit_return(NONE_C)
        self.eb.branch(self.body_block)

    def _new(self, name):
        return self.fn.append_basic_block(name)

    def _tmp(self):
        return self.eb.alloca(VAL)

    def _dec_depth(self, bb):
        bb.store(bb.sub(bb.load(self.depth_ptr), c32(1)), self.depth_ptr)

    def emit_return(self, val):
        if self.is_main:
            self.b.ret_void()
        else:
            self._dec_depth(self.b)
            self.b.ret(val)

    def unwind(self):
        if self._unwind is None:
            blk = self.fn.append_basic_block("unwind")
            bb = ir.IRBuilder(blk)
            if self.is_main:
                bb.ret_void()
            else:
                self._dec_depth(bb)
                bb.ret(NONE_C)
            self._unwind = blk
        return self._unwind

    def check(self):
        """After any fallible call: if the runtime flagged an error, unwind."""
        bad = self.b.icmp_signed("!=", self.b.load(self.err_ptr), c32(0))
        ok = self._new("ok")
        self.b.cbranch(bad, self.unwind(), ok)
        self.b.position_at_end(ok)

    def raise_rt(self, msg: str, line: int):
        self.call_rt("rt_raise", [self.be.str_handle(self, msg), c32(line)])
        self.check()

    # ── value helpers ────────────────────────────────────────────────────────
    def mk(self, tag, pay):
        t = tag if isinstance(tag, ir.Value) else c32(tag)
        p = pay if isinstance(pay, ir.Value) else c64(pay)
        v = self.b.insert_value(ir.Constant(VAL, ir.Undefined), t, 0)
        return self.b.insert_value(v, p, 1)

    def tag(self, v):
        return self.b.extract_value(v, 0)

    def pay(self, v):
        return self.b.extract_value(v, 1)

    def literal(self, pyval, line):
        return self.be.lit(self, pyval, line)

    # ── variables ────────────────────────────────────────────────────────────
    def is_builtin_ref(self, name):
        return (
            name in BUILTINS
            and name not in self.locals
            and name not in self.global_names
            and not self.be.has_slot(name)
        )

    def var_ptr(self, name):
        if name in self.locals:
            return self.locals[name]
        return self.be.slot_ptr(self, name)

    def load_checked(self, ptr, name, line):
        v = self.b.load(ptr)
        bad = self.b.icmp_signed("==", self.tag(v), c32(T_UNDEF))
        err, ok = self._new("undef"), self._new("defined")
        self.b.cbranch(bad, err, ok)
        self.b.position_at_end(err)
        self.call_rt(
            "rt_raise",
            [
                self.be.str_handle(self, f"NameError: name '{name}' is not defined"),
                c32(line),
            ],
        )
        self.b.branch(self.unwind())
        self.b.position_at_end(ok)
        return v

    # ── truthiness ───────────────────────────────────────────────────────────
    def truthy(self, v):
        t, p = self.tag(v), self.pay(v)
        res = self.eb.alloca(I1)
        simple = self.b.or_(
            self.b.icmp_signed("==", t, c32(T_INT)),
            self.b.icmp_signed("==", t, c32(T_BOOL)),
        )
        fast, slow, done = self._new("tfast"), self._new("tslow"), self._new("tdone")
        self.b.cbranch(simple, fast, slow)
        self.b.position_at_end(fast)
        self.b.store(self.b.icmp_signed("!=", p, c64(0)), res)
        self.b.branch(done)
        self.b.position_at_end(slow)
        r = self.call_rt("rt_truthy", [t, p])
        self.b.store(self.b.icmp_signed("!=", r, c32(0)), res)
        self.b.branch(done)
        self.b.position_at_end(done)
        return self.b.load(res)

    # ── binary operators: inline fast paths + runtime slow path ──────────────
    def binop(self, op, l, r, line):
        b = self.b
        lt, lp, rt_, rp = self.tag(l), self.pay(l), self.tag(r), self.pay(r)
        out = self._tmp()
        slow, done = self._new("slow"), self._new("done")
        inline = op in self.ARITH or op in CMP_OPS

        if inline:
            fast_i, chk_f, fast_f = (
                self._new("int"),
                self._new("chkf"),
                self._new("flt"),
            )
            both_i = b.and_(
                b.icmp_signed("==", lt, c32(T_INT)),
                b.icmp_signed("==", rt_, c32(T_INT)),
            )
            b.cbranch(both_i, fast_i, chk_f)

            b.position_at_end(fast_i)  # int op int
            if op in self.ARITH:
                res = getattr(b, self.ARITH[op] + "_with_overflow")(lp, rp)
                ok = self._new("noovf")
                b.cbranch(
                    b.extract_value(res, 1), slow, ok
                )  # overflow -> runtime raises
                b.position_at_end(ok)
                b.store(self.mk(T_INT, b.extract_value(res, 0)), out)
            else:
                c = b.icmp_signed(op, lp, rp)
                b.store(self.mk(T_BOOL, b.zext(c, I64)), out)
            b.branch(done)

            b.position_at_end(chk_f)  # float op float
            both_f = b.and_(
                b.icmp_signed("==", lt, c32(T_FLOAT)),
                b.icmp_signed("==", rt_, c32(T_FLOAT)),
            )
            b.cbranch(both_f, fast_f, slow)
            b.position_at_end(fast_f)
            fl, fr = b.bitcast(lp, DBL), b.bitcast(rp, DBL)
            if op in self.FARITH:
                res = getattr(b, self.FARITH[op])(fl, fr)
                b.store(self.mk(T_FLOAT, b.bitcast(res, I64)), out)
            else:
                c = (
                    b.fcmp_unordered("!=", fl, fr)
                    if op == "!="
                    else b.fcmp_ordered(op, fl, fr)
                )
                b.store(self.mk(T_BOOL, b.zext(c, I64)), out)
            b.branch(done)
        else:
            b.branch(slow)

        b.position_at_end(slow)
        self.call_rt("rt_binop", [c32(OPS.index(op)), lt, lp, rt_, rp, out, c32(line)])
        self.check()
        b.branch(done)
        b.position_at_end(done)
        return b.load(out)

    # ── statements ───────────────────────────────────────────────────────────
    def stmts(self, ss):
        for s in ss:
            getattr(self, "st_" + type(s).__name__)(s)

    def st_ExprStmt(self, n):
        self.ex(n.expr)

    def st_Assign(self, n):
        v = self.ex(n.value)
        self.b.store(v, self.var_ptr(n.target))

    def st_AugAssign(self, n):
        cur = self.load_checked(self.var_ptr(n.target), n.target, n.line)
        rhs = self.ex(n.value)
        self.b.store(self.binop(n.op[:-1], cur, rhs, n.line), self.var_ptr(n.target))

    def st_FuncDef(self, n):
        self.b.store(self.be.func_const(self, n.name), self.var_ptr(n.name))

    def st_Return(self, n):
        if self.is_main:
            raise PyRuntimeError("SyntaxError: 'return' outside function", n.line)
        v = self.ex(n.value) if n.value is not None else NONE_C
        self.emit_return(v)
        self.b.position_at_end(self._new("after_ret"))  # dead code lands here

    def st_If(self, n):
        cond = self.truthy(self.ex(n.test))
        then, end = self._new("then"), self._new("endif")
        els = self._new("else") if n.orelse else end
        self.b.cbranch(cond, then, els)
        self.b.position_at_end(then)
        self.stmts(n.body)
        if not self.b.block.is_terminated:
            self.b.branch(end)
        if n.orelse:
            self.b.position_at_end(els)
            self.stmts(n.orelse)
            if not self.b.block.is_terminated:
                self.b.branch(end)
        self.b.position_at_end(end)

    def st_While(self, n):
        cond_b, body, end = self._new("wcond"), self._new("wbody"), self._new("wend")
        self.b.branch(cond_b)
        self.b.position_at_end(cond_b)
        self.b.cbranch(self.truthy(self.ex(n.test)), body, end)
        self.b.position_at_end(body)
        self.stmts(n.body)
        if not self.b.block.is_terminated:
            self.b.branch(cond_b)
        self.b.position_at_end(end)

    def _is_range_call(self, it):
        return (
            isinstance(it, Call)
            and isinstance(it.func, Name)
            and it.func.id == "range"
            and "range" not in self.be.funcs
            and self.is_builtin_ref("range")
            and 1 <= len(it.args) <= 3
        )

    def _for_range(self, n):
        """`for i in range(...)` -> plain native counter loop (no list, no runtime calls)."""
        b = self.b
        vals = [self.ex(a) for a in n.iter.args]
        all_int = ir.Constant(I1, 1)
        for v in vals:
            all_int = b.and_(all_int, b.icmp_signed("==", self.tag(v), c32(T_INT)))
        bad, good = self._new("rbad"), self._new("rok")
        b.cbranch(all_int, good, bad)
        b.position_at_end(bad)
        self.call_rt(
            "rt_raise",
            [
                self.be.str_handle(
                    self, "TypeError: range() arguments must be integers"
                ),
                c32(n.line),
            ],
        )
        b.branch(self.unwind())
        b.position_at_end(good)

        pays = [self.pay(v) for v in vals]
        start, stop, step = (
            (c64(0), pays[0], c64(1))
            if len(pays) == 1
            else (pays[0], pays[1], c64(1))
            if len(pays) == 2
            else tuple(pays)
        )
        if len(pays) == 3:
            zero, okb = self._new("rzero"), self._new("rstep")
            b.cbranch(b.icmp_signed("==", step, c64(0)), zero, okb)
            b.position_at_end(zero)
            self.call_rt(
                "rt_raise",
                [
                    self.be.str_handle(
                        self, "ValueError: range() arg 3 must not be zero"
                    ),
                    c32(n.line),
                ],
            )
            b.branch(self.unwind())
            b.position_at_end(okb)

        idx = self.eb.alloca(I64)
        b.store(start, idx)
        cond_b, body, end = self._new("rcond"), self._new("rbody"), self._new("rend")
        b.branch(cond_b)
        b.position_at_end(cond_b)
        i = b.load(idx)
        c = b.select(
            b.icmp_signed(">", step, c64(0)),
            b.icmp_signed("<", i, stop),
            b.icmp_signed(">", i, stop),
        )
        b.cbranch(c, body, end)
        b.position_at_end(body)
        b.store(self.mk(T_INT, b.load(idx)), self.var_ptr(n.target))
        self.stmts(n.body)
        if not self.b.block.is_terminated:
            self.b.store(self.b.add(self.b.load(idx), step), idx)
            self.b.branch(cond_b)
        self.b.position_at_end(end)

    def st_For(self, n):
        if self._is_range_call(n.iter):
            return self._for_range(n)
        itv, idx, item = self._tmp(), self.eb.alloca(I64), self._tmp()
        self.b.store(self.ex(n.iter), itv)
        self.b.store(c64(0), idx)
        cond_b, body, end = self._new("fcond"), self._new("fbody"), self._new("fend")
        self.b.branch(cond_b)

        self.b.position_at_end(cond_b)
        it = self.b.load(itv)
        ln = self.call_rt("rt_iter_len", [self.tag(it), self.pay(it), c32(n.line)])
        self.check()
        self.b.cbranch(self.b.icmp_signed("<", self.b.load(idx), ln), body, end)

        self.b.position_at_end(body)
        it = self.b.load(itv)
        self.call_rt(
            "rt_iter_get",
            [self.tag(it), self.pay(it), self.b.load(idx), item, c32(n.line)],
        )
        self.check()
        self.b.store(self.b.load(item), self.var_ptr(n.target))
        self.stmts(n.body)
        if not self.b.block.is_terminated:
            self.b.store(self.b.add(self.b.load(idx), c64(1)), idx)
            self.b.branch(cond_b)
        self.b.position_at_end(end)

    # ── expressions ──────────────────────────────────────────────────────────
    def ex(self, n):
        return getattr(self, "ex_" + type(n).__name__)(n)

    def ex_IntLiteral(self, n):
        return self.literal(n.value, n.line)

    def ex_FloatLiteral(self, n):
        return self.literal(n.value, n.line)

    def ex_StringLiteral(self, n):
        return self.literal(n.value, n.line)

    def ex_BoolLiteral(self, n):
        return self.literal(n.value, n.line)

    def ex_NoneLiteral(self, n):
        return NONE_C

    def ex_Name(self, n):
        if self.is_builtin_ref(n.id):
            return self.be.builtin_const(self, n.id)
        return self.load_checked(self.var_ptr(n.id), n.id, n.line)

    def ex_BinOp(self, n):
        return self.binop(n.op, self.ex(n.left), self.ex(n.right), n.line)

    def ex_Compare(self, n):
        return self.binop(n.op, self.ex(n.left), self.ex(n.right), n.line)

    def ex_UnaryOp(self, n):
        if n.op in ("-", "+") and isinstance(n.operand, (IntLiteral, FloatLiteral)):
            return self.literal(
                -n.operand.value if n.op == "-" else n.operand.value, n.line
            )
        v = self.ex(n.operand)
        if n.op == "not":
            c = self.truthy(v)
            return self.mk(T_BOOL, self.b.zext(self.b.xor(c, ir.Constant(I1, 1)), I64))
        out = self._tmp()
        self.call_rt(
            "rt_unary",
            [c32(0 if n.op == "-" else 1), self.tag(v), self.pay(v), out, c32(n.line)],
        )
        self.check()
        return self.b.load(out)

    def ex_BoolOp(self, n):
        res = self._tmp()
        self.b.store(self.ex(n.values[0]), res)
        end = self._new("bend")
        for v in n.values[1:]:
            nxt = self._new("bnext")
            c = self.truthy(self.b.load(res))
            if n.op == "and":
                self.b.cbranch(c, nxt, end)
            else:
                self.b.cbranch(c, end, nxt)
            self.b.position_at_end(nxt)
            self.b.store(self.ex(v), res)
        self.b.branch(end)
        self.b.position_at_end(end)
        return self.b.load(res)

    def _pack_args(self, vals):
        """Store values into a stack array; return pointer to its first element."""
        arr = self.eb.alloca(ir.ArrayType(VAL, max(len(vals), 1)))
        for i, v in enumerate(vals):
            self.b.store(v, self.b.gep(arr, [c32(0), c32(i)]))
        return self.b.gep(arr, [c32(0), c32(0)])

    def ex_ListLiteral(self, n):
        vals = [self.ex(e) for e in n.elts]
        out = self._tmp()
        self.call_rt("rt_list_new", [c32(len(vals)), self._pack_args(vals), out])
        self.check()
        return self.b.load(out)

    def ex_Subscript(self, n):
        o, i = self.ex(n.value), self.ex(n.index)
        out = self._tmp()
        self.call_rt(
            "rt_subscript",
            [self.tag(o), self.pay(o), self.tag(i), self.pay(i), out, c32(n.line)],
        )
        self.check()
        return self.b.load(out)

    def ex_MethodCall(self, n):
        o = self.ex(n.obj)
        vals = [self.ex(a) for a in n.args]
        out = self._tmp()
        self.call_rt(
            "rt_method",
            [
                self.tag(o),
                self.pay(o),
                self.be.str_handle(self, n.method),
                c32(len(vals)),
                self._pack_args(vals),
                out,
                c32(n.line),
            ],
        )
        self.check()
        return self.b.load(out)

    def ex_Call(self, n):
        if not isinstance(n.func, Name):
            raise PyRuntimeError(
                "TypeError: the LLVM backend can only call named functions", n.line
            )
        name = n.func.id
        if name in self.locals or (
            name in self.global_names and name not in self.be.funcs
        ):
            raise PyRuntimeError(
                f"TypeError: cannot call variable '{name}' (only named functions are callable)",
                n.line,
            )

        # user-defined function -> direct native call
        if name in self.be.funcs:
            mangled, arity = self.be.funcs[name]
            vals = [self.ex(a) for a in n.args]
            if len(vals) != arity:
                self.raise_rt(
                    f"TypeError: {name}() takes {arity} argument(s) but {len(vals)} given",
                    n.line,
                )
                return NONE_C
            res = self.b.call(self.get_fn(mangled, arity), vals)
            self.check()
            return res

        # builtin -> runtime call
        if name in BUILTINS:
            vals = [self.ex(a) for a in n.args]
            out = self._tmp()
            self.call_rt(
                "rt_call_builtin",
                [
                    self.be.builtin_id(name),
                    c32(len(vals)),
                    self._pack_args(vals),
                    out,
                    c32(n.line),
                ],
            )
            self.check()
            return self.b.load(out)

        self.raise_rt(f"NameError: name '{name}' is not defined", n.line)
        return NONE_C


# ══════════════════════════════════════════════════════════════════════════════
# §10  BACKEND  (LLVM optimiser + MCJIT)
# ══════════════════════════════════════════════════════════════════════════════


def _init_llvm():
    for fn in (
        "initialize",
        "initialize_native_target",
        "initialize_native_asmprinter",
    ):
        f = getattr(llvm, fn, None)
        if f:
            try:
                f()
            except Exception:
                pass


class BackendBase:
    """Pieces shared by the JIT and the ahead-of-time backends."""

    def mangle(self, name: str) -> str:
        self._counter += 1
        return f"py_{name}_{self._counter}"

    def _optimize(self, mod):
        if self.opt <= 0:
            return
        try:  # new pass manager (llvmlite >= 0.45)
            pto = llvm.create_pipeline_tuning_options(speed_level=self.opt)
            pb = llvm.create_pass_builder(self.target_machine, pto)
            pb.getModulePassManager().run(mod, pb)
        except AttributeError:  # legacy pass manager
            pmb = llvm.create_pass_manager_builder()
            pmb.opt_level = self.opt
            pm = llvm.create_module_pass_manager()
            pmb.populate(pm)
            pm.run(mod)


class Backend(BackendBase):
    """JIT backend: compile in-process with MCJIT and run immediately (used by the REPL)."""

    def __init__(self, opt: int = 2, emit_ir: bool = False):
        _init_llvm()
        self.opt, self.emit_ir = opt, emit_ir
        target = llvm.Target.from_default_triple()
        self.target_machine = target.create_target_machine(opt=opt)
        self.engine = llvm.create_mcjit_compiler(
            llvm.parse_assembly(""), self.target_machine
        )
        self.rt = Runtime()
        self.funcs: dict = (
            {}
        )  # user function name -> (mangled symbol, arity); persists across REPL lines
        self._counter = 0

    max_depth = Runtime.MAX_DEPTH

    # ── target hooks used by CodeGen (JIT flavour: absolute addresses + Python heap) ──
    def flag_ptrs(self, cg):
        pt = ir.PointerType(I32)
        return (
            c64(ctypes.addressof(self.rt.err)).inttoptr(pt),
            c64(ctypes.addressof(self.rt.depth)).inttoptr(pt),
        )

    def slot_ptr(self, cg, name):
        return c64(self.rt.slot_addr(name)).inttoptr(VALP)

    def has_slot(self, name):
        return self.rt.has_slot(name)

    def str_handle(self, cg, s):
        return c64(HEAP.handle(s))

    def builtin_id(self, name):
        return c64(HEAP.handle(name))

    def lit(self, cg, v, line):
        return const_val(*encode(v, line))

    def builtin_const(self, cg, name):
        return const_val(T_BUILTIN, HEAP.handle(BUILTINS[name]))

    def func_const(self, cg, name):
        return const_val(T_FUNC, HEAP.handle(FuncRef(name)))

    def run(self, program: Program):
        ir_mod, main_name = CodeGen(self).compile(program)
        mod = llvm.parse_assembly(str(ir_mod))
        mod.verify()
        self._optimize(mod)
        if self.emit_ir:
            print(f"; ───── LLVM IR (opt level {self.opt}) ─────\n{mod}")
        self.engine.add_module(mod)
        self.engine.finalize_object()
        self.engine.run_static_constructors()
        addr = self.engine.get_function_address(main_name)
        ctypes.CFUNCTYPE(None)(addr)()
        err = self.rt.take_error()
        if err:
            raise err


# ══════════════════════════════════════════════════════════════════════════════
# §11  AHEAD-OF-TIME COMPILER  (AST -> LLVM IR -> object file -> native executable)
# ══════════════════════════════════════════════════════════════════════════════
#
# Same CodeGen as the JIT, but with a different "target":
#   * globals are real LLVM global variables (no absolute addresses)
#   * string literals / names are constant data embedded in the object file
#   * the runtime is plain C (RUNTIME_C below), compiled and linked with the object

AOT_BUILTINS = list(BUILTINS)

RUNTIME_C = r"""/* Py native runtime — linked into every executable produced by `py_llvm.py --compile`.
 * Mirrors the Python-side runtime used by the JIT: same value tags, same error messages. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <math.h>
#include <ctype.h>
#include <stdarg.h>

typedef struct { int32_t tag; int64_t pay; } Val;              /* == LLVM %Val = { i32, i64 } */
typedef struct { int64_t len; char data[]; } Str;              /* == LLVM { i64, [n+1 x i8] } */
typedef struct { int64_t len, cap; Val *items; } List;

enum { T_NONE = 0, T_BOOL = 1, T_INT = 2, T_FLOAT = 3, T_STR = 4, T_LIST = 5, T_BUILTIN = 6, T_FUNC = 7, T_UNDEF = 15 };

@@BUILTIN_DEFS@@

extern int32_t py_err;                                          /* defined by the generated module */
static char err_msg[1024];
static int32_t err_line;

static void fail(int line, const char *fmt, ...) {
    if (py_err) return;                                         /* first error wins */
    va_list ap; va_start(ap, fmt); vsnprintf(err_msg, sizeof err_msg, fmt, ap); va_end(ap);
    err_line = line; py_err = 1;
}
#define FAIL(...) do { fail(line, __VA_ARGS__); return; } while (0)

/* ── values ─────────────────────────────────────────────────────────────── */
static Val mkv(int32_t t, int64_t p) { Val v; v.tag = t; v.pay = p; return v; }
static int64_t d2b(double d) { int64_t b; memcpy(&b, &d, 8); return b; }
static double b2d(int64_t b) { double d; memcpy(&d, &b, 8); return d; }
static Val mkint(int64_t i) { return mkv(T_INT, i); }
static Val mkflt(double d) { return mkv(T_FLOAT, d2b(d)); }
static Val mkbool(int b) { return mkv(T_BOOL, b ? 1 : 0); }
static Val mknone(void) { return mkv(T_NONE, 0); }
static void *xmalloc(size_t n) { void *p = malloc(n ? n : 1); if (!p) { fputs("out of memory\n", stderr); exit(2); } return p; }
static Str *newstr(const char *s, int64_t n) { Str *r = xmalloc(sizeof(Str) + n + 1); r->len = n; if (n) memcpy(r->data, s, n); r->data[n] = 0; return r; }
static Val mkstr(const char *s, int64_t n) { return mkv(T_STR, (int64_t)(intptr_t)newstr(s, n)); }
#define STR(v)  ((Str *)(intptr_t)(v).pay)
#define LIST(v) ((List *)(intptr_t)(v).pay)

static List *newlist(int64_t n) { List *l = xmalloc(sizeof(List)); l->len = 0; l->cap = n < 4 ? 4 : n; l->items = xmalloc(sizeof(Val) * l->cap); return l; }
static void lpush(List *l, Val v) { if (l->len == l->cap) { l->cap *= 2; l->items = realloc(l->items, sizeof(Val) * l->cap); if (!l->items) exit(2); } l->items[l->len++] = v; }
static Val mklist(List *l) { return mkv(T_LIST, (int64_t)(intptr_t)l); }

static int is_num(Val v) { return v.tag == T_BOOL || v.tag == T_INT || v.tag == T_FLOAT; }
static int is_il(Val v) { return v.tag == T_BOOL || v.tag == T_INT; }
static double as_d(Val v) { return v.tag == T_FLOAT ? b2d(v.pay) : (double)v.pay; }

static const char *tname(Val v) {
    switch (v.tag) {
    case T_NONE: return "NoneType"; case T_BOOL: return "bool"; case T_INT: return "int";
    case T_FLOAT: return "float"; case T_STR: return "str"; case T_LIST: return "list";
    case T_FUNC: return "function"; case T_BUILTIN: return "builtin_function";
    }
    return "object";
}

/* ── string building / repr ─────────────────────────────────────────────── */
typedef struct { char *p; int64_t n, cap; } Buf;
static void bput(Buf *b, const char *s, int64_t n) {
    if (b->n + n + 1 > b->cap) { b->cap = (b->n + n + 1) * 2; b->p = realloc(b->p, b->cap); if (!b->p) exit(2); }
    memcpy(b->p + b->n, s, n); b->n += n; b->p[b->n] = 0;
}
static void bputs(Buf *b, const char *s) { bput(b, s, strlen(s)); }

static void fmt_float(Buf *b, double d) {                     /* Python-style repr(float) */
    if (isnan(d)) { bputs(b, "nan"); return; }
    if (isinf(d)) { bputs(b, d < 0 ? "-inf" : "inf"); return; }
    char t[64]; int p;
    for (p = 0; p <= 16; p++) { snprintf(t, sizeof t, "%.*e", p, d); if (strtod(t, NULL) == d) break; }
    char digits[32]; int nd = 0, neg = 0, i; char *s = t;
    if (*s == '-') { neg = 1; s++; }
    for (; *s && *s != 'e'; s++) if (*s != '.') digits[nd++] = *s;
    int ex = atoi(s + 1);
    while (nd > 1 && digits[nd - 1] == '0') nd--;
    if (neg) bputs(b, "-");
    if (ex >= -4 && ex < 16) {
        if (ex >= 0) {
            for (i = 0; i <= ex; i++) bput(b, i < nd ? &digits[i] : "0", 1);
            bputs(b, ".");
            if (nd > ex + 1) bput(b, digits + ex + 1, nd - ex - 1); else bputs(b, "0");
        } else {
            bputs(b, "0.");
            for (i = 0; i < -ex - 1; i++) bputs(b, "0");
            bput(b, digits, nd);
        }
    } else {
        bput(b, digits, 1);
        if (nd > 1) { bputs(b, "."); bput(b, digits + 1, nd - 1); }
        char e[16]; snprintf(e, sizeof e, "e%c%02d", ex < 0 ? '-' : '+', abs(ex)); bputs(b, e);
    }
}

static void vstr(Buf *b, Val v) {
    char t[32];
    switch (v.tag) {
    case T_NONE: bputs(b, "None"); break;
    case T_BOOL: bputs(b, v.pay ? "True" : "False"); break;
    case T_INT: snprintf(t, sizeof t, "%lld", (long long)v.pay); bputs(b, t); break;
    case T_FLOAT: fmt_float(b, b2d(v.pay)); break;
    case T_STR: bput(b, STR(v)->data, STR(v)->len); break;
    case T_LIST: {
        List *l = LIST(v); bputs(b, "[");
        for (int64_t i = 0; i < l->len; i++) { if (i) bputs(b, ", "); vstr(b, l->items[i]); }
        bputs(b, "]"); break; }
    case T_FUNC: bputs(b, "<function "); bputs(b, STR(v)->data); bputs(b, ">"); break;
    case T_BUILTIN: bputs(b, "<built-in function "); bputs(b, BNAMES[v.pay]); bputs(b, ">"); break;
    }
}

static int truthy(Val v) {
    switch (v.tag) {
    case T_NONE: return 0;
    case T_BOOL: case T_INT: return v.pay != 0;
    case T_FLOAT: return b2d(v.pay) != 0.0;
    case T_STR: return STR(v)->len > 0;
    case T_LIST: return LIST(v)->len > 0;
    }
    return 1;
}

/* ── equality / ordering ────────────────────────────────────────────────── */
static int veq(Val a, Val b) {
    if (is_num(a) && is_num(b)) return (a.tag != T_FLOAT && b.tag != T_FLOAT) ? a.pay == b.pay : as_d(a) == as_d(b);
    if (a.tag != b.tag) return 0;
    switch (a.tag) {
    case T_NONE: return 1;
    case T_STR: return STR(a)->len == STR(b)->len && !memcmp(STR(a)->data, STR(b)->data, STR(a)->len);
    case T_LIST: {
        List *x = LIST(a), *y = LIST(b);
        if (x->len != y->len) return 0;
        for (int64_t i = 0; i < x->len; i++) if (!veq(x->items[i], y->items[i])) return 0;
        return 1; }
    case T_FUNC: return !strcmp(STR(a)->data, STR(b)->data);
    case T_BUILTIN: return a.pay == b.pay;
    }
    return 0;
}

static const char *OPN[] = { "+", "-", "*", "/", "//", "%", "**", "==", "!=", "<", "<=", ">", ">=" };

/* returns 1 and stores result, or flags an error and returns 0 */
static int ordered(int op, Val a, Val b, int line, int *res) {
    int c;
    if (is_num(a) && is_num(b)) {
        if (is_il(a) && is_il(b)) c = a.pay < b.pay ? -1 : a.pay > b.pay;
        else {
            double x = as_d(a), y = as_d(b);
            switch (op) { case 9: *res = x < y; break; case 10: *res = x <= y; break; case 11: *res = x > y; break; default: *res = x >= y; }
            return 1;
        }
    } else if (a.tag == T_STR && b.tag == T_STR) {
        int64_t n = STR(a)->len < STR(b)->len ? STR(a)->len : STR(b)->len;
        c = memcmp(STR(a)->data, STR(b)->data, n);
        if (!c) c = STR(a)->len < STR(b)->len ? -1 : STR(a)->len > STR(b)->len;
    } else {
        fail(line, "TypeError: '%s' not supported between '%s' and '%s'", OPN[op], tname(a), tname(b));
        return 0;
    }
    switch (op) { case 9: *res = c < 0; break; case 10: *res = c <= 0; break; case 11: *res = c > 0; break; default: *res = c >= 0; }
    return 1;
}

/* ── arithmetic ─────────────────────────────────────────────────────────── */
#define OVERFLOW_MSG "OverflowError: integer does not fit in 64 bits (LLVM backend)"

static int dbl_to_int(double d, int64_t *out) {
    if (isnan(d) || isinf(d) || d >= 9223372036854775808.0 || d < -9223372036854775808.0) return 0;
    *out = (int64_t)d; return 1;
}
static int64_t count_of(Val v) { if (is_il(v)) return v.pay; double d = b2d(v.pay); int64_t r = 0; dbl_to_int(d, &r); return r; }

void rt_binop(int32_t op, int32_t lt, int64_t lp, int32_t rtg, int64_t rp, Val *out, int32_t line) {
    Val a = mkv(lt, lp), b = mkv(rtg, rp);
    if (op >= 7) {
        if (op == 7) { *out = mkbool(veq(a, b)); return; }
        if (op == 8) { *out = mkbool(!veq(a, b)); return; }
        int r; if (ordered(op, a, b, line, &r)) *out = mkbool(r);
        return;
    }
    /* strings and lists */
    if (op == 0 && a.tag == T_STR && b.tag == T_STR) {
        Str *x = STR(a), *y = STR(b); Str *r = xmalloc(sizeof(Str) + x->len + y->len + 1);
        r->len = x->len + y->len; memcpy(r->data, x->data, x->len); memcpy(r->data + x->len, y->data, y->len); r->data[r->len] = 0;
        *out = mkv(T_STR, (int64_t)(intptr_t)r); return;
    }
    if (op == 0 && a.tag == T_LIST && b.tag == T_LIST) {
        List *x = LIST(a), *y = LIST(b), *r = newlist(x->len + y->len);
        for (int64_t i = 0; i < x->len; i++) lpush(r, x->items[i]);
        for (int64_t i = 0; i < y->len; i++) lpush(r, y->items[i]);
        *out = mklist(r); return;
    }
    if (op == 2) {
        Val s = a, n = b;
        if (is_num(a) && (b.tag == T_STR || b.tag == T_LIST)) { s = b; n = a; }
        if ((s.tag == T_STR || s.tag == T_LIST) && is_num(n)) {
            int64_t k = count_of(n); if (k < 0) k = 0;
            if (s.tag == T_STR) {
                Str *x = STR(s); Str *r = xmalloc(sizeof(Str) + x->len * k + 1); r->len = x->len * k;
                for (int64_t i = 0; i < k; i++) memcpy(r->data + i * x->len, x->data, x->len);
                r->data[r->len] = 0; *out = mkv(T_STR, (int64_t)(intptr_t)r);
            } else {
                List *x = LIST(s), *r = newlist(x->len * k);
                for (int64_t i = 0; i < k; i++) for (int64_t j = 0; j < x->len; j++) lpush(r, x->items[j]);
                *out = mklist(r);
            }
            return;
        }
    }
    if (!is_num(a) || !is_num(b)) FAIL("TypeError: unsupported operand type(s) for '%s': '%s' and '%s'", OPN[op], tname(a), tname(b));

    int ints = is_il(a) && is_il(b);
    int64_t x = a.pay, y = b.pay, r;
    double dx = as_d(a), dy = as_d(b);
    switch (op) {
    case 0: if (ints) { if (__builtin_add_overflow(x, y, &r)) FAIL(OVERFLOW_MSG); *out = mkint(r); } else *out = mkflt(dx + dy); return;
    case 1: if (ints) { if (__builtin_sub_overflow(x, y, &r)) FAIL(OVERFLOW_MSG); *out = mkint(r); } else *out = mkflt(dx - dy); return;
    case 2: if (ints) { if (__builtin_mul_overflow(x, y, &r)) FAIL(OVERFLOW_MSG); *out = mkint(r); } else *out = mkflt(dx * dy); return;
    case 3: if (dy == 0) FAIL("ZeroDivisionError: division by zero"); *out = mkflt(dx / dy); return;
    case 4:
        if (dy == 0) FAIL("ZeroDivisionError: integer division by zero");
        if (ints) {
            if (y == -1) { if (__builtin_sub_overflow((int64_t)0, x, &r)) FAIL(OVERFLOW_MSG); *out = mkint(r); return; }
            r = x / y; if ((x % y != 0) && ((x < 0) != (y < 0))) r--;
            *out = mkint(r); return;
        }
        if (!dbl_to_int(floor(dx / dy), &r)) FAIL("OverflowError: cannot convert float to integer");
        *out = mkint(r); return;
    case 5:
        if (dy == 0) FAIL("ZeroDivisionError: modulo by zero");
        if (ints) {
            if (y == -1) { *out = mkint(0); return; }
            r = x % y; if (r != 0 && ((r < 0) != (y < 0))) r += y;
            *out = mkint(r); return;
        } else {
            double m = fmod(dx, dy); if (m != 0 && ((m < 0) != (dy < 0))) m += dy;
            *out = mkflt(m); return;
        }
    case 6:
        if (ints && y >= 0) {
            int64_t base = x, e = y; r = 1;
            while (e) {
                if (e & 1) { if (__builtin_mul_overflow(r, base, &r)) FAIL(OVERFLOW_MSG); }
                e >>= 1;
                if (e && __builtin_mul_overflow(base, base, &base)) FAIL(OVERFLOW_MSG);
            }
            *out = mkint(r); return;
        }
        if (dx == 0 && dy < 0) FAIL("ZeroDivisionError: 0 cannot be raised to a negative power");
        { double p = pow(dx, dy); if (isinf(p) && !isinf(dx) && !isinf(dy)) FAIL("OverflowError: result too large"); *out = mkflt(p); }
        return;
    }
}

void rt_unary(int32_t op, int32_t t, int64_t p, Val *out, int32_t line) {
    Val v = mkv(t, p);
    if (v.tag == T_INT || v.tag == T_FLOAT) {
        if (op == 1) { *out = v; return; }
        if (v.tag == T_FLOAT) { *out = mkflt(-b2d(p)); return; }
        if (p == INT64_MIN) FAIL(OVERFLOW_MSG);
        *out = mkint(-p); return;
    }
    FAIL("TypeError: bad operand type for unary '%c': '%s'", op == 0 ? '-' : '+', tname(v));
}

int32_t rt_truthy(int32_t t, int64_t p) { return truthy(mkv(t, p)); }

void rt_list_new(int32_t n, Val *arr, Val *out) {
    List *l = newlist(n); for (int i = 0; i < n; i++) lpush(l, arr[i]); *out = mklist(l);
}

void rt_subscript(int32_t ot, int64_t op, int32_t it, int64_t ip, Val *out, int32_t line) {
    Val o = mkv(ot, op), i = mkv(it, ip);
    if (o.tag != T_LIST && o.tag != T_STR) FAIL("TypeError: '%s' object is not subscriptable", tname(o));
    if (!is_num(i)) FAIL("TypeError: indices must be integers, not '%s'", tname(i));
    int64_t idx = count_of(i), len = o.tag == T_LIST ? LIST(o)->len : STR(o)->len;
    if (idx < -len || idx >= len) FAIL("IndexError: index %lld out of range (length %lld)", (long long)idx, (long long)len);
    if (idx < 0) idx += len;
    *out = o.tag == T_LIST ? LIST(o)->items[idx] : mkstr(STR(o)->data + idx, 1);
}

int64_t rt_iter_len(int32_t t, int64_t p, int32_t line) {
    Val o = mkv(t, p);
    if (o.tag == T_LIST) return LIST(o)->len;
    if (o.tag == T_STR) return STR(o)->len;
    fail(line, "TypeError: '%s' object is not iterable", tname(o)); return 0;
}
void rt_iter_get(int32_t t, int64_t p, int64_t i, Val *out, int32_t line) {
    Val o = mkv(t, p); (void)line;
    *out = o.tag == T_LIST ? LIST(o)->items[i] : mkstr(STR(o)->data + i, 1);
}

void rt_raise(int64_t msg, int32_t line) { fail(line, "%s", ((Str *)(intptr_t)msg)->data); }

/* ── methods ────────────────────────────────────────────────────────────── */
void rt_method(int32_t ot, int64_t op, int64_t name, int32_t n, Val *args, Val *out, int32_t line) {
    Val o = mkv(ot, op); const char *m = ((Str *)(intptr_t)name)->data; (void)args;
    if (o.tag == T_STR && (!strcmp(m, "lower") || !strcmp(m, "upper"))) {
        if (n) FAIL("TypeError: %s() takes no arguments", m);
        Str *s = STR(o), *r = newstr(s->data, s->len); int up = m[0] == 'u';
        for (int64_t i = 0; i < r->len; i++) r->data[i] = up ? toupper((unsigned char)r->data[i]) : tolower((unsigned char)r->data[i]);
        *out = mkv(T_STR, (int64_t)(intptr_t)r); return;
    }
    FAIL("AttributeError: '%s' object has no attribute '%s'", tname(o), m);
}

/* ── builtins ───────────────────────────────────────────────────────────── */
static void bi_print(int n, Val *a, Val *out, int line) {
    (void)out; (void)line; Buf b = {0};
    for (int i = 0; i < n; i++) { if (i) bputs(&b, " "); vstr(&b, a[i]); }
    bputs(&b, "\n"); fwrite(b.p, 1, b.n, stdout); free(b.p);
}
static void bi_len(int n, Val *a, Val *out, int line) {
    if (n != 1) FAIL("TypeError: len() takes exactly 1 argument");
    if (a[0].tag == T_STR) *out = mkint(STR(a[0])->len);
    else if (a[0].tag == T_LIST) *out = mkint(LIST(a[0])->len);
    else FAIL("TypeError: object of type '%s' has no len()", tname(a[0]));
}
static void bi_range(int n, Val *a, Val *out, int line) {
    if (n < 1 || n > 3) FAIL("TypeError: range() takes 1–3 arguments");
    int64_t v[3] = {0, 0, 1};
    for (int i = 0; i < n; i++) { if (!is_num(a[i])) FAIL("TypeError: range() arguments must be integers"); v[i] = count_of(a[i]); }
    int64_t start = 0, stop, step = 1;
    if (n == 1) stop = v[0]; else { start = v[0]; stop = v[1]; if (n == 3) step = v[2]; }
    if (step == 0) FAIL("ValueError: range() arg 3 must not be zero");
    List *l = newlist(0);
    for (int64_t i = start; step > 0 ? i < stop : i > stop; i += step) lpush(l, mkint(i));
    *out = mklist(l);
}
static void bi_int(int n, Val *a, Val *out, int line) {
    if (n != 1) FAIL("TypeError: int() takes 1 argument");
    Val v = a[0];
    if (is_il(v)) { *out = mkint(v.pay); return; }
    if (v.tag == T_FLOAT) { int64_t r; if (!dbl_to_int(b2d(v.pay), &r)) FAIL("OverflowError: cannot convert float to integer"); *out = mkint(r); return; }
    if (v.tag == T_STR) {
        const char *s = STR(v)->data, *e = s + STR(v)->len;
        while (s < e && isspace((unsigned char)*s)) s++;
        while (e > s && isspace((unsigned char)e[-1])) e--;
        const char *p = s; int neg = 0;
        if (p < e && (*p == '+' || *p == '-')) { neg = *p == '-'; p++; }
        int64_t r = 0; int ok = p < e;
        for (const char *q = p; q < e && ok; q++) {
            if (!isdigit((unsigned char)*q)) { ok = 0; break; }
            if (__builtin_mul_overflow(r, (int64_t)10, &r) || __builtin_add_overflow(r, (int64_t)(*q - '0') * (neg ? -1 : 1), &r)) FAIL(OVERFLOW_MSG);
        }
        if (!ok) FAIL("ValueError: invalid literal for int(): '%s'", STR(v)->data);
        *out = mkint(r); return;
    }
    FAIL("TypeError: int() argument must be a string or number, not '%s'", tname(v));
}
static void bi_float(int n, Val *a, Val *out, int line) {
    if (n != 1) FAIL("TypeError: float() takes 1 argument");
    Val v = a[0];
    if (is_num(v)) { *out = mkflt(as_d(v)); return; }
    if (v.tag == T_STR && STR(v)->len > 0) {
        char *end; const char *s = STR(v)->data;
        while (isspace((unsigned char)*s)) s++;
        double d = strtod(s, &end);
        while (isspace((unsigned char)*end)) end++;
        if (end == s || *end) FAIL("ValueError: could not convert string to float: '%s'", STR(v)->data);
        *out = mkflt(d); return;
    }
    FAIL("TypeError: float() argument must be a string or number, not '%s'", tname(v));
}
static void bi_str(int n, Val *a, Val *out, int line) {
    if (n != 1) FAIL("TypeError: str() takes 1 argument");
    Buf b = {0}; vstr(&b, a[0]); *out = mkstr(b.p ? b.p : "", b.n); free(b.p);
}
static void bi_bool(int n, Val *a, Val *out, int line) {
    if (n != 1) FAIL("TypeError: bool() takes 1 argument");
    *out = mkbool(truthy(a[0]));
}
static void bi_input(int n, Val *a, Val *out, int line) {
    if (n > 0) { Buf b = {0}; vstr(&b, a[0]); if (b.n) fwrite(b.p, 1, b.n, stdout); free(b.p); }
    fflush(stdout);
    char *ln = NULL; size_t cap = 0; ssize_t got = getline(&ln, &cap, stdin);
    if (got < 0) { free(ln); FAIL("EOFError: EOF when reading a line"); }
    if (got > 0 && ln[got - 1] == '\n') got--;
    *out = mkstr(ln, got); free(ln);
}
static void bi_abs(int n, Val *a, Val *out, int line) {
    if (n != 1) FAIL("TypeError: abs() takes 1 argument");
    Val v = a[0];
    if (v.tag == T_INT) { if (v.pay == INT64_MIN) FAIL(OVERFLOW_MSG); *out = mkint(v.pay < 0 ? -v.pay : v.pay); }
    else if (v.tag == T_FLOAT) *out = mkflt(fabs(b2d(v.pay)));
    else FAIL("TypeError: bad operand type for abs(): '%s'", tname(v));
}
static void bi_minmax(int n, Val *a, Val *out, int line, int want_max) {
    const char *nm = want_max ? "max" : "min";
    if (n < 1) FAIL("TypeError: %s() expected at least 1 argument", nm);
    Val *items = a; int64_t cnt = n;
    if (n == 1 && a[0].tag == T_LIST) { items = LIST(a[0])->items; cnt = LIST(a[0])->len; }
    else if (n == 1) FAIL("TypeError: '%s' object is not iterable", tname(a[0]));
    if (cnt == 0) FAIL("ValueError: %s() arg is an empty sequence", nm);
    Val best = items[0];
    for (int64_t i = 1; i < cnt; i++) {
        int r; if (!ordered(want_max ? 11 : 9, items[i], best, line, &r)) return;
        if (r) best = items[i];
    }
    *out = best;
}
static void bi_max(int n, Val *a, Val *out, int line) { bi_minmax(n, a, out, line, 1); }
static void bi_min(int n, Val *a, Val *out, int line) { bi_minmax(n, a, out, line, 0); }
static void bi_type(int n, Val *a, Val *out, int line) {
    if (n != 1) FAIL("TypeError: type() takes 1 argument");
    char t[64]; int k = snprintf(t, sizeof t, "<class '%s'>", tname(a[0])); *out = mkstr(t, k);
}
static void bi_append(int n, Val *a, Val *out, int line) {
    (void)out;
    if (n != 2) FAIL("TypeError: append() takes 2 arguments");
    if (a[0].tag != T_LIST) FAIL("TypeError: first argument must be a list");
    lpush(LIST(a[0]), a[1]);
}
static void bi_pop(int n, Val *a, Val *out, int line) {
    if (n != 1 && n != 2) FAIL("TypeError: pop() takes 1 or 2 arguments");
    if (a[0].tag != T_LIST) FAIL("TypeError: first argument must be a list");
    List *l = LIST(a[0]);
    if (l->len == 0) FAIL("IndexError: pop from empty list");
    int64_t idx = n == 2 ? (is_num(a[1]) ? count_of(a[1]) : 0) : -1;
    if (idx < 0) idx += l->len;
    if (idx < 0 || idx >= l->len) FAIL("IndexError: pop index out of range");
    *out = l->items[idx];
    memmove(l->items + idx, l->items + idx + 1, sizeof(Val) * (l->len - idx - 1)); l->len--;
}

void rt_call_builtin(int64_t id, int32_t n, Val *args, Val *out, int32_t line) {
    *out = mknone();
    switch (id) {
    case B_print: bi_print(n, args, out, line); break;
    case B_len: bi_len(n, args, out, line); break;
    case B_range: bi_range(n, args, out, line); break;
    case B_int: bi_int(n, args, out, line); break;
    case B_float: bi_float(n, args, out, line); break;
    case B_str: bi_str(n, args, out, line); break;
    case B_bool: bi_bool(n, args, out, line); break;
    case B_input: bi_input(n, args, out, line); break;
    case B_abs: bi_abs(n, args, out, line); break;
    case B_max: bi_max(n, args, out, line); break;
    case B_min: bi_min(n, args, out, line); break;
    case B_type: bi_type(n, args, out, line); break;
    case B_append: bi_append(n, args, out, line); break;
    case B_pop: bi_pop(n, args, out, line); break;
    }
}

/* ── program exit ───────────────────────────────────────────────────────── */
int32_t rt_finish(void) {
    fflush(stdout);
    if (py_err) {
        printf("\033[91mPyRuntimeError\033[0m: %s", err_msg);
        if (err_line) printf(" [line %d]", err_line);
        printf("\n"); fflush(stdout);
        return 1;
    }
    return 0;
}
"""


class AotBackend(BackendBase):
    max_depth = 4000

    def __init__(self, opt: int = 2, emit_ir: bool = False):
        _init_llvm()
        self.opt, self.emit_ir = opt, emit_ir
        target = llvm.Target.from_default_triple()
        self.target_machine = target.create_target_machine(
            opt=opt, reloc="pic", codemodel="default"
        )
        self.funcs: dict = {}
        self._counter = 0
        self._slots: dict = {}
        self._strs: dict = {}

    # ── target hooks used by CodeGen (AOT flavour: LLVM globals + embedded data) ──
    def flag_ptrs(self, cg):
        err = ir.GlobalVariable(cg.mod, I32, "py_err")
        err.initializer = c32(0)
        depth = ir.GlobalVariable(cg.mod, I32, "py_depth")
        depth.initializer = c32(0)
        return err, depth

    def _str_global(self, cg, s: str):
        g = self._strs.get(s)
        if g is None:
            data = s.encode("utf-8")
            arr = ir.ArrayType(ir.IntType(8), len(data) + 1)
            ty = ir.LiteralStructType(
                [I64, arr]
            )  # same layout as `Str` in the C runtime
            g = ir.GlobalVariable(cg.mod, ty, f"str.{len(self._strs)}")
            g.linkage, g.global_constant = "internal", True
            g.initializer = ir.Constant(
                ty, [c64(len(data)), ir.Constant(arr, bytearray(data + b"\0"))]
            )
            self._strs[s] = g
        return g

    def str_handle(self, cg, s):
        return self._str_global(cg, s).ptrtoint(I64)

    def slot_ptr(self, cg, name):
        g = self._slots.get(name)
        if g is None:
            g = ir.GlobalVariable(cg.mod, VAL, "g." + name)
            g.linkage = "internal"
            g.initializer = UNDEF_C
            self._slots[name] = g
        return g

    def has_slot(self, name):
        return name in self._slots

    def builtin_id(self, name):
        return c64(AOT_BUILTINS.index(name))

    def lit(self, cg, v, line):
        if isinstance(v, str):
            return ir.Constant(VAL, [c32(T_STR), self.str_handle(cg, v)])
        return const_val(*encode(v, line))

    def builtin_const(self, cg, name):
        return const_val(T_BUILTIN, AOT_BUILTINS.index(name))

    def func_const(self, cg, name):
        return ir.Constant(VAL, [c32(T_FUNC), self.str_handle(cg, name)])


def _runtime_source() -> str:
    defs = [
        "static const char *BNAMES[] = { "
        + ", ".join(f'"{n}"' for n in AOT_BUILTINS)
        + " };",
        "enum { "
        + ", ".join(f"B_{n} = {i}" for i, n in enumerate(AOT_BUILTINS))
        + " };",
    ]
    return RUNTIME_C.replace("@@BUILTIN_DEFS@@", "\n".join(defs))


def compile_executable(source: str, out_path: str, opt: int = 2, emit_ir: bool = False):
    """Compile Py source to a standalone native executable."""
    import shutil, subprocess, tempfile

    program = Parser(Lexer(source).tokenize()).parse()
    be = AotBackend(opt=opt, emit_ir=emit_ir)
    ir_mod, main_name = CodeGen(be).compile(program)

    # C-ABI entry point:  int main() { py_main(); return rt_finish(); }
    entry = ir.Function(ir_mod, ir.FunctionType(I32, []), "main")
    bb = ir.IRBuilder(entry.append_basic_block("entry"))
    bb.call(ir_mod.get_global(main_name), [])
    bb.ret(bb.call(ir.Function(ir_mod, ir.FunctionType(I32, []), "rt_finish"), []))

    mod = llvm.parse_assembly(str(ir_mod))
    mod.verify()
    be._optimize(mod)
    if emit_ir:
        print(f"; ───── LLVM IR (opt level {opt}) ─────\n{mod}")
    obj = be.target_machine.emit_object(mod)

    cc = (
        os.environ.get("CC")
        or shutil.which("cc")
        or shutil.which("gcc")
        or shutil.which("clang")
    )
    if not cc:
        raise PyError(
            "no C compiler found (install gcc/clang, or set $CC) — needed to link the runtime"
        )
    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "prog.o"), "wb") as fh:
            fh.write(obj)
        with open(os.path.join(td, "pyrt.c"), "w") as fh:
            fh.write(_runtime_source())
        cmd = [
            cc,
            "-O2",
            "-w",
            "-o",
            out_path,
            os.path.join(td, "pyrt.c"),
            os.path.join(td, "prog.o"),
            "-lm",
        ]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            raise PyError(f"linking failed:\n{r.stderr}")


# ══════════════════════════════════════════════════════════════════════════════
# §12  AST PRETTY PRINTER  (for --ast)
# ══════════════════════════════════════════════════════════════════════════════


def _print_ast(node, indent=0):
    pad = "  " * indent
    fields = {k: v for k, v in vars(node).items() if k != "line"}
    is_nodes = (
        lambda v: isinstance(v, list) and v and all(isinstance(x, ASTNode) for x in v)
    )
    scalars = {
        k: v
        for k, v in fields.items()
        if not isinstance(v, ASTNode) and not is_nodes(v)
    }
    print(
        pad + type(node).__name__ + "".join(f" {k}={v!r}" for k, v in scalars.items())
    )
    for k, v in fields.items():
        if isinstance(v, ASTNode):
            print(f"{pad}  {k}:")
            _print_ast(v, indent + 2)
        elif is_nodes(v):
            print(f"{pad}  {k}:")
            for x in v:
                _print_ast(x, indent + 2)


# ══════════════════════════════════════════════════════════════════════════════
# §13  PIPELINE
# ══════════════════════════════════════════════════════════════════════════════


def run_source(source: str, backend: Backend = None, show_ast: bool = False) -> Backend:
    backend = backend or Backend()
    program = Parser(Lexer(source).tokenize()).parse()
    if show_ast:
        print("\n── AST ─────────────────────────────────────────────")
        _print_ast(program)
        print("────────────────────────────────────────────────────\n")
    backend.run(program)
    return backend


# ══════════════════════════════════════════════════════════════════════════════
# §14  REPL
# ══════════════════════════════════════════════════════════════════════════════

BANNER = """\
\033[96m╔══════════════════════════════════════════════════════╗
║        Py  —  LLVM JIT  (llvmlite / MCJIT)           ║
║  Type Py code below.  'exit' or Ctrl-D to quit.      ║
║  'help' for a quick language reference.              ║
╚══════════════════════════════════════════════════════╝\033[0m"""

HELP_TEXT = """
Py Quick Reference  (compiled to native code through LLVM)
─────────────────────
Variables:     x = 10          y = 3.14       s = "hello"
Arithmetic:    + - * / // % **
Comparison:    == != < <= > >=
Logic:         and  or  not
Strings:       "hi" + " world"   len("hello")   str(42)
               "Hi".lower()      "hi".upper()
Lists:         lst = [1, 2, 3]   lst[0]   len(lst)   append(lst, 4)
Control flow:  if / elif / else,  while,  for i in range(n)
Functions:     def f(a, b): return a + b

Builtins: print len range int float str bool abs max min type input append pop
"""


def repl(backend: Backend):
    print(BANNER)
    buf = []
    while True:
        try:
            line = input("... " if buf else ">>> ")
        except (EOFError, KeyboardInterrupt):
            print("\nBye!")
            break
        if not buf and line.strip() == "exit":
            print("Bye!")
            break
        if not buf and line.strip() == "help":
            print(HELP_TEXT)
            continue
        if not buf and line.strip() == "":
            continue
        buf.append(line)
        source = "\n".join(buf)
        if line.rstrip().endswith(":") or (
            len(buf) > 1 and line.strip() != "" and _needs_more(source)
        ):
            continue
        if len(buf) > 1 and line.strip() != "" and buf[0].rstrip().endswith(":"):
            continue  # inside a block: wait for a blank line to finish it
        try:
            run_source(source + "\n", backend)
        except (LexerError, ParseError, PyRuntimeError) as e:
            print(e)
        except Exception as e:
            print(f"\033[91mInternalError\033[0m: {e}")
        finally:
            buf = []


def _needs_more(source: str) -> bool:
    lines = [
        l for l in source.splitlines() if l.strip() and not l.strip().startswith("#")
    ]
    return bool(lines) and lines[-1].rstrip().endswith(":")


# ══════════════════════════════════════════════════════════════════════════════
# §15  CLI
# ══════════════════════════════════════════════════════════════════════════════


def main():
    args = sys.argv[1:]
    show_ast = "--ast" in args
    emit_ir = "--emit-ir" in args
    compile_mode = "--compile" in args or "-c" in args
    opt = 0 if "--no-opt" in args else 2

    out_path, files, i = None, [], 0
    while i < len(args):
        a = args[i]
        if a == "-o" and i + 1 < len(args):
            out_path = args[i + 1]
            i += 1
        elif not a.startswith("-"):
            files.append(a)
        i += 1

    if compile_mode and not files:
        print("Usage: python py_llvm.py --compile script.ep [-o output]")
        sys.exit(1)

    if not files:
        repl(Backend(opt=opt, emit_ir=emit_ir))
        return

    path = files[0]
    if not os.path.exists(path):
        print(f"\033[91mFileNotFoundError\033[0m: No such file: {path!r}")
        sys.exit(1)
    with open(path, "r", encoding="utf-8") as fh:
        source = fh.read()
    try:
        if compile_mode:
            out_path = out_path or os.path.splitext(os.path.basename(path))[0]
            if show_ast:
                _print_ast(Parser(Lexer(source).tokenize()).parse())
            compile_executable(source, out_path, opt=opt, emit_ir=emit_ir)
            print(f"compiled {path} -> {out_path}")
        else:
            run_source(source, Backend(opt=opt, emit_ir=emit_ir), show_ast)
    except (LexerError, ParseError, PyRuntimeError, PyError) as e:
        print(e)
        sys.exit(1)
    except Exception as e:
        print(f"\033[91mInternalError\033[0m: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
