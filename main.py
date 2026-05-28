#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════╗
║                        E D U P Y                                 ║
║       An Educational Python-like Interpreter                     ║
║                                                                  ║
║  Architecture (all in this single file):                         ║
║    1. Errors      — LexerError, ParseError, RuntimeError         ║
║    2. Tokens      — TT enum + Token dataclass                    ║
║    3. Lexer       — source text → token list                     ║
║    4. AST Nodes   — dataclasses for every grammar construct      ║
║    5. Parser      — PEG-style recursive descent                  ║
║    6. Interpreter — tree-walk executor + scoped environments     ║
║    7. Builtins    — print, len, range, int, float, str, bool     ║
║    8. REPL        — interactive read-eval-print loop             ║
║    9. Runner      — run a .ep source file                        ║
╚══════════════════════════════════════════════════════════════════╝

Usage
-----
  REPL:          python edupy.py
  Run a file:    python edupy.py myscript.ep
  Dump AST:      python edupy.py myscript.ep --ast
"""

from __future__ import annotations
import sys, os, textwrap
from enum import Enum
from dataclasses import dataclass, field
from typing import Any, List, Optional


# ══════════════════════════════════════════════════════════════════════════════
# §1  ERRORS
# ══════════════════════════════════════════════════════════════════════════════


class EduPyError(Exception):
    """Base class for all EduPy errors."""

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


class LexerError(EduPyError):
    """Illegal character or unterminated literal."""


class ParseError(EduPyError):
    """Token stream violates the grammar."""


class EduPyRuntimeError(EduPyError):
    """Type error, undefined name, wrong arity, etc."""


class ReturnSignal(Exception):
    """Internal signal used to unwind the call stack on 'return'."""

    def __init__(self, value):
        self.value = value


# ══════════════════════════════════════════════════════════════════════════════
# §2  TOKENS
# ══════════════════════════════════════════════════════════════════════════════


class TT(Enum):
    """
    Token Types — mirrors CPython Grammar/Tokens and terminal symbols
    in Grammar/python.gram.
    """

    # Literals
    INTEGER = "INTEGER"
    FLOAT = "FLOAT"
    STRING = "STRING"
    # Keywords
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
    # Identifier
    NAME = "NAME"
    # Arithmetic
    PLUS = "+"
    MINUS = "-"
    STAR = "*"
    SLASH = "/"
    PERCENT = "%"
    DOUBLESLASH = "//"
    DOUBLESTAR = "**"
    # Comparison
    EQEQUAL = "=="
    NOTEQUAL = "!="
    LESS = "<"
    LESSEQUAL = "<="
    GREATER = ">"
    GREATEREQUAL = ">="
    # Assignment
    EQUAL = "="
    # Augmented assignment
    PLUSEQUAL = "+="
    MINEQUAL = "-="
    STAREQUAL = "*="
    SLASHEQUAL = "/="
    # Delimiters
    LPAREN = "("
    RPAREN = ")"
    LBRACKET = "["
    RBRACKET = "]"
    COLON = ":"
    COMMA = ","
    DOT = "."
    # Structural (indent-based)
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


@dataclass
class Token:
    """A single lexical token with position info."""

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
    """
    Single-pass, character-by-character tokeniser.

    Key design points (from CPython Lib/tokenize.py):
      • indent_stack tracks indentation depth → INDENT / DEDENT tokens
      • blank/comment lines are silently skipped (no NEWLINE emitted)
      • paren_depth > 0 suppresses physical-newline NEWLINE tokens,
        enabling implicit line continuation inside ( ) or [ ]
    """

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

    # ── Public ──────────────────────────────────────────────────────────────

    def tokenize(self) -> List[Token]:
        while self.pos < len(self.source):
            self._next_token()
        self._close_all_indents()
        if self.tokens and self.tokens[-1].type not in (TT.NEWLINE, TT.DEDENT):
            self.tokens.append(Token(TT.NEWLINE, "\n", self.line, self.col))
        self.tokens.append(Token(TT.EOF, None, self.line, self.col))
        return self.tokens

    # ── Character helpers ───────────────────────────────────────────────────

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

    def _tok(self, tt, val, ln, cl) -> Token:
        return Token(tt, val, ln, cl)

    def _err(self, msg):
        raise LexerError(msg, self.line)

    def _close_all_indents(self):
        while len(self.indent_stack) > 1:
            self.indent_stack.pop()
            self.tokens.append(Token(TT.DEDENT, None, self.line, self.col))

    # ── Main dispatch ───────────────────────────────────────────────────────

    def _next_token(self):
        if self.at_line_start and self.paren_depth == 0:
            self._handle_indentation()
            return

        ch = self._cur()

        if ch in (" ", "\t"):
            self._advance()
            return
        if ch == "\n":
            ln, cl = self._here()
            self._advance()
            if self.paren_depth == 0:
                self.tokens.append(Token(TT.NEWLINE, "\n", ln, cl))
                self.at_line_start = True
            return
        if ch == "\r":
            self._advance()
            return
        if ch == "#":
            while self._cur() not in ("\n", "\0"):
                self._advance()
            return
        if ch in ('"', "'"):
            self._read_string()
            return
        if ch.isdigit():
            self._read_number()
            return
        if ch.isalpha() or ch == "_":
            self._read_name()
            return
        self._read_operator()

    # ── Indentation ─────────────────────────────────────────────────────────

    def _handle_indentation(self):
        indent = 0
        while self._cur() in (" ", "\t"):
            indent = (indent // 8 + 1) * 8 if self._cur() == "\t" else indent + 1
            self._advance()

        ch = self._cur()
        # blank or comment line — skip entirely
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
                    f"IndentationError: unindent does not match any outer indentation level"
                )

    # ── Strings ─────────────────────────────────────────────────────────────

    def _read_string(self):
        ln, cl = self._here()
        q = self._advance()
        # triple-quoted
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
        # single-quoted
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

    # ── Numbers ─────────────────────────────────────────────────────────────

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

    # ── Names / keywords ────────────────────────────────────────────────────

    def _read_name(self):
        ln, cl = self._here()
        buf = []
        while self._cur().isalnum() or self._cur() == "_":
            buf.append(self._advance())
        name = "".join(buf)
        self.tokens.append(Token(KEYWORDS.get(name, TT.NAME), name, ln, cl))

    # ── Operators ───────────────────────────────────────────────────────────

    def _read_operator(self):
        ln, cl = self._here()
        ch = self._advance()

        def nxt(c):
            return self._cur() == c and (self._advance(), True)[1]

        if ch == "+":
            self.tokens.append(
                Token(
                    TT.PLUSEQUAL if nxt("=") else TT.PLUS,
                    ch + ("=" if self.tokens and self.tokens[-1].value == "+=" else ""),
                    ln,
                    cl,
                )
            )
            return
        # Rebuild with clear branching to avoid the above hack
        self.tokens.pop() if ch == "+" else None  # undo — we'll redo cleanly

        _single = {
            "%": TT.PERCENT,
            "(": TT.LPAREN,
            ")": TT.RPAREN,
            "[": TT.LBRACKET,
            "]": TT.RBRACKET,
            ":": TT.COLON,
            ",": TT.COMMA,
            ".": TT.DOT,
        }

        # We already consumed ch above; dispatch cleanly:
        if ch == "+":
            if self._cur() == "=":
                self._advance()
                self.tokens.append(Token(TT.PLUSEQUAL, "+=", ln, cl))
            else:
                self.tokens.append(Token(TT.PLUS, "+", ln, cl))
        elif ch == "-":
            if self._cur() == "=":
                self._advance()
                self.tokens.append(Token(TT.MINEQUAL, "-=", ln, cl))
            else:
                self.tokens.append(Token(TT.MINUS, "-", ln, cl))
        elif ch == "*":
            if self._cur() == "*":
                self._advance()
                self.tokens.append(Token(TT.DOUBLESTAR, "**", ln, cl))
            elif self._cur() == "=":
                self._advance()
                self.tokens.append(Token(TT.STAREQUAL, "*=", ln, cl))
            else:
                self.tokens.append(Token(TT.STAR, "*", ln, cl))
        elif ch == "/":
            if self._cur() == "/":
                self._advance()
                self.tokens.append(Token(TT.DOUBLESLASH, "//", ln, cl))
            elif self._cur() == "=":
                self._advance()
                self.tokens.append(Token(TT.SLASHEQUAL, "/=", ln, cl))
            else:
                self.tokens.append(Token(TT.SLASH, "/", ln, cl))
        elif ch == "=":
            if self._cur() == "=":
                self._advance()
                self.tokens.append(Token(TT.EQEQUAL, "==", ln, cl))
            else:
                self.tokens.append(Token(TT.EQUAL, "=", ln, cl))
        elif ch == "!":
            if self._cur() == "=":
                self._advance()
                self.tokens.append(Token(TT.NOTEQUAL, "!=", ln, cl))
            else:
                self._err("SyntaxError: '!' must be followed by '='")
        elif ch == "<":
            if self._cur() == "=":
                self._advance()
                self.tokens.append(Token(TT.LESSEQUAL, "<=", ln, cl))
            else:
                self.tokens.append(Token(TT.LESS, "<", ln, cl))
        elif ch == ">":
            if self._cur() == "=":
                self._advance()
                self.tokens.append(Token(TT.GREATEREQUAL, ">=", ln, cl))
            else:
                self.tokens.append(Token(TT.GREATER, ">", ln, cl))
        elif ch == "%":
            self.tokens.append(Token(TT.PERCENT, "%", ln, cl))
        elif ch == "(":
            self.paren_depth += 1
            self.tokens.append(Token(TT.LPAREN, "(", ln, cl))
        elif ch == ")":
            self.paren_depth = max(0, self.paren_depth - 1)
            self.tokens.append(Token(TT.RPAREN, ")", ln, cl))
        elif ch == "[":
            self.paren_depth += 1
            self.tokens.append(Token(TT.LBRACKET, "[", ln, cl))
        elif ch == "]":
            self.paren_depth = max(0, self.paren_depth - 1)
            self.tokens.append(Token(TT.RBRACKET, "]", ln, cl))
        elif ch == ":":
            self.tokens.append(Token(TT.COLON, ":", ln, cl))
        elif ch == ",":
            self.tokens.append(Token(TT.COMMA, ",", ln, cl))
        elif ch == ".":
            self.tokens.append(Token(TT.DOT, ".", ln, cl))
        else:
            self._err(f"SyntaxError: unexpected character {ch!r}")


# ══════════════════════════════════════════════════════════════════════════════
# §4  AST NODES
#     Inspired by CPython's  Grammar/python.asdl
# ══════════════════════════════════════════════════════════════════════════════


@dataclass
class ASTNode:
    line: int = 0

    def __repr__(self):
        parts = [f"{k}={v!r}" for k, v in self.__dict__.items() if k != "line"]
        return f"{type(self).__name__}({', '.join(parts)})"


# ── Root ──────────────────────────────────────────────────────────────────────
@dataclass
class Program(ASTNode):  # CPython: ast.Module
    body: List[ASTNode] = field(default_factory=list)


# ── Literals ──────────────────────────────────────────────────────────────────
@dataclass
class IntLiteral(ASTNode):  # ast.Constant(int)
    value: int = 0


@dataclass
class FloatLiteral(ASTNode):  # ast.Constant(float)
    value: float = 0.0


@dataclass
class StringLiteral(ASTNode):  # ast.Constant(str)
    value: str = ""


@dataclass
class BoolLiteral(ASTNode):  # ast.Constant(bool)
    value: bool = True


@dataclass
class NoneLiteral(ASTNode):  # ast.Constant(None)
    pass


# ── Expressions ───────────────────────────────────────────────────────────────
@dataclass
class Name(ASTNode):  # ast.Name(id, ctx)
    id: str = ""


@dataclass
class ListLiteral(ASTNode):  # ast.List(elts, ctx)
    elts: List[ASTNode] = field(default_factory=list)


@dataclass
class Subscript(ASTNode):  # ast.Subscript(value, slice, ctx)
    value: ASTNode = None
    index: ASTNode = None


@dataclass
class BinOp(ASTNode):  # ast.BinOp(left, op, right)
    left: ASTNode = None  # op ∈ {+,-,*,/,//,%,**}
    op: str = ""
    right: ASTNode = None


@dataclass
class UnaryOp(ASTNode):  # ast.UnaryOp(op, operand)
    op: str = ""  # op ∈ {+, -, not}
    operand: ASTNode = None


@dataclass
class Compare(ASTNode):  # ast.Compare(left, ops, comparators)
    left: ASTNode = None  # op ∈ {==,!=,<,<=,>,>=}
    op: str = ""
    right: ASTNode = None


@dataclass
class BoolOp(ASTNode):  # ast.BoolOp(op, values)
    op: str = ""  # 'and' | 'or'
    values: List[ASTNode] = field(default_factory=list)


@dataclass
class Call(ASTNode):  # ast.Call(func, args, keywords)
    func: ASTNode = None
    args: List[ASTNode] = field(default_factory=list)


# ── Statements ────────────────────────────────────────────────────────────────
@dataclass
class Assign(ASTNode):  # ast.Assign(targets, value)
    target: str = ""
    value: ASTNode = None


@dataclass
class AugAssign(ASTNode):  # ast.AugAssign(target, op, value)
    target: str = ""
    op: str = ""
    value: ASTNode = None


@dataclass
class ExprStmt(ASTNode):  # ast.Expr(value)
    expr: ASTNode = None


@dataclass
class Return(ASTNode):  # ast.Return(value)
    value: Optional[ASTNode] = None


@dataclass
class If(ASTNode):  # ast.If(test, body, orelse)
    test: ASTNode = None
    body: List[ASTNode] = field(default_factory=list)
    orelse: List[ASTNode] = field(default_factory=list)


@dataclass
class While(ASTNode):  # ast.While(test, body, orelse)
    test: ASTNode = None
    body: List[ASTNode] = field(default_factory=list)


@dataclass
class For(ASTNode):  # ast.For(target, iter, body)
    target: str = ""
    iter: ASTNode = None
    body: List[ASTNode] = field(default_factory=list)


@dataclass
class FuncDef(ASTNode):  # ast.FunctionDef(name, args, body)
    name: str = ""
    params: List[str] = field(default_factory=list)
    body: List[ASTNode] = field(default_factory=list)


# ══════════════════════════════════════════════════════════════════════════════
# §5  PARSER
#     PEG-style recursive descent, grammar mirrors CPython's python.gram
#
#  Grammar (EBNF):
#   program      := stmt* EOF
#   stmt         := func_def | if_stmt | while_stmt | for_stmt | simple_stmt
#   simple_stmt  := (assign | aug_assign | return | expr_stmt) NEWLINE
#   assign       := NAME '=' expr
#   aug_assign   := NAME ('+='|'-='|'*='|'/=') expr
#   return_stmt  := 'return' [expr]
#   func_def     := 'def' NAME '(' params? ')' ':' block
#   if_stmt      := 'if' expr ':' block elif_else?
#   elif_else    := ('elif' expr ':' block elif_else?) | ('else' ':' block)
#   while_stmt   := 'while' expr ':' block
#   for_stmt     := 'for' NAME 'in' expr ':' block
#   block        := NEWLINE INDENT stmt+ DEDENT
#   expr         := or_expr
#   or_expr      := and_expr  ('or'  and_expr)*
#   and_expr     := not_expr  ('and' not_expr)*
#   not_expr     := 'not' not_expr | comparison
#   comparison   := sum (comp_op sum)*
#   sum          := term     (('+' | '-') term)*
#   term         := factor   (('*'|'/'|'//'|'%') factor)*
#   factor       := ('+'|'-') factor | power
#   power        := primary  ['**' factor]
#   primary      := atom (call_args | subscript)*
#   atom         := INT | FLOAT | STR | True | False | None
#                 | NAME | '[' args? ']' | '(' expr ')'
# ══════════════════════════════════════════════════════════════════════════════


class Parser:
    def __init__(self, tokens: List[Token]):
        self.tokens = tokens
        self.pos = 0

    # ── Cursor ──────────────────────────────────────────────────────────────

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

    # ── Entry ────────────────────────────────────────────────────────────────

    def parse(self) -> Program:
        stmts = self._stmt_list()
        self._expect(TT.EOF, "expected end of file")
        return Program(body=stmts, line=1)

    # ── Statement list ───────────────────────────────────────────────────────

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

    # ── Simple statements ────────────────────────────────────────────────────

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

    # ── Compound statements ───────────────────────────────────────────────────

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

    # ── Expressions (precedence chain) ───────────────────────────────────────

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
# §6  ENVIRONMENT  (scoped variable store)
# ══════════════════════════════════════════════════════════════════════════════


class Environment:
    """
    A dictionary-backed variable scope.

    Scopes are linked by *parent* — lookup walks the chain outward
    (like CPython's LEGB rule, minus global/builtin distinctions).
    """

    def __init__(self, parent: "Environment" = None):
        self.vars: dict = {}
        self.parent: Environment = parent

    def get(self, name: str, line: int = None) -> Any:
        if name in self.vars:
            return self.vars[name]
        if self.parent:
            return self.parent.get(name, line)
        raise EduPyRuntimeError(f"NameError: name '{name}' is not defined", line)

    def set(self, name: str, value: Any):
        """Always sets in the *current* scope (like Python assignment)."""
        self.vars[name] = value

    def assign(self, name: str, value: Any, line: int = None):
        """
        Assign to the nearest scope that already owns *name*.
        Falls back to the current scope (new variable).
        """
        if name in self.vars:
            self.vars[name] = value
            return
        if self.parent and self.parent._owns(name):
            self.parent.assign(name, value, line)
            return
        self.vars[name] = value

    def _owns(self, name: str) -> bool:
        if name in self.vars:
            return True
        return self.parent._owns(name) if self.parent else False


# ══════════════════════════════════════════════════════════════════════════════
# §7  BUILTIN FUNCTIONS
# ══════════════════════════════════════════════════════════════════════════════


class EduPyFunction:
    """Represents a user-defined EduPy function (closure over its definition env)."""

    def __init__(self, node: FuncDef, closure: Environment):
        self.node = node
        self.closure = closure

    def __repr__(self):
        return f"<function {self.node.name}>"


def _builtin_print(args):
    print(*(_ep_str(a) for a in args))
    return None


def _builtin_len(args):
    if len(args) != 1:
        raise EduPyRuntimeError("TypeError: len() takes exactly 1 argument")
    v = args[0]
    if isinstance(v, (str, list)):
        return len(v)
    raise EduPyRuntimeError(f"TypeError: object of type '{_type_name(v)}' has no len()")


def _builtin_range(args):
    if not (1 <= len(args) <= 3):
        raise EduPyRuntimeError("TypeError: range() takes 1–3 arguments")
    iargs = []
    for a in args:
        if not isinstance(a, (int, float)):
            raise EduPyRuntimeError("TypeError: range() arguments must be integers")
        iargs.append(int(a))
    return list(range(*iargs))


def _builtin_int(args):
    if len(args) != 1:
        raise EduPyRuntimeError("TypeError: int() takes 1 argument")
    v = args[0]
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, (int, float)):
        return int(v)
    if isinstance(v, str):
        s = v.strip()
        if s.lstrip("-+").isdigit():
            return int(s)
        raise EduPyRuntimeError(f"ValueError: invalid literal for int(): {v!r}")
    raise EduPyRuntimeError(
        f"TypeError: int() argument must be a string or number, not '{_type_name(v)}'"
    )


def _builtin_float(args):
    if len(args) != 1:
        raise EduPyRuntimeError("TypeError: float() takes 1 argument")
    v = args[0]
    if isinstance(v, bool):
        return float(v)
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        s = v.strip()
        if s:
            return float(s)
    raise EduPyRuntimeError(
        f"TypeError: float() argument must be a string or number, not '{_type_name(v)}'"
    )


def _builtin_str(args):
    if len(args) != 1:
        raise EduPyRuntimeError("TypeError: str() takes 1 argument")
    return _ep_str(args[0])


def _builtin_bool(args):
    if len(args) != 1:
        raise EduPyRuntimeError("TypeError: bool() takes 1 argument")
    return _ep_bool(args[0])


def _builtin_input(args):
    prompt = _ep_str(args[0]) if args else ""
    return input(prompt)


def _builtin_abs(args):
    if len(args) != 1:
        raise EduPyRuntimeError("TypeError: abs() takes 1 argument")
    v = args[0]
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return abs(v)
    raise EduPyRuntimeError(f"TypeError: bad operand type for abs(): '{_type_name(v)}'")


def _builtin_max(args):
    if not args:
        raise EduPyRuntimeError("TypeError: max() expected at least 1 argument")
    items = args[0] if len(args) == 1 and isinstance(args[0], list) else args
    if not items:
        raise EduPyRuntimeError("ValueError: max() arg is an empty sequence")
    return max(items)


def _builtin_min(args):
    if not args:
        raise EduPyRuntimeError("TypeError: min() expected at least 1 argument")
    items = args[0] if len(args) == 1 and isinstance(args[0], list) else args
    if not items:
        raise EduPyRuntimeError("ValueError: min() arg is an empty sequence")
    return min(items)


def _builtin_type(args):
    if len(args) != 1:
        raise EduPyRuntimeError("TypeError: type() takes 1 argument")
    return f"<class '{_type_name(args[0])}'>"


def _builtin_append(args):
    # Called as append(list, value) — not method syntax
    if len(args) != 2:
        raise EduPyRuntimeError("TypeError: append() takes 2 arguments")
    lst, val = args
    if not isinstance(lst, list):
        raise EduPyRuntimeError("TypeError: first argument must be a list")
    lst.append(val)
    return None


def _builtin_pop(args):
    if len(args) not in (1, 2):
        raise EduPyRuntimeError("TypeError: pop() takes 1 or 2 arguments")
    lst = args[0]
    if not isinstance(lst, list):
        raise EduPyRuntimeError("TypeError: first argument must be a list")
    idx = int(args[1]) if len(args) == 2 else -1
    if not lst:
        raise EduPyRuntimeError("IndexError: pop from empty list")
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

# ── Value helpers ─────────────────────────────────────────────────────────────


def _ep_str(v) -> str:
    if v is None:
        return "None"
    if isinstance(v, bool):
        return "True" if v else "False"
    if isinstance(v, list):
        return "[" + ", ".join(_ep_str(x) for x in v) + "]"
    return str(v)


def _ep_bool(v) -> bool:
    if v is None:
        return False
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return v != 0
    if isinstance(v, str):
        return len(v) > 0
    if isinstance(v, list):
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
    if isinstance(v, EduPyFunction):
        return "function"
    return type(v).__name__


# ══════════════════════════════════════════════════════════════════════════════
# §8  INTERPRETER  (tree-walk)
# ══════════════════════════════════════════════════════════════════════════════


class Interpreter:
    """
    Executes an EduPy AST by walking the tree recursively.

    Dispatch pattern: visit(node) → _visit_<ClassName>(node)
    (same pattern as CPython's compiler/AST visitors)
    """

    def __init__(self):
        self.globals = Environment()
        for name, fn in BUILTINS.items():
            self.globals.set(name, fn)

    # ── Public ────────────────────────────────────────────────────────────────

    def run(self, program: Program):
        self._exec_stmts(program.body, self.globals)

    def eval_expr(self, source: str) -> Any:
        """Evaluate a single expression string (used by REPL)."""
        tokens = Lexer(source + "\n").tokenize()
        # Try as expression first
        p = Parser(tokens)
        try:
            node = p._expr()
            return self._eval(node, self.globals)
        except (ParseError, EduPyRuntimeError):
            raise

    # ── Statement execution ───────────────────────────────────────────────────

    def _exec_stmts(self, stmts: List[ASTNode], env: Environment):
        for stmt in stmts:
            self._exec(stmt, env)

    def _exec(self, node: ASTNode, env: Environment):
        name = type(node).__name__
        method = getattr(self, f"_exec_{name}", None)
        if method is None:
            raise EduPyRuntimeError(
                f"InternalError: no exec handler for {name}", node.line
            )
        method(node, env)

    def _exec_FuncDef(self, node: FuncDef, env: Environment):
        fn = EduPyFunction(node, env)
        env.set(node.name, fn)

    def _exec_Assign(self, node: Assign, env: Environment):
        env.set(node.target, self._eval(node.value, env))

    def _exec_AugAssign(self, node: AugAssign, env: Environment):
        current = env.get(node.target, node.line)
        rhs = self._eval(node.value, env)
        result = self._apply_binop(node.op[0], current, rhs, node.line)
        env.assign(node.target, result, node.line)

    def _exec_ExprStmt(self, node: ExprStmt, env: Environment):
        self._eval(node.expr, env)

    def _exec_Return(self, node: Return, env: Environment):
        value = self._eval(node.value, env) if node.value is not None else None
        raise ReturnSignal(value)

    def _exec_If(self, node: If, env: Environment):
        if _ep_bool(self._eval(node.test, env)):
            self._exec_stmts(node.body, env)
        elif node.orelse:
            self._exec_stmts(node.orelse, env)

    def _exec_While(self, node: While, env: Environment):
        while _ep_bool(self._eval(node.test, env)):
            self._exec_stmts(node.body, env)

    def _exec_For(self, node: For, env: Environment):
        iterable = self._eval(node.iter, env)
        if not isinstance(iterable, (list, str)):
            raise EduPyRuntimeError(
                f"TypeError: '{_type_name(iterable)}' object is not iterable", node.line
            )
        for item in iterable:
            env.set(node.target, item)
            self._exec_stmts(node.body, env)

    # ── Expression evaluation ─────────────────────────────────────────────────

    def _eval(self, node: ASTNode, env: Environment) -> Any:
        name = type(node).__name__
        method = getattr(self, f"_eval_{name}", None)
        if method is None:
            raise EduPyRuntimeError(
                f"InternalError: no eval handler for {name}", node.line
            )
        return method(node, env)

    def _eval_IntLiteral(self, n, e):
        return n.value

    def _eval_FloatLiteral(self, n, e):
        return n.value

    def _eval_StringLiteral(self, n, e):
        return n.value

    def _eval_BoolLiteral(self, n, e):
        return n.value

    def _eval_NoneLiteral(self, n, e):
        return None

    def _eval_Name(self, node: Name, env: Environment) -> Any:
        return env.get(node.id, node.line)

    def _eval_ListLiteral(self, node: ListLiteral, env: Environment) -> list:
        return [self._eval(e, env) for e in node.elts]

    def _eval_Subscript(self, node: Subscript, env: Environment) -> Any:
        obj = self._eval(node.value, env)
        idx = self._eval(node.index, env)
        if not isinstance(obj, (list, str)):
            raise EduPyRuntimeError(
                f"TypeError: '{_type_name(obj)}' object is not subscriptable", node.line
            )
        if not isinstance(idx, (int, float)):
            raise EduPyRuntimeError(
                f"TypeError: indices must be integers, not '{_type_name(idx)}'",
                node.line,
            )
        idx = int(idx)
        if idx < -len(obj) or idx >= len(obj):
            raise EduPyRuntimeError(
                f"IndexError: index {idx} out of range (length {len(obj)})", node.line
            )
        return obj[idx]

    def _eval_BinOp(self, node: BinOp, env: Environment) -> Any:
        left = self._eval(node.left, env)
        right = self._eval(node.right, env)
        return self._apply_binop(node.op, left, right, node.line)

    def _apply_binop(self, op: str, left: Any, right: Any, line: int) -> Any:
        # String concatenation
        if op == "+" and isinstance(left, str) and isinstance(right, str):
            return left + right
        # String repetition
        if op == "*" and isinstance(left, str) and isinstance(right, (int, float)):
            return left * int(right)
        if op == "*" and isinstance(left, (int, float)) and isinstance(right, str):
            return right * int(left)
        # List concatenation / repetition
        if op == "+" and isinstance(left, list) and isinstance(right, list):
            return left + right
        if op == "*" and isinstance(left, list) and isinstance(right, (int, float)):
            return left * int(right)
        # Numeric operations
        if (
            not isinstance(left, (int, float))
            or not isinstance(right, (int, float))
            or isinstance(left, bool)
            and op not in ("+", "-", "*", "/", "//", "%", "**")
        ):
            pass  # fall through to type error below
        if isinstance(left, (int, float)) and isinstance(right, (int, float)):
            if op == "+":
                return left + right
            if op == "-":
                return left - right
            if op == "*":
                return left * right
            if op == "**":
                return left**right
            if op == "%":
                if right == 0:
                    raise EduPyRuntimeError("ZeroDivisionError: modulo by zero", line)
                return left % right
            if op == "/":
                if right == 0:
                    raise EduPyRuntimeError("ZeroDivisionError: division by zero", line)
                return left / right
            if op == "//":
                if right == 0:
                    raise EduPyRuntimeError(
                        "ZeroDivisionError: integer division by zero", line
                    )
                return int(left // right)
        raise EduPyRuntimeError(
            f"TypeError: unsupported operand type(s) for '{op}': "
            f"'{_type_name(left)}' and '{_type_name(right)}'",
            line,
        )

    def _eval_UnaryOp(self, node: UnaryOp, env: Environment) -> Any:
        v = self._eval(node.operand, env)
        if node.op == "not":
            return not _ep_bool(v)
        if node.op == "-":
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                return -v
            raise EduPyRuntimeError(
                f"TypeError: bad operand type for unary '-': '{_type_name(v)}'",
                node.line,
            )
        if node.op == "+":
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                return +v
            raise EduPyRuntimeError(
                f"TypeError: bad operand type for unary '+': '{_type_name(v)}'",
                node.line,
            )

    def _eval_Compare(self, node: Compare, env: Environment) -> bool:
        left = self._eval(node.left, env)
        right = self._eval(node.right, env)
        op = node.op
        # None comparisons
        if op == "==":
            return left == right
        if op == "!=":
            return left != right
        # Ordered comparisons — must be same/compatible types
        for v in (left, right):
            if not isinstance(v, (int, float, str)):
                raise EduPyRuntimeError(
                    f"TypeError: '{op}' not supported between '{_type_name(left)}' and '{_type_name(right)}'",
                    node.line,
                )
        if op == "<":
            return left < right
        if op == "<=":
            return left <= right
        if op == ">":
            return left > right
        if op == ">=":
            return left >= right

    def _eval_BoolOp(self, node: BoolOp, env: Environment) -> Any:
        if node.op == "and":
            result = self._eval(node.values[0], env)
            for v in node.values[1:]:
                if not _ep_bool(result):
                    return result
                result = self._eval(v, env)
            return result
        else:  # or
            result = self._eval(node.values[0], env)
            for v in node.values[1:]:
                if _ep_bool(result):
                    return result
                result = self._eval(v, env)
            return result

    def _eval_Call(self, node: Call, env: Environment) -> Any:
        callee = self._eval(node.func, env)
        args = [self._eval(a, env) for a in node.args]

        # Built-in (Python callable)
        if callable(callee) and not isinstance(callee, EduPyFunction):
            result = callee(args)
            return result

        # User-defined EduPy function
        if isinstance(callee, EduPyFunction):
            fn = callee.node
            arity = len(fn.params)
            if len(args) != arity:
                raise EduPyRuntimeError(
                    f"TypeError: {fn.name}() takes {arity} argument(s) but {len(args)} given",
                    node.line,
                )
            call_env = Environment(parent=callee.closure)
            for param, val in zip(fn.params, args):
                call_env.set(param, val)
            result = None
            for stmt in fn.body:
                self._exec(stmt, call_env)
            return result

        raise EduPyRuntimeError(
            f"TypeError: '{_type_name(callee)}' object is not callable", node.line
        )

    def _exec_FuncDef(self, node: FuncDef, env: Environment):
        env.set(node.name, EduPyFunction(node, env))

    # Patch _eval_Call to properly catch return signals
    def _eval_Call(self, node: Call, env: Environment) -> Any:
        callee = self._eval(node.func, env)
        args = [self._eval(a, env) for a in node.args]

        if callable(callee) and not isinstance(callee, EduPyFunction):
            return callee(args)

        if isinstance(callee, EduPyFunction):
            fn = callee.node
            arity = len(fn.params)
            if len(args) != arity:
                raise EduPyRuntimeError(
                    f"TypeError: {fn.name}() takes {arity} argument(s) but {len(args)} given",
                    node.line,
                )
            call_env = Environment(parent=callee.closure)
            for param, val in zip(fn.params, args):
                call_env.set(param, val)
            result = None
            try:
                self._exec_stmts(fn.body, call_env)
            except ReturnSignal as ret:
                result = ret.value
            return result

        raise EduPyRuntimeError(
            f"TypeError: '{_type_name(callee)}' object is not callable", node.line
        )


# ══════════════════════════════════════════════════════════════════════════════
# §9  AST PRETTY PRINTER  (for --ast flag)
# ══════════════════════════════════════════════════════════════════════════════


def _print_ast(node, indent=0):
    pad = "  " * indent
    name = type(node).__name__

    if isinstance(node, (IntLiteral, FloatLiteral, StringLiteral, BoolLiteral)):
        print(f"{pad}{name}({node.value!r})")
    elif isinstance(node, NoneLiteral):
        print(f"{pad}NoneLiteral")
    elif isinstance(node, Name):
        print(f"{pad}Name({node.id!r})")
    elif isinstance(node, Program):
        print(f"{pad}Program [line {node.line}]")
        for s in node.body:
            _print_ast(s, indent + 1)
    elif isinstance(node, FuncDef):
        print(f"{pad}FuncDef name={node.name!r} params={node.params}")
        for s in node.body:
            _print_ast(s, indent + 1)
    elif isinstance(node, Assign):
        print(f"{pad}Assign target={node.target!r}")
        _print_ast(node.value, indent + 1)
    elif isinstance(node, AugAssign):
        print(f"{pad}AugAssign target={node.target!r} op={node.op!r}")
        _print_ast(node.value, indent + 1)
    elif isinstance(node, Return):
        print(f"{pad}Return")
        if node.value:
            _print_ast(node.value, indent + 1)
    elif isinstance(node, ExprStmt):
        print(f"{pad}ExprStmt")
        _print_ast(node.expr, indent + 1)
    elif isinstance(node, If):
        print(f"{pad}If")
        print(f"{pad}  test:")
        _print_ast(node.test, indent + 2)
        print(f"{pad}  body:")
        for s in node.body:
            _print_ast(s, indent + 2)
        if node.orelse:
            print(f"{pad}  orelse:")
            for s in node.orelse:
                _print_ast(s, indent + 2)
    elif isinstance(node, While):
        print(f"{pad}While")
        print(f"{pad}  test:")
        _print_ast(node.test, indent + 2)
        print(f"{pad}  body:")
        for s in node.body:
            _print_ast(s, indent + 2)
    elif isinstance(node, For):
        print(f"{pad}For target={node.target!r}")
        print(f"{pad}  iter:")
        _print_ast(node.iter, indent + 2)
        print(f"{pad}  body:")
        for s in node.body:
            _print_ast(s, indent + 2)
    elif isinstance(node, BinOp):
        print(f"{pad}BinOp op={node.op!r}")
        _print_ast(node.left, indent + 1)
        _print_ast(node.right, indent + 1)
    elif isinstance(node, UnaryOp):
        print(f"{pad}UnaryOp op={node.op!r}")
        _print_ast(node.operand, indent + 1)
    elif isinstance(node, Compare):
        print(f"{pad}Compare op={node.op!r}")
        _print_ast(node.left, indent + 1)
        _print_ast(node.right, indent + 1)
    elif isinstance(node, BoolOp):
        print(f"{pad}BoolOp op={node.op!r}")
        for v in node.values:
            _print_ast(v, indent + 1)
    elif isinstance(node, Call):
        print(f"{pad}Call")
        _print_ast(node.func, indent + 1)
        for a in node.args:
            _print_ast(a, indent + 1)
    elif isinstance(node, ListLiteral):
        print(f"{pad}ListLiteral [{len(node.elts)} elements]")
        for e in node.elts:
            _print_ast(e, indent + 1)
    elif isinstance(node, Subscript):
        print(f"{pad}Subscript")
        _print_ast(node.value, indent + 1)
        _print_ast(node.index, indent + 1)
    else:
        print(f"{pad}{name} (no printer)")


# ══════════════════════════════════════════════════════════════════════════════
# §10  PIPELINE  (source → tokens → AST → execute)
# ══════════════════════════════════════════════════════════════════════════════


def run_source(
    source: str, interpreter: Interpreter = None, filename: str = "<string>"
) -> Interpreter:
    """
    Full pipeline: source text → tokens → AST → execute.
    Returns the interpreter so the REPL can share state across lines.
    """
    if interpreter is None:
        interpreter = Interpreter()

    tokens = Lexer(source).tokenize()
    program = Parser(tokens).parse()
    interpreter.run(program)
    return interpreter


def run_source_with_ast(source: str, filename: str = "<string>"):
    """Run source and also print the AST before execution."""
    tokens = Lexer(source).tokenize()
    program = Parser(tokens).parse()
    print("\n── AST ─────────────────────────────────────────────")
    _print_ast(program)
    print("────────────────────────────────────────────────────\n")
    interp = Interpreter()
    interp.run(program)


# ══════════════════════════════════════════════════════════════════════════════
# §11  REPL
# ══════════════════════════════════════════════════════════════════════════════

BANNER = """\
\033[96m╔══════════════════════════════════════════════════════╗
║           EduPy  —  Educational Interpreter          ║
║  Type EduPy code below.  'exit' or Ctrl-D to quit.  ║
║  'help' for a quick language reference.              ║
╚══════════════════════════════════════════════════════╝\033[0m"""

HELP_TEXT = """
EduPy Quick Reference
─────────────────────
Variables:     x = 10          y = 3.14       s = "hello"
Arithmetic:    + - * / // % **
Comparison:    == != < <= > >=
Logic:         and  or  not
Strings:       "hi" + " world"   len("hello")   str(42)
Lists:         lst = [1, 2, 3]   lst[0]   len(lst)   append(lst, 4)
Control flow:
  if x > 0:
      print("positive")
  elif x == 0:
      print("zero")
  else:
      print("negative")

  while x > 0:
      x -= 1

  for i in range(5):
      print(i)

Functions:
  def greet(name):
      return "Hello, " + name

  print(greet("world"))

Builtins: print len range int float str bool abs max min type input append pop
"""


def repl():
    print(BANNER)
    interp = Interpreter()
    buf = []  # accumulate multi-line input
    prompt = ">>> "

    while True:
        cont_prompt = "... "
        try:
            line = input(prompt if not buf else cont_prompt)
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

        # If the line ends with ':' or the buffer isn't balanced, keep reading
        stripped = line.rstrip()
        if stripped.endswith(":") or (buf and _needs_more(source)):
            continue

        # Blank continuation line after block → flush buffer
        if buf and line.strip() == "" and len(buf) > 1:
            pass  # fall through to execute

        # Attempt execution
        try:
            run_source(source + "\n", interp)
        except (LexerError, ParseError, EduPyRuntimeError) as e:
            print(e)
        except Exception as e:
            print(f"\033[91mInternalError\033[0m: {e}")
        finally:
            buf = []


def _needs_more(source: str) -> bool:
    """Heuristic: return True if the source looks incomplete (open block)."""
    lines = [
        l for l in source.splitlines() if l.strip() and not l.strip().startswith("#")
    ]
    if not lines:
        return False
    last = lines[-1].rstrip()
    return last.endswith(":")


# ══════════════════════════════════════════════════════════════════════════════
# §12  CLI ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════


def main():
    args = sys.argv[1:]

    if not args:
        repl()
        return

    show_ast = "--ast" in args
    files = [a for a in args if not a.startswith("--")]

    if not files:
        print("Usage: python edupy.py [script.ep] [--ast]")
        sys.exit(1)

    filepath = files[0]

    if not os.path.exists(filepath):
        print(f"\033[91mFileNotFoundError\033[0m: No such file: {filepath!r}")
        sys.exit(1)

    with open(filepath, "r", encoding="utf-8") as fh:
        source = fh.read()

    try:
        if show_ast:
            run_source_with_ast(source, filename=filepath)
        else:
            run_source(source, filename=filepath)
    except (LexerError, ParseError, EduPyRuntimeError) as e:
        print(e)
        sys.exit(1)
    except Exception as e:
        print(f"\033[91mInternalError\033[0m: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
