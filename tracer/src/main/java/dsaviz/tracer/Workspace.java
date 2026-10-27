package dsaviz.tracer;

import com.google.gson.JsonArray;
import com.google.gson.JsonObject;

import javax.tools.Diagnostic;
import javax.tools.DiagnosticCollector;
import javax.tools.JavaCompiler;
import javax.tools.JavaFileObject;
import javax.tools.StandardJavaFileManager;
import javax.tools.ToolProvider;
import java.io.IOException;
import java.io.InputStream;
import java.io.UncheckedIOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.Locale;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import java.util.stream.Stream;

/** A temporary directory holding the user's code, LeetCode helper classes, and the compiled output. */
final class Workspace implements AutoCloseable {

    /**
     * LeetCode imports these implicitly. They go on line 1 so the user's line numbers stay unchanged.
     */
    static final String IMPORTS = "import java.util.*; import java.util.function.*; import java.util.stream.*; import java.math.*; ";

    private static final Pattern PACKAGE = Pattern.compile("^\\s*package\\s+[\\w.]+\\s*;", Pattern.MULTILINE);
    private static final List<String> HELPERS = List.of("ListNode", "TreeNode");

    final Path root;
    final Path classes;
    final String userFileName;
    private final String userSource;

    Workspace(String code, SourceInfo info) throws IOException {
        root = Files.createTempDirectory("dsaviz-");
        classes = Files.createDirectories(root.resolve("classes"));
        userFileName = (info.publicTopLevel != null ? info.publicTopLevel : "UserCode") + ".java";
        userSource = IMPORTS + blankPackage(code);
        Files.writeString(root.resolve(userFileName), userSource);
        for (String helper : HELPERS) {
            if (!info.declaredSimpleNames().contains(helper)) copyResource(helper + ".java");
        }
        copyResource("__LC.java");
        copyResource("__Out.java");
    }

    void writeMain(String source) throws IOException {
        Files.writeString(root.resolve("__Main.java"), source);
    }

    /** Compiles every source in the workspace. Returns the errors that point into the user's file. */
    JsonArray compile() throws IOException {
        JavaCompiler compiler = ToolProvider.getSystemJavaCompiler();
        DiagnosticCollector<JavaFileObject> diagnostics = new DiagnosticCollector<>();
        List<Path> sources;
        try (Stream<Path> files = Files.list(root)) {
            sources = files.filter(p -> p.toString().endsWith(".java")).sorted().toList();
        }
        try (StandardJavaFileManager fm = compiler.getStandardFileManager(diagnostics, Locale.ENGLISH, StandardCharsets.UTF_8)) {
            List<String> options = List.of("-g", "-proc:none", "-nowarn", "-encoding", "UTF-8", "-d", classes.toString());
            compiler.getTask(null, fm, diagnostics, options, null, fm.getJavaFileObjectsFromPaths(sources)).call();
        }
        JsonArray errors = new JsonArray();
        List<String> lines = userSource.lines().toList();
        for (Diagnostic<? extends JavaFileObject> d : diagnostics.getDiagnostics()) {
            if (d.getKind() != Diagnostic.Kind.ERROR) continue;
            JsonObject e = new JsonObject();
            boolean inUserFile = d.getSource() != null && d.getSource().getName().endsWith(userFileName);
            e.addProperty("message", d.getMessage(Locale.ENGLISH));
            if (inUserFile && d.getLineNumber() > 0) {
                int line = (int) d.getLineNumber();
                int shift = line == 1 ? IMPORTS.length() : 0;
                int col = (int) Math.max(1, d.getColumnNumber() - shift);
                e.addProperty("line", line);
                e.addProperty("column", col);
                long length = Math.max(1, d.getEndPosition() - d.getStartPosition());
                String text = line - 1 < lines.size() ? lines.get(line - 1) : "";
                int lineLength = Math.max(col, text.length() - shift + 1);
                e.addProperty("endColumn", (int) Math.min(lineLength + 1, col + length));
            } else {
                e.addProperty("line", 0);
                e.addProperty("column", 0);
                e.addProperty("endColumn", 0);
            }
            errors.add(e);
        }
        return errors;
    }

    private void copyResource(String name) throws IOException {
        try (InputStream in = Workspace.class.getResourceAsStream("/harness/" + name)) {
            if (in == null) throw new IOException("missing harness resource " + name);
            Files.write(root.resolve(name), in.readAllBytes());
        }
    }

    /** Replaces a package declaration with spaces so the code compiles in the default package without moving lines. */
    private static String blankPackage(String code) {
        Matcher m = PACKAGE.matcher(code);
        if (!m.find()) return code;
        return code.substring(0, m.start()) + " ".repeat(m.end() - m.start()) + code.substring(m.end());
    }

    @Override
    public void close() {
        try (Stream<Path> paths = Files.walk(root)) {
            List<Path> all = new ArrayList<>(paths.toList());
            all.sort(Comparator.reverseOrder());
            for (Path p : all) Files.deleteIfExists(p);
        } catch (IOException e) {
            throw new UncheckedIOException(e);
        }
    }
}
