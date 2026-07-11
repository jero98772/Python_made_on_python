(ns pyclj.core
  "A tree-walking interpreter for a small Python-like language ('Py'),
   translated from the original Python implementation.

   Pipeline: source -> Lexer -> tokens -> Parser -> AST -> Interpreter -> effects.

   Notes on the translation:
   - Python's mutable OOP objects (Lexer/Parser position state, Environment
     var stores, and Python's mutable lists) are modeled with Clojure atoms.
     This preserves the original's *reference* semantics -- in particular,
     Py lists are represented as `(atom [...])` so that `append`/`pop`
     mutate a list in place exactly as Python's list.append/list.pop would,
     and two variables bound to 'the same list' really do share state.
   - AST nodes are Clojure records; interpretation dispatches on record
     type via multimethods (`exec-node` / `eval-node`), mirroring the
     original's `_exec_<ClassName>` / `_eval_<ClassName>` dispatch."
  (:require [clojure.string :as str])
  (:gen-class))

;; ══════════════════════════════════════════════════════════════════════════
;; §1  ERRORS
;; ══════════════════════════════════════════════════════════════════════════

(defn- format-error [type-name message line]
  (str type-name ": " message (when line (str " [line " line "]"))))

(defn- format-error-colored [type-name message line]
  (str "\033[91m" type-name "\033[0m: " message (when line (str " [line " line "]"))))

(defn py-error
  "Build an ex-info representing a Py* error (Lexer/Parse/Runtime).
   The exception's message is colorized (red type label), mirroring the
   original PyError.__str__; ex-data carries the plain fields for callers
   that want an uncolored rendering (the original's .plain())."
  [type-name message line]
  (ex-info (format-error-colored type-name message line)
           {:py-error true
            :error-type type-name
            :message message
            :line line
            :plain (format-error type-name message line)}))

(defn lexer-error [message line] (py-error "LexerError" message line))
(defn parse-error [message line] (py-error "ParseError" message line))
(defn runtime-error [message line] (py-error "PyRuntimeError" message line))

(defn py-error? [e]
  (and (instance? clojure.lang.ExceptionInfo e) (:py-error (ex-data e))))

(defn return-signal
  "Internal control-flow signal used to unwind the call stack on 'return'."
  [value]
  (ex-info "::return-signal::" {:return-signal true :value value}))

(defn return-signal? [e]
  (and (instance? clojure.lang.ExceptionInfo e) (:return-signal (ex-data e))))

;; ══════════════════════════════════════════════════════════════════════════
;; §2  TOKENS
;; ══════════════════════════════════════════════════════════════════════════

(def keywords
  {"if" :if "elif" :elif "else" :else "while" :while "for" :for "in" :in
   "def" :def "return" :return "and" :and "or" :or "not" :not
   "True" :true "False" :false "None" :none})

;; Human-readable text for each token type -- used in error messages,
;; mirroring CPython TT.value strings from the original enum.
(def token-display
  {:integer "INTEGER" :float "FLOAT" :string "STRING"
   :if "if" :elif "elif" :else "else" :while "while" :for "for" :in "in"
   :def "def" :return "return" :and "and" :or "or" :not "not"
   :true "True" :false "False" :none "None" :name "NAME"
   :plus "+" :minus "-" :star "*" :slash "/" :percent "%"
   :doubleslash "//" :doublestar "**"
   :eqequal "==" :notequal "!=" :less "<" :lessequal "<=" :greater ">" :greaterequal ">="
   :equal "=" :plusequal "+=" :minequal "-=" :starequal "*=" :slashequal "/="
   :lparen "(" :rparen ")" :lbracket "[" :rbracket "]" :colon ":" :comma "," :dot "."
   :newline "NEWLINE" :indent "INDENT" :dedent "DEDENT" :eof "EOF"})

(defn tt-str [tt] (get token-display tt (name tt)))

(defrecord Token [type value line col])

;; ══════════════════════════════════════════════════════════════════════════
;; §3  LEXER
;; ══════════════════════════════════════════════════════════════════════════
;;
;; Single-pass, character-by-character tokeniser, mirroring CPython's
;; Lib/tokenize.py in spirit:
;;   • :indent-stack tracks indentation depth -> :indent / :dedent tokens
;;   • blank/comment lines are silently skipped (no :newline emitted)
;;   • :paren-depth > 0 suppresses physical-newline NEWLINE tokens,
;;     enabling implicit line continuation inside ( ) or [ ]
;;
;; Lexer state is a single atom threaded through helper functions, standing
;; in for the mutable `self.*` fields of the Python Lexer class.

(def ^:private escapes
  {\n "\n" \t "\t" \r "\r" \\ "\\" \' "'" \" "\""
   \0 "\u0000" \a "\u0007" \b "\b"})

(defn new-lexer [source]
  (atom {:source (vec source)
         :pos 0
         :line 1
         :col 1
         :tokens []
         :indent-stack [0]
         :at-line-start true
         :paren-depth 0}))

(defn- src-len [st] (count (:source @st)))

(defn- cur [st]
  (let [{:keys [source pos]} @st]
    (if (< pos (count source)) (nth source pos) \u0000)))

(defn- pk [st n]
  (let [{:keys [source pos]} @st
        idx (+ pos n)]
    (if (< idx (count source)) (nth source idx) \u0000)))

(defn- here [st] [(:line @st) (:col @st)])

(defn- adv! [st]
  (let [ch (cur st)]
    (if (= ch \newline)
      (swap! st (fn [s] (-> s (update :pos inc) (update :line inc) (assoc :col 1))))
      (swap! st (fn [s] (-> s (update :pos inc) (update :col inc)))))
    ch))

(defn- emit! [st type value line col]
  (swap! st update :tokens conj (->Token type value line col)))

(defn- lex-err! [st msg]
  (throw (lexer-error msg (:line @st))))

(defn- close-all-indents! [st]
  (while (> (count (:indent-stack @st)) 1)
    (swap! st update :indent-stack pop)
    (emit! st :dedent nil (:line @st) (:col @st))))

(defn- digit? [ch] (and (not= ch \u0000) (Character/isDigit ^char ch)))
(defn- name-start? [ch] (or (Character/isLetter ^char ch) (= ch \_)))
(defn- name-char? [ch] (or (Character/isLetterOrDigit ^char ch) (= ch \_)))

(declare handle-indentation! read-string-lit! read-number! read-name! read-operator!)

(defn- next-token! [st]
  (if (and (:at-line-start @st) (zero? (:paren-depth @st)))
    (handle-indentation! st)
    (let [ch (cur st)]
      (cond
        (or (= ch \space) (= ch \tab)) (adv! st)

        (= ch \newline)
        (let [[ln cl] (here st)]
          (adv! st)
          (when (zero? (:paren-depth @st))
            (emit! st :newline "\n" ln cl)
            (swap! st assoc :at-line-start true)))

        (= ch \return) (adv! st)

        (= ch \#) (do (while (not (contains? #{\newline \u0000} (cur st))) (adv! st)))

        (contains? #{\" \'} ch) (read-string-lit! st)
        (digit? ch) (read-number! st)
        (name-start? ch) (read-name! st)
        :else (read-operator! st)))))

(defn- handle-indentation! [st]
  (let [indent (atom 0)]
    (while (contains? #{\space \tab} (cur st))
      (reset! indent (if (= (cur st) \tab)
                       (* (+ (quot @indent 8) 1) 8)
                       (inc @indent)))
      (adv! st))
    (let [ch (cur st)]
      (if (or (contains? #{\newline \return \u0000} ch) (= ch \#))
        (do
          (when (= ch \#)
            (while (not (contains? #{\newline \u0000} (cur st))) (adv! st)))
          (when (= (cur st) \newline) (adv! st)))
        (do
          (swap! st assoc :at-line-start false)
          (let [current (peek (:indent-stack @st))]
            (cond
              (> @indent current)
              (do (swap! st update :indent-stack conj @indent)
                  (emit! st :indent @indent (:line @st) 1))

              (< @indent current)
              (do
                (while (and (> (count (:indent-stack @st)) 1)
                            (> (peek (:indent-stack @st)) @indent))
                  (swap! st update :indent-stack pop)
                  (emit! st :dedent @indent (:line @st) 1))
                (when (not= (peek (:indent-stack @st)) @indent)
                  (lex-err! st "IndentationError: unindent does not match any outer indentation level")))

              :else nil)))))))

(defn- read-string-lit! [st]
  (let [[ln cl] (here st)
        q (adv! st)]
    (if (and (= (cur st) q) (= (pk st 1) q))
      ;; triple-quoted
      (do
        (adv! st) (adv! st)
        (let [buf (StringBuilder.)]
          (loop []
            (let [ch (cur st)]
              (cond
                (= ch \u0000) (lex-err! st "SyntaxError: EOF in triple-quoted string")
                (and (= ch q) (= (pk st 1) q) (= (pk st 2) q))
                (do (adv! st) (adv! st) (adv! st))
                :else
                (do
                  (if (= ch \\)
                    (do (adv! st) (.append buf ^String (get escapes (adv! st) "")))
                    (.append buf (adv! st)))
                  (recur)))))
          (emit! st :string (str buf) ln cl)))
      ;; single-quoted
      (let [buf (StringBuilder.)]
        (loop []
          (let [ch (cur st)]
            (cond
              (= ch \u0000) (lex-err! st "SyntaxError: unterminated string")
              (= ch \newline) (lex-err! st "SyntaxError: EOL in string")
              (= ch q) (adv! st)
              (= ch \\) (do (adv! st) (.append buf ^String (get escapes (adv! st) "")) (recur))
              :else (do (.append buf (adv! st)) (recur)))))
        (emit! st :string (str buf) ln cl)))))

(defn- read-number! [st]
  (let [[ln cl] (here st)
        buf (StringBuilder.)
        is-float (atom false)]
    (while (digit? (cur st)) (.append buf (adv! st)))
    (when (and (= (cur st) \.) (digit? (pk st 1)))
      (reset! is-float true)
      (.append buf (adv! st))
      (while (digit? (cur st)) (.append buf (adv! st))))
    (when (contains? #{\e \E} (cur st))
      (reset! is-float true)
      (.append buf (adv! st))
      (when (contains? #{\+ \-} (cur st)) (.append buf (adv! st)))
      (when-not (digit? (cur st)) (lex-err! st "SyntaxError: invalid numeric literal"))
      (while (digit? (cur st)) (.append buf (adv! st))))
    (let [text (str buf)]
      (if @is-float
        (emit! st :float (Double/parseDouble text) ln cl)
        (emit! st :integer (Long/parseLong text) ln cl)))))

(defn- read-name! [st]
  (let [[ln cl] (here st)
        buf (StringBuilder.)]
    (while (name-char? (cur st)) (.append buf (adv! st)))
    (let [nm (str buf)]
      (emit! st (get keywords nm :name) nm ln cl))))

(defn- read-operator! [st]
  (let [[ln cl] (here st)
        ch (adv! st)]
    (case ch
      \+ (if (= (cur st) \=) (do (adv! st) (emit! st :plusequal "+=" ln cl)) (emit! st :plus "+" ln cl))
      \- (if (= (cur st) \=) (do (adv! st) (emit! st :minequal "-=" ln cl)) (emit! st :minus "-" ln cl))
      \* (cond
           (= (cur st) \*) (do (adv! st) (emit! st :doublestar "**" ln cl))
           (= (cur st) \=) (do (adv! st) (emit! st :starequal "*=" ln cl))
           :else (emit! st :star "*" ln cl))
      \/ (cond
           (= (cur st) \/) (do (adv! st) (emit! st :doubleslash "//" ln cl))
           (= (cur st) \=) (do (adv! st) (emit! st :slashequal "/=" ln cl))
           :else (emit! st :slash "/" ln cl))
      \= (if (= (cur st) \=) (do (adv! st) (emit! st :eqequal "==" ln cl)) (emit! st :equal "=" ln cl))
      \! (if (= (cur st) \=) (do (adv! st) (emit! st :notequal "!=" ln cl))
             (lex-err! st "SyntaxError: '!' must be followed by '='"))
      \< (if (= (cur st) \=) (do (adv! st) (emit! st :lessequal "<=" ln cl)) (emit! st :less "<" ln cl))
      \> (if (= (cur st) \=) (do (adv! st) (emit! st :greaterequal ">=" ln cl)) (emit! st :greater ">" ln cl))
      \% (emit! st :percent "%" ln cl)
      \( (do (swap! st update :paren-depth inc) (emit! st :lparen "(" ln cl))
      \) (do (swap! st update :paren-depth #(max 0 (dec %))) (emit! st :rparen ")" ln cl))
      \[ (do (swap! st update :paren-depth inc) (emit! st :lbracket "[" ln cl))
      \] (do (swap! st update :paren-depth #(max 0 (dec %))) (emit! st :rbracket "]" ln cl))
      \: (emit! st :colon ":" ln cl)
      \, (emit! st :comma "," ln cl)
      \. (emit! st :dot "." ln cl)
      (lex-err! st (str "SyntaxError: unexpected character " (pr-str (str ch)))))))

(defn tokenize! [st]
  (while (< (:pos @st) (src-len st))
    (next-token! st))
  (close-all-indents! st)
  (let [toks (:tokens @st)]
    (when (or (empty? toks) (not (contains? #{:newline :dedent} (:type (last toks)))))
      (emit! st :newline "\n" (:line @st) (:col @st))))
  (emit! st :eof nil (:line @st) (:col @st))
  (:tokens @st))

(defn lex
  "source (String) -> vector of Token"
  [source]
  (tokenize! (new-lexer source)))

;; ══════════════════════════════════════════════════════════════════════════
;; §4  AST NODES
;;     Inspired by CPython's Grammar/python.asdl
;; ══════════════════════════════════════════════════════════════════════════

(defrecord Program [body line])                    ; ast.Module

(defrecord IntLiteral [value line])                 ; ast.Constant(int)
(defrecord FloatLiteral [value line])                ; ast.Constant(float)
(defrecord StringLiteral [value line])               ; ast.Constant(str)
(defrecord BoolLiteral [value line])                 ; ast.Constant(bool)
(defrecord NoneLiteral [line])                       ; ast.Constant(None)

(defrecord Name [id line])                           ; ast.Name(id, ctx)
(defrecord ListLiteral [elts line])                  ; ast.List(elts, ctx)
(defrecord Subscript [value index line])             ; ast.Subscript(value, slice, ctx)
(defrecord BinOp [left op right line])               ; ast.BinOp(left, op, right)
(defrecord UnaryOp [op operand line])                ; ast.UnaryOp(op, operand)
(defrecord Compare [left op right line])             ; ast.Compare(left, ops, comparators)
(defrecord BoolOp [op values line])                  ; ast.BoolOp(op, values)
(defrecord Call [func args line])                    ; ast.Call(func, args, keywords)
(defrecord MethodCall [obj method args line])        ; ast.Call(func=Attribute(...), args)

(defrecord Assign [target value line])               ; ast.Assign(targets, value)
(defrecord AugAssign [target op value line])         ; ast.AugAssign(target, op, value)
(defrecord ExprStmt [expr line])                     ; ast.Expr(value)
(defrecord Return [value line])                      ; ast.Return(value)
(defrecord If [test body orelse line])               ; ast.If(test, body, orelse)
(defrecord While [test body line])                   ; ast.While(test, body, orelse)
(defrecord For [target iter body line])              ; ast.For(target, iter, body)
(defrecord FuncDef [name params body line])          ; ast.FunctionDef(name, args, body)

;; ══════════════════════════════════════════════════════════════════════════
;; §5  PARSER
;;     PEG-style recursive descent, grammar mirrors CPython's python.gram
;;
;;  Grammar (EBNF):
;;   program      := stmt* EOF
;;   stmt         := func_def | if_stmt | while_stmt | for_stmt | simple_stmt
;;   simple_stmt  := (assign | aug_assign | return | expr_stmt) NEWLINE
;;   assign       := NAME '=' expr
;;   aug_assign   := NAME ('+='|'-='|'*='|'/=') expr
;;   return_stmt  := 'return' [expr]
;;   func_def     := 'def' NAME '(' params? ')' ':' block
;;   if_stmt      := 'if' expr ':' block elif_else?
;;   elif_else    := ('elif' expr ':' block elif_else?) | ('else' ':' block)
;;   while_stmt   := 'while' expr ':' block
;;   for_stmt     := 'for' NAME 'in' expr ':' block
;;   block        := NEWLINE INDENT stmt+ DEDENT
;;   expr         := or_expr
;;   or_expr      := and_expr  ('or'  and_expr)*
;;   and_expr     := not_expr  ('and' not_expr)*
;;   not_expr     := 'not' not_expr | comparison
;;   comparison   := sum (comp_op sum)*
;;   sum          := term     (('+' | '-') term)*
;;   term         := factor   (('*'|'/'|'//'|'%') factor)*
;;   factor       := ('+'|'-') factor | power
;;   power        := primary  ['**' factor]
;;   primary      := atom (call_args | subscript | method_call)*
;;   method_call  := '.' NAME '(' args? ')'
;;   atom         := INT | FLOAT | STR | True | False | None
;;                 | NAME | '[' args? ']' | '(' expr ')'
;; ══════════════════════════════════════════════════════════════════════════

(defn new-parser [tokens]
  (atom {:tokens (vec tokens) :pos 0}))

(defn- p-cur [ps]
  (let [{:keys [tokens pos]} @ps]
    (nth tokens (min pos (dec (count tokens))))))

(defn- p-peek [ps n]
  (let [{:keys [tokens pos]} @ps]
    (nth tokens (min (+ pos n) (dec (count tokens))))))

(defn- p-prev [ps]
  (let [{:keys [tokens pos]} @ps]
    (nth tokens (max (dec pos) 0))))

(defn- p-advance! [ps]
  (let [tok (p-cur ps)]
    (when (< (:pos @ps) (dec (count (:tokens @ps))))
      (swap! ps update :pos inc))
    tok))

(defn- p-check [ps & types]
  (contains? (set types) (:type (p-cur ps))))

(defn- p-match [ps & types]
  (if (apply p-check ps types)
    (do (p-advance! ps) true)
    false))

(defn- p-err! [ps msg]
  (throw (parse-error (str "SyntaxError: " msg) (:line (p-cur ps)))))

(defn- p-expect!
  ([ps tt] (p-expect! ps tt nil))
  ([ps tt msg]
   (if (p-check ps tt)
     (p-advance! ps)
     (let [got (p-cur ps)
           desc (or msg (str "expected '" (tt-str tt) "', got '" (tt-str (:type got))
                              "' (" (pr-str (:value got)) ")"))]
       (throw (parse-error (str "SyntaxError: " desc) (:line got)))))))

(defn- p-skip-newlines! [ps]
  (while (p-check ps :newline) (p-advance! ps)))

(declare p-stmt-list p-stmt p-simple-stmt p-assign p-aug-assign p-return-stmt
         p-func-def p-if-stmt p-elif-or-else p-while-stmt p-for-stmt p-block
         p-expr p-or-expr p-and-expr p-not-expr p-comparison p-sum p-term
         p-factor p-power p-primary p-call-args p-atom)

(defn parse
  "tokens (vector of Token) -> Program"
  [tokens]
  (let [ps (new-parser tokens)
        stmts (p-stmt-list ps)]
    (p-expect! ps :eof "expected end of file")
    (->Program stmts 1)))

(defn- p-stmt-list [ps]
  (loop [stmts []]
    (p-skip-newlines! ps)
    (if (p-check ps :eof :dedent)
      stmts
      (recur (conj stmts (p-stmt ps))))))

(defn- p-stmt [ps]
  (p-skip-newlines! ps)
  (cond
    (p-match ps :def) (p-func-def ps)
    (p-match ps :if) (p-if-stmt ps)
    (p-match ps :while) (p-while-stmt ps)
    (p-match ps :for) (p-for-stmt ps)
    :else (p-simple-stmt ps)))

(defn- p-simple-stmt [ps]
  (let [node
        (cond
          (p-check ps :return)
          (do (p-advance! ps) (p-return-stmt ps))

          (and (p-check ps :name) (= (:type (p-peek ps 1)) :equal))
          (p-assign ps)

          (and (p-check ps :name)
               (contains? #{:plusequal :minequal :starequal :slashequal} (:type (p-peek ps 1))))
          (p-aug-assign ps)

          :else (->ExprStmt (p-expr ps) (:line (p-cur ps))))]
    (cond
      (p-check ps :newline) (p-advance! ps)
      (p-check ps :eof :dedent) nil
      :else (p-err! ps (str "expected newline after statement, got " (pr-str (tt-str (:type (p-cur ps)))))))
    node))

(defn- p-assign [ps]
  (let [t (p-expect! ps :name)]
    (p-expect! ps :equal)
    (->Assign (:value t) (p-expr ps) (:line t))))

(defn- p-aug-assign [ps]
  (let [t (p-advance! ps)
        op (p-advance! ps)]
    (->AugAssign (:value t) (:value op) (p-expr ps) (:line t))))

(defn- p-return-stmt [ps]
  (let [ln (:line (p-prev ps))]
    (if (p-check ps :newline :eof :dedent)
      (->Return nil ln)
      (->Return (p-expr ps) ln))))

(defn- p-func-def [ps]
  (let [ln (:line (p-prev ps))
        nm (p-expect! ps :name "expected function name")]
    (p-expect! ps :lparen "expected '(' after function name")
    (let [params (atom [])]
      (when (p-check ps :name)
        (swap! params conj (:value (p-advance! ps)))
        (while (p-match ps :comma)
          (when-not (p-check ps :name) (p-err! ps "expected parameter name"))
          (swap! params conj (:value (p-advance! ps)))))
      (p-expect! ps :rparen "expected ')'")
      (p-expect! ps :colon "expected ':' after function signature")
      (->FuncDef (:value nm) @params (p-block ps) ln))))

(defn- p-if-stmt [ps]
  (let [ln (:line (p-prev ps))
        test (p-expr ps)]
    (p-expect! ps :colon "expected ':' after if-condition")
    (let [body (p-block ps)
          orelse (p-elif-or-else ps)]
      (->If test body orelse ln))))

(defn- p-elif-or-else [ps]
  (p-skip-newlines! ps)
  (cond
    (p-match ps :elif)
    (let [ln (:line (p-prev ps))
          test (p-expr ps)]
      (p-expect! ps :colon "expected ':' after elif")
      (let [body (p-block ps)
            orelse (p-elif-or-else ps)]
        [(->If test body orelse ln)]))

    (p-match ps :else)
    (do (p-expect! ps :colon "expected ':' after else")
        (p-block ps))

    :else []))

(defn- p-while-stmt [ps]
  (let [ln (:line (p-prev ps))
        test (p-expr ps)]
    (p-expect! ps :colon "expected ':' after while")
    (->While test (p-block ps) ln)))

(defn- p-for-stmt [ps]
  (let [ln (:line (p-prev ps))
        var-tok (p-expect! ps :name "expected loop variable")]
    (p-expect! ps :in "expected 'in'")
    (let [itr (p-expr ps)]
      (p-expect! ps :colon "expected ':' after for-clause")
      (->For (:value var-tok) itr (p-block ps) ln))))

(defn- p-block [ps]
  (p-expect! ps :newline "expected newline before block")
  (p-expect! ps :indent "expected indented block")
  (let [stmts (p-stmt-list ps)]
    (when (empty? stmts) (p-err! ps "empty block"))
    (p-expect! ps :dedent "expected dedent after block")
    stmts))

;; ── Expressions (precedence chain) ──────────────────────────────────────────

(defn- p-expr [ps] (p-or-expr ps))

(defn- p-or-expr [ps]
  (let [node (p-and-expr ps)]
    (if (p-check ps :or)
      (loop [vals [node]]
        (if (p-match ps :or)
          (recur (conj vals (p-and-expr ps)))
          (->BoolOp "or" vals (:line node))))
      node)))

(defn- p-and-expr [ps]
  (let [node (p-not-expr ps)]
    (if (p-check ps :and)
      (loop [vals [node]]
        (if (p-match ps :and)
          (recur (conj vals (p-not-expr ps)))
          (->BoolOp "and" vals (:line node))))
      node)))

(defn- p-not-expr [ps]
  (if (p-match ps :not)
    (let [ln (:line (p-prev ps))]
      (->UnaryOp "not" (p-not-expr ps) ln))
    (p-comparison ps)))

(def ^:private compare-ops [:eqequal :notequal :less :lessequal :greater :greaterequal])

(defn- p-comparison [ps]
  (loop [node (p-sum ps)]
    (if (apply p-check ps compare-ops)
      (let [op (p-advance! ps)
            right (p-sum ps)]
        (recur (->Compare node (:value op) right (:line node))))
      node)))

(defn- p-sum [ps]
  (loop [node (p-term ps)]
    (if (p-check ps :plus :minus)
      (let [op (:value (p-advance! ps))
            right (p-term ps)]
        (recur (->BinOp node op right (:line node))))
      node)))

(defn- p-term [ps]
  (loop [node (p-factor ps)]
    (if (p-check ps :star :slash :doubleslash :percent)
      (let [op (:value (p-advance! ps))
            right (p-factor ps)]
        (recur (->BinOp node op right (:line node))))
      node)))

(defn- p-factor [ps]
  (if (p-check ps :plus :minus)
    (let [op (p-advance! ps)]
      (->UnaryOp (:value op) (p-factor ps) (:line op)))
    (p-power ps)))

(defn- p-power [ps]
  (let [base (p-primary ps)]
    (if (p-match ps :doublestar)
      (->BinOp base "**" (p-factor ps) (:line (p-prev ps)))
      base)))

(defn- p-primary [ps]
  (loop [node (p-atom ps)]
    (cond
      (p-check ps :lparen)
      (do (p-advance! ps)
          (let [ln (:line (p-prev ps))
                args (p-call-args ps)]
            (p-expect! ps :rparen "expected ')' after arguments")
            (recur (->Call node args ln))))

      (p-check ps :lbracket)
      (do (p-advance! ps)
          (let [ln (:line (p-prev ps))
                idx (p-expr ps)]
            (p-expect! ps :rbracket "expected ']' after index")
            (recur (->Subscript node idx ln))))

      (p-check ps :dot)
      (do (p-advance! ps)
          (let [ln (:line (p-prev ps))
                name-tok (p-expect! ps :name "expected attribute/method name after '.'")]
            (when-not (p-check ps :lparen)
              (p-err! ps (str "attribute access without a call is not supported: '." (:value name-tok) "'")))
            (p-advance! ps)
            (let [args (p-call-args ps)]
              (p-expect! ps :rparen "expected ')' after method arguments")
              (recur (->MethodCall node (:value name-tok) args ln)))))

      :else node)))

(defn- p-call-args [ps]
  (if (p-check ps :rparen)
    []
    (loop [args [(p-expr ps)]]
      (if (p-match ps :comma)
        (if (p-check ps :rparen)
          args
          (recur (conj args (p-expr ps))))
        args))))

(defn- p-atom [ps]
  (let [tok (p-cur ps)]
    (cond
      (p-match ps :integer) (->IntLiteral (:value tok) (:line tok))
      (p-match ps :float) (->FloatLiteral (:value tok) (:line tok))
      (p-match ps :string) (->StringLiteral (:value tok) (:line tok))
      (p-match ps :true) (->BoolLiteral true (:line tok))
      (p-match ps :false) (->BoolLiteral false (:line tok))
      (p-match ps :none) (->NoneLiteral (:line tok))
      (p-match ps :name) (->Name (:value tok) (:line tok))

      (p-match ps :lbracket)
      (let [elts (if (p-check ps :rbracket)
                   []
                   (loop [es [(p-expr ps)]]
                     (if (p-match ps :comma)
                       (if (p-check ps :rbracket) es (recur (conj es (p-expr ps))))
                       es)))]
        (p-expect! ps :rbracket "expected ']'")
        (->ListLiteral elts (:line tok)))

      (p-match ps :lparen)
      (let [node (p-expr ps)]
        (p-expect! ps :rparen "expected ')'")
        node)

      :else (p-err! ps (str "unexpected token " (pr-str (tt-str (:type tok))) " (" (pr-str (:value tok)) ")")))))

;; ══════════════════════════════════════════════════════════════════════════
;; §6  ENVIRONMENT  (scoped variable store)
;; ══════════════════════════════════════════════════════════════════════════
;;
;; A dictionary-backed variable scope (an atom holding a map). Scopes are
;; linked by :parent -- lookup walks the chain outward (like CPython's LEGB
;; rule, minus global/builtin distinctions).

(defrecord Env [vars parent])

(defn new-env
  ([] (->Env (atom {}) nil))
  ([parent] (->Env (atom {}) parent)))

(defn env-owns? [env nm]
  (or (contains? @(:vars env) nm)
      (and (:parent env) (env-owns? (:parent env) nm))))

(defn env-get
  "Look a name up the scope chain; raises NameError if not found."
  [env nm line]
  (cond
    (contains? @(:vars env) nm) (get @(:vars env) nm)
    (:parent env) (env-get (:parent env) nm line)
    :else (throw (runtime-error (str "NameError: name '" nm "' is not defined") line))))

(defn env-set!
  "Always sets in the *current* scope (like Python assignment)."
  [env nm value]
  (swap! (:vars env) assoc nm value))

(defn env-assign!
  "Assign to the nearest scope that already owns *name*, else the current scope."
  [env nm value line]
  (cond
    (contains? @(:vars env) nm) (swap! (:vars env) assoc nm value)
    (and (:parent env) (env-owns? (:parent env) nm)) (env-assign! (:parent env) nm value line)
    :else (swap! (:vars env) assoc nm value)))

;; ══════════════════════════════════════════════════════════════════════════
;; §7  BUILTIN FUNCTIONS & VALUE HELPERS
;; ══════════════════════════════════════════════════════════════════════════

(defrecord PyFunction [node closure])

;; Py lists are represented as `(atom [...])`. This gives them Python's
;; reference/mutation semantics: `x = lst; append(x, 1)` is visible through
;; every variable bound to the same list, exactly like real Python lists.
(defn py-list? [v] (instance? clojure.lang.Atom v))

(defn numericish? [v] (or (number? v) (boolean? v)))
(defn ->numval [v] (if (boolean? v) (if v 1 0) v))

(declare type-name)

(defn ep-str [v]
  (cond
    (nil? v) "None"
    (boolean? v) (if v "True" "False")
    (py-list? v) (str "[" (str/join ", " (map ep-str @v)) "]")
    :else (str v)))

(defn ep-bool [v]
  (cond
    (nil? v) false
    (boolean? v) v
    (number? v) (not (zero? v))
    (string? v) (pos? (count v))
    (py-list? v) (pos? (count @v))
    :else true))

(defn type-name [v]
  (cond
    (nil? v) "NoneType"
    (boolean? v) "bool"
    (py-list? v) "list"
    (integer? v) "int"
    (float? v) "float"
    (string? v) "str"
    (instance? PyFunction v) "function"
    (fn? v) "builtin_function_or_method"
    :else (str (type v))))

(defn- deep-unwrap [v]
  (if (py-list? v) (mapv deep-unwrap @v) v))

(defn- py-abs [v] (if (neg? v) (- v) v))

;; ── Builtins ─────────────────────────────────────────────────────────────

(defn builtin-print [args]
  (println (str/join " " (map ep-str args)))
  nil)

(defn builtin-len [args]
  (when (not= (count args) 1) (throw (runtime-error "TypeError: len() takes exactly 1 argument" nil)))
  (let [v (first args)]
    (cond
      (string? v) (count v)
      (py-list? v) (count @v)
      :else (throw (runtime-error (str "TypeError: object of type '" (type-name v) "' has no len()") nil)))))

(defn builtin-range [args]
  (when-not (<= 1 (count args) 3) (throw (runtime-error "TypeError: range() takes 1–3 arguments" nil)))
  (doseq [a args]
    (when-not (numericish? a) (throw (runtime-error "TypeError: range() arguments must be integers" nil))))
  (let [iargs (map #(long (->numval %)) args)]
    (atom (vec (apply range iargs)))))

(defn builtin-int [args]
  (when (not= (count args) 1) (throw (runtime-error "TypeError: int() takes 1 argument" nil)))
  (let [v (first args)]
    (cond
      (boolean? v) (if v 1 0)
      (number? v) (long v)
      (string? v)
      (let [s (str/trim v)]
        (if (re-matches #"[+-]?\d+" s)
          (Long/parseLong s)
          (throw (runtime-error (str "ValueError: invalid literal for int(): " (pr-str v)) nil))))
      :else (throw (runtime-error (str "TypeError: int() argument must be a string or number, not '" (type-name v) "'") nil)))))

(defn builtin-float [args]
  (when (not= (count args) 1) (throw (runtime-error "TypeError: float() takes 1 argument" nil)))
  (let [v (first args)]
    (cond
      (boolean? v) (if v 1.0 0.0)
      (number? v) (double v)
      (string? v)
      (let [s (str/trim v)]
        (if (seq s)
          (try (Double/parseDouble s)
               (catch Exception _
                 (throw (runtime-error (str "ValueError: could not convert string to float: " (pr-str v)) nil))))
          (throw (runtime-error "ValueError: could not convert string to float: ''" nil))))
      :else (throw (runtime-error (str "TypeError: float() argument must be a string or number, not '" (type-name v) "'") nil)))))

(defn builtin-str [args]
  (when (not= (count args) 1) (throw (runtime-error "TypeError: str() takes 1 argument" nil)))
  (ep-str (first args)))

(defn builtin-bool [args]
  (when (not= (count args) 1) (throw (runtime-error "TypeError: bool() takes 1 argument" nil)))
  (ep-bool (first args)))

(defn builtin-input [args]
  (when (seq args) (print (ep-str (first args))) (flush))
  (read-line))

(defn builtin-abs [args]
  (when (not= (count args) 1) (throw (runtime-error "TypeError: abs() takes 1 argument" nil)))
  (let [v (first args)]
    (if (number? v)
      (py-abs v)
      (throw (runtime-error (str "TypeError: bad operand type for abs(): '" (type-name v) "'") nil)))))

(defn- cmp-key [v] (->numval v))

(defn builtin-max [args]
  (when (empty? args) (throw (runtime-error "TypeError: max() expected at least 1 argument" nil)))
  (let [items (if (and (= (count args) 1) (py-list? (first args))) (vec @(first args)) (vec args))]
    (when (empty? items) (throw (runtime-error "ValueError: max() arg is an empty sequence" nil)))
    (try
      (reduce (fn [a b] (if (pos? (compare (cmp-key b) (cmp-key a))) b a)) items)
      (catch Exception _ (throw (runtime-error "TypeError: '>' not supported between the given types" nil))))))

(defn builtin-min [args]
  (when (empty? args) (throw (runtime-error "TypeError: min() expected at least 1 argument" nil)))
  (let [items (if (and (= (count args) 1) (py-list? (first args))) (vec @(first args)) (vec args))]
    (when (empty? items) (throw (runtime-error "ValueError: min() arg is an empty sequence" nil)))
    (try
      (reduce (fn [a b] (if (neg? (compare (cmp-key b) (cmp-key a))) b a)) items)
      (catch Exception _ (throw (runtime-error "TypeError: '<' not supported between the given types" nil))))))

(defn builtin-type [args]
  (when (not= (count args) 1) (throw (runtime-error "TypeError: type() takes 1 argument" nil)))
  (str "<class '" (type-name (first args)) "'>"))

(defn builtin-append
  "append(list, value) -- called as a function, not method syntax."
  [args]
  (when (not= (count args) 2) (throw (runtime-error "TypeError: append() takes 2 arguments" nil)))
  (let [[lst val] args]
    (when-not (py-list? lst) (throw (runtime-error "TypeError: first argument must be a list" nil)))
    (swap! lst conj val)
    nil))

(defn builtin-pop [args]
  (when-not (<= 1 (count args) 2) (throw (runtime-error "TypeError: pop() takes 1 or 2 arguments" nil)))
  (let [lst (first args)]
    (when-not (py-list? lst) (throw (runtime-error "TypeError: first argument must be a list" nil)))
    (let [items @lst
          n (count items)]
      (when (zero? n) (throw (runtime-error "IndexError: pop from empty list" nil)))
      (let [idx0 (if (= (count args) 2) (long (->numval (second args))) -1)
            idx (if (neg? idx0) (+ n idx0) idx0)]
        (when (or (< idx 0) (>= idx n))
          (throw (runtime-error "IndexError: pop index out of range" nil)))
        (let [val (nth items idx)]
          (reset! lst (vec (concat (subvec items 0 idx) (subvec items (inc idx)))))
          val)))))

(def builtins
  {"print" builtin-print
   "len" builtin-len
   "range" builtin-range
   "int" builtin-int
   "float" builtin-float
   "str" builtin-str
   "bool" builtin-bool
   "input" builtin-input
   "abs" builtin-abs
   "max" builtin-max
   "min" builtin-min
   "type" builtin-type
   "append" builtin-append
   "pop" builtin-pop})

;; ══════════════════════════════════════════════════════════════════════════
;; §8  INTERPRETER  (tree-walk)
;; ══════════════════════════════════════════════════════════════════════════
;;
;; Dispatch pattern: (exec-node node env) / (eval-node node env), dispatching
;; on the AST record's class -- the direct analogue of the original's
;; `_exec_<ClassName>` / `_eval_<ClassName>` method-name dispatch.

(defmulti exec-node (fn [node _env] (type node)))
(defmulti eval-node (fn [node _env] (type node)))

(defn exec-stmts [stmts env]
  (doseq [s stmts] (exec-node s env)))

(defn apply-binop [op left right line]
  (cond
    (and (= op "+") (string? left) (string? right)) (str left right)
    (and (= op "*") (string? left) (numericish? right)) (apply str (repeat (long (->numval right)) left))
    (and (= op "*") (numericish? left) (string? right)) (apply str (repeat (long (->numval left)) right))
    (and (= op "+") (py-list? left) (py-list? right)) (atom (vec (concat @left @right)))
    (and (= op "*") (py-list? left) (numericish? right)) (atom (vec (apply concat (repeat (long (->numval right)) @left))))
    (and (numericish? left) (numericish? right))
    (let [l (->numval left) r (->numval right)]
      (case op
        "+" (+ l r)
        "-" (- l r)
        "*" (* l r)
        "**" (let [res (Math/pow l r)]
               (if (and (integer? l) (integer? r) (>= r 0)) (long res) res))
        "%" (if (zero? r) (throw (runtime-error "ZeroDivisionError: modulo by zero" line)) (mod l r))
        "/" (if (zero? r) (throw (runtime-error "ZeroDivisionError: division by zero" line)) (/ (double l) (double r)))
        "//" (if (zero? r) (throw (runtime-error "ZeroDivisionError: integer division by zero" line))
                 (long (Math/floor (/ (double l) (double r)))))
        (throw (runtime-error (str "TypeError: unsupported operand type(s) for '" op "': '"
                                    (type-name left) "' and '" (type-name right) "'") line))))
    :else
    (throw (runtime-error (str "TypeError: unsupported operand type(s) for '" op "': '"
                                (type-name left) "' and '" (type-name right) "'") line))))

;; ── Statement execution ──────────────────────────────────────────────────

(defmethod exec-node FuncDef [node env]
  (env-set! env (:name node) (->PyFunction node env)))

(defmethod exec-node Assign [node env]
  (env-set! env (:target node) (eval-node (:value node) env)))

(defmethod exec-node AugAssign [node env]
  (let [current (env-get env (:target node) (:line node))
        rhs (eval-node (:value node) env)
        op-char (str (first (:op node)))
        result (apply-binop op-char current rhs (:line node))]
    (env-assign! env (:target node) result (:line node))))

(defmethod exec-node ExprStmt [node env]
  (eval-node (:expr node) env))

(defmethod exec-node Return [node env]
  (let [value (when (:value node) (eval-node (:value node) env))]
    (throw (return-signal value))))

(defmethod exec-node If [node env]
  (if (ep-bool (eval-node (:test node) env))
    (exec-stmts (:body node) env)
    (when (seq (:orelse node)) (exec-stmts (:orelse node) env))))

(defmethod exec-node While [node env]
  (while (ep-bool (eval-node (:test node) env))
    (exec-stmts (:body node) env)))

(defmethod exec-node For [node env]
  (let [iterable (eval-node (:iter node) env)]
    (cond
      (py-list? iterable)
      (doseq [item @iterable]
        (env-set! env (:target node) item)
        (exec-stmts (:body node) env))

      (string? iterable)
      (doseq [item (map str iterable)]
        (env-set! env (:target node) item)
        (exec-stmts (:body node) env))

      :else
      (throw (runtime-error (str "TypeError: '" (type-name iterable) "' object is not iterable") (:line node))))))

;; ── Expression evaluation ────────────────────────────────────────────────

(defmethod eval-node IntLiteral [n _e] (:value n))
(defmethod eval-node FloatLiteral [n _e] (:value n))
(defmethod eval-node StringLiteral [n _e] (:value n))
(defmethod eval-node BoolLiteral [n _e] (:value n))
(defmethod eval-node NoneLiteral [_n _e] nil)
(defmethod eval-node Name [n e] (env-get e (:id n) (:line n)))
(defmethod eval-node ListLiteral [n e] (atom (mapv #(eval-node % e) (:elts n))))

(defmethod eval-node Subscript [n e]
  (let [obj (eval-node (:value n) e)
        idx (eval-node (:index n) e)]
    (cond
      (not (or (py-list? obj) (string? obj)))
      (throw (runtime-error (str "TypeError: '" (type-name obj) "' object is not subscriptable") (:line n)))

      (not (numericish? idx))
      (throw (runtime-error (str "TypeError: indices must be integers, not '" (type-name idx) "'") (:line n)))

      :else
      (let [coll (if (py-list? obj) @obj obj)
            len (count coll)
            i (long (->numval idx))]
        (if (or (< i (- len)) (>= i len))
          (throw (runtime-error (str "IndexError: index " i " out of range (length " len ")") (:line n)))
          (let [real-i (if (neg? i) (+ len i) i)]
            (if (string? coll) (str (nth coll real-i)) (nth coll real-i))))))))

(defmethod eval-node BinOp [n e]
  (let [left (eval-node (:left n) e)
        right (eval-node (:right n) e)]
    (apply-binop (:op n) left right (:line n))))

(defmethod eval-node UnaryOp [n e]
  (let [v (eval-node (:operand n) e)]
    (case (:op n)
      "not" (not (ep-bool v))
      "-" (if (numericish? v)
            (- (->numval v))
            (throw (runtime-error (str "TypeError: bad operand type for unary '-': '" (type-name v) "'") (:line n))))
      "+" (if (numericish? v)
            (->numval v)
            (throw (runtime-error (str "TypeError: bad operand type for unary '+': '" (type-name v) "'") (:line n)))))))

(defmethod eval-node Compare [n e]
  (let [left (eval-node (:left n) e)
        right (eval-node (:right n) e)
        op (:op n)]
    (cond
      (= op "==") (= (deep-unwrap left) (deep-unwrap right))
      (= op "!=") (not= (deep-unwrap left) (deep-unwrap right))
      :else
      (do
        (doseq [v [left right]]
          (when-not (or (numericish? v) (string? v))
            (throw (runtime-error (str "TypeError: '" op "' not supported between '"
                                        (type-name left) "' and '" (type-name right) "'") (:line n)))))
        (let [l (->numval left) r (->numval right)
              c (try (compare l r)
                     (catch Exception _
                       (throw (runtime-error (str "TypeError: '" op "' not supported between instances of '"
                                                   (type-name left) "' and '" (type-name right) "'") (:line n)))))]
          (case op
            "<" (neg? c)
            "<=" (<= c 0)
            ">" (pos? c)
            ">=" (>= c 0)))))))

(defmethod eval-node BoolOp [n e]
  (let [vals (:values n)]
    (if (= (:op n) "and")
      (loop [result (eval-node (first vals) e) remaining (next vals)]
        (if (nil? remaining)
          result
          (if (ep-bool result)
            (recur (eval-node (first remaining) e) (next remaining))
            result)))
      (loop [result (eval-node (first vals) e) remaining (next vals)]
        (if (nil? remaining)
          result
          (if (ep-bool result)
            result
            (recur (eval-node (first remaining) e) (next remaining))))))))

(defmethod eval-node MethodCall [n e]
  (let [obj (eval-node (:obj n) e)
        args (mapv #(eval-node % e) (:args n))
        method (:method n)]
    (if (string? obj)
      (case method
        "lower" (do (when (seq args) (throw (runtime-error "TypeError: lower() takes no arguments" (:line n))))
                    (str/lower-case obj))
        "upper" (do (when (seq args) (throw (runtime-error "TypeError: upper() takes no arguments" (:line n))))
                    (str/upper-case obj))
        (throw (runtime-error (str "AttributeError: 'str' object has no attribute '" method "'") (:line n))))
      (throw (runtime-error (str "AttributeError: '" (type-name obj) "' object has no attribute '" method "'") (:line n))))))

(defmethod eval-node Call [n e]
  (let [callee (eval-node (:func n) e)
        args (mapv #(eval-node % e) (:args n))]
    (cond
      (and (fn? callee) (not (instance? PyFunction callee)))
      (callee args)

      (instance? PyFunction callee)
      (let [fn-node (:node callee)
            arity (count (:params fn-node))]
        (when (not= (count args) arity)
          (throw (runtime-error (str "TypeError: " (:name fn-node) "() takes " arity
                                      " argument(s) but " (count args) " given") (:line n))))
        (let [call-env (new-env (:closure callee))]
          (doseq [[p v] (map vector (:params fn-node) args)]
            (env-set! call-env p v))
          (try
            (exec-stmts (:body fn-node) call-env)
            nil
            (catch clojure.lang.ExceptionInfo ex
              (if (return-signal? ex) (:value (ex-data ex)) (throw ex))))))

      :else
      (throw (runtime-error (str "TypeError: '" (type-name callee) "' object is not callable") (:line n))))))

;; ── Interpreter entry points ─────────────────────────────────────────────

(defn new-interpreter []
  (let [globals (new-env)]
    (doseq [[nm f] builtins] (env-set! globals nm f))
    {:globals globals}))

(defn run-program!
  [interp program]
  (exec-stmts (:body program) (:globals interp))
  interp)

;; ══════════════════════════════════════════════════════════════════════════
;; §9  AST PRETTY PRINTER  (for --ast flag)
;; ══════════════════════════════════════════════════════════════════════════

(defn- ind [n] (apply str (repeat (* 2 n) " ")))

(defn print-ast
  ([node] (print-ast node 0))
  ([node depth]
   (let [p (ind depth)]
     (condp instance? node
       IntLiteral (println (str p "IntLiteral(" (pr-str (:value node)) ")"))
       FloatLiteral (println (str p "FloatLiteral(" (pr-str (:value node)) ")"))
       StringLiteral (println (str p "StringLiteral(" (pr-str (:value node)) ")"))
       BoolLiteral (println (str p "BoolLiteral(" (pr-str (:value node)) ")"))
       NoneLiteral (println (str p "NoneLiteral"))
       Name (println (str p "Name(" (pr-str (:id node)) ")"))

       Program (do (println (str p "Program [line " (:line node) "]"))
                   (doseq [s (:body node)] (print-ast s (inc depth))))

       FuncDef (do (println (str p "FuncDef name=" (pr-str (:name node)) " params=" (:params node)))
                   (doseq [s (:body node)] (print-ast s (inc depth))))

       Assign (do (println (str p "Assign target=" (pr-str (:target node))))
                  (print-ast (:value node) (inc depth)))

       AugAssign (do (println (str p "AugAssign target=" (pr-str (:target node)) " op=" (pr-str (:op node))))
                     (print-ast (:value node) (inc depth)))

       Return (do (println (str p "Return"))
                  (when (:value node) (print-ast (:value node) (inc depth))))

       ExprStmt (do (println (str p "ExprStmt"))
                    (print-ast (:expr node) (inc depth)))

       If (do (println (str p "If"))
              (println (str p "  test:"))
              (print-ast (:test node) (+ depth 2))
              (println (str p "  body:"))
              (doseq [s (:body node)] (print-ast s (+ depth 2)))
              (when (seq (:orelse node))
                (println (str p "  orelse:"))
                (doseq [s (:orelse node)] (print-ast s (+ depth 2)))))

       While (do (println (str p "While"))
                 (println (str p "  test:"))
                 (print-ast (:test node) (+ depth 2))
                 (println (str p "  body:"))
                 (doseq [s (:body node)] (print-ast s (+ depth 2))))

       For (do (println (str p "For target=" (pr-str (:target node))))
               (println (str p "  iter:"))
               (print-ast (:iter node) (+ depth 2))
               (println (str p "  body:"))
               (doseq [s (:body node)] (print-ast s (+ depth 2))))

       BinOp (do (println (str p "BinOp op=" (pr-str (:op node))))
                 (print-ast (:left node) (inc depth))
                 (print-ast (:right node) (inc depth)))

       UnaryOp (do (println (str p "UnaryOp op=" (pr-str (:op node))))
                   (print-ast (:operand node) (inc depth)))

       Compare (do (println (str p "Compare op=" (pr-str (:op node))))
                   (print-ast (:left node) (inc depth))
                   (print-ast (:right node) (inc depth)))

       BoolOp (do (println (str p "BoolOp op=" (pr-str (:op node))))
                  (doseq [v (:values node)] (print-ast v (inc depth))))

       Call (do (println (str p "Call"))
                (print-ast (:func node) (inc depth))
                (doseq [a (:args node)] (print-ast a (inc depth))))

       MethodCall (do (println (str p "MethodCall method=" (pr-str (:method node))))
                      (print-ast (:obj node) (inc depth))
                      (doseq [a (:args node)] (print-ast a (inc depth))))

       ListLiteral (do (println (str p "ListLiteral [" (count (:elts node)) " elements]"))
                       (doseq [el (:elts node)] (print-ast el (inc depth))))

       Subscript (do (println (str p "Subscript"))
                     (print-ast (:value node) (inc depth))
                     (print-ast (:index node) (inc depth)))

       (println (str p (.getSimpleName (class node)) " (no printer)"))))))

;; ══════════════════════════════════════════════════════════════════════════
;; §10  PIPELINE  (source -> tokens -> AST -> execute)
;; ══════════════════════════════════════════════════════════════════════════

(defn run-source
  "Full pipeline: source text -> tokens -> AST -> execute.
   Returns the interpreter so the REPL can share state across lines."
  ([source] (run-source source (new-interpreter)))
  ([source interp]
   (let [tokens (lex source)
         program (parse tokens)]
     (run-program! interp program)
     interp)))

(defn run-source-with-ast
  "Run source and also print the AST before execution."
  [source]
  (let [tokens (lex source)
        program (parse tokens)]
    (println "\n── AST ─────────────────────────────────────────────")
    (print-ast program)
    (println "────────────────────────────────────────────────────\n")
    (run-source source)))

;; ══════════════════════════════════════════════════════════════════════════
;; §11  REPL
;; ══════════════════════════════════════════════════════════════════════════

(def banner
  (str "\033[96m╔══════════════════════════════════════════════════════╗\n"
       "║           Py  —  cational Interpreter          ║\n"
       "║  Type Py code below.  'exit' or Ctrl-D to quit.  ║\n"
       "║  'help' for a quick language reference.              ║\n"
       "╚══════════════════════════════════════════════════════╝\033[0m"))

(def help-text
  "
Py Quick Reference
─────────────────────
Variables:     x = 10          y = 3.14       s = \"hello\"
Arithmetic:    + - * / // % **
Comparison:    == != < <= > >=
Logic:         and  or  not
Strings:       \"hi\" + \" world\"   len(\"hello\")   str(42)
               \"Hi\".lower()      \"hi\".upper()
Lists:         lst = [1, 2, 3]   lst[0]   len(lst)   append(lst, 4)
Control flow:
  if x > 0:
      print(\"positive\")
  elif x == 0:
      print(\"zero\")
  else:
      print(\"negative\")

  while x > 0:
      x -= 1

  for i in range(5):
      print(i)

Functions:
  def greet(name):
      return \"Hello, \" + name

  print(greet(\"world\"))

Builtins: print len range int float str bool abs max min type input append pop
String methods: .lower()  .upper()
")

(defn- needs-more? [source]
  (let [lines (->> (str/split-lines source)
                    (filter #(and (seq (str/trim %)) (not (str/starts-with? (str/trim %) "#")))))]
    (if (empty? lines)
      false
      (str/ends-with? (str/trimr (last lines)) ":"))))

(defn- report-exception [e]
  (if (py-error? e)
    (println (.getMessage ^Throwable e))
    (println (str "\033[91mInternalError\033[0m: " (.getMessage ^Throwable e)))))

(defn repl []
  (println banner)
  (let [interp (new-interpreter)]
    (loop [buf []]
      (print (if (empty? buf) ">>> " "... "))
      (flush)
      (let [line (read-line)]
        (cond
          (nil? line)
          (println "\nBye!")

          (and (empty? buf) (= (str/trim line) "exit"))
          (println "Bye!")

          (and (empty? buf) (= (str/trim line) "help"))
          (do (println help-text) (recur buf))

          (and (empty? buf) (= (str/trim line) ""))
          (recur buf)

          :else
          (let [buf2 (conj buf line)
                source (str/join "\n" buf2)
                stripped (str/trimr line)]
            (if (or (str/ends-with? stripped ":") (needs-more? source))
              (recur buf2)
              (do
                (try
                  (run-source (str source "\n") interp)
                  (catch clojure.lang.ExceptionInfo e (report-exception e))
                  (catch Exception e (report-exception e)))
                (recur [])))))))))

;; ══════════════════════════════════════════════════════════════════════════
;; §12  CLI ENTRY POINT
;; ══════════════════════════════════════════════════════════════════════════

(defn -main [& args]
  (if (empty? args)
    (repl)
    (let [show-ast (boolean (some #(= % "--ast") args))
          files (remove #(str/starts-with? % "--") args)]
      (if (empty? files)
        (do (println "Usage: bb core.clj [script.ep] [--ast]")
            (System/exit 1))
        (let [filepath (first files)
              f (java.io.File. ^String filepath)]
          (if-not (.exists f)
            (do (println (str "\033[91mFileNotFoundError\033[0m: No such file: " (pr-str filepath)))
                (System/exit 1))
            (let [source (slurp filepath)]
              (try
                (if show-ast
                  (run-source-with-ast source)
                  (run-source source))
                (catch clojure.lang.ExceptionInfo e (report-exception e) (System/exit 1))
                (catch Exception e (report-exception e) (System/exit 1))))))))))

(apply -main *command-line-args*)