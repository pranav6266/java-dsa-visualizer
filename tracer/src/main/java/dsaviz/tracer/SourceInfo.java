package dsaviz.tracer;

import com.github.javaparser.JavaParser;
import com.github.javaparser.ParseResult;
import com.github.javaparser.ParserConfiguration;
import com.github.javaparser.ast.CompilationUnit;
import com.github.javaparser.ast.Modifier;
import com.github.javaparser.ast.Node;
import com.github.javaparser.ast.body.ClassOrInterfaceDeclaration;
import com.github.javaparser.ast.body.FieldDeclaration;
import com.github.javaparser.ast.body.MethodDeclaration;
import com.github.javaparser.ast.body.Parameter;
import com.github.javaparser.ast.body.TypeDeclaration;
import com.github.javaparser.ast.expr.ArrayAccessExpr;
import com.github.javaparser.ast.expr.Expression;
import com.github.javaparser.ast.expr.FieldAccessExpr;
import com.github.javaparser.ast.expr.MethodCallExpr;
import com.github.javaparser.ast.expr.NameExpr;
import com.github.javaparser.ast.stmt.DoStmt;
import com.github.javaparser.ast.stmt.ForEachStmt;
import com.github.javaparser.ast.stmt.ForStmt;
import com.github.javaparser.ast.stmt.Statement;
import com.github.javaparser.ast.stmt.WhileStmt;
import com.google.gson.JsonArray;
import com.google.gson.JsonObject;

import java.util.ArrayList;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Optional;
import java.util.Set;

/** Static facts about the user's source: methods to run, loops, declared types, and array index uses. */
final class SourceInfo {

    record Param(String name, String type) {}

    record MethodInfo(String cls, String name, List<Param> params, String returnType, boolean isStatic,
                      int startLine, int endLine) {}

    record DeclaredClass(String name, String qualifiedName, boolean nested, List<Param> fields) {}

    final boolean parsed;
    final String packageName;
    final String publicTopLevel;
    final List<MethodInfo> methods = new ArrayList<>();
    final List<DeclaredClass> classes = new ArrayList<>();
    final JsonArray loops = new JsonArray();
    final JsonArray indexUses = new JsonArray();

    private SourceInfo(boolean parsed, String packageName, String publicTopLevel) {
        this.parsed = parsed;
        this.packageName = packageName;
        this.publicTopLevel = publicTopLevel;
    }

    static SourceInfo of(String source) {
        ParserConfiguration config = new ParserConfiguration()
                .setLanguageLevel(ParserConfiguration.LanguageLevel.JAVA_21);
        ParseResult<CompilationUnit> result = new JavaParser(config).parse(source);
        if (!result.isSuccessful() || result.getResult().isEmpty()) {
            return new SourceInfo(false, null, null);
        }
        CompilationUnit cu = result.getResult().get();
        String pkg = cu.getPackageDeclaration().map(p -> p.getNameAsString()).orElse(null);
        String publicTop = cu.getTypes().stream()
                .filter(t -> t.hasModifier(Modifier.Keyword.PUBLIC))
                .map(TypeDeclaration::getNameAsString)
                .findFirst().orElse(null);
        SourceInfo info = new SourceInfo(true, pkg, publicTop);
        info.collectClasses(cu);
        info.collectMethods(cu);
        info.collectLoops(cu);
        info.collectIndexUses(cu);
        return info;
    }

    /** Names of every class the user declared, top-level or nested (simple names). */
    Set<String> declaredSimpleNames() {
        Set<String> names = new LinkedHashSet<>();
        for (DeclaredClass c : classes) names.add(c.name());
        return names;
    }

    Optional<DeclaredClass> declared(String simpleName) {
        return classes.stream().filter(c -> c.name().equals(simpleName)).findFirst();
    }

    /** Binary names of top-level user classes, used for JDI class filters. */
    List<String> topLevelClassNames() {
        return classes.stream().filter(c -> !c.nested()).map(DeclaredClass::qualifiedName).toList();
    }

    private void collectClasses(CompilationUnit cu) {
        for (ClassOrInterfaceDeclaration decl : cu.findAll(ClassOrInterfaceDeclaration.class)) {
            List<Param> fields = new ArrayList<>();
            for (FieldDeclaration f : decl.getFields()) {
                if (f.isStatic()) continue;
                f.getVariables().forEach(v -> fields.add(new Param(v.getNameAsString(), v.getTypeAsString())));
            }
            boolean nested = decl.isNestedType();
            String binary = binaryName(decl);
            classes.add(new DeclaredClass(decl.getNameAsString(), binary, nested, fields));
        }
    }

    private static String binaryName(ClassOrInterfaceDeclaration decl) {
        StringBuilder name = new StringBuilder(decl.getNameAsString());
        Node parent = decl.getParentNode().orElse(null);
        while (parent instanceof ClassOrInterfaceDeclaration outer) {
            name.insert(0, outer.getNameAsString() + "$");
            parent = outer.getParentNode().orElse(null);
        }
        return name.toString();
    }

    private void collectMethods(CompilationUnit cu) {
        for (TypeDeclaration<?> type : cu.getTypes()) {
            if (!(type instanceof ClassOrInterfaceDeclaration cls) || cls.isInterface()) continue;
            for (MethodDeclaration m : cls.getMethods()) {
                if (m.isPrivate() || m.getBody().isEmpty()) continue;
                List<Param> params = new ArrayList<>();
                for (Parameter p : m.getParameters()) {
                    params.add(new Param(p.getNameAsString(), p.getTypeAsString() + (p.isVarArgs() ? "[]" : "")));
                }
                methods.add(new MethodInfo(cls.getNameAsString(), m.getNameAsString(), params,
                        m.getTypeAsString(), m.isStatic(), line(m, true), line(m, false)));
            }
        }
        // Prefer the LeetCode convention: methods of a class named Solution first, public ones before others.
        methods.sort((a, b) -> Integer.compare(rank(a), rank(b)));
    }

    private int rank(MethodInfo m) {
        int r = m.cls().equals("Solution") ? 0 : 10;
        return r + (m.name().equals("main") ? 5 : 0);
    }

    private void collectLoops(CompilationUnit cu) {
        for (Statement s : cu.findAll(Statement.class)) {
            String kind;
            int header;
            if (s instanceof ForStmt) { kind = "for"; header = line(s, true); }
            else if (s instanceof ForEachStmt) { kind = "foreach"; header = line(s, true); }
            else if (s instanceof WhileStmt) { kind = "while"; header = line(s, true); }
            else if (s instanceof DoStmt d) { kind = "do"; header = line(d.getCondition(), true); }
            else continue;
            JsonObject loop = new JsonObject();
            loop.addProperty("kind", kind);
            loop.addProperty("method", enclosingMethod(s));
            loop.addProperty("start", line(s, true));
            loop.addProperty("end", line(s, false));
            loop.addProperty("header", header);
            loops.add(loop);
        }
    }

    private void collectIndexUses(CompilationUnit cu) {
        for (ArrayAccessExpr access : cu.findAll(ArrayAccessExpr.class)) {
            int dim = 0;
            Expression base = access.getName();
            while (base instanceof ArrayAccessExpr inner) { base = inner.getName(); dim++; }
            String array = simpleName(base);
            if (array == null) continue;
            addIndexUses(array, access.getIndex(), dim, access);
        }
        for (MethodCallExpr call : cu.findAll(MethodCallExpr.class)) {
            String name = call.getNameAsString();
            if (!(name.equals("charAt") || name.equals("get") || name.equals("set")) || call.getArguments().isEmpty()) continue;
            String array = call.getScope().map(SourceInfo::simpleName).orElse(null);
            if (array == null) continue;
            addIndexUses(array, call.getArgument(0), 0, call);
        }
    }

    /** Records {@code array[var]}: only a bare variable index, so the variable's value is exactly the cell it points at. */
    private void addIndexUses(String array, Expression index, int dim, Node at) {
        Expression e = index;
        while (e.isEnclosedExpr()) e = e.asEnclosedExpr().getInner();
        if (!(e instanceof NameExpr n)) return;
        for (String var : List.of(n.getNameAsString())) {
            JsonObject use = new JsonObject();
            use.addProperty("array", array);
            use.addProperty("index", var);
            use.addProperty("dim", dim);
            use.addProperty("method", enclosingMethod(at));
            use.addProperty("line", line(at, true));
            indexUses.add(use);
        }
    }

    private static String simpleName(Expression e) {
        if (e instanceof NameExpr n) return n.getNameAsString();
        if (e instanceof FieldAccessExpr f) return f.getNameAsString();
        return null;
    }

    private static String enclosingMethod(Node n) {
        return n.findAncestor(MethodDeclaration.class).map(MethodDeclaration::getNameAsString).orElse("");
    }

    private static int line(Node n, boolean begin) {
        return n.getRange().map(r -> begin ? r.begin.line : r.end.line).orElse(0);
    }

    JsonObject methodsJson() {
        JsonArray arr = new JsonArray();
        for (MethodInfo m : methods) {
            JsonObject o = new JsonObject();
            o.addProperty("cls", m.cls());
            o.addProperty("name", m.name());
            o.addProperty("returnType", m.returnType());
            o.addProperty("static", m.isStatic());
            o.addProperty("startLine", m.startLine());
            o.addProperty("endLine", m.endLine());
            JsonArray ps = new JsonArray();
            for (Param p : m.params()) {
                JsonObject po = new JsonObject();
                po.addProperty("name", p.name());
                po.addProperty("type", p.type());
                ps.add(po);
            }
            o.add("params", ps);
            arr.add(o);
        }
        JsonObject out = new JsonObject();
        out.add("methods", arr);
        out.add("loops", loops);
        out.add("indexUses", indexUses);
        return out;
    }
}
