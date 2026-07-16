mod token {
//! Tokens produced by the lexer.
//!
//! `TokKind` carries payload data for literals/names. `Tag` is the
//! "shape only" counterpart used by the parser to test/match token
//! kinds without caring about the payload (mirrors how the Python
//! original compared against bare `TT` enum members).

#[derive(Debug, Clone, PartialEq)]
pub enum TokKind {
    Integer(i64),
    Float(f64),
    Str(String),
    Name(String),

    If,
    Elif,
    Else,
    While,
    For,
    In,
    Def,
    Return,
    And,
    Or,
    Not,
    True,
    False,
    None,

    Plus,
    Minus,
    Star,
    Slash,
    Percent,
    DoubleSlash,
    DoubleStar,

    EqEqual,
    NotEqual,
    Less,
    LessEqual,
    Greater,
    GreaterEqual,

    Equal,

    PlusEqual,
    MinusEqual,
    StarEqual,
    SlashEqual,

    LParen,
    RParen,
    LBracket,
    RBracket,
    Colon,
    Comma,
    Dot,

    Newline,
    Indent,
    Dedent,
    Eof,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Tag {
    Integer,
    Float,
    Str,
    Name,
    If,
    Elif,
    Else,
    While,
    For,
    In,
    Def,
    Return,
    And,
    Or,
    Not,
    True,
    False,
    None,
    Plus,
    Minus,
    Star,
    Slash,
    Percent,
    DoubleSlash,
    DoubleStar,
    EqEqual,
    NotEqual,
    Less,
    LessEqual,
    Greater,
    GreaterEqual,
    Equal,
    PlusEqual,
    MinusEqual,
    StarEqual,
    SlashEqual,
    LParen,
    RParen,
    LBracket,
    RBracket,
    Colon,
    Comma,
    Dot,
    Newline,
    Indent,
    Dedent,
    Eof,
}

impl Tag {
    /// Human readable form, mirrors the `.value` string of the Python TT enum.
    pub fn human(self) -> &'static str {
        match self {
            Tag::Integer => "INTEGER",
            Tag::Float => "FLOAT",
            Tag::Str => "STRING",
            Tag::Name => "NAME",
            Tag::If => "if",
            Tag::Elif => "elif",
            Tag::Else => "else",
            Tag::While => "while",
            Tag::For => "for",
            Tag::In => "in",
            Tag::Def => "def",
            Tag::Return => "return",
            Tag::And => "and",
            Tag::Or => "or",
            Tag::Not => "not",
            Tag::True => "True",
            Tag::False => "False",
            Tag::None => "None",
            Tag::Plus => "+",
            Tag::Minus => "-",
            Tag::Star => "*",
            Tag::Slash => "/",
            Tag::Percent => "%",
            Tag::DoubleSlash => "//",
            Tag::DoubleStar => "**",
            Tag::EqEqual => "==",
            Tag::NotEqual => "!=",
            Tag::Less => "<",
            Tag::LessEqual => "<=",
            Tag::Greater => ">",
            Tag::GreaterEqual => ">=",
            Tag::Equal => "=",
            Tag::PlusEqual => "+=",
            Tag::MinusEqual => "-=",
            Tag::StarEqual => "*=",
            Tag::SlashEqual => "/=",
            Tag::LParen => "(",
            Tag::RParen => ")",
            Tag::LBracket => "[",
            Tag::RBracket => "]",
            Tag::Colon => ":",
            Tag::Comma => ",",
            Tag::Dot => ".",
            Tag::Newline => "NEWLINE",
            Tag::Indent => "INDENT",
            Tag::Dedent => "DEDENT",
            Tag::Eof => "EOF",
        }
    }
}

impl TokKind {
    pub fn tag(&self) -> Tag {
        match self {
            TokKind::Integer(_) => Tag::Integer,
            TokKind::Float(_) => Tag::Float,
            TokKind::Str(_) => Tag::Str,
            TokKind::Name(_) => Tag::Name,
            TokKind::If => Tag::If,
            TokKind::Elif => Tag::Elif,
            TokKind::Else => Tag::Else,
            TokKind::While => Tag::While,
            TokKind::For => Tag::For,
            TokKind::In => Tag::In,
            TokKind::Def => Tag::Def,
            TokKind::Return => Tag::Return,
            TokKind::And => Tag::And,
            TokKind::Or => Tag::Or,
            TokKind::Not => Tag::Not,
            TokKind::True => Tag::True,
            TokKind::False => Tag::False,
            TokKind::None => Tag::None,
            TokKind::Plus => Tag::Plus,
            TokKind::Minus => Tag::Minus,
            TokKind::Star => Tag::Star,
            TokKind::Slash => Tag::Slash,
            TokKind::Percent => Tag::Percent,
            TokKind::DoubleSlash => Tag::DoubleSlash,
            TokKind::DoubleStar => Tag::DoubleStar,
            TokKind::EqEqual => Tag::EqEqual,
            TokKind::NotEqual => Tag::NotEqual,
            TokKind::Less => Tag::Less,
            TokKind::LessEqual => Tag::LessEqual,
            TokKind::Greater => Tag::Greater,
            TokKind::GreaterEqual => Tag::GreaterEqual,
            TokKind::Equal => Tag::Equal,
            TokKind::PlusEqual => Tag::PlusEqual,
            TokKind::MinusEqual => Tag::MinusEqual,
            TokKind::StarEqual => Tag::StarEqual,
            TokKind::SlashEqual => Tag::SlashEqual,
            TokKind::LParen => Tag::LParen,
            TokKind::RParen => Tag::RParen,
            TokKind::LBracket => Tag::LBracket,
            TokKind::RBracket => Tag::RBracket,
            TokKind::Colon => Tag::Colon,
            TokKind::Comma => Tag::Comma,
            TokKind::Dot => Tag::Dot,
            TokKind::Newline => Tag::Newline,
            TokKind::Indent => Tag::Indent,
            TokKind::Dedent => Tag::Dedent,
            TokKind::Eof => Tag::Eof,
        }
    }

    /// A short display of the token's payload, used in error messages.
    pub fn describe(&self) -> String {
        match self {
            TokKind::Integer(v) => v.to_string(),
            TokKind::Float(v) => v.to_string(),
            TokKind::Str(v) => format!("{:?}", v),
            TokKind::Name(v) => v.clone(),
            other => other.tag().human().to_string(),
        }
    }

    /// Mimics Python's `repr()` of the token's payload value, as used in
    /// the original interpreter's parser error messages (e.g. `{got.value!r}`).
    pub fn describe_quoted(&self) -> String {
        match self {
            TokKind::Integer(v) => v.to_string(),
            TokKind::Float(v) => v.to_string(),
            TokKind::Str(v) => python_repr_str(v),
            TokKind::Name(v) => python_repr_str(v),
            TokKind::Eof => "None".to_string(),
            TokKind::Newline => "'\\n'".to_string(),
            TokKind::Indent | TokKind::Dedent => "None".to_string(),
            other => python_repr_str(other.tag().human()),
        }
    }
}

fn python_repr_str(s: &str) -> String {
    if s.contains('\'') && !s.contains('"') {
        format!("\"{}\"", s)
    } else {
        format!("'{}'", s.replace('\\', "\\\\").replace('\'', "\\'"))
    }
}

#[derive(Debug, Clone)]
pub struct Token {
    pub kind: TokKind,
    pub line: usize,
    pub col: usize,
}

impl Token {
    pub fn new(kind: TokKind, line: usize, col: usize) -> Self {
        Token { kind, line, col }
    }
}
}

mod errors {
use crate::value::Value;
use std::fmt;

/// Mirrors the Python `PyError` hierarchy (LexerError / ParseError / PyRuntimeError).
#[derive(Debug, Clone)]
pub enum PyError {
    Lexer(String, Option<usize>),
    Parse(String, Option<usize>),
    Runtime(String, Option<usize>),
}

impl PyError {
    fn label(&self) -> &'static str {
        match self {
            PyError::Lexer(..) => "LexerError",
            PyError::Parse(..) => "ParseError",
            PyError::Runtime(..) => "PyRuntimeError",
        }
    }

    fn message(&self) -> &str {
        match self {
            PyError::Lexer(m, _) | PyError::Parse(m, _) | PyError::Runtime(m, _) => m,
        }
    }

    fn line(&self) -> Option<usize> {
        match self {
            PyError::Lexer(_, l) | PyError::Parse(_, l) | PyError::Runtime(_, l) => *l,
        }
    }

    /// Colorless rendering (used when writing to non-tty sinks, tests, etc).
    #[allow(dead_code)]
    pub fn plain(&self) -> String {
        let loc = match self.line() {
            Some(l) => format!(" [line {}]", l),
            Option::None => String::new(),
        };
        format!("{}: {}{}", self.label(), self.message(), loc)
    }
}

impl fmt::Display for PyError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        let loc = match self.line() {
            Some(l) => format!(" [line {}]", l),
            Option::None => String::new(),
        };
        write!(f, "\x1b[91m{}\x1b[0m: {}{}", self.label(), self.message(), loc)
    }
}

/// Statement execution can either fail with a `PyError` or unwind the
/// call stack because of a `return` statement — this plays the role
/// that raising `ReturnSignal` played in the Python interpreter.
pub enum Flow {
    Error(PyError),
    Return(Value),
}

impl From<PyError> for Flow {
    fn from(e: PyError) -> Self {
        Flow::Error(e)
    }
}

#[allow(dead_code)]
pub type EvalResult = Result<Value, PyError>;
pub type ExecResult = Result<(), Flow>;
}

mod ast {
//! AST nodes. Roughly mirrors CPython's `Grammar/python.asdl`, same as
//! the reference Python implementation being ported.

#[derive(Debug, Clone)]
pub enum Expr {
    Int(i64, usize),
    Float(f64, usize),
    Str(String, usize),
    Bool(bool, usize),
    NoneLit(usize),
    Name(String, usize),
    List(Vec<Expr>, usize),
    Subscript {
        value: Box<Expr>,
        index: Box<Expr>,
        line: usize,
    },
    BinOp {
        left: Box<Expr>,
        op: String,
        right: Box<Expr>,
        line: usize,
    },
    UnaryOp {
        op: String,
        operand: Box<Expr>,
        line: usize,
    },
    Compare {
        left: Box<Expr>,
        op: String,
        right: Box<Expr>,
        line: usize,
    },
    BoolOp {
        op: String,
        values: Vec<Expr>,
        line: usize,
    },
    Call {
        func: Box<Expr>,
        args: Vec<Expr>,
        line: usize,
    },
    MethodCall {
        obj: Box<Expr>,
        method: String,
        args: Vec<Expr>,
        line: usize,
    },
}

impl Expr {
    pub fn line(&self) -> usize {
        match self {
            Expr::Int(_, l) | Expr::Float(_, l) | Expr::Str(_, l) | Expr::Bool(_, l) | Expr::NoneLit(l) => *l,
            Expr::Name(_, l) => *l,
            Expr::List(_, l) => *l,
            Expr::Subscript { line, .. }
            | Expr::BinOp { line, .. }
            | Expr::UnaryOp { line, .. }
            | Expr::Compare { line, .. }
            | Expr::BoolOp { line, .. }
            | Expr::Call { line, .. }
            | Expr::MethodCall { line, .. } => *line,
        }
    }
}

#[derive(Debug, Clone)]
pub enum Stmt {
    FuncDef {
        name: String,
        params: Vec<String>,
        body: Vec<Stmt>,
        line: usize,
    },
    Assign {
        target: String,
        value: Expr,
        line: usize,
    },
    AugAssign {
        target: String,
        op: String,
        value: Expr,
        line: usize,
    },
    ExprStmt {
        expr: Expr,
        #[allow(dead_code)]
        line: usize,
    },
    Return {
        value: Option<Expr>,
        #[allow(dead_code)]
        line: usize,
    },
    If {
        test: Expr,
        body: Vec<Stmt>,
        orelse: Vec<Stmt>,
        #[allow(dead_code)]
        line: usize,
    },
    While {
        test: Expr,
        body: Vec<Stmt>,
        #[allow(dead_code)]
        line: usize,
    },
    For {
        target: String,
        iter: Expr,
        body: Vec<Stmt>,
        line: usize,
    },
}

#[derive(Debug, Clone)]
pub struct Program {
    pub body: Vec<Stmt>,
}
}

mod lexer {
//! Single-pass, character-by-character tokenizer.
//!
//! Key design points (from CPython Lib/tokenize.py), mirrored from the
//! original Python implementation:
//!   * `indent_stack` tracks indentation depth -> INDENT / DEDENT tokens
//!   * blank/comment lines are silently skipped (no NEWLINE emitted)
//!   * `paren_depth` > 0 suppresses physical-newline NEWLINE tokens,
//!     enabling implicit line continuation inside `(` `)` or `[` `]`

use crate::errors::PyError;
use crate::token::{TokKind, Token};

pub struct Lexer {
    src: Vec<char>,
    pos: usize,
    line: usize,
    col: usize,
    tokens: Vec<Token>,
    indent_stack: Vec<usize>,
    at_line_start: bool,
    paren_depth: i32,
}

impl Lexer {
    pub fn new(source: &str) -> Self {
        Lexer {
            src: source.chars().collect(),
            pos: 0,
            line: 1,
            col: 1,
            tokens: Vec::new(),
            indent_stack: vec![0],
            at_line_start: true,
            paren_depth: 0,
        }
    }

    pub fn tokenize(mut self) -> Result<Vec<Token>, PyError> {
        while self.pos < self.src.len() {
            self.next_token()?;
        }
        self.close_all_indents();
        let needs_newline = !matches!(
            self.tokens.last().map(|t| &t.kind),
            Some(TokKind::Newline) | Some(TokKind::Dedent)
        );
        if needs_newline {
            self.tokens.push(Token::new(TokKind::Newline, self.line, self.col));
        }
        self.tokens.push(Token::new(TokKind::Eof, self.line, self.col));
        Ok(self.tokens)
    }

    // ── Character helpers ───────────────────────────────────────────────

    fn cur(&self) -> char {
        *self.src.get(self.pos).unwrap_or(&'\0')
    }

    fn peek_at(&self, n: usize) -> char {
        *self.src.get(self.pos + n).unwrap_or(&'\0')
    }

    fn here(&self) -> (usize, usize) {
        (self.line, self.col)
    }

    fn advance(&mut self) -> char {
        let ch = self.src[self.pos];
        self.pos += 1;
        if ch == '\n' {
            self.line += 1;
            self.col = 1;
        } else {
            self.col += 1;
        }
        ch
    }

    fn err<T>(&self, msg: &str) -> Result<T, PyError> {
        Err(PyError::Lexer(msg.to_string(), Some(self.line)))
    }

    fn close_all_indents(&mut self) {
        while self.indent_stack.len() > 1 {
            self.indent_stack.pop();
            self.tokens.push(Token::new(TokKind::Dedent, self.line, self.col));
        }
    }

    // ── Main dispatch ───────────────────────────────────────────────────

    fn next_token(&mut self) -> Result<(), PyError> {
        if self.at_line_start && self.paren_depth == 0 {
            return self.handle_indentation();
        }

        let ch = self.cur();

        if ch == ' ' || ch == '\t' {
            self.advance();
            return Ok(());
        }
        if ch == '\n' {
            let (ln, cl) = self.here();
            self.advance();
            if self.paren_depth == 0 {
                self.tokens.push(Token::new(TokKind::Newline, ln, cl));
                self.at_line_start = true;
            }
            return Ok(());
        }
        if ch == '\r' {
            self.advance();
            return Ok(());
        }
        if ch == '#' {
            while self.cur() != '\n' && self.cur() != '\0' {
                self.advance();
            }
            return Ok(());
        }
        if ch == '"' || ch == '\'' {
            return self.read_string();
        }
        if ch.is_ascii_digit() {
            return self.read_number();
        }
        if ch.is_alphabetic() || ch == '_' {
            return self.read_name();
        }
        self.read_operator()
    }

    // ── Indentation ──────────────────────────────────────────────────────

    fn handle_indentation(&mut self) -> Result<(), PyError> {
        let mut indent = 0usize;
        while self.cur() == ' ' || self.cur() == '\t' {
            if self.cur() == '\t' {
                indent = (indent / 8 + 1) * 8;
            } else {
                indent += 1;
            }
            self.advance();
        }

        let ch = self.cur();
        // blank or comment line — skip entirely
        if ch == '\n' || ch == '\r' || ch == '\0' || ch == '#' {
            if ch == '#' {
                while self.cur() != '\n' && self.cur() != '\0' {
                    self.advance();
                }
            }
            if self.cur() == '\n' {
                self.advance();
            }
            return Ok(());
        }

        self.at_line_start = false;
        let current = *self.indent_stack.last().unwrap();

        if indent > current {
            self.indent_stack.push(indent);
            self.tokens.push(Token::new(TokKind::Indent, self.line, 1));
        } else if indent < current {
            while self.indent_stack.len() > 1 && *self.indent_stack.last().unwrap() > indent {
                self.indent_stack.pop();
                self.tokens.push(Token::new(TokKind::Dedent, self.line, 1));
            }
            if *self.indent_stack.last().unwrap() != indent {
                return self.err("IndentationError: unindent does not match any outer indentation level");
            }
        }
        Ok(())
    }

    // ── Strings ──────────────────────────────────────────────────────────

    fn read_string(&mut self) -> Result<(), PyError> {
        let (ln, cl) = self.here();
        let q = self.advance();
        // triple-quoted
        if self.cur() == q && self.peek_at(1) == q {
            self.advance();
            self.advance();
            let mut buf = String::new();
            loop {
                let ch = self.cur();
                if ch == '\0' {
                    return self.err("SyntaxError: EOF in triple-quoted string");
                }
                if ch == q && self.peek_at(1) == q && self.peek_at(2) == q {
                    self.advance();
                    self.advance();
                    self.advance();
                    break;
                }
                if ch == '\\' {
                    self.advance();
                    let esc = self.advance();
                    buf.push_str(escape_str(esc));
                } else {
                    buf.push(self.advance());
                }
            }
            self.tokens.push(Token::new(TokKind::Str(buf), ln, cl));
            return Ok(());
        }
        // single-quoted
        let mut buf = String::new();
        loop {
            let ch = self.cur();
            if ch == '\0' {
                return self.err("SyntaxError: unterminated string");
            }
            if ch == '\n' {
                return self.err("SyntaxError: EOL in string");
            }
            if ch == q {
                self.advance();
                break;
            }
            if ch == '\\' {
                self.advance();
                let esc = self.advance();
                buf.push_str(escape_str(esc));
            } else {
                buf.push(self.advance());
            }
        }
        self.tokens.push(Token::new(TokKind::Str(buf), ln, cl));
        Ok(())
    }

    // ── Numbers ──────────────────────────────────────────────────────────

    fn read_number(&mut self) -> Result<(), PyError> {
        let (ln, cl) = self.here();
        let mut digits = String::new();
        let mut is_float = false;
        while self.cur().is_ascii_digit() {
            digits.push(self.advance());
        }
        if self.cur() == '.' && self.peek_at(1).is_ascii_digit() {
            is_float = true;
            digits.push(self.advance());
            while self.cur().is_ascii_digit() {
                digits.push(self.advance());
            }
        }
        if self.cur() == 'e' || self.cur() == 'E' {
            is_float = true;
            digits.push(self.advance());
            if self.cur() == '+' || self.cur() == '-' {
                digits.push(self.advance());
            }
            if !self.cur().is_ascii_digit() {
                return self.err("SyntaxError: invalid numeric literal");
            }
            while self.cur().is_ascii_digit() {
                digits.push(self.advance());
            }
        }
        if is_float {
            let v: f64 = digits.parse().unwrap_or(0.0);
            self.tokens.push(Token::new(TokKind::Float(v), ln, cl));
        } else {
            let v: i64 = digits.parse().unwrap_or(0);
            self.tokens.push(Token::new(TokKind::Integer(v), ln, cl));
        }
        Ok(())
    }

    // ── Names / keywords ─────────────────────────────────────────────────

    fn read_name(&mut self) -> Result<(), PyError> {
        let (ln, cl) = self.here();
        let mut buf = String::new();
        while self.cur().is_alphanumeric() || self.cur() == '_' {
            buf.push(self.advance());
        }
        let kind = match buf.as_str() {
            "if" => TokKind::If,
            "elif" => TokKind::Elif,
            "else" => TokKind::Else,
            "while" => TokKind::While,
            "for" => TokKind::For,
            "in" => TokKind::In,
            "def" => TokKind::Def,
            "return" => TokKind::Return,
            "and" => TokKind::And,
            "or" => TokKind::Or,
            "not" => TokKind::Not,
            "True" => TokKind::True,
            "False" => TokKind::False,
            "None" => TokKind::None,
            _ => TokKind::Name(buf),
        };
        self.tokens.push(Token::new(kind, ln, cl));
        Ok(())
    }

    // ── Operators ────────────────────────────────────────────────────────

    fn read_operator(&mut self) -> Result<(), PyError> {
        let (ln, cl) = self.here();
        let ch = self.advance();
        let kind = match ch {
            '+' => {
                if self.cur() == '=' {
                    self.advance();
                    TokKind::PlusEqual
                } else {
                    TokKind::Plus
                }
            }
            '-' => {
                if self.cur() == '=' {
                    self.advance();
                    TokKind::MinusEqual
                } else {
                    TokKind::Minus
                }
            }
            '*' => {
                if self.cur() == '*' {
                    self.advance();
                    TokKind::DoubleStar
                } else if self.cur() == '=' {
                    self.advance();
                    TokKind::StarEqual
                } else {
                    TokKind::Star
                }
            }
            '/' => {
                if self.cur() == '/' {
                    self.advance();
                    TokKind::DoubleSlash
                } else if self.cur() == '=' {
                    self.advance();
                    TokKind::SlashEqual
                } else {
                    TokKind::Slash
                }
            }
            '=' => {
                if self.cur() == '=' {
                    self.advance();
                    TokKind::EqEqual
                } else {
                    TokKind::Equal
                }
            }
            '!' => {
                if self.cur() == '=' {
                    self.advance();
                    TokKind::NotEqual
                } else {
                    return self.err("SyntaxError: '!' must be followed by '='");
                }
            }
            '<' => {
                if self.cur() == '=' {
                    self.advance();
                    TokKind::LessEqual
                } else {
                    TokKind::Less
                }
            }
            '>' => {
                if self.cur() == '=' {
                    self.advance();
                    TokKind::GreaterEqual
                } else {
                    TokKind::Greater
                }
            }
            '%' => TokKind::Percent,
            '(' => {
                self.paren_depth += 1;
                TokKind::LParen
            }
            ')' => {
                self.paren_depth = (self.paren_depth - 1).max(0);
                TokKind::RParen
            }
            '[' => {
                self.paren_depth += 1;
                TokKind::LBracket
            }
            ']' => {
                self.paren_depth = (self.paren_depth - 1).max(0);
                TokKind::RBracket
            }
            ':' => TokKind::Colon,
            ',' => TokKind::Comma,
            '.' => TokKind::Dot,
            other => {
                return self.err(&format!("SyntaxError: unexpected character {:?}", other));
            }
        };
        self.tokens.push(Token::new(kind, ln, cl));
        Ok(())
    }
}

fn escape_str(c: char) -> &'static str {
    match c {
        'n' => "\n",
        't' => "\t",
        'r' => "\r",
        '\\' => "\\",
        '\'' => "'",
        '"' => "\"",
        '0' => "\0",
        'a' => "\u{7}",
        'b' => "\u{8}",
        _ => "",
    }
}
}

mod value {
use crate::ast::Stmt;
use crate::env::Env;
use std::cell::RefCell;
use std::rc::Rc;

/// Runtime values. Lists are `Rc<RefCell<..>>` so that mutation
/// (append/pop, or assignment through a shared reference) matches
/// Python's reference semantics for mutable objects.
#[derive(Clone)]
pub enum Value {
    Int(i64),
    Float(f64),
    Str(String),
    Bool(bool),
    None,
    List(Rc<RefCell<Vec<Value>>>),
    Function(Rc<PyFunction>),
    /// Name of a builtin (dispatched by `crate::builtins::call`).
    Builtin(String),
}

pub struct PyFunction {
    pub name: String,
    pub params: Vec<String>,
    pub body: Vec<Stmt>,
    pub closure: Rc<Env>,
}

impl Value {
    pub fn new_list(v: Vec<Value>) -> Value {
        Value::List(Rc::new(RefCell::new(v)))
    }

    pub fn is_number(&self) -> bool {
        matches!(self, Value::Int(_) | Value::Float(_) | Value::Bool(_))
    }

    /// Numeric value as f64, for arithmetic where bool counts as 0/1
    /// (Python: bool is a subclass of int).
    pub fn as_f64(&self) -> Option<f64> {
        match self {
            Value::Int(i) => Some(*i as f64),
            Value::Float(f) => Some(*f),
            Value::Bool(b) => Some(if *b { 1.0 } else { 0.0 }),
            _ => None,
        }
    }

    pub fn as_i64(&self) -> Option<i64> {
        match self {
            Value::Int(i) => Some(*i),
            Value::Bool(b) => Some(if *b { 1 } else { 0 }),
            Value::Float(f) => Some(*f as i64),
            _ => None,
        }
    }

    /// True if this numeric value should be treated as a Python `int`
    /// (int or bool) rather than `float`, for result-typing purposes.
    pub fn is_int_like(&self) -> bool {
        matches!(self, Value::Int(_) | Value::Bool(_))
    }
}

pub fn type_name(v: &Value) -> &'static str {
    match v {
        Value::None => "NoneType",
        Value::Bool(_) => "bool",
        Value::Int(_) => "int",
        Value::Float(_) => "float",
        Value::Str(_) => "str",
        Value::List(_) => "list",
        Value::Function(_) => "function",
        Value::Builtin(_) => "builtin_function_or_method",
    }
}

pub fn ep_str(v: &Value) -> String {
    match v {
        Value::None => "None".to_string(),
        Value::Bool(b) => {
            if *b {
                "True".to_string()
            } else {
                "False".to_string()
            }
        }
        Value::Int(i) => i.to_string(),
        Value::Float(f) => format_float(*f),
        Value::Str(s) => s.clone(),
        Value::List(l) => {
            let items: Vec<String> = l.borrow().iter().map(ep_str).collect();
            format!("[{}]", items.join(", "))
        }
        Value::Function(f) => format!("<function {}>", f.name),
        Value::Builtin(n) => format!("<built-in function {}>", n),
    }
}

/// Render a float the way Python's `repr`/`str` roughly would:
/// whole-valued floats keep a trailing `.0`.
pub fn format_float(f: f64) -> String {
    if f.is_nan() {
        "nan".to_string()
    } else if f.is_infinite() {
        if f > 0.0 {
            "inf".to_string()
        } else {
            "-inf".to_string()
        }
    } else if f.fract() == 0.0 && f.abs() < 1e16 {
        format!("{:.1}", f)
    } else {
        f.to_string()
    }
}

pub fn ep_bool(v: &Value) -> bool {
    match v {
        Value::None => false,
        Value::Bool(b) => *b,
        Value::Int(i) => *i != 0,
        Value::Float(f) => *f != 0.0,
        Value::Str(s) => !s.is_empty(),
        Value::List(l) => !l.borrow().is_empty(),
        Value::Function(_) | Value::Builtin(_) => true,
    }
}

pub fn values_equal(a: &Value, b: &Value) -> bool {
    use Value::*;
    match (a, b) {
        (None, None) => true,
        (None, _) | (_, None) => false,
        (Str(x), Str(y)) => x == y,
        (List(x), List(y)) => {
            let xb = x.borrow();
            let yb = y.borrow();
            xb.len() == yb.len() && xb.iter().zip(yb.iter()).all(|(p, q)| values_equal(p, q))
        }
        (Str(_), _) | (_, Str(_)) | (List(_), _) | (_, List(_)) => false,
        (Function(x), Function(y)) => Rc::ptr_eq(x, y),
        (Function(_), _) | (_, Function(_)) => false,
        (Builtin(x), Builtin(y)) => x == y,
        (Builtin(_), _) | (_, Builtin(_)) => false,
        // Remaining combinations are all numeric (Int/Float/Bool).
        _ => a.as_f64() == b.as_f64(),
    }
}
}

mod env {
//! A dictionary-backed variable scope.
//!
//! Scopes are linked by `parent` — lookup walks the chain outward
//! (like CPython's LEGB rule, minus global/builtin distinctions),
//! mirroring the original Python `Environment` class.

use crate::errors::PyError;
use crate::value::Value;
use std::cell::RefCell;
use std::collections::HashMap;
use std::rc::Rc;

pub struct Env {
    pub vars: RefCell<HashMap<String, Value>>,
    pub parent: Option<Rc<Env>>,
}

impl Env {
    pub fn new(parent: Option<Rc<Env>>) -> Rc<Env> {
        Rc::new(Env {
            vars: RefCell::new(HashMap::new()),
            parent,
        })
    }

    pub fn get(&self, name: &str, line: Option<usize>) -> Result<Value, PyError> {
        if let Some(v) = self.vars.borrow().get(name) {
            return Ok(v.clone());
        }
        if let Some(p) = &self.parent {
            return p.get(name, line);
        }
        Err(PyError::Runtime(
            format!("NameError: name '{}' is not defined", name),
            line,
        ))
    }

    /// Always sets in the *current* scope (like Python assignment).
    pub fn set(&self, name: &str, value: Value) {
        self.vars.borrow_mut().insert(name.to_string(), value);
    }

    pub fn owns(&self, name: &str) -> bool {
        if self.vars.borrow().contains_key(name) {
            return true;
        }
        match &self.parent {
            Some(p) => p.owns(name),
            Option::None => false,
        }
    }

    /// Assign to the nearest scope that already owns `name`.
    /// Falls back to the current scope (new variable).
    pub fn assign(&self, name: &str, value: Value) {
        if self.vars.borrow().contains_key(name) {
            self.vars.borrow_mut().insert(name.to_string(), value);
            return;
        }
        if let Some(p) = &self.parent {
            if p.owns(name) {
                p.assign(name, value);
                return;
            }
        }
        self.vars.borrow_mut().insert(name.to_string(), value);
    }
}
}

mod builtins {
//! Builtin functions, mirroring the `BUILTINS` dict of the Python
//! reference implementation. Dispatched by name from `Value::Builtin`.

use crate::errors::PyError;
use crate::value::{ep_bool, ep_str, type_name, Value};

pub const NAMES: &[&str] = &[
    "print", "len", "range", "int", "float", "str", "bool", "input", "abs", "max", "min", "type",
    "append", "pop",
];

fn rt<T>(msg: impl Into<String>) -> Result<T, PyError> {
    Err(PyError::Runtime(msg.into(), None))
}

pub fn call(name: &str, args: &[Value]) -> Result<Value, PyError> {
    match name {
        "print" => builtin_print(args),
        "len" => builtin_len(args),
        "range" => builtin_range(args),
        "int" => builtin_int(args),
        "float" => builtin_float(args),
        "str" => builtin_str(args),
        "bool" => builtin_bool(args),
        "input" => builtin_input(args),
        "abs" => builtin_abs(args),
        "max" => builtin_max(args),
        "min" => builtin_min(args),
        "type" => builtin_type(args),
        "append" => builtin_append(args),
        "pop" => builtin_pop(args),
        _ => rt(format!("NameError: name '{}' is not defined", name)),
    }
}

fn builtin_print(args: &[Value]) -> Result<Value, PyError> {
    let parts: Vec<String> = args.iter().map(ep_str).collect();
    println!("{}", parts.join(" "));
    Ok(Value::None)
}

fn builtin_len(args: &[Value]) -> Result<Value, PyError> {
    if args.len() != 1 {
        return rt("TypeError: len() takes exactly 1 argument");
    }
    match &args[0] {
        Value::Str(s) => Ok(Value::Int(s.chars().count() as i64)),
        Value::List(l) => Ok(Value::Int(l.borrow().len() as i64)),
        other => rt(format!("TypeError: object of type '{}' has no len()", type_name(other))),
    }
}

fn builtin_range(args: &[Value]) -> Result<Value, PyError> {
    if args.is_empty() || args.len() > 3 {
        return rt("TypeError: range() takes 1\u{2013}3 arguments");
    }
    let mut ints = Vec::with_capacity(args.len());
    for a in args {
        match a.as_i64() {
            Some(_) if a.is_number() => ints.push(a.as_i64().unwrap()),
            _ => return rt("TypeError: range() arguments must be integers"),
        }
    }
    let (start, stop, step) = match ints.len() {
        1 => (0, ints[0], 1),
        2 => (ints[0], ints[1], 1),
        3 => (ints[0], ints[1], ints[2]),
        _ => unreachable!(),
    };
    if step == 0 {
        return rt("ValueError: range() arg 3 must not be zero");
    }
    let mut out = Vec::new();
    if step > 0 {
        let mut i = start;
        while i < stop {
            out.push(Value::Int(i));
            i += step;
        }
    } else {
        let mut i = start;
        while i > stop {
            out.push(Value::Int(i));
            i += step;
        }
    }
    Ok(Value::new_list(out))
}

fn builtin_int(args: &[Value]) -> Result<Value, PyError> {
    if args.len() != 1 {
        return rt("TypeError: int() takes 1 argument");
    }
    match &args[0] {
        Value::Bool(b) => Ok(Value::Int(if *b { 1 } else { 0 })),
        Value::Int(i) => Ok(Value::Int(*i)),
        Value::Float(f) => Ok(Value::Int(*f as i64)),
        Value::Str(s) => {
            let t = s.trim();
            let (sign, rest) = if let Some(r) = t.strip_prefix('-') {
                ("-", r)
            } else if let Some(r) = t.strip_prefix('+') {
                ("", r)
            } else {
                ("", t)
            };
            if !rest.is_empty() && rest.chars().all(|c| c.is_ascii_digit()) {
                let combined = format!("{}{}", sign, rest);
                combined
                    .parse::<i64>()
                    .map(Value::Int)
                    .or_else(|_| rt(format!("ValueError: invalid literal for int(): {:?}", s)))
            } else {
                rt(format!("ValueError: invalid literal for int(): {:?}", s))
            }
        }
        other => rt(format!(
            "TypeError: int() argument must be a string or number, not '{}'",
            type_name(other)
        )),
    }
}

fn builtin_float(args: &[Value]) -> Result<Value, PyError> {
    if args.len() != 1 {
        return rt("TypeError: float() takes 1 argument");
    }
    match &args[0] {
        Value::Bool(b) => Ok(Value::Float(if *b { 1.0 } else { 0.0 })),
        Value::Int(i) => Ok(Value::Float(*i as f64)),
        Value::Float(f) => Ok(Value::Float(*f)),
        Value::Str(s) => {
            let t = s.trim();
            if t.is_empty() {
                return rt(format!(
                    "TypeError: float() argument must be a string or number, not '{}'",
                    "str"
                ));
            }
            t.parse::<f64>()
                .map(Value::Float)
                .or_else(|_| rt(format!("ValueError: could not convert string to float: {:?}", s)))
        }
        other => rt(format!(
            "TypeError: float() argument must be a string or number, not '{}'",
            type_name(other)
        )),
    }
}

fn builtin_str(args: &[Value]) -> Result<Value, PyError> {
    if args.len() != 1 {
        return rt("TypeError: str() takes 1 argument");
    }
    Ok(Value::Str(ep_str(&args[0])))
}

fn builtin_bool(args: &[Value]) -> Result<Value, PyError> {
    if args.len() != 1 {
        return rt("TypeError: bool() takes 1 argument");
    }
    Ok(Value::Bool(ep_bool(&args[0])))
}

fn builtin_input(args: &[Value]) -> Result<Value, PyError> {
    use std::io::Write;
    if let Some(a) = args.first() {
        print!("{}", ep_str(a));
        let _ = std::io::stdout().flush();
    }
    let mut line = String::new();
    std::io::stdin()
        .read_line(&mut line)
        .map_err(|e| PyError::Runtime(format!("IOError: {}", e), None))?;
    if line.ends_with('\n') {
        line.pop();
        if line.ends_with('\r') {
            line.pop();
        }
    }
    Ok(Value::Str(line))
}

fn builtin_abs(args: &[Value]) -> Result<Value, PyError> {
    if args.len() != 1 {
        return rt("TypeError: abs() takes 1 argument");
    }
    match &args[0] {
        Value::Int(i) => Ok(Value::Int(i.abs())),
        Value::Float(f) => Ok(Value::Float(f.abs())),
        other => rt(format!("TypeError: bad operand type for abs(): '{}'", type_name(other))),
    }
}

fn cmp_values(a: &Value, b: &Value) -> std::cmp::Ordering {
    use std::cmp::Ordering;
    match (a, b) {
        (Value::Str(x), Value::Str(y)) => x.cmp(y),
        _ => a
            .as_f64()
            .unwrap_or(f64::NAN)
            .partial_cmp(&b.as_f64().unwrap_or(f64::NAN))
            .unwrap_or(Ordering::Equal),
    }
}

fn builtin_max(args: &[Value]) -> Result<Value, PyError> {
    if args.is_empty() {
        return rt("TypeError: max() expected at least 1 argument");
    }
    let items: Vec<Value> = if args.len() == 1 {
        match &args[0] {
            Value::List(l) => l.borrow().clone(),
            _ => args.to_vec(),
        }
    } else {
        args.to_vec()
    };
    if items.is_empty() {
        return rt("ValueError: max() arg is an empty sequence");
    }
    let mut best = items[0].clone();
    for v in &items[1..] {
        if cmp_values(v, &best) == std::cmp::Ordering::Greater {
            best = v.clone();
        }
    }
    Ok(best)
}

fn builtin_min(args: &[Value]) -> Result<Value, PyError> {
    if args.is_empty() {
        return rt("TypeError: min() expected at least 1 argument");
    }
    let items: Vec<Value> = if args.len() == 1 {
        match &args[0] {
            Value::List(l) => l.borrow().clone(),
            _ => args.to_vec(),
        }
    } else {
        args.to_vec()
    };
    if items.is_empty() {
        return rt("ValueError: min() arg is an empty sequence");
    }
    let mut best = items[0].clone();
    for v in &items[1..] {
        if cmp_values(v, &best) == std::cmp::Ordering::Less {
            best = v.clone();
        }
    }
    Ok(best)
}

fn builtin_type(args: &[Value]) -> Result<Value, PyError> {
    if args.len() != 1 {
        return rt("TypeError: type() takes 1 argument");
    }
    Ok(Value::Str(format!("<class '{}'>", type_name(&args[0]))))
}

fn builtin_append(args: &[Value]) -> Result<Value, PyError> {
    if args.len() != 2 {
        return rt("TypeError: append() takes 2 arguments");
    }
    match &args[0] {
        Value::List(l) => {
            l.borrow_mut().push(args[1].clone());
            Ok(Value::None)
        }
        _ => rt("TypeError: first argument must be a list"),
    }
}

fn builtin_pop(args: &[Value]) -> Result<Value, PyError> {
    if args.is_empty() || args.len() > 2 {
        return rt("TypeError: pop() takes 1 or 2 arguments");
    }
    match &args[0] {
        Value::List(l) => {
            let idx = if args.len() == 2 {
                args[1].as_i64().unwrap_or(-1)
            } else {
                -1
            };
            let mut lst = l.borrow_mut();
            if lst.is_empty() {
                return rt("IndexError: pop from empty list");
            }
            let len = lst.len() as i64;
            let real_idx = if idx < 0 { idx + len } else { idx };
            if real_idx < 0 || real_idx >= len {
                return rt(format!("IndexError: pop index {} out of range", idx));
            }
            Ok(lst.remove(real_idx as usize))
        }
        _ => rt("TypeError: first argument must be a list"),
    }
}
}

mod parser {
//! PEG-style recursive descent parser. Grammar mirrors CPython's
//! `python.gram`, translated line-for-line from the Python reference
//! implementation being ported.
//!
//! Grammar (EBNF):
//!   program      := stmt* EOF
//!   stmt         := func_def | if_stmt | while_stmt | for_stmt | simple_stmt
//!   simple_stmt  := (assign | aug_assign | return | expr_stmt) NEWLINE
//!   assign       := NAME '=' expr
//!   aug_assign   := NAME ('+='|'-='|'*='|'/=') expr
//!   return_stmt  := 'return' [expr]
//!   func_def     := 'def' NAME '(' params? ')' ':' block
//!   if_stmt      := 'if' expr ':' block elif_else?
//!   elif_else    := ('elif' expr ':' block elif_else?) | ('else' ':' block)
//!   while_stmt   := 'while' expr ':' block
//!   for_stmt     := 'for' NAME 'in' expr ':' block
//!   block        := NEWLINE INDENT stmt+ DEDENT
//!   expr         := or_expr
//!   or_expr      := and_expr  ('or'  and_expr)*
//!   and_expr     := not_expr  ('and' not_expr)*
//!   not_expr     := 'not' not_expr | comparison
//!   comparison   := sum (comp_op sum)*
//!   sum          := term     (('+' | '-') term)*
//!   term         := factor   (('*'|'/'|'//'|'%') factor)*
//!   factor       := ('+'|'-') factor | power
//!   power        := primary  ['**' factor]
//!   primary      := atom (call_args | subscript | method_call)*
//!   method_call  := '.' NAME '(' args? ')'
//!   atom         := INT | FLOAT | STR | True | False | None
//!                 | NAME | '[' args? ']' | '(' expr ')'

use crate::ast::{Expr, Program, Stmt};
use crate::errors::PyError;
use crate::token::{Tag, TokKind, Token};

type PResult<T> = Result<T, PyError>;

pub struct Parser {
    tokens: Vec<Token>,
    pos: usize,
}

impl Parser {
    pub fn new(tokens: Vec<Token>) -> Self {
        Parser { tokens, pos: 0 }
    }

    // ── Cursor ────────────────────────────────────────────────────────────

    fn cur(&self) -> &Token {
        &self.tokens[self.pos.min(self.tokens.len() - 1)]
    }

    fn prev(&self) -> &Token {
        let idx = if self.pos == 0 { 0 } else { self.pos - 1 };
        &self.tokens[idx]
    }

    fn peek_tag(&self, n: usize) -> Tag {
        self.tokens[(self.pos + n).min(self.tokens.len() - 1)].kind.tag()
    }

    fn advance(&mut self) -> Token {
        let tok = self.cur().clone();
        if self.pos < self.tokens.len() - 1 {
            self.pos += 1;
        }
        tok
    }

    fn check(&self, tags: &[Tag]) -> bool {
        tags.contains(&self.cur().kind.tag())
    }

    fn matches(&mut self, tags: &[Tag]) -> bool {
        if self.check(tags) {
            self.advance();
            true
        } else {
            false
        }
    }

    fn expect(&mut self, tag: Tag, msg: Option<&str>) -> PResult<Token> {
        if !self.check(&[tag]) {
            let got = self.cur();
            let desc = match msg {
                Some(m) => m.to_string(),
                Option::None => format!(
                    "expected '{}', got '{}' ({})",
                    tag.human(),
                    got.kind.tag().human(),
                    got.kind.describe_quoted()
                ),
            };
            return Err(PyError::Parse(format!("SyntaxError: {}", desc), Some(got.line)));
        }
        Ok(self.advance())
    }

    fn err<T>(&self, msg: &str) -> PResult<T> {
        Err(PyError::Parse(format!("SyntaxError: {}", msg), Some(self.cur().line)))
    }

    fn skip_newlines(&mut self) {
        while self.check(&[Tag::Newline]) {
            self.advance();
        }
    }

    // ── Entry ─────────────────────────────────────────────────────────────

    pub fn parse(&mut self) -> PResult<Program> {
        let stmts = self.stmt_list()?;
        self.expect(Tag::Eof, Some("expected end of file"))?;
        Ok(Program { body: stmts })
    }

    // ── Statement list ───────────────────────────────────────────────────

    fn stmt_list(&mut self) -> PResult<Vec<Stmt>> {
        let mut stmts = Vec::new();
        loop {
            self.skip_newlines();
            if self.check(&[Tag::Eof, Tag::Dedent]) {
                break;
            }
            stmts.push(self.stmt()?);
        }
        Ok(stmts)
    }

    fn stmt(&mut self) -> PResult<Stmt> {
        self.skip_newlines();
        if self.matches(&[Tag::Def]) {
            return self.func_def();
        }
        if self.matches(&[Tag::If]) {
            return self.if_stmt();
        }
        if self.matches(&[Tag::While]) {
            return self.while_stmt();
        }
        if self.matches(&[Tag::For]) {
            return self.for_stmt();
        }
        self.simple_stmt()
    }

    // ── Simple statements ────────────────────────────────────────────────

    fn simple_stmt(&mut self) -> PResult<Stmt> {
        let node = if self.check(&[Tag::Return]) {
            self.advance();
            self.return_stmt()?
        } else if self.check(&[Tag::Name]) && self.peek_tag(1) == Tag::Equal {
            self.assign()?
        } else if self.check(&[Tag::Name])
            && matches!(
                self.peek_tag(1),
                Tag::PlusEqual | Tag::MinusEqual | Tag::StarEqual | Tag::SlashEqual
            )
        {
            self.aug_assign()?
        } else {
            let line = self.cur().line;
            Stmt::ExprStmt { expr: self.expr()?, line }
        };

        if self.check(&[Tag::Newline]) {
            self.advance();
        } else if !self.check(&[Tag::Eof, Tag::Dedent]) {
            let got = self.cur().kind.tag().human().to_string();
            return self.err(&format!("expected newline after statement, got '{}'", got));
        }
        Ok(node)
    }

    fn assign(&mut self) -> PResult<Stmt> {
        let t = self.expect(Tag::Name, None)?;
        let name = name_of(&t);
        self.expect(Tag::Equal, None)?;
        Ok(Stmt::Assign {
            target: name,
            value: self.expr()?,
            line: t.line,
        })
    }

    fn aug_assign(&mut self) -> PResult<Stmt> {
        let t = self.advance();
        let name = name_of(&t);
        let op_tok = self.advance();
        let op = op_tok.kind.tag().human().to_string();
        Ok(Stmt::AugAssign {
            target: name,
            op,
            value: self.expr()?,
            line: t.line,
        })
    }

    fn return_stmt(&mut self) -> PResult<Stmt> {
        let ln = self.prev().line;
        if self.check(&[Tag::Newline, Tag::Eof, Tag::Dedent]) {
            return Ok(Stmt::Return { value: Option::None, line: ln });
        }
        Ok(Stmt::Return {
            value: Some(self.expr()?),
            line: ln,
        })
    }

    // ── Compound statements ──────────────────────────────────────────────

    fn func_def(&mut self) -> PResult<Stmt> {
        let ln = self.prev().line;
        let name_tok = self.expect(Tag::Name, Some("expected function name"))?;
        let name = name_of(&name_tok);
        self.expect(Tag::LParen, Some("expected '(' after function name"))?;
        let mut params = Vec::new();
        if self.check(&[Tag::Name]) {
            params.push(name_of(&self.advance()));
            while self.matches(&[Tag::Comma]) {
                if !self.check(&[Tag::Name]) {
                    return self.err("expected parameter name");
                }
                params.push(name_of(&self.advance()));
            }
        }
        self.expect(Tag::RParen, Some("expected ')'"))?;
        self.expect(Tag::Colon, Some("expected ':' after function signature"))?;
        let body = self.block()?;
        Ok(Stmt::FuncDef { name, params, body, line: ln })
    }

    fn if_stmt(&mut self) -> PResult<Stmt> {
        let ln = self.prev().line;
        let test = self.expr()?;
        self.expect(Tag::Colon, Some("expected ':' after if-condition"))?;
        let body = self.block()?;
        let orelse = self.elif_or_else()?;
        Ok(Stmt::If { test, body, orelse, line: ln })
    }

    fn elif_or_else(&mut self) -> PResult<Vec<Stmt>> {
        self.skip_newlines();
        if self.matches(&[Tag::Elif]) {
            let ln = self.prev().line;
            let test = self.expr()?;
            self.expect(Tag::Colon, Some("expected ':' after elif"))?;
            let body = self.block()?;
            let orelse = self.elif_or_else()?;
            return Ok(vec![Stmt::If { test, body, orelse, line: ln }]);
        }
        if self.matches(&[Tag::Else]) {
            self.expect(Tag::Colon, Some("expected ':' after else"))?;
            return self.block();
        }
        Ok(Vec::new())
    }

    fn while_stmt(&mut self) -> PResult<Stmt> {
        let ln = self.prev().line;
        let test = self.expr()?;
        self.expect(Tag::Colon, Some("expected ':' after while"))?;
        let body = self.block()?;
        Ok(Stmt::While { test, body, line: ln })
    }

    fn for_stmt(&mut self) -> PResult<Stmt> {
        let ln = self.prev().line;
        let var = self.expect(Tag::Name, Some("expected loop variable"))?;
        let target = name_of(&var);
        self.expect(Tag::In, Some("expected 'in'"))?;
        let iter = self.expr()?;
        self.expect(Tag::Colon, Some("expected ':' after for-clause"))?;
        let body = self.block()?;
        Ok(Stmt::For { target, iter, body, line: ln })
    }

    fn block(&mut self) -> PResult<Vec<Stmt>> {
        self.expect(Tag::Newline, Some("expected newline before block"))?;
        self.expect(Tag::Indent, Some("expected indented block"))?;
        let stmts = self.stmt_list()?;
        if stmts.is_empty() {
            return self.err("empty block");
        }
        self.expect(Tag::Dedent, Some("expected dedent after block"))?;
        Ok(stmts)
    }

    // ── Expressions (precedence chain) ───────────────────────────────────

    fn expr(&mut self) -> PResult<Expr> {
        self.or_expr()
    }

    fn or_expr(&mut self) -> PResult<Expr> {
        let node = self.and_expr()?;
        if self.check(&[Tag::Or]) {
            let ln = node.line();
            let mut vals = vec![node];
            while self.matches(&[Tag::Or]) {
                vals.push(self.and_expr()?);
            }
            return Ok(Expr::BoolOp { op: "or".to_string(), values: vals, line: ln });
        }
        Ok(node)
    }

    fn and_expr(&mut self) -> PResult<Expr> {
        let node = self.not_expr()?;
        if self.check(&[Tag::And]) {
            let ln = node.line();
            let mut vals = vec![node];
            while self.matches(&[Tag::And]) {
                vals.push(self.not_expr()?);
            }
            return Ok(Expr::BoolOp { op: "and".to_string(), values: vals, line: ln });
        }
        Ok(node)
    }

    fn not_expr(&mut self) -> PResult<Expr> {
        if self.matches(&[Tag::Not]) {
            let ln = self.prev().line;
            let operand = self.not_expr()?;
            return Ok(Expr::UnaryOp {
                op: "not".to_string(),
                operand: Box::new(operand),
                line: ln,
            });
        }
        self.comparison()
    }

    fn comparison(&mut self) -> PResult<Expr> {
        let mut node = self.sum()?;
        while self.check(&[
            Tag::EqEqual,
            Tag::NotEqual,
            Tag::Less,
            Tag::LessEqual,
            Tag::Greater,
            Tag::GreaterEqual,
        ]) {
            let op_tok = self.advance();
            let op = op_tok.kind.tag().human().to_string();
            let right = self.sum()?;
            let ln = node.line();
            node = Expr::Compare {
                left: Box::new(node),
                op,
                right: Box::new(right),
                line: ln,
            };
        }
        Ok(node)
    }

    fn sum(&mut self) -> PResult<Expr> {
        let mut node = self.term()?;
        while self.check(&[Tag::Plus, Tag::Minus]) {
            let op = self.advance().kind.tag().human().to_string();
            let right = self.term()?;
            let ln = node.line();
            node = Expr::BinOp {
                left: Box::new(node),
                op,
                right: Box::new(right),
                line: ln,
            };
        }
        Ok(node)
    }

    fn term(&mut self) -> PResult<Expr> {
        let mut node = self.factor()?;
        while self.check(&[Tag::Star, Tag::Slash, Tag::DoubleSlash, Tag::Percent]) {
            let op = self.advance().kind.tag().human().to_string();
            let right = self.factor()?;
            let ln = node.line();
            node = Expr::BinOp {
                left: Box::new(node),
                op,
                right: Box::new(right),
                line: ln,
            };
        }
        Ok(node)
    }

    fn factor(&mut self) -> PResult<Expr> {
        if self.check(&[Tag::Plus, Tag::Minus]) {
            let op_tok = self.advance();
            let op = op_tok.kind.tag().human().to_string();
            let operand = self.factor()?;
            return Ok(Expr::UnaryOp {
                op,
                operand: Box::new(operand),
                line: op_tok.line,
            });
        }
        self.power()
    }

    fn power(&mut self) -> PResult<Expr> {
        let base = self.primary()?;
        if self.matches(&[Tag::DoubleStar]) {
            let ln = self.prev().line;
            let right = self.factor()?;
            return Ok(Expr::BinOp {
                left: Box::new(base),
                op: "**".to_string(),
                right: Box::new(right),
                line: ln,
            });
        }
        Ok(base)
    }

    fn primary(&mut self) -> PResult<Expr> {
        let mut node = self.atom()?;
        loop {
            if self.check(&[Tag::LParen]) {
                self.advance();
                let ln = self.prev().line;
                let args = self.call_args()?;
                self.expect(Tag::RParen, Some("expected ')' after arguments"))?;
                node = Expr::Call { func: Box::new(node), args, line: ln };
            } else if self.check(&[Tag::LBracket]) {
                self.advance();
                let ln = self.prev().line;
                let idx = self.expr()?;
                self.expect(Tag::RBracket, Some("expected ']' after index"))?;
                node = Expr::Subscript {
                    value: Box::new(node),
                    index: Box::new(idx),
                    line: ln,
                };
            } else if self.check(&[Tag::Dot]) {
                self.advance();
                let ln = self.prev().line;
                let name_tok = self.expect(Tag::Name, Some("expected attribute/method name after '.'"))?;
                let method = name_of(&name_tok);
                if !self.check(&[Tag::LParen]) {
                    return self.err(&format!(
                        "attribute access without a call is not supported: '.{}'",
                        method
                    ));
                }
                self.advance(); // consume '('
                let args = self.call_args()?;
                self.expect(Tag::RParen, Some("expected ')' after method arguments"))?;
                node = Expr::MethodCall { obj: Box::new(node), method, args, line: ln };
            } else {
                break;
            }
        }
        Ok(node)
    }

    fn call_args(&mut self) -> PResult<Vec<Expr>> {
        let mut args = Vec::new();
        if !self.check(&[Tag::RParen]) {
            args.push(self.expr()?);
            while self.matches(&[Tag::Comma]) {
                if self.check(&[Tag::RParen]) {
                    break;
                }
                args.push(self.expr()?);
            }
        }
        Ok(args)
    }

    fn atom(&mut self) -> PResult<Expr> {
        let tok = self.cur().clone();
        if self.matches(&[Tag::Integer]) {
            if let TokKind::Integer(v) = tok.kind {
                return Ok(Expr::Int(v, tok.line));
            }
        }
        if self.matches(&[Tag::Float]) {
            if let TokKind::Float(v) = tok.kind {
                return Ok(Expr::Float(v, tok.line));
            }
        }
        if self.matches(&[Tag::Str]) {
            if let TokKind::Str(v) = tok.kind {
                return Ok(Expr::Str(v, tok.line));
            }
        }
        if self.matches(&[Tag::True]) {
            return Ok(Expr::Bool(true, tok.line));
        }
        if self.matches(&[Tag::False]) {
            return Ok(Expr::Bool(false, tok.line));
        }
        if self.matches(&[Tag::None]) {
            return Ok(Expr::NoneLit(tok.line));
        }
        if self.matches(&[Tag::Name]) {
            if let TokKind::Name(v) = tok.kind {
                return Ok(Expr::Name(v, tok.line));
            }
        }
        if self.matches(&[Tag::LBracket]) {
            let mut elts = Vec::new();
            if !self.check(&[Tag::RBracket]) {
                elts.push(self.expr()?);
                while self.matches(&[Tag::Comma]) {
                    if self.check(&[Tag::RBracket]) {
                        break;
                    }
                    elts.push(self.expr()?);
                }
            }
            self.expect(Tag::RBracket, Some("expected ']'"))?;
            return Ok(Expr::List(elts, tok.line));
        }
        if self.matches(&[Tag::LParen]) {
            let node = self.expr()?;
            self.expect(Tag::RParen, Some("expected ')'"))?;
            return Ok(node);
        }
        self.err(&format!(
            "unexpected token '{}' ({})",
            tok.kind.tag().human(),
            tok.kind.describe_quoted()
        ))
    }
}

fn name_of(t: &Token) -> String {
    match &t.kind {
        TokKind::Name(s) => s.clone(),
        other => other.describe(),
    }
}
}

mod interpreter {
//! Tree-walk interpreter. Executes the AST recursively, matching the
//! dispatch pattern of the Python reference implementation
//! (`_exec_<Kind>` / `_eval_<Kind>`), just folded into `match`.

use crate::ast::{Expr, Program, Stmt};
use crate::builtins;
use crate::env::Env;
use crate::errors::{ExecResult, Flow, PyError};
use crate::value::{ep_bool, type_name, values_equal, PyFunction, Value};
use std::rc::Rc;

pub struct Interpreter {
    pub globals: Rc<Env>,
}

impl Interpreter {
    pub fn new() -> Self {
        let globals = Env::new(None);
        for name in builtins::NAMES {
            globals.set(name, Value::Builtin(name.to_string()));
        }
        Interpreter { globals }
    }

    pub fn run(&self, program: &Program) -> Result<(), PyError> {
        match self.exec_stmts(&program.body, &self.globals) {
            Ok(()) => Ok(()),
            // A bare top-level `return` simply ends the script early —
            // there's no caller to hand a value back to.
            Err(Flow::Return(_)) => Ok(()),
            Err(Flow::Error(e)) => Err(e),
        }
    }

    // ── Statement execution ───────────────────────────────────────────────

    fn exec_stmts(&self, stmts: &[Stmt], env: &Rc<Env>) -> ExecResult {
        for stmt in stmts {
            self.exec(stmt, env)?;
        }
        Ok(())
    }

    fn exec(&self, node: &Stmt, env: &Rc<Env>) -> ExecResult {
        match node {
            Stmt::FuncDef { name, params, body, .. } => {
                let f = PyFunction {
                    name: name.clone(),
                    params: params.clone(),
                    body: body.clone(),
                    closure: env.clone(),
                };
                env.set(name, Value::Function(Rc::new(f)));
                Ok(())
            }
            Stmt::Assign { target, value, .. } => {
                let v = self.eval(value, env)?;
                env.set(target, v);
                Ok(())
            }
            Stmt::AugAssign { target, op, value, line } => {
                let current = env.get(target, Some(*line))?;
                let rhs = self.eval(value, env)?;
                let base_op = op.chars().next().unwrap_or('+').to_string();
                let result = self.apply_binop(&base_op, &current, &rhs, *line)?;
                env.assign(target, result);
                Ok(())
            }
            Stmt::ExprStmt { expr, .. } => {
                self.eval(expr, env)?;
                Ok(())
            }
            Stmt::Return { value, .. } => {
                let v = match value {
                    Some(e) => self.eval(e, env)?,
                    Option::None => Value::None,
                };
                Err(Flow::Return(v))
            }
            Stmt::If { test, body, orelse, .. } => {
                if ep_bool(&self.eval(test, env)?) {
                    self.exec_stmts(body, env)
                } else if !orelse.is_empty() {
                    self.exec_stmts(orelse, env)
                } else {
                    Ok(())
                }
            }
            Stmt::While { test, body, .. } => {
                while ep_bool(&self.eval(test, env)?) {
                    self.exec_stmts(body, env)?;
                }
                Ok(())
            }
            Stmt::For { target, iter, body, line } => {
                let iterable = self.eval(iter, env)?;
                match iterable {
                    Value::List(l) => {
                        // Snapshot to allow mutation of the list during iteration,
                        // matching Python's "iterate over a copy of the reference" feel
                        // is not quite right — but avoids holding a live borrow
                        // across arbitrary body execution.
                        let items: Vec<Value> = l.borrow().clone();
                        for item in items {
                            env.set(target, item);
                            self.exec_stmts(body, env)?;
                        }
                        Ok(())
                    }
                    Value::Str(s) => {
                        for ch in s.chars() {
                            env.set(target, Value::Str(ch.to_string()));
                            self.exec_stmts(body, env)?;
                        }
                        Ok(())
                    }
                    other => Err(Flow::Error(PyError::Runtime(
                        format!("TypeError: '{}' object is not iterable", type_name(&other)),
                        Some(*line),
                    ))),
                }
            }
        }
    }

    // ── Expression evaluation ─────────────────────────────────────────────

    fn eval(&self, node: &Expr, env: &Rc<Env>) -> Result<Value, PyError> {
        match node {
            Expr::Int(v, _) => Ok(Value::Int(*v)),
            Expr::Float(v, _) => Ok(Value::Float(*v)),
            Expr::Str(v, _) => Ok(Value::Str(v.clone())),
            Expr::Bool(v, _) => Ok(Value::Bool(*v)),
            Expr::NoneLit(_) => Ok(Value::None),
            Expr::Name(name, line) => env.get(name, Some(*line)),
            Expr::List(elts, _) => {
                let mut out = Vec::with_capacity(elts.len());
                for e in elts {
                    out.push(self.eval(e, env)?);
                }
                Ok(Value::new_list(out))
            }
            Expr::Subscript { value, index, line } => {
                let obj = self.eval(value, env)?;
                let idx = self.eval(index, env)?;
                self.eval_subscript(&obj, &idx, *line)
            }
            Expr::BinOp { left, op, right, line } => {
                let l = self.eval(left, env)?;
                let r = self.eval(right, env)?;
                self.apply_binop(op, &l, &r, *line)
            }
            Expr::UnaryOp { op, operand, line } => {
                let v = self.eval(operand, env)?;
                self.eval_unary(op, &v, *line)
            }
            Expr::Compare { left, op, right, line } => {
                let l = self.eval(left, env)?;
                let r = self.eval(right, env)?;
                self.eval_compare(op, &l, &r, *line)
            }
            Expr::BoolOp { op, values, .. } => self.eval_boolop(op, values, env),
            Expr::Call { func, args, line } => {
                let callee = self.eval(func, env)?;
                let mut arg_vals = Vec::with_capacity(args.len());
                for a in args {
                    arg_vals.push(self.eval(a, env)?);
                }
                self.eval_call(&callee, arg_vals, *line)
            }
            Expr::MethodCall { obj, method, args, line } => {
                let o = self.eval(obj, env)?;
                let mut arg_vals = Vec::with_capacity(args.len());
                for a in args {
                    arg_vals.push(self.eval(a, env)?);
                }
                self.eval_method_call(&o, method, &arg_vals, *line)
            }
        }
    }

    fn eval_subscript(&self, obj: &Value, idx: &Value, line: usize) -> Result<Value, PyError> {
        match obj {
            Value::List(l) => {
                let i = require_index(idx, line)?;
                let lst = l.borrow();
                let len = lst.len() as i64;
                let real = if i < 0 { i + len } else { i };
                if real < 0 || real >= len {
                    return Err(PyError::Runtime(
                        format!("IndexError: index {} out of range (length {})", i, len),
                        Some(line),
                    ));
                }
                Ok(lst[real as usize].clone())
            }
            Value::Str(s) => {
                let i = require_index(idx, line)?;
                let chars: Vec<char> = s.chars().collect();
                let len = chars.len() as i64;
                let real = if i < 0 { i + len } else { i };
                if real < 0 || real >= len {
                    return Err(PyError::Runtime(
                        format!("IndexError: index {} out of range (length {})", i, len),
                        Some(line),
                    ));
                }
                Ok(Value::Str(chars[real as usize].to_string()))
            }
            other => Err(PyError::Runtime(
                format!("TypeError: '{}' object is not subscriptable", type_name(other)),
                Some(line),
            )),
        }
    }

    fn apply_binop(&self, op: &str, left: &Value, right: &Value, line: usize) -> Result<Value, PyError> {
        // String concatenation
        if op == "+" {
            if let (Value::Str(a), Value::Str(b)) = (left, right) {
                return Ok(Value::Str(format!("{}{}", a, b)));
            }
            if let (Value::List(a), Value::List(b)) = (left, right) {
                let mut out = a.borrow().clone();
                out.extend(b.borrow().clone());
                return Ok(Value::new_list(out));
            }
        }
        // String / list repetition
        if op == "*" {
            if let (Value::Str(a), b) = (left, right) {
                if b.is_number() {
                    let n = b.as_i64().unwrap_or(0).max(0) as usize;
                    return Ok(Value::Str(a.repeat(n)));
                }
            }
            if let (a, Value::Str(b)) = (left, right) {
                if a.is_number() {
                    let n = a.as_i64().unwrap_or(0).max(0) as usize;
                    return Ok(Value::Str(b.repeat(n)));
                }
            }
            if let (Value::List(a), b) = (left, right) {
                if b.is_number() {
                    let n = b.as_i64().unwrap_or(0).max(0) as usize;
                    let base = a.borrow();
                    let mut out = Vec::with_capacity(base.len() * n);
                    for _ in 0..n {
                        out.extend(base.clone());
                    }
                    return Ok(Value::new_list(out));
                }
            }
        }

        if left.is_number() && right.is_number() {
            let both_int = left.is_int_like() && right.is_int_like();

            // Division always promotes to float, same as Python's `/`.
            if op == "/" {
                let rf = right.as_f64().unwrap();
                if rf == 0.0 {
                    return Err(PyError::Runtime("ZeroDivisionError: division by zero".to_string(), Some(line)));
                }
                return Ok(Value::Float(left.as_f64().unwrap() / rf));
            }

            if both_int {
                let li = left.as_i64().unwrap();
                let ri = right.as_i64().unwrap();
                return match op {
                    "+" => Ok(Value::Int(li.wrapping_add(ri))),
                    "-" => Ok(Value::Int(li.wrapping_sub(ri))),
                    "*" => Ok(Value::Int(li.wrapping_mul(ri))),
                    "**" => {
                        if ri >= 0 {
                            Ok(Value::Int(li.wrapping_pow(ri as u32)))
                        } else {
                            Ok(Value::Float((li as f64).powf(ri as f64)))
                        }
                    }
                    "%" => {
                        if ri == 0 {
                            Err(PyError::Runtime("ZeroDivisionError: modulo by zero".to_string(), Some(line)))
                        } else {
                            Ok(Value::Int(py_mod_i64(li, ri)))
                        }
                    }
                    "//" => {
                        if ri == 0 {
                            Err(PyError::Runtime(
                                "ZeroDivisionError: integer division by zero".to_string(),
                                Some(line),
                            ))
                        } else {
                            Ok(Value::Int(py_floordiv_i64(li, ri)))
                        }
                    }
                    other => Err(PyError::Runtime(format!("InternalError: unknown operator '{}'", other), Some(line))),
                };
            }

            // Mixed int/float — result is always float (except `//`, which
            // the original interpreter always casts back down to int).
            let lf = left.as_f64().unwrap();
            let rf = right.as_f64().unwrap();
            return match op {
                "+" => Ok(Value::Float(lf + rf)),
                "-" => Ok(Value::Float(lf - rf)),
                "*" => Ok(Value::Float(lf * rf)),
                "**" => Ok(Value::Float(lf.powf(rf))),
                "%" => {
                    if rf == 0.0 {
                        Err(PyError::Runtime("ZeroDivisionError: modulo by zero".to_string(), Some(line)))
                    } else {
                        Ok(Value::Float(lf - (lf / rf).floor() * rf))
                    }
                }
                "//" => {
                    if rf == 0.0 {
                        Err(PyError::Runtime(
                            "ZeroDivisionError: integer division by zero".to_string(),
                            Some(line),
                        ))
                    } else {
                        Ok(Value::Int((lf / rf).floor() as i64))
                    }
                }
                other => Err(PyError::Runtime(format!("InternalError: unknown operator '{}'", other), Some(line))),
            };
        }

        Err(PyError::Runtime(
            format!(
                "TypeError: unsupported operand type(s) for '{}': '{}' and '{}'",
                op,
                type_name(left),
                type_name(right)
            ),
            Some(line),
        ))
    }

    fn eval_unary(&self, op: &str, v: &Value, line: usize) -> Result<Value, PyError> {
        match op {
            "not" => Ok(Value::Bool(!ep_bool(v))),
            "-" => match v {
                Value::Int(i) => Ok(Value::Int(-i)),
                Value::Float(f) => Ok(Value::Float(-f)),
                other => Err(PyError::Runtime(
                    format!("TypeError: bad operand type for unary '-': '{}'", type_name(other)),
                    Some(line),
                )),
            },
            "+" => match v {
                Value::Int(i) => Ok(Value::Int(*i)),
                Value::Float(f) => Ok(Value::Float(*f)),
                other => Err(PyError::Runtime(
                    format!("TypeError: bad operand type for unary '+': '{}'", type_name(other)),
                    Some(line),
                )),
            },
            other => Err(PyError::Runtime(format!("InternalError: unknown unary op '{}'", other), Some(line))),
        }
    }

    fn eval_compare(&self, op: &str, left: &Value, right: &Value, line: usize) -> Result<Value, PyError> {
        if op == "==" {
            return Ok(Value::Bool(values_equal(left, right)));
        }
        if op == "!=" {
            return Ok(Value::Bool(!values_equal(left, right)));
        }
        // Ordered comparisons — only defined between numbers, and between strings.
        let ordering = match (left, right) {
            (Value::Str(a), Value::Str(b)) => a.partial_cmp(b),
            (a, b) if a.is_number() && b.is_number() => a.as_f64().unwrap().partial_cmp(&b.as_f64().unwrap()),
            _ => {
                return Err(PyError::Runtime(
                    format!(
                        "TypeError: '{}' not supported between '{}' and '{}'",
                        op,
                        type_name(left),
                        type_name(right)
                    ),
                    Some(line),
                ))
            }
        };
        let ord = match ordering {
            Some(o) => o,
            Option::None => {
                return Err(PyError::Runtime(
                    format!(
                        "TypeError: '{}' not supported between '{}' and '{}'",
                        op,
                        type_name(left),
                        type_name(right)
                    ),
                    Some(line),
                ))
            }
        };
        use std::cmp::Ordering::*;
        let result = match op {
            "<" => ord == Less,
            "<=" => ord == Less || ord == Equal,
            ">" => ord == Greater,
            ">=" => ord == Greater || ord == Equal,
            _ => unreachable!(),
        };
        Ok(Value::Bool(result))
    }

    fn eval_boolop(&self, op: &str, values: &[Expr], env: &Rc<Env>) -> Result<Value, PyError> {
        if values.is_empty() {
            return Ok(Value::None);
        }
        let mut result = self.eval(&values[0], env)?;
        if op == "and" {
            for v in &values[1..] {
                if !ep_bool(&result) {
                    return Ok(result);
                }
                result = self.eval(v, env)?;
            }
        } else {
            for v in &values[1..] {
                if ep_bool(&result) {
                    return Ok(result);
                }
                result = self.eval(v, env)?;
            }
        }
        Ok(result)
    }

    fn eval_method_call(&self, obj: &Value, method: &str, args: &[Value], line: usize) -> Result<Value, PyError> {
        if let Value::Str(s) = obj {
            match method {
                "lower" => {
                    if !args.is_empty() {
                        return Err(PyError::Runtime("TypeError: lower() takes no arguments".to_string(), Some(line)));
                    }
                    return Ok(Value::Str(s.to_lowercase()));
                }
                "upper" => {
                    if !args.is_empty() {
                        return Err(PyError::Runtime("TypeError: upper() takes no arguments".to_string(), Some(line)));
                    }
                    return Ok(Value::Str(s.to_uppercase()));
                }
                _ => {
                    return Err(PyError::Runtime(
                        format!("AttributeError: 'str' object has no attribute '{}'", method),
                        Some(line),
                    ))
                }
            }
        }
        Err(PyError::Runtime(
            format!("AttributeError: '{}' object has no attribute '{}'", type_name(obj), method),
            Some(line),
        ))
    }

    fn eval_call(&self, callee: &Value, args: Vec<Value>, line: usize) -> Result<Value, PyError> {
        match callee {
            Value::Builtin(name) => builtins::call(name, &args),
            Value::Function(f) => {
                let arity = f.params.len();
                if args.len() != arity {
                    return Err(PyError::Runtime(
                        format!(
                            "TypeError: {}() takes {} argument(s) but {} given",
                            f.name,
                            arity,
                            args.len()
                        ),
                        Some(line),
                    ));
                }
                let call_env = Env::new(Some(f.closure.clone()));
                for (param, val) in f.params.iter().zip(args.into_iter()) {
                    call_env.set(param, val);
                }
                match self.exec_stmts(&f.body, &call_env) {
                    Ok(()) => Ok(Value::None),
                    Err(Flow::Return(v)) => Ok(v),
                    Err(Flow::Error(e)) => Err(e),
                }
            }
            other => Err(PyError::Runtime(
                format!("TypeError: '{}' object is not callable", type_name(other)),
                Some(line),
            )),
        }
    }
}

fn require_index(idx: &Value, line: usize) -> Result<i64, PyError> {
    if idx.is_number() {
        Ok(idx.as_i64().unwrap_or(0))
    } else {
        Err(PyError::Runtime(
            format!("TypeError: indices must be integers, not '{}'", type_name(idx)),
            Some(line),
        ))
    }
}

/// Python-style floor division: rounds toward negative infinity
/// (Rust's `/` truncates toward zero instead).
fn py_floordiv_i64(a: i64, b: i64) -> i64 {
    let q = a / b;
    let r = a % b;
    if r != 0 && (r < 0) != (b < 0) {
        q - 1
    } else {
        q
    }
}

/// Python-style modulo: result takes the sign of the divisor
/// (Rust's `%` takes the sign of the dividend instead).
fn py_mod_i64(a: i64, b: i64) -> i64 {
    let r = a % b;
    if r != 0 && (r < 0) != (b < 0) {
        r + b
    } else {
        r
    }
}
}


use ast::{Expr, Program, Stmt};
use errors::PyError;
use interpreter::Interpreter;
use lexer::Lexer;
use parser::Parser;
use std::io::Write;

// ══════════════════════════════════════════════════════════════════════
//  Pipeline: source -> tokens -> AST -> execute
// ══════════════════════════════════════════════════════════════════════

fn parse_source(source: &str) -> Result<Program, PyError> {
    let tokens = Lexer::new(source).tokenize()?;
    Parser::new(tokens).parse()
}

fn run_source(source: &str, interp: &Interpreter) -> Result<(), PyError> {
    let program = parse_source(source)?;
    interp.run(&program)
}

fn run_source_with_ast(source: &str) -> Result<(), PyError> {
    let program = parse_source(source)?;
    println!("\n── AST ──────────────────────────────────────────────");
    print_program(&program);
    println!("───────────────────────────────────────────────────────\n");
    let interp = Interpreter::new();
    interp.run(&program)
}

// ══════════════════════════════════════════════════════════════════════
//  AST pretty printer (for --ast flag)
// ══════════════════════════════════════════════════════════════════════

fn print_program(p: &Program) {
    println!("Program");
    for s in &p.body {
        print_stmt(s, 1);
    }
}

fn print_stmt(node: &Stmt, indent: usize) {
    let pad = "  ".repeat(indent);
    match node {
        Stmt::FuncDef { name, params, body, .. } => {
            println!("{}FuncDef name={:?} params={:?}", pad, name, params);
            for s in body {
                print_stmt(s, indent + 1);
            }
        }
        Stmt::Assign { target, value, .. } => {
            println!("{}Assign target={:?}", pad, target);
            print_expr(value, indent + 1);
        }
        Stmt::AugAssign { target, op, value, .. } => {
            println!("{}AugAssign target={:?} op={:?}", pad, target, op);
            print_expr(value, indent + 1);
        }
        Stmt::ExprStmt { expr, .. } => {
            println!("{}ExprStmt", pad);
            print_expr(expr, indent + 1);
        }
        Stmt::Return { value, .. } => {
            println!("{}Return", pad);
            if let Some(v) = value {
                print_expr(v, indent + 1);
            }
        }
        Stmt::If { test, body, orelse, .. } => {
            println!("{}If", pad);
            println!("{}  test:", pad);
            print_expr(test, indent + 2);
            println!("{}  body:", pad);
            for s in body {
                print_stmt(s, indent + 2);
            }
            if !orelse.is_empty() {
                println!("{}  orelse:", pad);
                for s in orelse {
                    print_stmt(s, indent + 2);
                }
            }
        }
        Stmt::While { test, body, .. } => {
            println!("{}While", pad);
            println!("{}  test:", pad);
            print_expr(test, indent + 2);
            println!("{}  body:", pad);
            for s in body {
                print_stmt(s, indent + 2);
            }
        }
        Stmt::For { target, iter, body, .. } => {
            println!("{}For target={:?}", pad, target);
            println!("{}  iter:", pad);
            print_expr(iter, indent + 2);
            println!("{}  body:", pad);
            for s in body {
                print_stmt(s, indent + 2);
            }
        }
    }
}

fn print_expr(node: &Expr, indent: usize) {
    let pad = "  ".repeat(indent);
    match node {
        Expr::Int(v, _) => println!("{}IntLiteral({:?})", pad, v),
        Expr::Float(v, _) => println!("{}FloatLiteral({:?})", pad, v),
        Expr::Str(v, _) => println!("{}StringLiteral({:?})", pad, v),
        Expr::Bool(v, _) => println!("{}BoolLiteral({:?})", pad, v),
        Expr::NoneLit(_) => println!("{}NoneLiteral", pad),
        Expr::Name(id, _) => println!("{}Name({:?})", pad, id),
        Expr::List(elts, _) => {
            println!("{}ListLiteral [{} elements]", pad, elts.len());
            for e in elts {
                print_expr(e, indent + 1);
            }
        }
        Expr::Subscript { value, index, .. } => {
            println!("{}Subscript", pad);
            print_expr(value, indent + 1);
            print_expr(index, indent + 1);
        }
        Expr::BinOp { left, op, right, .. } => {
            println!("{}BinOp op={:?}", pad, op);
            print_expr(left, indent + 1);
            print_expr(right, indent + 1);
        }
        Expr::UnaryOp { op, operand, .. } => {
            println!("{}UnaryOp op={:?}", pad, op);
            print_expr(operand, indent + 1);
        }
        Expr::Compare { left, op, right, .. } => {
            println!("{}Compare op={:?}", pad, op);
            print_expr(left, indent + 1);
            print_expr(right, indent + 1);
        }
        Expr::BoolOp { op, values, .. } => {
            println!("{}BoolOp op={:?}", pad, op);
            for v in values {
                print_expr(v, indent + 1);
            }
        }
        Expr::Call { func, args, .. } => {
            println!("{}Call", pad);
            print_expr(func, indent + 1);
            for a in args {
                print_expr(a, indent + 1);
            }
        }
        Expr::MethodCall { obj, method, args, .. } => {
            println!("{}MethodCall method={:?}", pad, method);
            print_expr(obj, indent + 1);
            for a in args {
                print_expr(a, indent + 1);
            }
        }
    }
}

// ══════════════════════════════════════════════════════════════════════
//  REPL
// ══════════════════════════════════════════════════════════════════════

const BANNER: &str = "\x1b[96m╔══════════════════════════════════════════════════════╗\n║           Py  —  a tiny Python-like interpreter        ║\n║  Type Py code below.  'exit' or Ctrl-D to quit.        ║\n║  'help' for a quick language reference.                ║\n╚══════════════════════════════════════════════════════╝\x1b[0m";

const HELP_TEXT: &str = r#"
Py Quick Reference
-----------------------
Variables:     x = 10          y = 3.14       s = "hello"
Arithmetic:    + - * / // % **
Comparison:    == != < <= > >=
Logic:         and  or  not
Strings:       "hi" + " world"   len("hello")   str(42)
               "Hi".lower()      "hi".upper()
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
String methods: .lower()  .upper()
"#;

fn needs_more(source: &str) -> bool {
    let lines: Vec<&str> = source
        .lines()
        .filter(|l| !l.trim().is_empty() && !l.trim().starts_with('#'))
        .collect();
    match lines.last() {
        Some(last) => last.trim_end().ends_with(':'),
        Option::None => false,
    }
}

fn repl() {
    println!("{}", BANNER);
    let interp = Interpreter::new();
    let mut buf: Vec<String> = Vec::new();

    loop {
        let prompt = if buf.is_empty() { ">>> " } else { "... " };
        print!("{}", prompt);
        let _ = std::io::stdout().flush();

        let mut line = String::new();
        let bytes_read = std::io::stdin().read_line(&mut line).unwrap_or(0);
        if bytes_read == 0 {
            println!("\nBye!");
            break;
        }
        // strip trailing newline
        if line.ends_with('\n') {
            line.pop();
            if line.ends_with('\r') {
                line.pop();
            }
        }

        if buf.is_empty() && line.trim() == "exit" {
            println!("Bye!");
            break;
        }
        if buf.is_empty() && line.trim() == "help" {
            println!("{}", HELP_TEXT);
            continue;
        }
        if buf.is_empty() && line.trim().is_empty() {
            continue;
        }

        buf.push(line.clone());
        let source = buf.join("\n");

        let stripped = line.trim_end();
        if stripped.ends_with(':') || needs_more(&source) {
            continue;
        }

        match run_source(&format!("{}\n", source), &interp) {
            Ok(()) => {}
            Err(e) => println!("{}", e),
        }
        buf.clear();
    }
}

// ══════════════════════════════════════════════════════════════════════
//  CLI entry point
// ══════════════════════════════════════════════════════════════════════

fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();

    if args.is_empty() {
        repl();
        return;
    }

    let show_ast = args.iter().any(|a| a == "--ast");
    let files: Vec<&String> = args.iter().filter(|a| !a.starts_with("--")).collect();

    if files.is_empty() {
        println!("Usage: py <script.py> [--ast]");
        std::process::exit(1);
    }

    let filepath = files[0];

    let source = match std::fs::read_to_string(filepath) {
        Ok(s) => s,
        Err(_) => {
            println!("\x1b[91mFileNotFoundError\x1b[0m: No such file: {:?}", filepath);
            std::process::exit(1);
        }
    };

    let result = if show_ast {
        run_source_with_ast(&source)
    } else {
        let interp = Interpreter::new();
        run_source(&source, &interp)
    };

    if let Err(e) = result {
        println!("{}", e);
        std::process::exit(1);
    }
}