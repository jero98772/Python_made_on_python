import java.io.*;
import java.math.BigDecimal;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.*;
import java.util.regex.Pattern;

/**
 * Py - a small tree-walking interpreter for a Python-like language.
 * Java 21 port.  Run directly with:   java Py.java [script] [--ast]
 *
 * Pipeline: source -> Lexer -> tokens -> Parser -> AST -> Interpreter
 *
 * Value mapping:  int -> Long   float -> Double   str -> String
 *                 bool -> Boolean   list -> List<Object>   None -> null
 */
public class Main {

    // ══════════════════════════════════════════════════════════════════════
    // §1  ERRORS
    // ══════════════════════════════════════════════════════════════════════

    static class PyError extends RuntimeException {
        final String msg;
        final int line;

        PyError(String message, int line) {
            super(message);
            this.msg = message;
            this.line = line;
        }

        private String loc() {
            return line > 0 ? " [line " + line + "]" : "";
        }

        String plain() {
            return getClass().getSimpleName() + ": " + msg + loc();
        }

        @Override
        public String toString() {
            return "\033[91m" + getClass().getSimpleName() + "\033[0m: " + msg + loc();
        }
    }

    /** Illegal character or unterminated literal. */
    static class LexerError extends PyError {
        LexerError(String m, int line) { super(m, line); }
    }

    /** Token stream violates the grammar. */
    static class ParseError extends PyError {
        ParseError(String m, int line) { super(m, line); }
    }

    /** Type error, undefined name, wrong arity, etc. */
    static class PyRuntimeError extends PyError {
        PyRuntimeError(String m, int line) { super(m, line); }
    }

    static PyRuntimeError rt(String msg) { return new PyRuntimeError(msg, 0); }
    static PyRuntimeError rt(String msg, int line) { return new PyRuntimeError(msg, line); }

    /** Internal signal used to unwind the call stack on 'return'. */
    static final class ReturnSignal extends RuntimeException {
        final Object value;

        ReturnSignal(Object value) {
            super(null, null, false, false); // no stack trace: cheap to throw
            this.value = value;
        }
    }

    // ══════════════════════════════════════════════════════════════════════
    // §2  TOKENS
    // ══════════════════════════════════════════════════════════════════════

    enum TT {
        // Literals
        INTEGER("INTEGER"), FLOAT("FLOAT"), STRING("STRING"),
        // Keywords
        IF("if"), ELIF("elif"), ELSE("else"), WHILE("while"), FOR("for"), IN("in"),
        DEF("def"), RETURN("return"), AND("and"), OR("or"), NOT("not"),
        TRUE("True"), FALSE("False"), NONE("None"),
        // Identifier
        NAME("NAME"),
        // Arithmetic
        PLUS("+"), MINUS("-"), STAR("*"), SLASH("/"), PERCENT("%"),
        DOUBLESLASH("//"), DOUBLESTAR("**"),
        // Comparison
        EQEQUAL("=="), NOTEQUAL("!="), LESS("<"), LESSEQUAL("<="),
        GREATER(">"), GREATEREQUAL(">="),
        // Assignment
        EQUAL("="),
        PLUSEQUAL("+="), MINEQUAL("-="), STAREQUAL("*="), SLASHEQUAL("/="),
        // Delimiters
        LPAREN("("), RPAREN(")"), LBRACKET("["), RBRACKET("]"),
        COLON(":"), COMMA(","), DOT("."),
        // Structural
        NEWLINE("NEWLINE"), INDENT("INDENT"), DEDENT("DEDENT"), EOF("EOF");

        final String text;
        TT(String text) { this.text = text; }
    }

    static final Map<String, TT> KEYWORDS = Map.ofEntries(
            Map.entry("if", TT.IF), Map.entry("elif", TT.ELIF), Map.entry("else", TT.ELSE),
            Map.entry("while", TT.WHILE), Map.entry("for", TT.FOR), Map.entry("in", TT.IN),
            Map.entry("def", TT.DEF), Map.entry("return", TT.RETURN),
            Map.entry("and", TT.AND), Map.entry("or", TT.OR), Map.entry("not", TT.NOT),
            Map.entry("True", TT.TRUE), Map.entry("False", TT.FALSE), Map.entry("None", TT.NONE));

    record Token(TT type, Object value, int line, int col) {
        @Override
        public String toString() {
            return "Token(" + type.name() + ", " + pyRepr(value) + ", " + line + ":" + col + ")";
        }
    }

    // ══════════════════════════════════════════════════════════════════════
    // §3  LEXER
    // ══════════════════════════════════════════════════════════════════════

    static final class Lexer {
        private static final Map<Character, String> ESCAPES = Map.of(
                'n', "\n", 't', "\t", 'r', "\r", '\\', "\\", '\'', "'", '"', "\"",
                '0', "\0", 'a', "\007", 'b', "\b");

        private final String source;
        private int pos = 0, line = 1, col = 1;
        private final List<Token> tokens = new ArrayList<>();
        private final List<Integer> indentStack = new ArrayList<>(List.of(0));
        private boolean atLineStart = true;
        private int parenDepth = 0;

        Lexer(String source) { this.source = source; }

        List<Token> tokenize() {
            while (pos < source.length()) nextToken();
            closeAllIndents();
            if (!tokens.isEmpty()) {
                TT last = tokens.get(tokens.size() - 1).type();
                if (last != TT.NEWLINE && last != TT.DEDENT)
                    tokens.add(new Token(TT.NEWLINE, "\n", line, col));
            }
            tokens.add(new Token(TT.EOF, null, line, col));
            return tokens;
        }

        // ── character helpers ──
        private char cur() { return pos < source.length() ? source.charAt(pos) : '\0'; }

        private char peek(int n) {
            int i = pos + n;
            return i < source.length() ? source.charAt(i) : '\0';
        }

        private char advance() {
            if (pos >= source.length()) return '\0';
            char ch = source.charAt(pos++);
            if (ch == '\n') { line++; col = 1; } else col++;
            return ch;
        }

        private boolean match(char c) {
            if (cur() == c) { advance(); return true; }
            return false;
        }

        private LexerError err(String msg) { return new LexerError(msg, line); }

        private void emit(TT tt, int ln, int cl) { tokens.add(new Token(tt, tt.text, ln, cl)); }

        private void closeAllIndents() {
            while (indentStack.size() > 1) {
                indentStack.remove(indentStack.size() - 1);
                tokens.add(new Token(TT.DEDENT, null, line, col));
            }
        }

        // ── main dispatch ──
        private void nextToken() {
            if (atLineStart && parenDepth == 0) { handleIndentation(); return; }

            char ch = cur();
            if (ch == ' ' || ch == '\t' || ch == '\r') { advance(); return; }
            if (ch == '\n') {
                int ln = line, cl = col;
                advance();
                if (parenDepth == 0) {
                    tokens.add(new Token(TT.NEWLINE, "\n", ln, cl));
                    atLineStart = true;
                }
                return;
            }
            if (ch == '#') {
                while (cur() != '\n' && cur() != '\0') advance();
                return;
            }
            if (ch == '"' || ch == '\'') { readString(); return; }
            if (Character.isDigit(ch)) { readNumber(); return; }
            if (Character.isLetter(ch) || ch == '_') { readName(); return; }
            readOperator();
        }

        // ── indentation ──
        private void handleIndentation() {
            int indent = 0;
            while (cur() == ' ' || cur() == '\t') {
                indent = cur() == '\t' ? (indent / 8 + 1) * 8 : indent + 1;
                advance();
            }
            if (pos >= source.length()) return;

            char ch = cur();
            // blank or comment-only line: skip entirely (also handles CRLF)
            if (ch == '\n' || ch == '\r' || ch == '#') {
                if (ch == '#') while (cur() != '\n' && cur() != '\0') advance();
                if (cur() == '\r') advance();
                if (cur() == '\n') advance();
                return;
            }

            atLineStart = false;
            int current = indentStack.get(indentStack.size() - 1);
            if (indent > current) {
                indentStack.add(indent);
                tokens.add(new Token(TT.INDENT, indent, line, 1));
            } else if (indent < current) {
                while (indentStack.size() > 1 && indentStack.get(indentStack.size() - 1) > indent) {
                    indentStack.remove(indentStack.size() - 1);
                    tokens.add(new Token(TT.DEDENT, indent, line, 1));
                }
                if (indentStack.get(indentStack.size() - 1) != indent)
                    throw err("IndentationError: unindent does not match any outer indentation level");
            }
        }

        // ── strings ──
        private void readString() {
            int ln = line, cl = col;
            char q = advance();
            StringBuilder buf = new StringBuilder();

            if (cur() == q && peek(1) == q) { // triple-quoted
                advance();
                advance();
                while (true) {
                    char ch = cur();
                    if (ch == '\0') throw err("SyntaxError: EOF in triple-quoted string");
                    if (ch == q && peek(1) == q && peek(2) == q) {
                        advance(); advance(); advance();
                        break;
                    }
                    if (ch == '\\') {
                        advance();
                        buf.append(ESCAPES.getOrDefault(advance(), ""));
                    } else {
                        buf.append(advance());
                    }
                }
                tokens.add(new Token(TT.STRING, buf.toString(), ln, cl));
                return;
            }

            while (true) { // single-quoted
                char ch = cur();
                if (ch == '\0') throw err("SyntaxError: unterminated string");
                if (ch == '\n') throw err("SyntaxError: EOL in string");
                if (ch == q) { advance(); break; }
                if (ch == '\\') {
                    advance();
                    buf.append(ESCAPES.getOrDefault(advance(), ""));
                } else {
                    buf.append(advance());
                }
            }
            tokens.add(new Token(TT.STRING, buf.toString(), ln, cl));
        }

        // ── numbers ──
        private void readNumber() {
            int ln = line, cl = col;
            StringBuilder digits = new StringBuilder();
            boolean isFloat = false;
            while (Character.isDigit(cur())) digits.append(advance());
            if (cur() == '.' && Character.isDigit(peek(1))) {
                isFloat = true;
                digits.append(advance());
                while (Character.isDigit(cur())) digits.append(advance());
            }
            if (cur() == 'e' || cur() == 'E') {
                isFloat = true;
                digits.append(advance());
                if (cur() == '+' || cur() == '-') digits.append(advance());
                if (!Character.isDigit(cur())) throw err("SyntaxError: invalid numeric literal");
                while (Character.isDigit(cur())) digits.append(advance());
            }
            String text = digits.toString();
            try {
                if (isFloat) tokens.add(new Token(TT.FLOAT, Double.parseDouble(text), ln, cl));
                else tokens.add(new Token(TT.INTEGER, Long.parseLong(text), ln, cl));
            } catch (NumberFormatException e) {
                throw err("SyntaxError: numeric literal out of range");
            }
        }

        // ── names / keywords ──
        private void readName() {
            int ln = line, cl = col;
            StringBuilder buf = new StringBuilder();
            while (Character.isLetterOrDigit(cur()) || cur() == '_') buf.append(advance());
            String name = buf.toString();
            tokens.add(new Token(KEYWORDS.getOrDefault(name, TT.NAME), name, ln, cl));
        }

        // ── operators ──
        private void readOperator() {
            int ln = line, cl = col;
            char ch = advance();
            switch (ch) {
                case '+' -> emit(match('=') ? TT.PLUSEQUAL : TT.PLUS, ln, cl);
                case '-' -> emit(match('=') ? TT.MINEQUAL : TT.MINUS, ln, cl);
                case '*' -> {
                    if (match('*')) emit(TT.DOUBLESTAR, ln, cl);
                    else if (match('=')) emit(TT.STAREQUAL, ln, cl);
                    else emit(TT.STAR, ln, cl);
                }
                case '/' -> {
                    if (match('/')) emit(TT.DOUBLESLASH, ln, cl);
                    else if (match('=')) emit(TT.SLASHEQUAL, ln, cl);
                    else emit(TT.SLASH, ln, cl);
                }
                case '=' -> emit(match('=') ? TT.EQEQUAL : TT.EQUAL, ln, cl);
                case '!' -> {
                    if (match('=')) emit(TT.NOTEQUAL, ln, cl);
                    else throw err("SyntaxError: '!' must be followed by '='");
                }
                case '<' -> emit(match('=') ? TT.LESSEQUAL : TT.LESS, ln, cl);
                case '>' -> emit(match('=') ? TT.GREATEREQUAL : TT.GREATER, ln, cl);
                case '%' -> emit(TT.PERCENT, ln, cl);
                case '(' -> { parenDepth++; emit(TT.LPAREN, ln, cl); }
                case ')' -> { parenDepth = Math.max(0, parenDepth - 1); emit(TT.RPAREN, ln, cl); }
                case '[' -> { parenDepth++; emit(TT.LBRACKET, ln, cl); }
                case ']' -> { parenDepth = Math.max(0, parenDepth - 1); emit(TT.RBRACKET, ln, cl); }
                case ':' -> emit(TT.COLON, ln, cl);
                case ',' -> emit(TT.COMMA, ln, cl);
                case '.' -> emit(TT.DOT, ln, cl);
                default -> throw err("SyntaxError: unexpected character " + pyRepr(String.valueOf(ch)));
            }
        }
    }

    // ══════════════════════════════════════════════════════════════════════
    // §4  AST NODES
    // ══════════════════════════════════════════════════════════════════════

    sealed interface Node {
        int line();
    }

    // Root
    record Program(List<Node> body, int line) implements Node {}

    // Literals
    record IntLiteral(long value, int line) implements Node {}
    record FloatLiteral(double value, int line) implements Node {}
    record StringLiteral(String value, int line) implements Node {}
    record BoolLiteral(boolean value, int line) implements Node {}
    record NoneLiteral(int line) implements Node {}

    // Expressions
    record Name(String id, int line) implements Node {}
    record ListLiteral(List<Node> elts, int line) implements Node {}
    record Subscript(Node value, Node index, int line) implements Node {}
    record BinOp(Node left, String op, Node right, int line) implements Node {}
    record UnaryOp(String op, Node operand, int line) implements Node {}
    record Compare(Node left, String op, Node right, int line) implements Node {}
    record BoolOp(String op, List<Node> values, int line) implements Node {}
    record Call(Node func, List<Node> args, int line) implements Node {}
    record MethodCall(Node obj, String method, List<Node> args, int line) implements Node {}

    // Statements
    record Assign(String target, Node value, int line) implements Node {}
    record AugAssign(String target, String op, Node value, int line) implements Node {}
    record ExprStmt(Node expr, int line) implements Node {}
    record Return(Node value, int line) implements Node {}
    record If(Node test, List<Node> body, List<Node> orelse, int line) implements Node {}
    record While(Node test, List<Node> body, int line) implements Node {}
    record For(String target, Node iter, List<Node> body, int line) implements Node {}
    record FuncDef(String name, List<String> params, List<Node> body, int line) implements Node {}

    // ══════════════════════════════════════════════════════════════════════
    // §5  PARSER  (recursive descent)
    //
    //  program      := stmt* EOF
    //  stmt         := func_def | if_stmt | while_stmt | for_stmt | simple_stmt
    //  simple_stmt  := (assign | aug_assign | return | expr_stmt) NEWLINE
    //  func_def     := 'def' NAME '(' params? ')' ':' block
    //  if_stmt      := 'if' expr ':' block elif_else?
    //  while_stmt   := 'while' expr ':' block
    //  for_stmt     := 'for' NAME 'in' expr ':' block
    //  block        := NEWLINE INDENT stmt+ DEDENT
    //  expr         := or_expr
    //  or_expr      := and_expr ('or' and_expr)*
    //  and_expr     := not_expr ('and' not_expr)*
    //  not_expr     := 'not' not_expr | comparison
    //  comparison   := sum (comp_op sum)*
    //  sum          := term (('+'|'-') term)*
    //  term         := factor (('*'|'/'|'//'|'%') factor)*
    //  factor       := ('+'|'-') factor | power
    //  power        := primary ['**' factor]
    //  primary      := atom (call_args | subscript | method_call)*
    //  atom         := INT | FLOAT | STR | True | False | None
    //                | NAME | '[' args? ']' | '(' expr ')'
    // ══════════════════════════════════════════════════════════════════════

    static final class Parser {
        private final List<Token> tokens;
        private int pos = 0;

        Parser(List<Token> tokens) { this.tokens = tokens; }

        // ── cursor ──
        private Token cur() { return tokens.get(Math.min(pos, tokens.size() - 1)); }
        private Token peek(int n) { return tokens.get(Math.min(pos + n, tokens.size() - 1)); }
        private Token prev() { return tokens.get(Math.max(pos - 1, 0)); }

        private Token advance() {
            Token t = cur();
            if (pos < tokens.size() - 1) pos++;
            return t;
        }

        private boolean check(TT... types) {
            TT t = cur().type();
            for (TT x : types) if (t == x) return true;
            return false;
        }

        private boolean match(TT... types) {
            if (check(types)) { advance(); return true; }
            return false;
        }

        private Token expect(TT tt) { return expect(tt, ""); }

        private Token expect(TT tt, String msg) {
            if (!check(tt)) {
                Token got = cur();
                String desc = msg.isEmpty()
                        ? "expected '" + tt.text + "', got '" + got.type().text + "' (" + pyRepr(got.value()) + ")"
                        : msg;
                throw new ParseError("SyntaxError: " + desc, got.line());
            }
            return advance();
        }

        private ParseError err(String msg) { return new ParseError("SyntaxError: " + msg, cur().line()); }

        private void skipNewlines() { while (check(TT.NEWLINE)) advance(); }

        // ── entry ──
        Program parse() {
            List<Node> stmts = stmtList();
            expect(TT.EOF, "expected end of file");
            return new Program(stmts, 1);
        }

        private List<Node> stmtList() {
            List<Node> stmts = new ArrayList<>();
            while (true) {
                skipNewlines();
                if (check(TT.EOF, TT.DEDENT)) break;
                stmts.add(stmt());
            }
            return stmts;
        }

        private Node stmt() {
            skipNewlines();
            if (match(TT.DEF)) return funcDef();
            if (match(TT.IF)) return ifStmt();
            if (match(TT.WHILE)) return whileStmt();
            if (match(TT.FOR)) return forStmt();
            return simpleStmt();
        }

        // ── simple statements ──
        private Node simpleStmt() {
            Node node;
            if (check(TT.RETURN)) {
                advance();
                node = returnStmt();
            } else if (check(TT.NAME) && peek(1).type() == TT.EQUAL) {
                node = assign();
            } else if (check(TT.NAME) && (peek(1).type() == TT.PLUSEQUAL || peek(1).type() == TT.MINEQUAL
                    || peek(1).type() == TT.STAREQUAL || peek(1).type() == TT.SLASHEQUAL)) {
                node = augAssign();
            } else {
                Node e = expr();
                node = new ExprStmt(e, cur().line());
            }

            if (check(TT.NEWLINE)) advance();
            else if (!check(TT.EOF, TT.DEDENT))
                throw err("expected newline after statement, got " + pyRepr(cur().type().text));
            return node;
        }

        private Assign assign() {
            Token t = expect(TT.NAME);
            expect(TT.EQUAL);
            return new Assign((String) t.value(), expr(), t.line());
        }

        private AugAssign augAssign() {
            Token t = advance();
            Token op = advance();
            return new AugAssign((String) t.value(), op.type().text, expr(), t.line());
        }

        private Return returnStmt() {
            int ln = prev().line();
            if (check(TT.NEWLINE, TT.EOF, TT.DEDENT)) return new Return(null, ln);
            return new Return(expr(), ln);
        }

        // ── compound statements ──
        private FuncDef funcDef() {
            int ln = prev().line();
            Token name = expect(TT.NAME, "expected function name");
            expect(TT.LPAREN, "expected '(' after function name");
            List<String> params = new ArrayList<>();
            if (check(TT.NAME)) {
                params.add((String) advance().value());
                while (match(TT.COMMA)) {
                    if (!check(TT.NAME)) throw err("expected parameter name");
                    params.add((String) advance().value());
                }
            }
            expect(TT.RPAREN, "expected ')'");
            expect(TT.COLON, "expected ':' after function signature");
            return new FuncDef((String) name.value(), params, block(), ln);
        }

        private If ifStmt() {
            int ln = prev().line();
            Node test = expr();
            expect(TT.COLON, "expected ':' after if-condition");
            List<Node> body = block();
            List<Node> orelse = elifOrElse();
            return new If(test, body, orelse, ln);
        }

        private List<Node> elifOrElse() {
            skipNewlines();
            if (match(TT.ELIF)) {
                int ln = prev().line();
                Node test = expr();
                expect(TT.COLON, "expected ':' after elif");
                List<Node> body = block();
                List<Node> orelse = elifOrElse();
                return List.of(new If(test, body, orelse, ln));
            }
            if (match(TT.ELSE)) {
                expect(TT.COLON, "expected ':' after else");
                return block();
            }
            return List.of();
        }

        private While whileStmt() {
            int ln = prev().line();
            Node test = expr();
            expect(TT.COLON, "expected ':' after while");
            return new While(test, block(), ln);
        }

        private For forStmt() {
            int ln = prev().line();
            Token var = expect(TT.NAME, "expected loop variable");
            expect(TT.IN, "expected 'in'");
            Node itr = expr();
            expect(TT.COLON, "expected ':' after for-clause");
            return new For((String) var.value(), itr, block(), ln);
        }

        private List<Node> block() {
            expect(TT.NEWLINE, "expected newline before block");
            expect(TT.INDENT, "expected indented block");
            List<Node> stmts = stmtList();
            if (stmts.isEmpty()) throw err("empty block");
            expect(TT.DEDENT, "expected dedent after block");
            return stmts;
        }

        // ── expressions (precedence chain) ──
        Node expr() { return orExpr(); }

        private Node orExpr() {
            Node node = andExpr();
            if (check(TT.OR)) {
                List<Node> vals = new ArrayList<>(List.of(node));
                while (match(TT.OR)) vals.add(andExpr());
                return new BoolOp("or", vals, node.line());
            }
            return node;
        }

        private Node andExpr() {
            Node node = notExpr();
            if (check(TT.AND)) {
                List<Node> vals = new ArrayList<>(List.of(node));
                while (match(TT.AND)) vals.add(notExpr());
                return new BoolOp("and", vals, node.line());
            }
            return node;
        }

        private Node notExpr() {
            if (match(TT.NOT)) {
                int ln = prev().line();
                return new UnaryOp("not", notExpr(), ln);
            }
            return comparison();
        }

        private Node comparison() {
            Node node = sum();
            while (check(TT.EQEQUAL, TT.NOTEQUAL, TT.LESS, TT.LESSEQUAL, TT.GREATER, TT.GREATEREQUAL)) {
                String op = advance().type().text;
                Node right = sum();
                node = new Compare(node, op, right, node.line());
            }
            return node;
        }

        private Node sum() {
            Node node = term();
            while (check(TT.PLUS, TT.MINUS)) {
                String op = advance().type().text;
                Node right = term();
                node = new BinOp(node, op, right, node.line());
            }
            return node;
        }

        private Node term() {
            Node node = factor();
            while (check(TT.STAR, TT.SLASH, TT.DOUBLESLASH, TT.PERCENT)) {
                String op = advance().type().text;
                Node right = factor();
                node = new BinOp(node, op, right, node.line());
            }
            return node;
        }

        private Node factor() {
            if (check(TT.PLUS, TT.MINUS)) {
                Token op = advance();
                return new UnaryOp(op.type().text, factor(), op.line());
            }
            return power();
        }

        private Node power() {
            Node base = primary();
            if (match(TT.DOUBLESTAR)) {
                int ln = prev().line();
                return new BinOp(base, "**", factor(), ln);
            }
            return base;
        }

        private Node primary() {
            Node node = atom();
            while (true) {
                if (check(TT.LPAREN)) {
                    advance();
                    int ln = prev().line();
                    List<Node> args = callArgs();
                    expect(TT.RPAREN, "expected ')' after arguments");
                    node = new Call(node, args, ln);
                } else if (check(TT.LBRACKET)) {
                    advance();
                    int ln = prev().line();
                    Node idx = expr();
                    expect(TT.RBRACKET, "expected ']' after index");
                    node = new Subscript(node, idx, ln);
                } else if (check(TT.DOT)) {
                    advance();
                    int ln = prev().line();
                    Token nameTok = expect(TT.NAME, "expected attribute/method name after '.'");
                    if (!check(TT.LPAREN))
                        throw err("attribute access without a call is not supported: '." + nameTok.value() + "'");
                    advance(); // '('
                    List<Node> args = callArgs();
                    expect(TT.RPAREN, "expected ')' after method arguments");
                    node = new MethodCall(node, (String) nameTok.value(), args, ln);
                } else {
                    break;
                }
            }
            return node;
        }

        private List<Node> callArgs() {
            List<Node> args = new ArrayList<>();
            if (!check(TT.RPAREN)) {
                args.add(expr());
                while (match(TT.COMMA)) {
                    if (check(TT.RPAREN)) break;
                    args.add(expr());
                }
            }
            return args;
        }

        private Node atom() {
            Token tok = cur();
            if (match(TT.INTEGER)) return new IntLiteral((Long) tok.value(), tok.line());
            if (match(TT.FLOAT)) return new FloatLiteral((Double) tok.value(), tok.line());
            if (match(TT.STRING)) return new StringLiteral((String) tok.value(), tok.line());
            if (match(TT.TRUE)) return new BoolLiteral(true, tok.line());
            if (match(TT.FALSE)) return new BoolLiteral(false, tok.line());
            if (match(TT.NONE)) return new NoneLiteral(tok.line());
            if (match(TT.NAME)) return new Name((String) tok.value(), tok.line());
            if (match(TT.LBRACKET)) {
                List<Node> elts = new ArrayList<>();
                if (!check(TT.RBRACKET)) {
                    elts.add(expr());
                    while (match(TT.COMMA)) {
                        if (check(TT.RBRACKET)) break;
                        elts.add(expr());
                    }
                }
                expect(TT.RBRACKET, "expected ']'");
                return new ListLiteral(elts, tok.line());
            }
            if (match(TT.LPAREN)) {
                Node node = expr();
                expect(TT.RPAREN, "expected ')'");
                return node;
            }
            throw err("unexpected token " + pyRepr(tok.type().text) + " (" + pyRepr(tok.value()) + ")");
        }
    }

    // ══════════════════════════════════════════════════════════════════════
    // §6  ENVIRONMENT  (scoped variable store)
    // ══════════════════════════════════════════════════════════════════════

    static final class Environment {
        final Map<String, Object> vars = new HashMap<>(); // containsKey needed: None is null
        final Environment parent;

        Environment(Environment parent) { this.parent = parent; }

        Object get(String name, int line) {
            for (Environment e = this; e != null; e = e.parent)
                if (e.vars.containsKey(name)) return e.vars.get(name);
            throw rt("NameError: name '" + name + "' is not defined", line);
        }

        /** Always sets in the current scope. */
        void set(String name, Object value) { vars.put(name, value); }

        /** Assign to the nearest scope that already owns name; else current scope. */
        void assign(String name, Object value) {
            for (Environment e = this; e != null; e = e.parent) {
                if (e.vars.containsKey(name)) { e.vars.put(name, value); return; }
            }
            vars.put(name, value);
        }
    }

    // ══════════════════════════════════════════════════════════════════════
    // §7  VALUES & BUILTINS
    // ══════════════════════════════════════════════════════════════════════

    static final class PyFunction {
        final FuncDef node;
        final Environment closure;

        PyFunction(FuncDef node, Environment closure) { this.node = node; this.closure = closure; }

        @Override
        public String toString() { return "<function " + node.name() + ">"; }
    }

    @FunctionalInterface
    interface Fn { Object apply(List<Object> args); }

    record Builtin(String name, Fn fn) {
        @Override
        public String toString() { return "<built-in function " + name + ">"; }
    }

    static final BufferedReader STDIN =
            new BufferedReader(new InputStreamReader(System.in, StandardCharsets.UTF_8));

    // ── value helpers ──

    /** int, float and bool all count as numbers (bool is an int subclass in Python). */
    static boolean isNum(Object v) { return v instanceof Long || v instanceof Double || v instanceof Boolean; }
    static boolean isRealNum(Object v) { return v instanceof Long || v instanceof Double; }

    static long toLong(Object v) {
        if (v instanceof Boolean b) return b ? 1 : 0;
        if (v instanceof Long l) return l;
        return (long) (double) (Double) v;
    }

    static double toDouble(Object v) {
        if (v instanceof Boolean b) return b ? 1.0 : 0.0;
        if (v instanceof Long l) return (double) l;
        return (Double) v;
    }

    @SuppressWarnings("unchecked")
    static List<Object> asList(Object o) { return (List<Object>) o; }

    static List<String> codePoints(String s) {
        List<String> out = new ArrayList<>();
        s.codePoints().forEach(cp -> out.add(new String(Character.toChars(cp))));
        return out;
    }

    /** Python-style float formatting: 3.0, 1e+16, 1.5e-05, inf, nan. */
    static String fmtDouble(double d) {
        if (Double.isNaN(d)) return "nan";
        if (Double.isInfinite(d)) return d > 0 ? "inf" : "-inf";
        if (d == 0) return (1 / d < 0) ? "-0.0" : "0.0";
        BigDecimal bd = new BigDecimal(Double.toString(d)).stripTrailingZeros();
        double abs = Math.abs(d);
        if (abs >= 1e-4 && abs < 1e16) {
            String s = bd.toPlainString();
            return s.contains(".") ? s : s + ".0";
        }
        String digits = bd.unscaledValue().abs().toString();
        int exp = digits.length() - bd.scale() - 1;
        String mant = digits.length() > 1 ? digits.charAt(0) + "." + digits.substring(1) : digits;
        return (d < 0 ? "-" : "") + mant + "e" + (exp < 0 ? "-" : "+") + String.format("%02d", Math.abs(exp));
    }

    static String epStr(Object v) {
        if (v == null) return "None";
        if (v instanceof Boolean b) return b ? "True" : "False";
        if (v instanceof Double d) return fmtDouble(d);
        if (v instanceof List<?> l) {
            StringJoiner sj = new StringJoiner(", ", "[", "]");
            for (Object x : l) sj.add(epStr(x));
            return sj.toString();
        }
        return v.toString();
    }

    /** repr()-style rendering (quotes around strings). */
    static String pyRepr(Object v) {
        if (v instanceof String s) {
            char q = (s.indexOf('\'') >= 0 && s.indexOf('"') < 0) ? '"' : '\'';
            StringBuilder sb = new StringBuilder().append(q);
            for (char c : s.toCharArray()) {
                switch (c) {
                    case '\\' -> sb.append("\\\\");
                    case '\n' -> sb.append("\\n");
                    case '\t' -> sb.append("\\t");
                    case '\r' -> sb.append("\\r");
                    default -> {
                        if (c == q) sb.append('\\');
                        sb.append(c);
                    }
                }
            }
            return sb.append(q).toString();
        }
        if (v instanceof List<?> l) {
            StringJoiner sj = new StringJoiner(", ", "[", "]");
            for (Object x : l) sj.add(pyRepr(x));
            return sj.toString();
        }
        return epStr(v);
    }

    static boolean epBool(Object v) {
        if (v == null) return false;
        if (v instanceof Boolean b) return b;
        if (v instanceof Long l) return l != 0;
        if (v instanceof Double d) return d != 0.0;
        if (v instanceof String s) return !s.isEmpty();
        if (v instanceof List<?> l) return !l.isEmpty();
        return true;
    }

    static String typeName(Object v) {
        if (v == null) return "NoneType";
        if (v instanceof Boolean) return "bool";
        if (v instanceof Long) return "int";
        if (v instanceof Double) return "float";
        if (v instanceof String) return "str";
        if (v instanceof List) return "list";
        if (v instanceof PyFunction || v instanceof Builtin) return "function";
        return v.getClass().getSimpleName();
    }

    static boolean pyEquals(Object a, Object b) {
        if (a == null || b == null) return a == b;
        if (isNum(a) && isNum(b)) {
            if (a instanceof Double || b instanceof Double) return toDouble(a) == toDouble(b);
            return toLong(a) == toLong(b);
        }
        if (a instanceof String x && b instanceof String y) return x.equals(y);
        if (a instanceof List<?> x && b instanceof List<?> y) {
            if (x.size() != y.size()) return false;
            for (int i = 0; i < x.size(); i++) if (!pyEquals(x.get(i), y.get(i))) return false;
            return true;
        }
        return a == b;
    }

    /** <, <=, >, >= on numbers or strings. */
    static boolean ordered(String op, Object l, Object r, int line) {
        boolean strs = l instanceof String && r instanceof String;
        if (!strs && !(isNum(l) && isNum(r)))
            throw rt("TypeError: '" + op + "' not supported between '" + typeName(l)
                    + "' and '" + typeName(r) + "'", line);
        if (strs) {
            int c = ((String) l).compareTo((String) r);
            return switch (op) {
                case "<" -> c < 0;
                case "<=" -> c <= 0;
                case ">" -> c > 0;
                default -> c >= 0;
            };
        }
        if (!(l instanceof Double) && !(r instanceof Double)) {
            long x = toLong(l), y = toLong(r);
            return switch (op) {
                case "<" -> x < y;
                case "<=" -> x <= y;
                case ">" -> x > y;
                default -> x >= y;
            };
        }
        double x = toDouble(l), y = toDouble(r);
        return switch (op) {
            case "<" -> x < y;
            case "<=" -> x <= y;
            case ">" -> x > y;
            default -> x >= y;
        };
    }

    static final Pattern DEC = Pattern.compile("[+-]?(\\d+\\.?\\d*|\\.\\d+)([eE][+-]?\\d+)?");
    static final Pattern SPECIAL = Pattern.compile("[+-]?(inf|infinity|nan)", Pattern.CASE_INSENSITIVE);
    static final Pattern INT_RE = Pattern.compile("[+-]?\\d+");

    static final Map<String, Builtin> BUILTINS = new LinkedHashMap<>();

    static void reg(String name, Fn fn) { BUILTINS.put(name, new Builtin(name, fn)); }

    static void need(List<Object> a, int n, String msg) {
        if (a.size() != n) throw rt("TypeError: " + msg);
    }

    static {
        reg("print", a -> {
            StringJoiner sj = new StringJoiner(" ");
            for (Object x : a) sj.add(epStr(x));
            System.out.println(sj);
            return null;
        });

        reg("len", a -> {
            need(a, 1, "len() takes exactly 1 argument");
            Object v = a.get(0);
            if (v instanceof String s) return (long) s.codePointCount(0, s.length());
            if (v instanceof List<?> l) return (long) l.size();
            throw rt("TypeError: object of type '" + typeName(v) + "' has no len()");
        });

        reg("range", a -> {
            if (a.isEmpty() || a.size() > 3) throw rt("TypeError: range() takes 1-3 arguments");
            long[] n = new long[a.size()];
            for (int i = 0; i < n.length; i++) {
                if (!isNum(a.get(i))) throw rt("TypeError: range() arguments must be integers");
                n[i] = toLong(a.get(i));
            }
            long start = 0, stop, step = 1;
            if (n.length == 1) stop = n[0];
            else { start = n[0]; stop = n[1]; if (n.length == 3) step = n[2]; }
            if (step == 0) throw rt("ValueError: range() arg 3 must not be zero");
            List<Object> out = new ArrayList<>();
            if (step > 0) for (long i = start; i < stop; i += step) out.add(i);
            else for (long i = start; i > stop; i += step) out.add(i);
            return out;
        });

        reg("int", a -> {
            need(a, 1, "int() takes 1 argument");
            Object v = a.get(0);
            if (v instanceof Boolean || v instanceof Long) return toLong(v);
            if (v instanceof Double d) {
                if (d.isNaN() || d.isInfinite()) throw rt("ValueError: cannot convert float " + fmtDouble(d) + " to integer");
                return (long) (double) d;
            }
            if (v instanceof String s) {
                String t = s.strip();
                if (INT_RE.matcher(t).matches()) {
                    try { return Long.parseLong(t.startsWith("+") ? t.substring(1) : t); }
                    catch (NumberFormatException e) { throw rt("OverflowError: integer too large for the Java port"); }
                }
                throw rt("ValueError: invalid literal for int(): " + pyRepr(s));
            }
            throw rt("TypeError: int() argument must be a string or number, not '" + typeName(v) + "'");
        });

        reg("float", a -> {
            need(a, 1, "float() takes 1 argument");
            Object v = a.get(0);
            if (isNum(v)) return toDouble(v);
            if (v instanceof String s) {
                String t = s.strip();
                if (DEC.matcher(t).matches()) return Double.parseDouble(t);
                if (SPECIAL.matcher(t).matches()) {
                    boolean neg = t.startsWith("-");
                    if (t.toLowerCase().endsWith("nan")) return Double.NaN;
                    return neg ? Double.NEGATIVE_INFINITY : Double.POSITIVE_INFINITY;
                }
                throw rt("ValueError: could not convert string to float: " + pyRepr(s));
            }
            throw rt("TypeError: float() argument must be a string or number, not '" + typeName(v) + "'");
        });

        reg("str", a -> {
            need(a, 1, "str() takes 1 argument");
            return epStr(a.get(0));
        });

        reg("bool", a -> {
            need(a, 1, "bool() takes 1 argument");
            return epBool(a.get(0));
        });

        reg("input", a -> {
            System.out.print(a.isEmpty() ? "" : epStr(a.get(0)));
            System.out.flush();
            try {
                String s = STDIN.readLine();
                if (s == null) throw rt("EOFError: EOF when reading a line");
                return s;
            } catch (IOException e) {
                throw rt("IOError: " + e.getMessage());
            }
        });

        reg("abs", a -> {
            need(a, 1, "abs() takes 1 argument");
            Object v = a.get(0);
            if (v instanceof Long l) return Math.abs(l);
            if (v instanceof Double d) return Math.abs(d);
            throw rt("TypeError: bad operand type for abs(): '" + typeName(v) + "'");
        });

        reg("max", a -> extreme("max", ">", a));
        reg("min", a -> extreme("min", "<", a));

        reg("type", a -> {
            need(a, 1, "type() takes 1 argument");
            return "<class '" + typeName(a.get(0)) + "'>";
        });

        // append(list, value) - function syntax, not method syntax
        reg("append", a -> {
            need(a, 2, "append() takes 2 arguments");
            if (!(a.get(0) instanceof List)) throw rt("TypeError: first argument must be a list");
            asList(a.get(0)).add(a.get(1));
            return null;
        });

        reg("pop", a -> {
            if (a.size() != 1 && a.size() != 2) throw rt("TypeError: pop() takes 1 or 2 arguments");
            if (!(a.get(0) instanceof List)) throw rt("TypeError: first argument must be a list");
            List<Object> lst = asList(a.get(0));
            if (lst.isEmpty()) throw rt("IndexError: pop from empty list");
            long idx = a.size() == 2 ? toLong(a.get(1)) : -1;
            if (idx < 0) idx += lst.size();
            if (idx < 0 || idx >= lst.size()) throw rt("IndexError: pop index out of range");
            return lst.remove((int) idx);
        });
    }

    private static Object extreme(String name, String op, List<Object> a) {
        if (a.isEmpty()) throw rt("TypeError: " + name + "() expected at least 1 argument");
        List<Object> items = (a.size() == 1 && a.get(0) instanceof List) ? asList(a.get(0)) : a;
        if (items.isEmpty()) throw rt("ValueError: " + name + "() arg is an empty sequence");
        Object best = items.get(0);
        for (int i = 1; i < items.size(); i++)
            if (ordered(op, items.get(i), best, 0)) best = items.get(i);
        return best;
    }

    // ══════════════════════════════════════════════════════════════════════
    // §8  INTERPRETER  (tree-walk)
    // ══════════════════════════════════════════════════════════════════════

    static final class Interpreter {
        final Environment globals = new Environment(null);

        Interpreter() {
            for (Map.Entry<String, Builtin> e : BUILTINS.entrySet()) globals.set(e.getKey(), e.getValue());
        }

        void run(Program program) {
            try {
                execStmts(program.body(), globals);
            } catch (ReturnSignal r) {
                throw rt("SyntaxError: 'return' outside function");
            } catch (StackOverflowError so) {
                throw rt("RecursionError: maximum recursion depth exceeded");
            }
        }

        /** Evaluate a single expression string. */
        Object evalExpr(String source) {
            Parser p = new Parser(new Lexer(source + "\n").tokenize());
            return eval(p.expr(), globals);
        }

        // ── statements ──
        private void execStmts(List<Node> stmts, Environment env) {
            for (Node s : stmts) exec(s, env);
        }

        private void exec(Node node, Environment env) {
            switch (node) {
                case FuncDef n -> env.set(n.name(), new PyFunction(n, env));
                case Assign n -> env.set(n.target(), eval(n.value(), env));
                case AugAssign n -> {
                    Object current = env.get(n.target(), n.line());
                    Object rhs = eval(n.value(), env);
                    env.assign(n.target(), applyBinop(n.op().substring(0, 1), current, rhs, n.line()));
                }
                case ExprStmt n -> eval(n.expr(), env);
                case Return n -> throw new ReturnSignal(n.value() != null ? eval(n.value(), env) : null);
                case If n -> {
                    if (epBool(eval(n.test(), env))) execStmts(n.body(), env);
                    else if (!n.orelse().isEmpty()) execStmts(n.orelse(), env);
                }
                case While n -> {
                    while (epBool(eval(n.test(), env))) execStmts(n.body(), env);
                }
                case For n -> {
                    Object it = eval(n.iter(), env);
                    if (it instanceof String s) {
                        for (String ch : codePoints(s)) {
                            env.set(n.target(), ch);
                            execStmts(n.body(), env);
                        }
                    } else if (it instanceof List<?>) {
                        List<Object> lst = asList(it);
                        for (int i = 0; i < lst.size(); i++) { // live iteration, like Python
                            env.set(n.target(), lst.get(i));
                            execStmts(n.body(), env);
                        }
                    } else {
                        throw rt("TypeError: '" + typeName(it) + "' object is not iterable", n.line());
                    }
                }
                default -> throw rt("InternalError: no exec handler for "
                        + node.getClass().getSimpleName(), node.line());
            }
        }

        // ── expressions ──
        private Object eval(Node node, Environment env) {
            return switch (node) {
                case IntLiteral n -> n.value();
                case FloatLiteral n -> n.value();
                case StringLiteral n -> n.value();
                case BoolLiteral n -> n.value();
                case NoneLiteral n -> null;
                case Name n -> env.get(n.id(), n.line());
                case ListLiteral n -> {
                    List<Object> out = new ArrayList<>();
                    for (Node e : n.elts()) out.add(eval(e, env));
                    yield out;
                }
                case Subscript n -> evalSubscript(n, env);
                case BinOp n -> applyBinop(n.op(), eval(n.left(), env), eval(n.right(), env), n.line());
                case UnaryOp n -> evalUnary(n, env);
                case Compare n -> evalCompare(n, env);
                case BoolOp n -> evalBoolOp(n, env);
                case MethodCall n -> evalMethodCall(n, env);
                case Call n -> evalCall(n, env);
                default -> throw rt("InternalError: no eval handler for "
                        + node.getClass().getSimpleName(), node.line());
            };
        }

        private Object evalSubscript(Subscript n, Environment env) {
            Object obj = eval(n.value(), env);
            Object idxv = eval(n.index(), env);
            if (!(obj instanceof List || obj instanceof String))
                throw rt("TypeError: '" + typeName(obj) + "' object is not subscriptable", n.line());
            if (!isNum(idxv))
                throw rt("TypeError: indices must be integers, not '" + typeName(idxv) + "'", n.line());
            long idx = toLong(idxv);
            if (obj instanceof String s) {
                List<String> cps = codePoints(s);
                int len = cps.size();
                if (idx < -len || idx >= len)
                    throw rt("IndexError: index " + idx + " out of range (length " + len + ")", n.line());
                return cps.get((int) (idx < 0 ? idx + len : idx));
            }
            List<Object> lst = asList(obj);
            int len = lst.size();
            if (idx < -len || idx >= len)
                throw rt("IndexError: index " + idx + " out of range (length " + len + ")", n.line());
            return lst.get((int) (idx < 0 ? idx + len : idx));
        }

        private Object evalUnary(UnaryOp n, Environment env) {
            Object v = eval(n.operand(), env);
            switch (n.op()) {
                case "not":
                    return !epBool(v);
                case "-":
                    if (v instanceof Long l) return -l;
                    if (v instanceof Double d) return -d;
                    throw rt("TypeError: bad operand type for unary '-': '" + typeName(v) + "'", n.line());
                case "+":
                    if (isRealNum(v)) return v;
                    throw rt("TypeError: bad operand type for unary '+': '" + typeName(v) + "'", n.line());
                default:
                    throw rt("InternalError: unknown unary operator " + n.op(), n.line());
            }
        }

        private Object evalCompare(Compare n, Environment env) {
            Object left = eval(n.left(), env);
            Object right = eval(n.right(), env);
            return switch (n.op()) {
                case "==" -> pyEquals(left, right);
                case "!=" -> !pyEquals(left, right);
                default -> ordered(n.op(), left, right, n.line());
            };
        }

        private Object evalBoolOp(BoolOp n, Environment env) {
            boolean isAnd = n.op().equals("and");
            Object result = eval(n.values().get(0), env);
            for (int i = 1; i < n.values().size(); i++) {
                if (isAnd ? !epBool(result) : epBool(result)) return result; // short-circuit
                result = eval(n.values().get(i), env);
            }
            return result;
        }

        private Object evalMethodCall(MethodCall n, Environment env) {
            Object obj = eval(n.obj(), env);
            List<Object> args = new ArrayList<>();
            for (Node a : n.args()) args.add(eval(a, env));
            String m = n.method();

            if (obj instanceof String s) {
                if (m.equals("lower") || m.equals("upper")) {
                    if (!args.isEmpty()) throw rt("TypeError: " + m + "() takes no arguments", n.line());
                    return m.equals("lower") ? s.toLowerCase() : s.toUpperCase();
                }
                throw rt("AttributeError: 'str' object has no attribute '" + m + "'", n.line());
            }
            throw rt("AttributeError: '" + typeName(obj) + "' object has no attribute '" + m + "'", n.line());
        }

        private Object evalCall(Call n, Environment env) {
            Object callee = eval(n.func(), env);
            List<Object> args = new ArrayList<>();
            for (Node a : n.args()) args.add(eval(a, env));

            if (callee instanceof Builtin b) {
                try {
                    return b.fn().apply(args);
                } catch (PyRuntimeError e) {
                    // attach the call-site line to builtin errors that have none
                    if (e.line == 0) throw new PyRuntimeError(e.msg, n.line());
                    throw e;
                }
            }

            if (callee instanceof PyFunction f) {
                FuncDef fn = f.node;
                if (args.size() != fn.params().size())
                    throw rt("TypeError: " + fn.name() + "() takes " + fn.params().size()
                            + " argument(s) but " + args.size() + " given", n.line());
                Environment callEnv = new Environment(f.closure);
                for (int i = 0; i < args.size(); i++) callEnv.set(fn.params().get(i), args.get(i));
                try {
                    execStmts(fn.body(), callEnv);
                } catch (ReturnSignal ret) {
                    return ret.value;
                }
                return null;
            }

            throw rt("TypeError: '" + typeName(callee) + "' object is not callable", n.line());
        }
    }

    // ── arithmetic ──

    static Object applyBinop(String op, Object l, Object r, int line) {
        // strings
        if (op.equals("+") && l instanceof String a && r instanceof String b) return a + b;
        if (op.equals("*") && l instanceof String s && isNum(r)) return repeatStr(s, toLong(r), line);
        if (op.equals("*") && isNum(l) && r instanceof String s2) return repeatStr(s2, toLong(l), line);
        // lists
        if (op.equals("+") && l instanceof List<?> && r instanceof List<?>) {
            List<Object> out = new ArrayList<>(asList(l));
            out.addAll(asList(r));
            return out;
        }
        if (op.equals("*") && l instanceof List<?> && isNum(r)) return repeatList(asList(l), toLong(r), line);

        // numbers
        if (isNum(l) && isNum(r)) {
            if (!(l instanceof Double) && !(r instanceof Double)) {
                long x = toLong(l), y = toLong(r);
                try {
                    return switch (op) {
                        case "+" -> Math.addExact(x, y);
                        case "-" -> Math.subtractExact(x, y);
                        case "*" -> Math.multiplyExact(x, y);
                        case "**" -> intPow(x, y, line);
                        case "%" -> {
                            if (y == 0) throw rt("ZeroDivisionError: modulo by zero", line);
                            yield Math.floorMod(x, y);
                        }
                        case "/" -> {
                            if (y == 0) throw rt("ZeroDivisionError: division by zero", line);
                            yield (double) x / y;
                        }
                        case "//" -> {
                            if (y == 0) throw rt("ZeroDivisionError: integer division by zero", line);
                            yield Math.floorDiv(x, y);
                        }
                        default -> throw rt("InternalError: unknown operator " + op, line);
                    };
                } catch (ArithmeticException e) {
                    throw rt("OverflowError: integer overflow (Py ints are 64-bit in the Java port)", line);
                }
            }
            double x = toDouble(l), y = toDouble(r);
            return switch (op) {
                case "+" -> x + y;
                case "-" -> x - y;
                case "*" -> x * y;
                case "**" -> {
                    if (x == 0 && y < 0)
                        throw rt("ZeroDivisionError: 0.0 cannot be raised to a negative power", line);
                    yield Math.pow(x, y);
                }
                case "%" -> {
                    if (y == 0) throw rt("ZeroDivisionError: modulo by zero", line);
                    double m = x % y;
                    if (m != 0 && (m < 0) != (y < 0)) m += y;
                    yield m;
                }
                case "/" -> {
                    if (y == 0) throw rt("ZeroDivisionError: division by zero", line);
                    yield x / y;
                }
                case "//" -> {
                    if (y == 0) throw rt("ZeroDivisionError: integer division by zero", line);
                    yield (long) Math.floor(x / y);
                }
                default -> throw rt("InternalError: unknown operator " + op, line);
            };
        }

        throw rt("TypeError: unsupported operand type(s) for '" + op + "': '"
                + typeName(l) + "' and '" + typeName(r) + "'", line);
    }

    private static Object intPow(long base, long exp, int line) {
        if (exp < 0) {
            if (base == 0) throw rt("ZeroDivisionError: 0.0 cannot be raised to a negative power", line);
            return Math.pow(base, exp); // int ** negative int -> float, like Python
        }
        long result = 1, b = base, e = exp;
        while (e > 0) {
            if ((e & 1) == 1) result = Math.multiplyExact(result, b);
            e >>= 1;
            if (e > 0) b = Math.multiplyExact(b, b);
        }
        return result;
    }

    private static final long MAX_SEQ = 1L << 28;

    private static String repeatStr(String s, long n, int line) {
        if (n <= 0 || s.isEmpty()) return "";
        if ((long) s.length() * n > MAX_SEQ) throw rt("MemoryError: string too large", line);
        return s.repeat((int) n);
    }

    private static List<Object> repeatList(List<Object> l, long n, int line) {
        List<Object> out = new ArrayList<>();
        if (n <= 0) return out;
        if ((long) l.size() * n > MAX_SEQ) throw rt("MemoryError: list too large", line);
        for (long i = 0; i < n; i++) out.addAll(l);
        return out;
    }

    // ══════════════════════════════════════════════════════════════════════
    // §9  AST PRETTY PRINTER  (for --ast flag)
    // ══════════════════════════════════════════════════════════════════════

    static void printAst(Node node, int indent) {
        String pad = "  ".repeat(indent);
        switch (node) {
            case IntLiteral n -> System.out.println(pad + "IntLiteral(" + pyRepr(n.value()) + ")");
            case FloatLiteral n -> System.out.println(pad + "FloatLiteral(" + pyRepr(n.value()) + ")");
            case StringLiteral n -> System.out.println(pad + "StringLiteral(" + pyRepr(n.value()) + ")");
            case BoolLiteral n -> System.out.println(pad + "BoolLiteral(" + pyRepr(n.value()) + ")");
            case NoneLiteral n -> System.out.println(pad + "NoneLiteral");
            case Name n -> System.out.println(pad + "Name(" + pyRepr(n.id()) + ")");
            case Program n -> {
                System.out.println(pad + "Program [line " + n.line() + "]");
                for (Node s : n.body()) printAst(s, indent + 1);
            }
            case FuncDef n -> {
                System.out.println(pad + "FuncDef name=" + pyRepr(n.name()) + " params=" + pyRepr(n.params()));
                for (Node s : n.body()) printAst(s, indent + 1);
            }
            case Assign n -> {
                System.out.println(pad + "Assign target=" + pyRepr(n.target()));
                printAst(n.value(), indent + 1);
            }
            case AugAssign n -> {
                System.out.println(pad + "AugAssign target=" + pyRepr(n.target()) + " op=" + pyRepr(n.op()));
                printAst(n.value(), indent + 1);
            }
            case Return n -> {
                System.out.println(pad + "Return");
                if (n.value() != null) printAst(n.value(), indent + 1);
            }
            case ExprStmt n -> {
                System.out.println(pad + "ExprStmt");
                printAst(n.expr(), indent + 1);
            }
            case If n -> {
                System.out.println(pad + "If");
                System.out.println(pad + "  test:");
                printAst(n.test(), indent + 2);
                System.out.println(pad + "  body:");
                for (Node s : n.body()) printAst(s, indent + 2);
                if (!n.orelse().isEmpty()) {
                    System.out.println(pad + "  orelse:");
                    for (Node s : n.orelse()) printAst(s, indent + 2);
                }
            }
            case While n -> {
                System.out.println(pad + "While");
                System.out.println(pad + "  test:");
                printAst(n.test(), indent + 2);
                System.out.println(pad + "  body:");
                for (Node s : n.body()) printAst(s, indent + 2);
            }
            case For n -> {
                System.out.println(pad + "For target=" + pyRepr(n.target()));
                System.out.println(pad + "  iter:");
                printAst(n.iter(), indent + 2);
                System.out.println(pad + "  body:");
                for (Node s : n.body()) printAst(s, indent + 2);
            }
            case BinOp n -> {
                System.out.println(pad + "BinOp op=" + pyRepr(n.op()));
                printAst(n.left(), indent + 1);
                printAst(n.right(), indent + 1);
            }
            case UnaryOp n -> {
                System.out.println(pad + "UnaryOp op=" + pyRepr(n.op()));
                printAst(n.operand(), indent + 1);
            }
            case Compare n -> {
                System.out.println(pad + "Compare op=" + pyRepr(n.op()));
                printAst(n.left(), indent + 1);
                printAst(n.right(), indent + 1);
            }
            case BoolOp n -> {
                System.out.println(pad + "BoolOp op=" + pyRepr(n.op()));
                for (Node v : n.values()) printAst(v, indent + 1);
            }
            case Call n -> {
                System.out.println(pad + "Call");
                printAst(n.func(), indent + 1);
                for (Node a : n.args()) printAst(a, indent + 1);
            }
            case MethodCall n -> {
                System.out.println(pad + "MethodCall method=" + pyRepr(n.method()));
                printAst(n.obj(), indent + 1);
                for (Node a : n.args()) printAst(a, indent + 1);
            }
            case ListLiteral n -> {
                System.out.println(pad + "ListLiteral [" + n.elts().size() + " elements]");
                for (Node e : n.elts()) printAst(e, indent + 1);
            }
            case Subscript n -> {
                System.out.println(pad + "Subscript");
                printAst(n.value(), indent + 1);
                printAst(n.index(), indent + 1);
            }
        }
    }

    // ══════════════════════════════════════════════════════════════════════
    // §10  PIPELINE  (source -> tokens -> AST -> execute)
    // ══════════════════════════════════════════════════════════════════════

    static Interpreter runSource(String source, Interpreter interpreter) {
        if (interpreter == null) interpreter = new Interpreter();
        List<Token> tokens = new Lexer(source).tokenize();
        Program program = new Parser(tokens).parse();
        interpreter.run(program);
        return interpreter;
    }

    static void runSourceWithAst(String source) {
        List<Token> tokens = new Lexer(source).tokenize();
        Program program = new Parser(tokens).parse();
        System.out.println("\n── AST ─────────────────────────────────────────────");
        printAst(program, 0);
        System.out.println("────────────────────────────────────────────────────\n");
        new Interpreter().run(program);
    }

    // ══════════════════════════════════════════════════════════════════════
    // §11  REPL
    // ══════════════════════════════════════════════════════════════════════

    static String banner() {
        String bar = "═".repeat(54);
        String[] lines = {
                "Py  —  Educational Interpreter",
                "Type Py code below.  'exit' or Ctrl-D to quit.",
                "'help' for a quick language reference.",
                "Block statements end with a blank line."
        };
        StringBuilder sb = new StringBuilder("\033[96m╔" + bar + "╗\n");
        for (String l : lines) sb.append(String.format("║ %-52s ║%n", l));
        sb.append("╚").append(bar).append("╝\033[0m");
        return sb.toString();
    }

    static final String HELP_TEXT = """

            Py Quick Reference
            ─────────────────────
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
            """;

    static void repl() throws IOException {
        System.out.println(banner());
        Interpreter interp = new Interpreter();
        List<String> buf = new ArrayList<>();
        boolean blockMode = false; // a line ended with ':' -> read until a blank line

        while (true) {
            System.out.print(buf.isEmpty() ? ">>> " : "... ");
            System.out.flush();
            String line = STDIN.readLine();
            if (line == null) { System.out.println("\nBye!"); break; }

            String trimmed = line.strip();
            if (buf.isEmpty()) {
                if (trimmed.equals("exit")) { System.out.println("Bye!"); break; }
                if (trimmed.equals("help")) { System.out.println(HELP_TEXT); continue; }
                if (trimmed.isEmpty()) continue;
            }

            if (!trimmed.isEmpty()) {
                buf.add(line);
                if (line.stripTrailing().endsWith(":")) blockMode = true;
                if (blockMode) continue;
            }

            // execute (single line, or blank line ended a block)
            String source = String.join("\n", buf) + "\n";
            buf.clear();
            blockMode = false;
            try {
                runSource(source, interp);
            } catch (PyError e) {
                System.out.println(e);
            } catch (RuntimeException e) {
                System.out.println("\033[91mInternalError\033[0m: " + e);
            }
        }
    }

    // ══════════════════════════════════════════════════════════════════════
    // §12  CLI ENTRY POINT
    // ══════════════════════════════════════════════════════════════════════

    static int realMain(String[] args) {
        try {
            if (args.length == 0) {
                repl();
                return 0;
            }

            boolean showAst = Arrays.asList(args).contains("--ast");
            List<String> files = new ArrayList<>();
            for (String a : args) if (!a.startsWith("--")) files.add(a);

            if (files.isEmpty()) {
                System.out.println("Usage: java Py.java [script] [--ast]");
                return 1;
            }

            String filepath = files.get(0);
            Path path = Path.of(filepath);
            if (!Files.exists(path)) {
                System.out.println("\033[91mFileNotFoundError\033[0m: No such file: " + pyRepr(filepath));
                return 1;
            }

            String source = Files.readString(path, StandardCharsets.UTF_8);
            if (showAst) runSourceWithAst(source);
            else runSource(source, null);
            return 0;
        } catch (PyError e) {
            System.out.println(e);
            return 1;
        } catch (Exception e) {
            System.out.println("\033[91mInternalError\033[0m: " + e);
            return 1;
        }
    }

    public static void main(String[] args) throws Exception {
        System.setOut(new PrintStream(new FileOutputStream(FileDescriptor.out), true, StandardCharsets.UTF_8));
        // Run on a thread with a big stack so deeply recursive Py programs work.
        int[] code = {0};
        Thread t = new Thread(null, () -> code[0] = realMain(args), "py-main", 512L * 1024 * 1024);
        t.start();
        t.join();
        System.out.flush();
        System.exit(code[0]);
    }
}