// ============================================================================
//                              E D U P Y  (C++)
//                An Educational Python-like Interpreter
//
//  Architecture (all in this single file):
//    1. Errors      - LexerError, ParseError, RuntimeError
//    2. Tokens      - TT enum + Token struct
//    3. Lexer       - source text -> token list
//    4. AST Nodes   - structs for every grammar construct
//    5. Parser      - PEG-style recursive descent
//    6. Interpreter - tree-walk executor + scoped environments
//    7. Builtins    - print, len, range, int, float, str, bool, ...
//    8. REPL        - interactive read-eval-print loop
//    9. Runner      - run a .ep source file
//
// Usage
// -----
//   REPL:          ./edupy
//   Run a file:    ./edupy myscript.ep
//   Dump AST:      ./edupy myscript.ep --ast
// ============================================================================

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <map>
#include <memory>
#include <sstream>
#include <string>
#include <unordered_map>
#include <variant>
#include <vector>

// ============================================================================
// SECTION 1: ERRORS
// ============================================================================

class EduPyError : public std::exception {
public:
    std::string message;
    int line; // 0 means "no line"

    EduPyError(std::string msg, int ln = 0) : message(std::move(msg)), line(ln) {}

    virtual std::string typeName() const { return "EduPyError"; }

    // Colorized (for terminal display)
    std::string colored() const {
        std::string loc = line ? (" [line " + std::to_string(line) + "]") : "";
        return "\033[91m" + typeName() + "\033[0m: " + message + loc;
    }

    // Plain (no ANSI codes)
    std::string plain() const {
        std::string loc = line ? (" [line " + std::to_string(line) + "]") : "";
        return typeName() + ": " + message + loc;
    }

    const char* what() const noexcept override { return message.c_str(); }
};

class LexerError : public EduPyError {
public:
    using EduPyError::EduPyError;
    std::string typeName() const override { return "LexerError"; }
};

class ParseError : public EduPyError {
public:
    using EduPyError::EduPyError;
    std::string typeName() const override { return "ParseError"; }
};

class EduPyRuntimeError : public EduPyError {
public:
    using EduPyError::EduPyError;
    std::string typeName() const override { return "EduPyRuntimeError"; }
};

// Internal control-flow signal used to unwind the call stack on 'return'.
struct ReturnSignal {
    struct Value* value; // raw pointer into a shared_ptr-managed Value (see below)
    std::shared_ptr<struct Value> sp; // keep alive
};

// ============================================================================
// SECTION 2: TOKENS
// ============================================================================

enum class TT {
    // Literals
    INTEGER, FLOAT, STRING,
    // Keywords
    IF, ELIF, ELSE, WHILE, FOR, IN, DEF, RETURN,
    AND, OR, NOT, TRUE_, FALSE_, NONE_,
    // Identifier
    NAME,
    // Arithmetic
    PLUS, MINUS, STAR, SLASH, PERCENT, DOUBLESLASH, DOUBLESTAR,
    // Comparison
    EQEQUAL, NOTEQUAL, LESS, LESSEQUAL, GREATER, GREATEREQUAL,
    // Assignment
    EQUAL,
    // Augmented assignment
    PLUSEQUAL, MINEQUAL, STAREQUAL, SLASHEQUAL,
    // Delimiters
    LPAREN, RPAREN, LBRACKET, RBRACKET, COLON, COMMA, DOT,
    // Structural (indent-based)
    NEWLINE, INDENT, DEDENT, EOF_
};

// Human-readable text for a token type (mirrors the Python TT.value strings)
static std::string ttValue(TT t) {
    switch (t) {
        case TT::INTEGER: return "INTEGER";
        case TT::FLOAT: return "FLOAT";
        case TT::STRING: return "STRING";
        case TT::IF: return "if";
        case TT::ELIF: return "elif";
        case TT::ELSE: return "else";
        case TT::WHILE: return "while";
        case TT::FOR: return "for";
        case TT::IN: return "in";
        case TT::DEF: return "def";
        case TT::RETURN: return "return";
        case TT::AND: return "and";
        case TT::OR: return "or";
        case TT::NOT: return "not";
        case TT::TRUE_: return "True";
        case TT::FALSE_: return "False";
        case TT::NONE_: return "None";
        case TT::NAME: return "NAME";
        case TT::PLUS: return "+";
        case TT::MINUS: return "-";
        case TT::STAR: return "*";
        case TT::SLASH: return "/";
        case TT::PERCENT: return "%";
        case TT::DOUBLESLASH: return "//";
        case TT::DOUBLESTAR: return "**";
        case TT::EQEQUAL: return "==";
        case TT::NOTEQUAL: return "!=";
        case TT::LESS: return "<";
        case TT::LESSEQUAL: return "<=";
        case TT::GREATER: return ">";
        case TT::GREATEREQUAL: return ">=";
        case TT::EQUAL: return "=";
        case TT::PLUSEQUAL: return "+=";
        case TT::MINEQUAL: return "-=";
        case TT::STAREQUAL: return "*=";
        case TT::SLASHEQUAL: return "/=";
        case TT::LPAREN: return "(";
        case TT::RPAREN: return ")";
        case TT::LBRACKET: return "[";
        case TT::RBRACKET: return "]";
        case TT::COLON: return ":";
        case TT::COMMA: return ",";
        case TT::DOT: return ".";
        case TT::NEWLINE: return "NEWLINE";
        case TT::INDENT: return "INDENT";
        case TT::DEDENT: return "DEDENT";
        case TT::EOF_: return "EOF";
    }
    return "?";
}

// Token name (for repr-like debug output), mirrors Python's TT.name
static std::string ttName(TT t) {
    switch (t) {
        case TT::INTEGER: return "INTEGER";
        case TT::FLOAT: return "FLOAT";
        case TT::STRING: return "STRING";
        case TT::IF: return "IF";
        case TT::ELIF: return "ELIF";
        case TT::ELSE: return "ELSE";
        case TT::WHILE: return "WHILE";
        case TT::FOR: return "FOR";
        case TT::IN: return "IN";
        case TT::DEF: return "DEF";
        case TT::RETURN: return "RETURN";
        case TT::AND: return "AND";
        case TT::OR: return "OR";
        case TT::NOT: return "NOT";
        case TT::TRUE_: return "TRUE";
        case TT::FALSE_: return "FALSE";
        case TT::NONE_: return "NONE";
        case TT::NAME: return "NAME";
        case TT::PLUS: return "PLUS";
        case TT::MINUS: return "MINUS";
        case TT::STAR: return "STAR";
        case TT::SLASH: return "SLASH";
        case TT::PERCENT: return "PERCENT";
        case TT::DOUBLESLASH: return "DOUBLESLASH";
        case TT::DOUBLESTAR: return "DOUBLESTAR";
        case TT::EQEQUAL: return "EQEQUAL";
        case TT::NOTEQUAL: return "NOTEQUAL";
        case TT::LESS: return "LESS";
        case TT::LESSEQUAL: return "LESSEQUAL";
        case TT::GREATER: return "GREATER";
        case TT::GREATEREQUAL: return "GREATEREQUAL";
        case TT::EQUAL: return "EQUAL";
        case TT::PLUSEQUAL: return "PLUSEQUAL";
        case TT::MINEQUAL: return "MINEQUAL";
        case TT::STAREQUAL: return "STAREQUAL";
        case TT::SLASHEQUAL: return "SLASHEQUAL";
        case TT::LPAREN: return "LPAREN";
        case TT::RPAREN: return "RPAREN";
        case TT::LBRACKET: return "LBRACKET";
        case TT::RBRACKET: return "RBRACKET";
        case TT::COLON: return "COLON";
        case TT::COMMA: return "COMMA";
        case TT::DOT: return "DOT";
        case TT::NEWLINE: return "NEWLINE";
        case TT::INDENT: return "INDENT";
        case TT::DEDENT: return "DEDENT";
        case TT::EOF_: return "EOF";
    }
    return "?";
}

static const std::unordered_map<std::string, TT> KEYWORDS = {
    {"if", TT::IF}, {"elif", TT::ELIF}, {"else", TT::ELSE},
    {"while", TT::WHILE}, {"for", TT::FOR}, {"in", TT::IN},
    {"def", TT::DEF}, {"return", TT::RETURN},
    {"and", TT::AND}, {"or", TT::OR}, {"not", TT::NOT},
    {"True", TT::TRUE_}, {"False", TT::FALSE_}, {"None", TT::NONE_},
};

// A token's literal value. We use a small variant to mirror Python's
// dynamically-typed `value` field (can be int, double, string, or empty).
struct TokenValue {
    enum class Kind { NONE, INT, FLOAT, STR } kind = Kind::NONE;
    long long i = 0;
    double f = 0.0;
    std::string s;

    TokenValue() = default;
    static TokenValue none() { return TokenValue{}; }
    static TokenValue ofInt(long long v) { TokenValue t; t.kind = Kind::INT; t.i = v; return t; }
    static TokenValue ofFloat(double v) { TokenValue t; t.kind = Kind::FLOAT; t.f = v; return t; }
    static TokenValue ofStr(std::string v) { TokenValue t; t.kind = Kind::STR; t.s = std::move(v); return t; }

    std::string repr() const {
        switch (kind) {
            case Kind::NONE: return "None";
            case Kind::INT: return std::to_string(i);
            case Kind::FLOAT: {
                std::ostringstream oss;
                oss << f;
                return oss.str();
            }
            case Kind::STR: return "'" + s + "'";
        }
        return "";
    }
};

struct Token {
    TT type;
    TokenValue value;
    int line;
    int col;

    std::string repr() const {
        return "Token(" + ttName(type) + ", " + value.repr() + ", " +
               std::to_string(line) + ":" + std::to_string(col) + ")";
    }
};

// ============================================================================
// SECTION 3: LEXER
// ============================================================================
//
// Single-pass, character-by-character tokeniser.
//
// Key design points (from CPython Lib/tokenize.py):
//   - indent_stack tracks indentation depth -> INDENT / DEDENT tokens
//   - blank/comment lines are silently skipped (no NEWLINE emitted)
//   - paren_depth > 0 suppresses physical-newline NEWLINE tokens,
//     enabling implicit line continuation inside ( ) or [ ]
// ============================================================================

class Lexer {
public:
    explicit Lexer(std::string source) : source_(std::move(source)) {}

    std::vector<Token> tokenize() {
        while (pos_ < source_.size()) {
            nextToken();
        }
        closeAllIndents();
        if (!tokens_.empty() && tokens_.back().type != TT::NEWLINE &&
            tokens_.back().type != TT::DEDENT) {
            tokens_.push_back({TT::NEWLINE, TokenValue::ofStr("\n"), line_, col_});
        }
        tokens_.push_back({TT::EOF_, TokenValue::none(), line_, col_});
        return tokens_;
    }

private:
    static const std::unordered_map<char, std::string> ESCAPES_INIT() {
        return {};
    }

    // escape map: char -> replacement string
    char escapeFor(char c, bool& found) {
        found = true;
        switch (c) {
            case 'n': return '\n';
            case 't': return '\t';
            case 'r': return '\r';
            case '\\': return '\\';
            case '\'': return '\'';
            case '"': return '"';
            case '0': return '\0';
            case 'a': return '\a';
            case 'b': return '\b';
            default: found = false; return '\0';
        }
    }

    std::string source_;
    size_t pos_ = 0;
    int line_ = 1;
    int col_ = 1;
    std::vector<Token> tokens_;
    std::vector<int> indent_stack_ = {0};
    bool at_line_start_ = true;
    int paren_depth_ = 0;

    // -- Character helpers --------------------------------------------------

    char cur() const { return pos_ < source_.size() ? source_[pos_] : '\0'; }

    char peek(int n = 1) const {
        size_t idx = pos_ + n;
        return idx < source_.size() ? source_[idx] : '\0';
    }

    std::pair<int, int> here() const { return {line_, col_}; }

    char advance() {
        char ch = source_[pos_];
        pos_++;
        if (ch == '\n') {
            line_++;
            col_ = 1;
        } else {
            col_++;
        }
        return ch;
    }

    [[noreturn]] void err(const std::string& msg) {
        throw LexerError(msg, line_);
    }

    void closeAllIndents() {
        while (indent_stack_.size() > 1) {
            indent_stack_.pop_back();
            tokens_.push_back({TT::DEDENT, TokenValue::none(), line_, col_});
        }
    }

    // -- Main dispatch --------------------------------------------------------

    void nextToken() {
        if (at_line_start_ && paren_depth_ == 0) {
            handleIndentation();
            return;
        }

        char ch = cur();

        if (ch == ' ' || ch == '\t') {
            advance();
            return;
        }
        if (ch == '\n') {
            auto [ln, cl] = here();
            advance();
            if (paren_depth_ == 0) {
                tokens_.push_back({TT::NEWLINE, TokenValue::ofStr("\n"), ln, cl});
                at_line_start_ = true;
            }
            return;
        }
        if (ch == '\r') {
            advance();
            return;
        }
        if (ch == '#') {
            while (cur() != '\n' && cur() != '\0') advance();
            return;
        }
        if (ch == '"' || ch == '\'') {
            readString();
            return;
        }
        if (isdigit((unsigned char)ch)) {
            readNumber();
            return;
        }
        if (isalpha((unsigned char)ch) || ch == '_') {
            readName();
            return;
        }
        readOperator();
    }

    // -- Indentation -----------------------------------------------------------

    void handleIndentation() {
        int indent = 0;
        while (cur() == ' ' || cur() == '\t') {
            if (cur() == '\t') {
                indent = (indent / 8 + 1) * 8;
            } else {
                indent += 1;
            }
            advance();
        }

        char ch = cur();
        // blank or comment line - skip entirely
        if (ch == '\n' || ch == '\r' || ch == '\0' || ch == '#') {
            if (ch == '#') {
                while (cur() != '\n' && cur() != '\0') advance();
            }
            if (cur() == '\n') advance();
            return;
        }

        at_line_start_ = false;
        int current = indent_stack_.back();

        if (indent > current) {
            indent_stack_.push_back(indent);
            tokens_.push_back({TT::INDENT, TokenValue::ofInt(indent), line_, 1});
        } else if (indent < current) {
            while (indent_stack_.size() > 1 && indent_stack_.back() > indent) {
                indent_stack_.pop_back();
                tokens_.push_back({TT::DEDENT, TokenValue::ofInt(indent), line_, 1});
            }
            if (indent_stack_.back() != indent) {
                err("IndentationError: unindent does not match any outer indentation level");
            }
        }
    }

    // -- Strings -----------------------------------------------------------------

    void readString() {
        auto [ln, cl] = here();
        char q = advance();
        // triple-quoted
        if (cur() == q && peek() == q) {
            advance();
            advance();
            std::string buf;
            while (true) {
                char ch = cur();
                if (ch == '\0') {
                    err("SyntaxError: EOF in triple-quoted string");
                }
                if (ch == q && peek() == q && peek(2) == q) {
                    advance();
                    advance();
                    advance();
                    break;
                }
                if (ch != '\\') {
                    buf.push_back(advance());
                } else {
                    advance(); // consume backslash
                    char esc = advance();
                    bool found;
                    char repl = escapeFor(esc, found);
                    if (found) buf.push_back(repl);
                    // else: empty string appended (matches Python .get(..., ""))
                }
            }
            tokens_.push_back({TT::STRING, TokenValue::ofStr(buf), ln, cl});
            return;
        }
        // single-quoted
        std::string buf;
        while (true) {
            char ch = cur();
            if (ch == '\0') {
                err("SyntaxError: unterminated string");
            }
            if (ch == '\n') {
                err("SyntaxError: EOL in string");
            }
            if (ch == q) {
                advance();
                break;
            }
            if (ch == '\\') {
                advance();
                char esc = advance();
                bool found;
                char repl = escapeFor(esc, found);
                if (found) buf.push_back(repl);
            } else {
                buf.push_back(advance());
            }
        }
        tokens_.push_back({TT::STRING, TokenValue::ofStr(buf), ln, cl});
    }

    // -- Numbers -------------------------------------------------------------------

    void readNumber() {
        auto [ln, cl] = here();
        std::string digits;
        bool is_float = false;
        while (isdigit((unsigned char)cur())) digits.push_back(advance());
        if (cur() == '.' && isdigit((unsigned char)peek())) {
            is_float = true;
            digits.push_back(advance());
            while (isdigit((unsigned char)cur())) digits.push_back(advance());
        }
        if (cur() == 'e' || cur() == 'E') {
            is_float = true;
            digits.push_back(advance());
            if (cur() == '+' || cur() == '-') digits.push_back(advance());
            if (!isdigit((unsigned char)cur())) {
                err("SyntaxError: invalid numeric literal");
            }
            while (isdigit((unsigned char)cur())) digits.push_back(advance());
        }
        if (is_float) {
            tokens_.push_back({TT::FLOAT, TokenValue::ofFloat(std::stod(digits)), ln, cl});
        } else {
            tokens_.push_back({TT::INTEGER, TokenValue::ofInt(std::stoll(digits)), ln, cl});
        }
    }

    // -- Names / keywords -------------------------------------------------------------

    void readName() {
        auto [ln, cl] = here();
        std::string buf;
        while (isalnum((unsigned char)cur()) || cur() == '_') buf.push_back(advance());
        auto it = KEYWORDS.find(buf);
        TT type = (it != KEYWORDS.end()) ? it->second : TT::NAME;
        tokens_.push_back({type, TokenValue::ofStr(buf), ln, cl});
    }

    // -- Operators ----------------------------------------------------------------------

    void readOperator() {
        auto [ln, cl] = here();
        char ch = advance();

        switch (ch) {
            case '+':
                if (cur() == '=') { advance(); tokens_.push_back({TT::PLUSEQUAL, TokenValue::ofStr("+="), ln, cl}); }
                else tokens_.push_back({TT::PLUS, TokenValue::ofStr("+"), ln, cl});
                break;
            case '-':
                if (cur() == '=') { advance(); tokens_.push_back({TT::MINEQUAL, TokenValue::ofStr("-="), ln, cl}); }
                else tokens_.push_back({TT::MINUS, TokenValue::ofStr("-"), ln, cl});
                break;
            case '*':
                if (cur() == '*') { advance(); tokens_.push_back({TT::DOUBLESTAR, TokenValue::ofStr("**"), ln, cl}); }
                else if (cur() == '=') { advance(); tokens_.push_back({TT::STAREQUAL, TokenValue::ofStr("*="), ln, cl}); }
                else tokens_.push_back({TT::STAR, TokenValue::ofStr("*"), ln, cl});
                break;
            case '/':
                if (cur() == '/') { advance(); tokens_.push_back({TT::DOUBLESLASH, TokenValue::ofStr("//"), ln, cl}); }
                else if (cur() == '=') { advance(); tokens_.push_back({TT::SLASHEQUAL, TokenValue::ofStr("/="), ln, cl}); }
                else tokens_.push_back({TT::SLASH, TokenValue::ofStr("/"), ln, cl});
                break;
            case '=':
                if (cur() == '=') { advance(); tokens_.push_back({TT::EQEQUAL, TokenValue::ofStr("=="), ln, cl}); }
                else tokens_.push_back({TT::EQUAL, TokenValue::ofStr("="), ln, cl});
                break;
            case '!':
                if (cur() == '=') { advance(); tokens_.push_back({TT::NOTEQUAL, TokenValue::ofStr("!="), ln, cl}); }
                else err("SyntaxError: '!' must be followed by '='");
                break;
            case '<':
                if (cur() == '=') { advance(); tokens_.push_back({TT::LESSEQUAL, TokenValue::ofStr("<="), ln, cl}); }
                else tokens_.push_back({TT::LESS, TokenValue::ofStr("<"), ln, cl});
                break;
            case '>':
                if (cur() == '=') { advance(); tokens_.push_back({TT::GREATEREQUAL, TokenValue::ofStr(">="), ln, cl}); }
                else tokens_.push_back({TT::GREATER, TokenValue::ofStr(">"), ln, cl});
                break;
            case '%':
                tokens_.push_back({TT::PERCENT, TokenValue::ofStr("%"), ln, cl});
                break;
            case '(':
                paren_depth_ += 1;
                tokens_.push_back({TT::LPAREN, TokenValue::ofStr("("), ln, cl});
                break;
            case ')':
                paren_depth_ = std::max(0, paren_depth_ - 1);
                tokens_.push_back({TT::RPAREN, TokenValue::ofStr(")"), ln, cl});
                break;
            case '[':
                paren_depth_ += 1;
                tokens_.push_back({TT::LBRACKET, TokenValue::ofStr("["), ln, cl});
                break;
            case ']':
                paren_depth_ = std::max(0, paren_depth_ - 1);
                tokens_.push_back({TT::RBRACKET, TokenValue::ofStr("]"), ln, cl});
                break;
            case ':':
                tokens_.push_back({TT::COLON, TokenValue::ofStr(":"), ln, cl});
                break;
            case ',':
                tokens_.push_back({TT::COMMA, TokenValue::ofStr(","), ln, cl});
                break;
            case '.':
                tokens_.push_back({TT::DOT, TokenValue::ofStr("."), ln, cl});
                break;
            default:
                err(std::string("SyntaxError: unexpected character '") + ch + "'");
        }
    }
};

// ============================================================================
// SECTION 4: AST NODES
//     Inspired by CPython's Grammar/python.asdl
// ============================================================================

enum class NodeType {
    Program,
    IntLiteral, FloatLiteral, StringLiteral, BoolLiteral, NoneLiteral,
    Name, ListLiteral, Subscript, BinOp, UnaryOp, Compare, BoolOp, Call,
    Assign, AugAssign, ExprStmt, Return, If, While, For, FuncDef
};

struct ASTNode {
    NodeType type;
    int line = 0;

    // Literal payloads
    long long intVal = 0;
    double floatVal = 0.0;
    std::string strVal;       // StringLiteral value, or BinOp/UnaryOp/Compare/BoolOp op,
                               // or Name id, or Assign/AugAssign/For target,
                               // or FuncDef name
    bool boolVal = false;     // BoolLiteral value

    // Children (meaning depends on `type`)
    std::shared_ptr<ASTNode> a; // left / value / test / func / iter / operand
    std::shared_ptr<ASTNode> b; // right / index

    std::vector<std::shared_ptr<ASTNode>> body;    // Program.body, If.body, While.body,
                                                     // For.body, FuncDef.body
    std::vector<std::shared_ptr<ASTNode>> orelse;   // If.orelse
    std::vector<std::shared_ptr<ASTNode>> elts;     // ListLiteral.elts / Call.args / BoolOp.values
    std::vector<std::string> params;                // FuncDef.params

    explicit ASTNode(NodeType t, int ln = 0) : type(t), line(ln) {}
};

using ASTPtr = std::shared_ptr<ASTNode>;

template <typename... Args>
ASTPtr makeNode(NodeType t, int line) {
    return std::make_shared<ASTNode>(t, line);
}

// ============================================================================
// SECTION 5: PARSER
//     PEG-style recursive descent, grammar mirrors CPython's python.gram
//
//  Grammar (EBNF):
//   program      := stmt* EOF
//   stmt         := func_def | if_stmt | while_stmt | for_stmt | simple_stmt
//   simple_stmt  := (assign | aug_assign | return | expr_stmt) NEWLINE
//   assign       := NAME '=' expr
//   aug_assign   := NAME ('+='|'-='|'*='|'/=') expr
//   return_stmt  := 'return' [expr]
//   func_def     := 'def' NAME '(' params? ')' ':' block
//   if_stmt      := 'if' expr ':' block elif_else?
//   elif_else    := ('elif' expr ':' block elif_else?) | ('else' ':' block)
//   while_stmt   := 'while' expr ':' block
//   for_stmt     := 'for' NAME 'in' expr ':' block
//   block        := NEWLINE INDENT stmt+ DEDENT
//   expr         := or_expr
//   or_expr      := and_expr  ('or'  and_expr)*
//   and_expr     := not_expr  ('and' not_expr)*
//   not_expr     := 'not' not_expr | comparison
//   comparison   := sum (comp_op sum)*
//   sum          := term     (('+' | '-') term)*
//   term         := factor   (('*'|'/'|'//'|'%') factor)*
//   factor       := ('+'|'-') factor | power
//   power        := primary  ['**' factor]
//   primary      := atom (call_args | subscript)*
//   atom         := INT | FLOAT | STR | True | False | None
//                 | NAME | '[' args? ']' | '(' expr ')'
// ============================================================================

class Parser {
public:
    explicit Parser(std::vector<Token> tokens) : tokens_(std::move(tokens)) {}

    ASTPtr parse() {
        auto stmts = stmtList();
        expect(TT::EOF_, "expected end of file");
        auto prog = makeNode(NodeType::Program, 1);
        prog->body = std::move(stmts);
        return prog;
    }

    // Public for REPL single-expression evaluation (mirrors Python's p._expr())
    ASTPtr exprPublic() { return expr(); }

private:
    std::vector<Token> tokens_;
    size_t pos_ = 0;

    // -- Cursor --------------------------------------------------------------

    const Token& cur() const { return tokens_[std::min(pos_, tokens_.size() - 1)]; }

    const Token& peek(size_t n = 1) const {
        return tokens_[std::min(pos_ + n, tokens_.size() - 1)];
    }

    const Token& prev() const {
        return tokens_[pos_ == 0 ? 0 : pos_ - 1];
    }

    const Token& advance() {
        const Token& tok = cur();
        if (pos_ < tokens_.size() - 1) pos_++;
        return tok;
    }

    bool check(TT t) const { return cur().type == t; }
    bool check(TT t1, TT t2) const { return cur().type == t1 || cur().type == t2; }
    bool check(TT t1, TT t2, TT t3) const {
        return cur().type == t1 || cur().type == t2 || cur().type == t3;
    }
    bool check(TT t1, TT t2, TT t3, TT t4, TT t5, TT t6) const {
        TT c = cur().type;
        return c == t1 || c == t2 || c == t3 || c == t4 || c == t5 || c == t6;
    }

    bool match(TT t) {
        if (check(t)) { advance(); return true; }
        return false;
    }
    // Multi-type match (used for binary operator chains)
    bool matchAny(const std::vector<TT>& types) {
        for (TT t : types) {
            if (check(t)) { advance(); return true; }
        }
        return false;
    }
    bool checkAny(const std::vector<TT>& types) const {
        for (TT t : types) if (cur().type == t) return true;
        return false;
    }

    const Token& expect(TT tt, const std::string& msg = "") {
        if (!check(tt)) {
            const Token& got = cur();
            std::string desc = msg.empty()
                ? ("expected '" + ttValue(tt) + "', got '" + ttValue(got.type) +
                   "' (" + got.value.repr() + ")")
                : msg;
            throw ParseError("SyntaxError: " + desc, got.line);
        }
        return advance();
    }

    [[noreturn]] void err(const std::string& msg) {
        throw ParseError("SyntaxError: " + msg, cur().line);
    }

    void skipNewlines() {
        while (check(TT::NEWLINE)) advance();
    }

    // -- Statement list --------------------------------------------------------

    std::vector<ASTPtr> stmtList() {
        std::vector<ASTPtr> stmts;
        while (true) {
            skipNewlines();
            if (check(TT::EOF_) || check(TT::DEDENT)) break;
            stmts.push_back(stmt());
        }
        return stmts;
    }

    ASTPtr stmt() {
        skipNewlines();
        if (match(TT::DEF)) return funcDef();
        if (match(TT::IF)) return ifStmt();
        if (match(TT::WHILE)) return whileStmt();
        if (match(TT::FOR)) return forStmt();
        return simpleStmt();
    }

    // -- Simple statements ------------------------------------------------------

    ASTPtr simpleStmt() {
        ASTPtr node;
        if (check(TT::RETURN)) {
            advance();
            node = returnStmt();
        } else if (check(TT::NAME) && peek(1).type == TT::EQUAL) {
            node = assignStmt();
        } else if (check(TT::NAME) &&
                   (peek(1).type == TT::PLUSEQUAL || peek(1).type == TT::MINEQUAL ||
                    peek(1).type == TT::STAREQUAL || peek(1).type == TT::SLASHEQUAL)) {
            node = augAssignStmt();
        } else {
            auto e = expr();
            node = makeNode(NodeType::ExprStmt, e->line);
            node->a = e;
        }

        if (check(TT::NEWLINE)) {
            advance();
        } else if (!check(TT::EOF_) && !check(TT::DEDENT)) {
            err("expected newline after statement, got '" + ttValue(cur().type) + "'");
        }
        return node;
    }

    ASTPtr assignStmt() {
        const Token& t = expect(TT::NAME);
        expect(TT::EQUAL);
        auto node = makeNode(NodeType::Assign, t.line);
        node->strVal = t.value.s;
        node->a = expr();
        return node;
    }

    ASTPtr augAssignStmt() {
        const Token& t = advance();
        const Token& op = advance();
        auto node = makeNode(NodeType::AugAssign, t.line);
        node->strVal = t.value.s;       // target name
        node->intVal = 0;                 // unused
        node->floatVal = 0;                // unused
        node->a = expr();                  // value
        // store op in a second string field via 'b'? We need an op string.
        // Reuse: store op text in node->params[0] for simplicity.
        node->params.push_back(op.value.s);
        return node;
    }

    ASTPtr returnStmt() {
        int ln = prev().line;
        auto node = makeNode(NodeType::Return, ln);
        if (check(TT::NEWLINE) || check(TT::EOF_) || check(TT::DEDENT)) {
            node->a = nullptr;
            return node;
        }
        node->a = expr();
        return node;
    }

    // -- Compound statements -----------------------------------------------------

    ASTPtr funcDef() {
        int ln = prev().line;
        const Token& name = expect(TT::NAME, "expected function name");
        expect(TT::LPAREN, "expected '(' after function name");
        std::vector<std::string> params;
        if (check(TT::NAME)) {
            params.push_back(advance().value.s);
            while (match(TT::COMMA)) {
                if (!check(TT::NAME)) err("expected parameter name");
                params.push_back(advance().value.s);
            }
        }
        expect(TT::RPAREN, "expected ')'");
        expect(TT::COLON, "expected ':' after function signature");
        auto body = block();
        auto node = makeNode(NodeType::FuncDef, ln);
        node->strVal = name.value.s;
        node->params = std::move(params);
        node->body = std::move(body);
        return node;
    }

    ASTPtr ifStmt() {
        int ln = prev().line;
        auto test = expr();
        expect(TT::COLON, "expected ':' after if-condition");
        auto body = block();
        auto orelse = elifOrElse();
        auto node = makeNode(NodeType::If, ln);
        node->a = test;
        node->body = std::move(body);
        node->orelse = std::move(orelse);
        return node;
    }

    std::vector<ASTPtr> elifOrElse() {
        skipNewlines();
        if (match(TT::ELIF)) {
            int ln = prev().line;
            auto test = expr();
            expect(TT::COLON, "expected ':' after elif");
            auto body = block();
            auto orelse = elifOrElse();
            auto node = makeNode(NodeType::If, ln);
            node->a = test;
            node->body = std::move(body);
            node->orelse = std::move(orelse);
            return {node};
        }
        if (match(TT::ELSE)) {
            expect(TT::COLON, "expected ':' after else");
            return block();
        }
        return {};
    }

    ASTPtr whileStmt() {
        int ln = prev().line;
        auto test = expr();
        expect(TT::COLON, "expected ':' after while");
        auto node = makeNode(NodeType::While, ln);
        node->a = test;
        node->body = block();
        return node;
    }

    ASTPtr forStmt() {
        int ln = prev().line;
        const Token& var = expect(TT::NAME, "expected loop variable");
        expect(TT::IN, "expected 'in'");
        auto itr = expr();
        expect(TT::COLON, "expected ':' after for-clause");
        auto node = makeNode(NodeType::For, ln);
        node->strVal = var.value.s;
        node->a = itr;
        node->body = block();
        return node;
    }

    std::vector<ASTPtr> block() {
        expect(TT::NEWLINE, "expected newline before block");
        expect(TT::INDENT, "expected indented block");
        auto stmts = stmtList();
        if (stmts.empty()) err("empty block");
        expect(TT::DEDENT, "expected dedent after block");
        return stmts;
    }

    // -- Expressions (precedence chain) ------------------------------------------

    ASTPtr expr() { return orExpr(); }

    ASTPtr orExpr() {
        auto node = andExpr();
        if (check(TT::OR)) {
            std::vector<ASTPtr> vals = {node};
            while (match(TT::OR)) vals.push_back(andExpr());
            auto bo = makeNode(NodeType::BoolOp, node->line);
            bo->strVal = "or";
            bo->elts = std::move(vals);
            return bo;
        }
        return node;
    }

    ASTPtr andExpr() {
        auto node = notExpr();
        if (check(TT::AND)) {
            std::vector<ASTPtr> vals = {node};
            while (match(TT::AND)) vals.push_back(notExpr());
            auto bo = makeNode(NodeType::BoolOp, node->line);
            bo->strVal = "and";
            bo->elts = std::move(vals);
            return bo;
        }
        return node;
    }

    ASTPtr notExpr() {
        if (match(TT::NOT)) {
            int ln = prev().line;
            auto node = makeNode(NodeType::UnaryOp, ln);
            node->strVal = "not";
            node->a = notExpr();
            return node;
        }
        return comparison();
    }

    ASTPtr comparison() {
        auto node = sum();
        while (checkAny({TT::EQEQUAL, TT::NOTEQUAL, TT::LESS, TT::LESSEQUAL,
                          TT::GREATER, TT::GREATEREQUAL})) {
            const Token& op = advance();
            auto right = sum();
            auto cmp = makeNode(NodeType::Compare, node->line);
            cmp->a = node;
            cmp->strVal = op.value.s;
            cmp->b = right;
            node = cmp;
        }
        return node;
    }

    ASTPtr sum() {
        auto node = term();
        while (checkAny({TT::PLUS, TT::MINUS})) {
            std::string op = advance().value.s;
            auto right = term();
            auto bin = makeNode(NodeType::BinOp, node->line);
            bin->a = node;
            bin->strVal = op;
            bin->b = right;
            node = bin;
        }
        return node;
    }

    ASTPtr term() {
        auto node = factor();
        while (checkAny({TT::STAR, TT::SLASH, TT::DOUBLESLASH, TT::PERCENT})) {
            std::string op = advance().value.s;
            auto right = factor();
            auto bin = makeNode(NodeType::BinOp, node->line);
            bin->a = node;
            bin->strVal = op;
            bin->b = right;
            node = bin;
        }
        return node;
    }

    ASTPtr factor() {
        if (checkAny({TT::PLUS, TT::MINUS})) {
            const Token& op = advance();
            auto node = makeNode(NodeType::UnaryOp, op.line);
            node->strVal = op.value.s;
            node->a = factor();
            return node;
        }
        return power();
    }

    ASTPtr power() {
        auto base = primary();
        if (match(TT::DOUBLESTAR)) {
            int ln = prev().line;
            auto bin = makeNode(NodeType::BinOp, ln);
            bin->a = base;
            bin->strVal = "**";
            bin->b = factor();
            return bin;
        }
        return base;
    }

    ASTPtr primary() {
        auto node = atom();
        while (true) {
            if (check(TT::LPAREN)) {
                advance();
                int ln = prev().line;
                auto args = callArgs();
                expect(TT::RPAREN, "expected ')' after arguments");
                auto call = makeNode(NodeType::Call, ln);
                call->a = node;
                call->elts = std::move(args);
                node = call;
            } else if (check(TT::LBRACKET)) {
                advance();
                int ln = prev().line;
                auto idx = expr();
                expect(TT::RBRACKET, "expected ']' after index");
                auto sub = makeNode(NodeType::Subscript, ln);
                sub->a = node;
                sub->b = idx;
                node = sub;
            } else {
                break;
            }
        }
        return node;
    }

    std::vector<ASTPtr> callArgs() {
        std::vector<ASTPtr> args;
        if (!check(TT::RPAREN)) {
            args.push_back(expr());
            while (match(TT::COMMA)) {
                if (check(TT::RPAREN)) break;
                args.push_back(expr());
            }
        }
        return args;
    }

    ASTPtr atom() {
        const Token& tok = cur();
        if (match(TT::INTEGER)) {
            auto node = makeNode(NodeType::IntLiteral, tok.line);
            node->intVal = tok.value.i;
            return node;
        }
        if (match(TT::FLOAT)) {
            auto node = makeNode(NodeType::FloatLiteral, tok.line);
            node->floatVal = tok.value.f;
            return node;
        }
        if (match(TT::STRING)) {
            auto node = makeNode(NodeType::StringLiteral, tok.line);
            node->strVal = tok.value.s;
            return node;
        }
        if (match(TT::TRUE_)) {
            auto node = makeNode(NodeType::BoolLiteral, tok.line);
            node->boolVal = true;
            return node;
        }
        if (match(TT::FALSE_)) {
            auto node = makeNode(NodeType::BoolLiteral, tok.line);
            node->boolVal = false;
            return node;
        }
        if (match(TT::NONE_)) {
            return makeNode(NodeType::NoneLiteral, tok.line);
        }
        if (match(TT::NAME)) {
            auto node = makeNode(NodeType::Name, tok.line);
            node->strVal = tok.value.s;
            return node;
        }
        if (match(TT::LBRACKET)) {
            std::vector<ASTPtr> elts;
            if (!check(TT::RBRACKET)) {
                elts.push_back(expr());
                while (match(TT::COMMA)) {
                    if (check(TT::RBRACKET)) break;
                    elts.push_back(expr());
                }
            }
            expect(TT::RBRACKET, "expected ']'");
            auto node = makeNode(NodeType::ListLiteral, tok.line);
            node->elts = std::move(elts);
            return node;
        }
        if (match(TT::LPAREN)) {
            auto node = expr();
            expect(TT::RPAREN, "expected ')'");
            return node;
        }
        err("unexpected token '" + ttValue(tok.type) + "' (" + tok.value.repr() + ")");
    }
};

// ============================================================================
// SECTION 6: VALUES & ENVIRONMENT
// ============================================================================

// Forward declaration
struct EduPyFunction;

// Dynamic value type, equivalent to Python's `Any` used for runtime values:
// None | bool | int | float | str | list | EduPyFunction | builtin function
struct Value {
    enum class Kind { NONE, BOOL, INT, FLOAT, STR, LIST, FUNC, BUILTIN } kind = Kind::NONE;

    bool b = false;
    long long i = 0;
    double f = 0.0;
    std::string s;
    std::shared_ptr<std::vector<Value>> list;
    std::shared_ptr<EduPyFunction> func;

    // Builtin function pointer type
    using BuiltinFn = Value (*)(const std::vector<Value>& args);
    BuiltinFn builtin = nullptr;
    std::string builtinName; // for error messages

    Value() = default;

    static Value none() { return Value(); }
    static Value ofBool(bool v) { Value x; x.kind = Kind::BOOL; x.b = v; return x; }
    static Value ofInt(long long v) { Value x; x.kind = Kind::INT; x.i = v; return x; }
    static Value ofFloat(double v) { Value x; x.kind = Kind::FLOAT; x.f = v; return x; }
    static Value ofStr(std::string v) { Value x; x.kind = Kind::STR; x.s = std::move(v); return x; }
    static Value ofList(std::vector<Value> v) {
        Value x; x.kind = Kind::LIST; x.list = std::make_shared<std::vector<Value>>(std::move(v)); return x;
    }
    static Value ofFunc(std::shared_ptr<EduPyFunction> fn) {
        Value x; x.kind = Kind::FUNC; x.func = std::move(fn); return x;
    }
    static Value ofBuiltin(BuiltinFn fn, std::string name) {
        Value x; x.kind = Kind::BUILTIN; x.builtin = fn; x.builtinName = std::move(name); return x;
    }

    bool isNumber() const { return kind == Kind::INT || kind == Kind::FLOAT || kind == Kind::BOOL; }
    // Numeric (int/float) but NOT bool — matches Python's
    // `isinstance(v, (int, float))` checks where bool is a subtype of int
    // but most numeric checks in EduPy explicitly exclude bool via separate
    // `not isinstance(v, bool)` guards. We expose both helpers.
    bool isIntOrFloat() const { return kind == Kind::INT || kind == Kind::FLOAT; }

    double asDouble() const {
        if (kind == Kind::INT) return (double)i;
        if (kind == Kind::FLOAT) return f;
        if (kind == Kind::BOOL) return b ? 1.0 : 0.0;
        return 0.0;
    }
    long long asLong() const {
        if (kind == Kind::INT) return i;
        if (kind == Kind::FLOAT) return (long long)f;
        if (kind == Kind::BOOL) return b ? 1 : 0;
        return 0;
    }
};

// EduPyFunction: a user-defined function (closure over its definition env)
class Environment;

struct EduPyFunction {
    ASTPtr node; // FuncDef
    std::shared_ptr<Environment> closure;

    std::string repr() const { return "<function " + node->strVal + ">"; }
};

// ----------------------------------------------------------------------------
// Environment: dictionary-backed variable scope.
//
// Scopes are linked by *parent* - lookup walks the chain outward
// (like CPython's LEGB rule, minus global/builtin distinctions).
// ----------------------------------------------------------------------------

class Environment : public std::enable_shared_from_this<Environment> {
public:
    std::unordered_map<std::string, Value> vars;
    std::shared_ptr<Environment> parent;

    explicit Environment(std::shared_ptr<Environment> p = nullptr) : parent(std::move(p)) {}

    Value get(const std::string& name, int line = 0) {
        auto it = vars.find(name);
        if (it != vars.end()) return it->second;
        if (parent) return parent->get(name, line);
        throw EduPyRuntimeError("NameError: name '" + name + "' is not defined", line);
    }

    // Always sets in the *current* scope (like Python assignment)
    void set(const std::string& name, const Value& value) {
        vars[name] = value;
    }

    // Assign to the nearest scope that already owns *name*.
    // Falls back to the current scope (new variable).
    void assign(const std::string& name, const Value& value, int line = 0) {
        if (vars.find(name) != vars.end()) {
            vars[name] = value;
            return;
        }
        if (parent && parent->owns(name)) {
            parent->assign(name, value, line);
            return;
        }
        vars[name] = value;
    }

    bool owns(const std::string& name) const {
        if (vars.find(name) != vars.end()) return true;
        return parent ? parent->owns(name) : false;
    }
};

// ============================================================================
// SECTION 7: VALUE HELPERS & BUILTIN FUNCTIONS
// ============================================================================

static std::string typeName(const Value& v) {
    switch (v.kind) {
        case Value::Kind::NONE: return "NoneType";
        case Value::Kind::BOOL: return "bool";
        case Value::Kind::INT: return "int";
        case Value::Kind::FLOAT: return "float";
        case Value::Kind::STR: return "str";
        case Value::Kind::LIST: return "list";
        case Value::Kind::FUNC: return "function";
        case Value::Kind::BUILTIN: return "function";
    }
    return "object";
}

// Format a double the way Python's str()/repr() would for typical cases.
static std::string formatDouble(double d) {
    if (std::isinf(d)) return d > 0 ? "inf" : "-inf";
    if (std::isnan(d)) return "nan";
    // Python prints floats like 3.0, 0.1, 1e+20 etc. We approximate with
    // up to 17 significant digits, trimmed, ensuring a decimal point or
    // exponent is present (so 3.0 doesn't print as "3").
    std::ostringstream oss;
    oss.precision(17);
    oss << d;
    std::string s = oss.str();
    // If no '.' or 'e'/'E' present, ensure trailing ".0"
    if (s.find('.') == std::string::npos &&
        s.find('e') == std::string::npos &&
        s.find('E') == std::string::npos &&
        s.find("inf") == std::string::npos &&
        s.find("nan") == std::string::npos) {
        s += ".0";
    }
    return s;
}

static std::string epStr(const Value& v) {
    switch (v.kind) {
        case Value::Kind::NONE: return "None";
        case Value::Kind::BOOL: return v.b ? "True" : "False";
        case Value::Kind::INT: return std::to_string(v.i);
        case Value::Kind::FLOAT: return formatDouble(v.f);
        case Value::Kind::STR: return v.s;
        case Value::Kind::LIST: {
            std::string out = "[";
            for (size_t idx = 0; idx < v.list->size(); ++idx) {
                if (idx) out += ", ";
                const Value& x = (*v.list)[idx];
                // EduPy's _ep_str for list elements that are strings does NOT
                // add quotes (mirrors the Python reference implementation,
                // which calls _ep_str recursively without repr-quoting).
                out += epStr(x);
            }
            out += "]";
            return out;
        }
        case Value::Kind::FUNC: return v.func->repr();
        case Value::Kind::BUILTIN: return "<builtin function " + v.builtinName + ">";
    }
    return "";
}

static bool epBool(const Value& v) {
    switch (v.kind) {
        case Value::Kind::NONE: return false;
        case Value::Kind::BOOL: return v.b;
        case Value::Kind::INT: return v.i != 0;
        case Value::Kind::FLOAT: return v.f != 0.0;
        case Value::Kind::STR: return !v.s.empty();
        case Value::Kind::LIST: return !v.list->empty();
        case Value::Kind::FUNC: return true;
        case Value::Kind::BUILTIN: return true;
    }
    return true;
}

// ---- Builtins ---------------------------------------------------------------
//
// NOTE: builtins below are implemented as free functions matching
// Value::BuiltinFn = Value(*)(const std::vector<Value>&). They throw
// EduPyRuntimeError on misuse, mirroring the Python implementation.

static Value builtin_print(const std::vector<Value>& args) {
    for (size_t i = 0; i < args.size(); ++i) {
        if (i) std::cout << " ";
        std::cout << epStr(args[i]);
    }
    std::cout << "\n";
    return Value::none();
}

static Value builtin_len(const std::vector<Value>& args) {
    if (args.size() != 1) throw EduPyRuntimeError("TypeError: len() takes exactly 1 argument");
    const Value& v = args[0];
    if (v.kind == Value::Kind::STR) return Value::ofInt((long long)v.s.size());
    if (v.kind == Value::Kind::LIST) return Value::ofInt((long long)v.list->size());
    throw EduPyRuntimeError("TypeError: object of type '" + typeName(v) + "' has no len()");
}

static Value builtin_range(const std::vector<Value>& args) {
    if (args.size() < 1 || args.size() > 3)
        throw EduPyRuntimeError("TypeError: range() takes 1-3 arguments");
    std::vector<long long> iargs;
    for (const auto& a : args) {
        if (!a.isIntOrFloat() && a.kind != Value::Kind::BOOL)
            throw EduPyRuntimeError("TypeError: range() arguments must be integers");
        iargs.push_back(a.asLong());
    }
    long long start = 0, stop = 0, step = 1;
    if (iargs.size() == 1) { stop = iargs[0]; }
    else if (iargs.size() == 2) { start = iargs[0]; stop = iargs[1]; }
    else { start = iargs[0]; stop = iargs[1]; step = iargs[2]; }

    if (step == 0) throw EduPyRuntimeError("ValueError: range() arg 3 must not be zero");

    std::vector<Value> out;
    if (step > 0) {
        for (long long v = start; v < stop; v += step) out.push_back(Value::ofInt(v));
    } else {
        for (long long v = start; v > stop; v += step) out.push_back(Value::ofInt(v));
    }
    return Value::ofList(std::move(out));
}

// Helper: does a string represent an integer literal (with optional sign),
// mirroring Python's `s.lstrip("-+").isdigit()`.
static bool isDigitsStripSign(const std::string& s) {
    size_t i = 0;
    while (i < s.size() && (s[i] == '-' || s[i] == '+')) i++;
    if (i >= s.size()) return false; // empty after stripping -> not digits
    for (; i < s.size(); ++i) {
        if (!isdigit((unsigned char)s[i])) return false;
    }
    return true;
}

static std::string strip(const std::string& s) {
    size_t a = 0, b = s.size();
    while (a < b && isspace((unsigned char)s[a])) a++;
    while (b > a && isspace((unsigned char)s[b - 1])) b--;
    return s.substr(a, b - a);
}

static Value builtin_int(const std::vector<Value>& args) {
    if (args.size() != 1) throw EduPyRuntimeError("TypeError: int() takes 1 argument");
    const Value& v = args[0];
    if (v.kind == Value::Kind::BOOL) return Value::ofInt(v.b ? 1 : 0);
    if (v.kind == Value::Kind::INT) return Value::ofInt(v.i);
    if (v.kind == Value::Kind::FLOAT) return Value::ofInt((long long)v.f);
    if (v.kind == Value::Kind::STR) {
        std::string s = strip(v.s);
        if (isDigitsStripSign(s)) {
            return Value::ofInt(std::stoll(s));
        }
        throw EduPyRuntimeError("ValueError: invalid literal for int(): '" + v.s + "'");
    }
    throw EduPyRuntimeError("TypeError: int() argument must be a string or number, not '" + typeName(v) + "'");
}

static Value builtin_float(const std::vector<Value>& args) {
    if (args.size() != 1) throw EduPyRuntimeError("TypeError: float() takes 1 argument");
    const Value& v = args[0];
    if (v.kind == Value::Kind::BOOL) return Value::ofFloat(v.b ? 1.0 : 0.0);
    if (v.kind == Value::Kind::INT) return Value::ofFloat((double)v.i);
    if (v.kind == Value::Kind::FLOAT) return Value::ofFloat(v.f);
    if (v.kind == Value::Kind::STR) {
        std::string s = strip(v.s);
        if (!s.empty()) {
            try {
                size_t idx;
                double d = std::stod(s, &idx);
                if (idx == s.size()) return Value::ofFloat(d);
            } catch (...) {
                // fall through to error below
            }
        }
    }
    throw EduPyRuntimeError("TypeError: float() argument must be a string or number, not '" + typeName(v) + "'");
}

static Value builtin_str(const std::vector<Value>& args) {
    if (args.size() != 1) throw EduPyRuntimeError("TypeError: str() takes 1 argument");
    return Value::ofStr(epStr(args[0]));
}

static Value builtin_bool(const std::vector<Value>& args) {
    if (args.size() != 1) throw EduPyRuntimeError("TypeError: bool() takes 1 argument");
    return Value::ofBool(epBool(args[0]));
}

static Value builtin_input(const std::vector<Value>& args) {
    std::string prompt = args.empty() ? "" : epStr(args[0]);
    std::cout << prompt;
    std::string line;
    if (!std::getline(std::cin, line)) {
        // EOF: Python's input() raises EOFError; we mirror with empty string
        // to avoid crashing, but a stricter port could throw here.
        return Value::ofStr("");
    }
    return Value::ofStr(line);
}

static Value builtin_abs(const std::vector<Value>& args) {
    if (args.size() != 1) throw EduPyRuntimeError("TypeError: abs() takes 1 argument");
    const Value& v = args[0];
    if (v.isIntOrFloat()) {
        if (v.kind == Value::Kind::INT) return Value::ofInt(std::abs(v.i));
        return Value::ofFloat(std::fabs(v.f));
    }
    throw EduPyRuntimeError("TypeError: bad operand type for abs(): '" + typeName(v) + "'");
}

// Comparison used by max()/min(): mirrors Python's default `<` semantics for
// the value types EduPy supports (numbers compare numerically, strings
// lexicographically). Mixed numeric/string comparisons would raise in real
// Python; we keep it simple since EduPy's own Compare already restricts to
// compatible types.
static bool valueLess(const Value& a, const Value& b) {
    if (a.isIntOrFloat() && b.isIntOrFloat()) return a.asDouble() < b.asDouble();
    if (a.kind == Value::Kind::STR && b.kind == Value::Kind::STR) return a.s < b.s;
    // Fallback: compare doubles
    return a.asDouble() < b.asDouble();
}

static Value builtin_max(const std::vector<Value>& args) {
    if (args.empty()) throw EduPyRuntimeError("TypeError: max() expected at least 1 argument");
    const std::vector<Value>* items;
    std::vector<Value> single;
    if (args.size() == 1 && args[0].kind == Value::Kind::LIST) {
        items = args[0].list.get();
    } else {
        single = args;
        items = &single;
    }
    if (items->empty()) throw EduPyRuntimeError("ValueError: max() arg is an empty sequence");
    Value best = (*items)[0];
    for (size_t i = 1; i < items->size(); ++i) {
        if (valueLess(best, (*items)[i])) best = (*items)[i];
    }
    return best;
}

static Value builtin_min(const std::vector<Value>& args) {
    if (args.empty()) throw EduPyRuntimeError("TypeError: min() expected at least 1 argument");
    const std::vector<Value>* items;
    std::vector<Value> single;
    if (args.size() == 1 && args[0].kind == Value::Kind::LIST) {
        items = args[0].list.get();
    } else {
        single = args;
        items = &single;
    }
    if (items->empty()) throw EduPyRuntimeError("ValueError: min() arg is an empty sequence");
    Value best = (*items)[0];
    for (size_t i = 1; i < items->size(); ++i) {
        if (valueLess((*items)[i], best)) best = (*items)[i];
    }
    return best;
}

static Value builtin_type(const std::vector<Value>& args) {
    if (args.size() != 1) throw EduPyRuntimeError("TypeError: type() takes 1 argument");
    return Value::ofStr("<class '" + typeName(args[0]) + "'>");
}

// append(list, value) — not method syntax
static Value builtin_append(const std::vector<Value>& args) {
    if (args.size() != 2) throw EduPyRuntimeError("TypeError: append() takes 2 arguments");
    if (args[0].kind != Value::Kind::LIST) throw EduPyRuntimeError("TypeError: first argument must be a list");
    args[0].list->push_back(args[1]);
    return Value::none();
}

static Value builtin_pop(const std::vector<Value>& args) {
    if (args.size() != 1 && args.size() != 2)
        throw EduPyRuntimeError("TypeError: pop() takes 1 or 2 arguments");
    if (args[0].kind != Value::Kind::LIST) throw EduPyRuntimeError("TypeError: first argument must be a list");
    auto& lst = *args[0].list;
    long long idx = args.size() == 2 ? args[1].asLong() : -1;
    if (lst.empty()) throw EduPyRuntimeError("IndexError: pop from empty list");
    if (idx < 0) idx += (long long)lst.size();
    if (idx < 0 || idx >= (long long)lst.size())
        throw EduPyRuntimeError("IndexError: pop index out of range");
    Value v = lst[idx];
    lst.erase(lst.begin() + idx);
    return v;
}

// Registry: name -> builtin function pointer
static const std::vector<std::pair<std::string, Value::BuiltinFn>> BUILTINS = {
    {"print", builtin_print},
    {"len", builtin_len},
    {"range", builtin_range},
    {"int", builtin_int},
    {"float", builtin_float},
    {"str", builtin_str},
    {"bool", builtin_bool},
    {"input", builtin_input},
    {"abs", builtin_abs},
    {"max", builtin_max},
    {"min", builtin_min},
    {"type", builtin_type},
    {"append", builtin_append},
    {"pop", builtin_pop},
};

// ============================================================================
// SECTION 8: INTERPRETER (tree-walk)
// ============================================================================
//
// Executes an EduPy AST by walking the tree recursively.
// Dispatch pattern: eval(node) / exec(node) switch on node->type.
// ============================================================================

// Internal exception used to implement `return` (mirrors Python's
// ReturnSignal). Carries a Value by value.
struct ReturnException {
    Value value;
};

class Interpreter {
public:
    std::shared_ptr<Environment> globals;

    Interpreter() {
        globals = std::make_shared<Environment>();
        for (const auto& [name, fn] : BUILTINS) {
            globals->set(name, Value::ofBuiltin(fn, name));
        }
    }

    void run(const ASTPtr& program) {
        execStmts(program->body, globals);
    }

    // Evaluate a single expression string (used by REPL)
    Value evalExpr(const std::string& source) {
        Lexer lex(source + "\n");
        auto tokens = lex.tokenize();
        Parser p(tokens);
        auto node = p.exprPublic();
        return eval(node, globals);
    }

    // -- Statement execution --------------------------------------------------

    void execStmts(const std::vector<ASTPtr>& stmts, const std::shared_ptr<Environment>& env) {
        for (const auto& stmt : stmts) exec(stmt, env);
    }

    void exec(const ASTPtr& node, const std::shared_ptr<Environment>& env) {
        switch (node->type) {
            case NodeType::FuncDef: {
                auto fn = std::make_shared<EduPyFunction>();
                fn->node = node;
                fn->closure = env;
                env->set(node->strVal, Value::ofFunc(fn));
                return;
            }
            case NodeType::Assign: {
                env->set(node->strVal, eval(node->a, env));
                return;
            }
            case NodeType::AugAssign: {
                Value current = env->get(node->strVal, node->line);
                Value rhs = eval(node->a, env);
                // op is stored in params[0], e.g. "+=" -> take first char '+'
                char opChar = node->params.empty() ? '+' : node->params[0][0];
                Value result = applyBinOp(std::string(1, opChar), current, rhs, node->line);
                env->assign(node->strVal, result, node->line);
                return;
            }
            case NodeType::ExprStmt: {
                eval(node->a, env);
                return;
            }
            case NodeType::Return: {
                Value value = node->a ? eval(node->a, env) : Value::none();
                throw ReturnException{value};
            }
            case NodeType::If: {
                if (epBool(eval(node->a, env))) {
                    execStmts(node->body, env);
                } else if (!node->orelse.empty()) {
                    execStmts(node->orelse, env);
                }
                return;
            }
            case NodeType::While: {
                while (epBool(eval(node->a, env))) {
                    execStmts(node->body, env);
                }
                return;
            }
            case NodeType::For: {
                Value iterable = eval(node->a, env);
                if (iterable.kind == Value::Kind::LIST) {
                    // Copy to avoid iterator invalidation if the list is
                    // mutated during the loop (matches Python's behavior of
                    // iterating a snapshot when append happens via builtin,
                    // though Python itself iterates live; we choose snapshot
                    // for safety/parity with simple scripts).
                    auto items = *iterable.list;
                    for (const auto& item : items) {
                        env->set(node->strVal, item);
                        execStmts(node->body, env);
                    }
                } else if (iterable.kind == Value::Kind::STR) {
                    for (char c : iterable.s) {
                        env->set(node->strVal, Value::ofStr(std::string(1, c)));
                        execStmts(node->body, env);
                    }
                } else {
                    throw EduPyRuntimeError(
                        "TypeError: '" + typeName(iterable) + "' object is not iterable", node->line);
                }
                return;
            }
            default:
                throw EduPyRuntimeError("InternalError: no exec handler for node", node->line);
        }
    }

    // -- Expression evaluation --------------------------------------------------

    Value eval(const ASTPtr& node, const std::shared_ptr<Environment>& env) {
        switch (node->type) {
            case NodeType::IntLiteral: return Value::ofInt(node->intVal);
            case NodeType::FloatLiteral: return Value::ofFloat(node->floatVal);
            case NodeType::StringLiteral: return Value::ofStr(node->strVal);
            case NodeType::BoolLiteral: return Value::ofBool(node->boolVal);
            case NodeType::NoneLiteral: return Value::none();
            case NodeType::Name: return env->get(node->strVal, node->line);
            case NodeType::ListLiteral: {
                std::vector<Value> out;
                out.reserve(node->elts.size());
                for (const auto& e : node->elts) out.push_back(eval(e, env));
                return Value::ofList(std::move(out));
            }
            case NodeType::Subscript: {
                Value obj = eval(node->a, env);
                Value idxv = eval(node->b, env);
                if (obj.kind != Value::Kind::LIST && obj.kind != Value::Kind::STR) {
                    throw EduPyRuntimeError(
                        "TypeError: '" + typeName(obj) + "' object is not subscriptable", node->line);
                }
                if (!idxv.isIntOrFloat() && idxv.kind != Value::Kind::BOOL) {
                    throw EduPyRuntimeError(
                        "TypeError: indices must be integers, not '" + typeName(idxv) + "'", node->line);
                }
                long long idx = idxv.asLong();
                long long len = obj.kind == Value::Kind::LIST ? (long long)obj.list->size() : (long long)obj.s.size();
                if (idx < -len || idx >= len) {
                    throw EduPyRuntimeError(
                        "IndexError: index " + std::to_string(idx) + " out of range (length " +
                        std::to_string(len) + ")", node->line);
                }
                long long realIdx = idx < 0 ? idx + len : idx;
                if (obj.kind == Value::Kind::LIST) return (*obj.list)[realIdx];
                return Value::ofStr(std::string(1, obj.s[realIdx]));
            }
            case NodeType::BinOp: {
                Value left = eval(node->a, env);
                Value right = eval(node->b, env);
                return applyBinOp(node->strVal, left, right, node->line);
            }
            case NodeType::UnaryOp: {
                Value v = eval(node->a, env);
                if (node->strVal == "not") return Value::ofBool(!epBool(v));
                if (node->strVal == "-") {
                    if (v.isIntOrFloat()) {
                        if (v.kind == Value::Kind::INT) return Value::ofInt(-v.i);
                        return Value::ofFloat(-v.f);
                    }
                    throw EduPyRuntimeError(
                        "TypeError: bad operand type for unary '-': '" + typeName(v) + "'", node->line);
                }
                if (node->strVal == "+") {
                    if (v.isIntOrFloat()) {
                        return v; // unary plus is identity
                    }
                    throw EduPyRuntimeError(
                        "TypeError: bad operand type for unary '+': '" + typeName(v) + "'", node->line);
                }
                return Value::none();
            }
            case NodeType::Compare: {
                Value left = eval(node->a, env);
                Value right = eval(node->b, env);
                const std::string& op = node->strVal;
                if (op == "==") return Value::ofBool(valuesEqual(left, right));
                if (op == "!=") return Value::ofBool(!valuesEqual(left, right));
                // Ordered comparisons - must be int/float/str
                for (const Value* v : {&left, &right}) {
                    if (v->kind != Value::Kind::INT && v->kind != Value::Kind::FLOAT &&
                        v->kind != Value::Kind::BOOL && v->kind != Value::Kind::STR) {
                        throw EduPyRuntimeError(
                            "TypeError: '" + op + "' not supported between '" + typeName(left) +
                            "' and '" + typeName(right) + "'", node->line);
                    }
                }
                if (op == "<") return Value::ofBool(compareLess(left, right));
                if (op == "<=") return Value::ofBool(!compareLess(right, left));
                if (op == ">") return Value::ofBool(compareLess(right, left));
                if (op == ">=") return Value::ofBool(!compareLess(left, right));
                return Value::none();
            }
            case NodeType::BoolOp: {
                if (node->strVal == "and") {
                    Value result = eval(node->elts[0], env);
                    for (size_t i = 1; i < node->elts.size(); ++i) {
                        if (!epBool(result)) return result;
                        result = eval(node->elts[i], env);
                    }
                    return result;
                } else { // or
                    Value result = eval(node->elts[0], env);
                    for (size_t i = 1; i < node->elts.size(); ++i) {
                        if (epBool(result)) return result;
                        result = eval(node->elts[i], env);
                    }
                    return result;
                }
            }
            case NodeType::Call: {
                Value callee = eval(node->a, env);
                std::vector<Value> args;
                args.reserve(node->elts.size());
                for (const auto& a : node->elts) args.push_back(eval(a, env));

                if (callee.kind == Value::Kind::BUILTIN) {
                    return callee.builtin(args);
                }

                if (callee.kind == Value::Kind::FUNC) {
                    const auto& fn = callee.func;
                    const ASTPtr& fnNode = fn->node;
                    size_t arity = fnNode->params.size();
                    if (args.size() != arity) {
                        throw EduPyRuntimeError(
                            "TypeError: " + fnNode->strVal + "() takes " + std::to_string(arity) +
                            " argument(s) but " + std::to_string(args.size()) + " given", node->line);
                    }
                    auto callEnv = std::make_shared<Environment>(fn->closure);
                    for (size_t i = 0; i < arity; ++i) {
                        callEnv->set(fnNode->params[i], args[i]);
                    }
                    try {
                        execStmts(fnNode->body, callEnv);
                    } catch (ReturnException& ret) {
                        return ret.value;
                    }
                    return Value::none();
                }

                throw EduPyRuntimeError(
                    "TypeError: '" + typeName(callee) + "' object is not callable", node->line);
            }
            default:
                throw EduPyRuntimeError("InternalError: no eval handler for node", node->line);
        }
    }

private:
    // Equality used for == / != . Mirrors Python's structural equality for
    // the types EduPy supports (numbers compare across int/float/bool,
    // strings compare by content, lists compare elementwise, None == None).
    static bool valuesEqual(const Value& a, const Value& b) {
        // Numeric types (including bool) compare by numeric value, like Python
        bool aNum = a.kind == Value::Kind::INT || a.kind == Value::Kind::FLOAT || a.kind == Value::Kind::BOOL;
        bool bNum = b.kind == Value::Kind::INT || b.kind == Value::Kind::FLOAT || b.kind == Value::Kind::BOOL;
        if (aNum && bNum) return a.asDouble() == b.asDouble();
        if (a.kind != b.kind) return false;
        switch (a.kind) {
            case Value::Kind::NONE: return true;
            case Value::Kind::STR: return a.s == b.s;
            case Value::Kind::LIST: {
                if (a.list->size() != b.list->size()) return false;
                for (size_t i = 0; i < a.list->size(); ++i) {
                    if (!valuesEqual((*a.list)[i], (*b.list)[i])) return false;
                }
                return true;
            }
            default: return false; // functions etc. compare unequal
        }
    }

    // `<` for ordered comparisons (int/float/bool numeric, or str lexicographic)
    static bool compareLess(const Value& a, const Value& b) {
        bool aNum = a.kind == Value::Kind::INT || a.kind == Value::Kind::FLOAT || a.kind == Value::Kind::BOOL;
        bool bNum = b.kind == Value::Kind::INT || b.kind == Value::Kind::FLOAT || b.kind == Value::Kind::BOOL;
        if (aNum && bNum) return a.asDouble() < b.asDouble();
        if (a.kind == Value::Kind::STR && b.kind == Value::Kind::STR) return a.s < b.s;
        // Mixed types: fall back to numeric comparison (best effort)
        return a.asDouble() < b.asDouble();
    }

public:
    // -- Binary operator application -----------------------------------------
    static Value applyBinOp(const std::string& op, const Value& left, const Value& right, int line) {
        // String concatenation
        if (op == "+" && left.kind == Value::Kind::STR && right.kind == Value::Kind::STR) {
            return Value::ofStr(left.s + right.s);
        }
        // String repetition
        if (op == "*" && left.kind == Value::Kind::STR && right.isIntOrFloat()) {
            return Value::ofStr(repeatStr(left.s, (long long)right.asLong()));
        }
        if (op == "*" && left.isIntOrFloat() && right.kind == Value::Kind::STR) {
            return Value::ofStr(repeatStr(right.s, (long long)left.asLong()));
        }
        // List concatenation / repetition
        if (op == "+" && left.kind == Value::Kind::LIST && right.kind == Value::Kind::LIST) {
            std::vector<Value> out = *left.list;
            out.insert(out.end(), right.list->begin(), right.list->end());
            return Value::ofList(std::move(out));
        }
        if (op == "*" && left.kind == Value::Kind::LIST && right.isIntOrFloat()) {
            return Value::ofList(repeatList(*left.list, right.asLong()));
        }

        // Numeric operations
        bool leftNumeric = left.kind == Value::Kind::INT || left.kind == Value::Kind::FLOAT || left.kind == Value::Kind::BOOL;
        bool rightNumeric = right.kind == Value::Kind::INT || right.kind == Value::Kind::FLOAT || right.kind == Value::Kind::BOOL;

        if (leftNumeric && rightNumeric) {
            bool bothInt = (left.kind == Value::Kind::INT || left.kind == Value::Kind::BOOL) &&
                           (right.kind == Value::Kind::INT || right.kind == Value::Kind::BOOL);

            if (op == "+") {
                if (bothInt) return Value::ofInt(left.asLong() + right.asLong());
                return Value::ofFloat(left.asDouble() + right.asDouble());
            }
            if (op == "-") {
                if (bothInt) return Value::ofInt(left.asLong() - right.asLong());
                return Value::ofFloat(left.asDouble() - right.asDouble());
            }
            if (op == "*") {
                if (bothInt) return Value::ofInt(left.asLong() * right.asLong());
                return Value::ofFloat(left.asDouble() * right.asDouble());
            }
            if (op == "**") {
                if (bothInt && right.asLong() >= 0) {
                    long long base = left.asLong();
                    long long exp = right.asLong();
                    long long result = 1;
                    for (long long e = 0; e < exp; ++e) result *= base;
                    return Value::ofInt(result);
                }
                return Value::ofFloat(std::pow(left.asDouble(), right.asDouble()));
            }
            if (op == "%") {
                if (right.asDouble() == 0) {
                    throw EduPyRuntimeError("ZeroDivisionError: modulo by zero", line);
                }
                if (bothInt) {
                    long long l = left.asLong(), r = right.asLong();
                    long long m = l % r;
                    // Python's % follows the sign of the divisor
                    if (m != 0 && ((m < 0) != (r < 0))) m += r;
                    return Value::ofInt(m);
                }
                double l = left.asDouble(), r = right.asDouble();
                double m = std::fmod(l, r);
                if (m != 0 && ((m < 0) != (r < 0))) m += r;
                return Value::ofFloat(m);
            }
            if (op == "/") {
                if (right.asDouble() == 0) {
                    throw EduPyRuntimeError("ZeroDivisionError: division by zero", line);
                }
                return Value::ofFloat(left.asDouble() / right.asDouble());
            }
            if (op == "//") {
                if (right.asDouble() == 0) {
                    throw EduPyRuntimeError("ZeroDivisionError: integer division by zero", line);
                }
                // Python's // floors toward negative infinity
                double q = std::floor(left.asDouble() / right.asDouble());
                return Value::ofInt((long long)q);
            }
        }

        throw EduPyRuntimeError(
            "TypeError: unsupported operand type(s) for '" + op + "': '" +
            typeName(left) + "' and '" + typeName(right) + "'", line);
    }

private:
    static std::string repeatStr(const std::string& s, long long n) {
        if (n <= 0) return "";
        std::string out;
        out.reserve(s.size() * (size_t)n);
        for (long long i = 0; i < n; ++i) out += s;
        return out;
    }

    static std::vector<Value> repeatList(const std::vector<Value>& v, long long n) {
        std::vector<Value> out;
        if (n <= 0) return out;
        out.reserve(v.size() * (size_t)n);
        for (long long i = 0; i < n; ++i) {
            out.insert(out.end(), v.begin(), v.end());
        }
        return out;
    }
};

// ============================================================================
// SECTION 9: AST PRETTY PRINTER (for --ast flag)
// ============================================================================

static void printAst(const ASTPtr& node, int indent = 0) {
    std::string pad(indent * 2, ' ');

    switch (node->type) {
        case NodeType::IntLiteral:
            std::cout << pad << "IntLiteral(" << node->intVal << ")\n";
            break;
        case NodeType::FloatLiteral:
            std::cout << pad << "FloatLiteral(" << formatDouble(node->floatVal) << ")\n";
            break;
        case NodeType::StringLiteral:
            std::cout << pad << "StringLiteral('" << node->strVal << "')\n";
            break;
        case NodeType::BoolLiteral:
            std::cout << pad << "BoolLiteral(" << (node->boolVal ? "True" : "False") << ")\n";
            break;
        case NodeType::NoneLiteral:
            std::cout << pad << "NoneLiteral\n";
            break;
        case NodeType::Name:
            std::cout << pad << "Name('" << node->strVal << "')\n";
            break;
        case NodeType::Program:
            std::cout << pad << "Program [line " << node->line << "]\n";
            for (const auto& s : node->body) printAst(s, indent + 1);
            break;
        case NodeType::FuncDef: {
            std::cout << pad << "FuncDef name='" << node->strVal << "' params=[";
            for (size_t i = 0; i < node->params.size(); ++i) {
                if (i) std::cout << ", ";
                std::cout << "'" << node->params[i] << "'";
            }
            std::cout << "]\n";
            for (const auto& s : node->body) printAst(s, indent + 1);
            break;
        }
        case NodeType::Assign:
            std::cout << pad << "Assign target='" << node->strVal << "'\n";
            printAst(node->a, indent + 1);
            break;
        case NodeType::AugAssign:
            std::cout << pad << "AugAssign target='" << node->strVal << "' op='"
                      << (node->params.empty() ? "" : node->params[0]) << "'\n";
            printAst(node->a, indent + 1);
            break;
        case NodeType::Return:
            std::cout << pad << "Return\n";
            if (node->a) printAst(node->a, indent + 1);
            break;
        case NodeType::ExprStmt:
            std::cout << pad << "ExprStmt\n";
            printAst(node->a, indent + 1);
            break;
        case NodeType::If:
            std::cout << pad << "If\n";
            std::cout << pad << "  test:\n";
            printAst(node->a, indent + 2);
            std::cout << pad << "  body:\n";
            for (const auto& s : node->body) printAst(s, indent + 2);
            if (!node->orelse.empty()) {
                std::cout << pad << "  orelse:\n";
                for (const auto& s : node->orelse) printAst(s, indent + 2);
            }
            break;
        case NodeType::While:
            std::cout << pad << "While\n";
            std::cout << pad << "  test:\n";
            printAst(node->a, indent + 2);
            std::cout << pad << "  body:\n";
            for (const auto& s : node->body) printAst(s, indent + 2);
            break;
        case NodeType::For:
            std::cout << pad << "For target='" << node->strVal << "'\n";
            std::cout << pad << "  iter:\n";
            printAst(node->a, indent + 2);
            std::cout << pad << "  body:\n";
            for (const auto& s : node->body) printAst(s, indent + 2);
            break;
        case NodeType::BinOp:
            std::cout << pad << "BinOp op='" << node->strVal << "'\n";
            printAst(node->a, indent + 1);
            printAst(node->b, indent + 1);
            break;
        case NodeType::UnaryOp:
            std::cout << pad << "UnaryOp op='" << node->strVal << "'\n";
            printAst(node->a, indent + 1);
            break;
        case NodeType::Compare:
            std::cout << pad << "Compare op='" << node->strVal << "'\n";
            printAst(node->a, indent + 1);
            printAst(node->b, indent + 1);
            break;
        case NodeType::BoolOp:
            std::cout << pad << "BoolOp op='" << node->strVal << "'\n";
            for (const auto& v : node->elts) printAst(v, indent + 1);
            break;
        case NodeType::Call:
            std::cout << pad << "Call\n";
            printAst(node->a, indent + 1);
            for (const auto& a : node->elts) printAst(a, indent + 1);
            break;
        case NodeType::ListLiteral:
            std::cout << pad << "ListLiteral [" << node->elts.size() << " elements]\n";
            for (const auto& e : node->elts) printAst(e, indent + 1);
            break;
        case NodeType::Subscript:
            std::cout << pad << "Subscript\n";
            printAst(node->a, indent + 1);
            printAst(node->b, indent + 1);
            break;
        default:
            std::cout << pad << "(no printer)\n";
            break;
    }
}

// ============================================================================
// SECTION 10: PIPELINE (source -> tokens -> AST -> execute)
// ============================================================================

// Full pipeline: source text -> tokens -> AST -> execute.
// Returns the interpreter so the REPL can share state across lines.
static void runSource(const std::string& source, Interpreter& interp) {
    Lexer lex(source);
    auto tokens = lex.tokenize();
    Parser parser(tokens);
    auto program = parser.parse();
    interp.run(program);
}

// Run source and also print the AST before execution.
static void runSourceWithAst(const std::string& source) {
    Lexer lex(source);
    auto tokens = lex.tokenize();
    Parser parser(tokens);
    auto program = parser.parse();
    std::cout << "\n-- AST -----------------------------------------------\n";
    printAst(program);
    std::cout << "--------------------------------------------------------\n\n";
    Interpreter interp;
    interp.run(program);
}

// ============================================================================
// SECTION 11: REPL
// ============================================================================

static const char* BANNER =
    "\033[96m+========================================================+\n"
    "|           EduPy  -  Educational Interpreter           |\n"
    "|  Type EduPy code below.  'exit' or Ctrl-D to quit.    |\n"
    "|  'help' for a quick language reference.               |\n"
    "+========================================================+\033[0m";

static const char* HELP_TEXT = R"(
EduPy Quick Reference
----------------------
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
)";

// Heuristic: return True if the source looks incomplete (open block).
static bool needsMore(const std::string& source) {
    std::vector<std::string> lines;
    {
        std::istringstream iss(source);
        std::string l;
        while (std::getline(iss, l)) {
            // strip
            std::string stripped = strip(l);
            if (!stripped.empty() && stripped[0] != '#') lines.push_back(l);
        }
    }
    if (lines.empty()) return false;
    std::string last = lines.back();
    // rstrip
    while (!last.empty() && isspace((unsigned char)last.back())) last.pop_back();
    return !last.empty() && last.back() == ':';
}

static void repl() {
    std::cout << BANNER << "\n";
    Interpreter interp;
    std::vector<std::string> buf;
    const std::string promptStr = ">>> ";
    const std::string contPrompt = "... ";

    while (true) {
        std::cout << (buf.empty() ? promptStr : contPrompt);
        std::string line;
        if (!std::getline(std::cin, line)) {
            std::cout << "\nBye!\n";
            break;
        }

        if (buf.empty() && strip(line) == "exit") {
            std::cout << "Bye!\n";
            break;
        }
        if (buf.empty() && strip(line) == "help") {
            std::cout << HELP_TEXT;
            continue;
        }
        if (buf.empty() && strip(line).empty()) {
            continue;
        }

        buf.push_back(line);
        std::string source;
        for (size_t i = 0; i < buf.size(); ++i) {
            if (i) source += "\n";
            source += buf[i];
        }

        // If the line ends with ':' or the buffer isn't balanced, keep reading
        std::string strippedRight = line;
        while (!strippedRight.empty() && isspace((unsigned char)strippedRight.back())) strippedRight.pop_back();

        if ((!strippedRight.empty() && strippedRight.back() == ':') ||
            (!buf.empty() && needsMore(source))) {
            continue;
        }

        // Attempt execution
        try {
            runSource(source + "\n", interp);
        } catch (const EduPyError& e) {
            std::cout << e.colored() << "\n";
        } catch (const ReturnException&) {
            // 'return' outside a function — Python's reference impl would
            // let ReturnSignal propagate as an uncaught exception leading to
            // a Python traceback; here we surface a clear runtime error.
            std::cout << "\033[91mEduPyRuntimeError\033[0m: 'return' outside function\n";
        } catch (const std::exception& e) {
            std::cout << "\033[91mInternalError\033[0m: " << e.what() << "\n";
        }
        buf.clear();
    }
}

// ============================================================================
// SECTION 12: CLI ENTRY POINT
// ============================================================================

int main(int argc, char** argv) {
    std::vector<std::string> args(argv + 1, argv + argc);

    if (args.empty()) {
        repl();
        return 0;
    }

    bool showAst = false;
    std::vector<std::string> files;
    for (const auto& a : args) {
        if (a == "--ast") showAst = true;
        else if (a.rfind("--", 0) != 0) files.push_back(a);
    }

    if (files.empty()) {
        std::cout << "Usage: edupy [script.ep] [--ast]\n";
        return 1;
    }

    const std::string& filepath = files[0];
    std::ifstream fh(filepath);
    if (!fh) {
        std::cout << "\033[91mFileNotFoundError\033[0m: No such file: '" << filepath << "'\n";
        return 1;
    }

    std::ostringstream ss;
    ss << fh.rdbuf();
    std::string source = ss.str();

    try {
        if (showAst) {
            runSourceWithAst(source);
        } else {
            Interpreter interp;
            runSource(source, interp);
        }
    } catch (const EduPyError& e) {
        std::cout << e.colored() << "\n";
        return 1;
    } catch (const ReturnException&) {
        std::cout << "\033[91mEduPyRuntimeError\033[0m: 'return' outside function\n";
        return 1;
    } catch (const std::exception& e) {
        std::cout << "\033[91mInternalError\033[0m: " << e.what() << "\n";
        return 1;
    }

    return 0;
}