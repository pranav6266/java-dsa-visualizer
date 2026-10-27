package dsaviz.tracer;

import com.github.javaparser.StaticJavaParser;
import com.github.javaparser.ast.type.ArrayType;
import com.github.javaparser.ast.type.ClassOrInterfaceType;
import com.github.javaparser.ast.type.PrimitiveType;
import com.github.javaparser.ast.type.Type;
import com.google.gson.JsonArray;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import com.google.gson.JsonPrimitive;
import com.google.gson.JsonSyntaxException;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/** Turns LeetCode-format input text into a generated {@code __Main} that builds the inputs and calls the method. */
final class InputBuilder {

    /** Thrown for input text that doesn't fit the parameter's type; the message is shown next to the input field. */
    static final class InputException extends Exception {
        final String param;

        InputException(String param, String message) {
            super(message);
            this.param = param;
        }
    }

    private static final Pattern CYCLE = Pattern.compile("^(.*\\])\\s*,?\\s*pos\\s*=\\s*(-?\\d+)\\s*$", Pattern.DOTALL);

    private final SourceInfo info;
    private String param;

    InputBuilder(SourceInfo info) {
        this.info = info;
    }

    String mainSource(SourceInfo.MethodInfo method, Map<String, String> inputs) throws InputException {
        StringBuilder body = new StringBuilder();
        List<String> args = new ArrayList<>();
        for (SourceInfo.Param p : method.params()) {
            param = p.name();
            String text = inputs.getOrDefault(p.name(), "").trim();
            if (text.isEmpty()) throw new InputException(p.name(), "Enter a value for " + p.name());
            Type type = StaticJavaParser.parseType(p.type());
            String expr = buildTop(type, text);
            String local = "__in_" + p.name();
            body.append("        ").append(sourceType(type)).append(' ').append(local).append(" = ").append(expr).append(";\n");
            args.add(local);
        }
        String target = method.isStatic() ? method.cls() : "new " + method.cls() + "()";
        String call = target + "." + method.name() + "(" + String.join(", ", args) + ");";
        return Workspace.IMPORTS + "\npublic class __Main {\n"
                + "    public static void main(String[] __args) throws Throwable {\n"
                + "        System.setOut(new java.io.PrintStream(new __Out(new java.io.FileOutputStream(java.io.FileDescriptor.out)),"
                + " true, java.nio.charset.StandardCharsets.UTF_8));\n"
                + body
                + "        " + call + "\n"
                + "    }\n}\n";
    }

    private String buildTop(Type type, String text) throws InputException {
        int cyclePos = -1;
        if (linkedClass(type).isPresent()) {
            Matcher m = CYCLE.matcher(text);
            if (m.matches()) {
                text = m.group(1);
                cyclePos = Integer.parseInt(m.group(2));
            }
        }
        JsonElement value;
        try {
            value = JsonParser.parseString(text);
        } catch (JsonSyntaxException e) {
            if (isString(type)) return javaString(text);
            throw fail("isn't valid input. Use LeetCode format, like [1,2,3] or \"abc\"");
        }
        if (cyclePos >= 0) return linked(type, value, cyclePos);
        return expr(type, value);
    }

    private String expr(Type type, JsonElement v) throws InputException {
        if (v.isJsonNull()) {
            if (type instanceof PrimitiveType) throw fail("can't be null");
            return "null";
        }
        if (type instanceof PrimitiveType p) return primitive(p.getType().asString(), v);
        if (type instanceof ArrayType a) {
            if (!v.isJsonArray()) throw fail("should be an array, like [1,2,3]");
            List<String> items = new ArrayList<>();
            for (JsonElement e : v.getAsJsonArray()) items.add(expr(a.getComponentType(), e));
            return "new " + sourceType(a) + "{" + String.join(", ", items) + "}";
        }
        ClassOrInterfaceType c = type.asClassOrInterfaceType();
        String name = c.getNameAsString();
        switch (name) {
            case "Integer", "Long", "Short", "Byte", "Double", "Float", "Boolean", "Character" -> {
                return primitive(unbox(name), v);
            }
            case "String", "CharSequence" -> {
                if (!v.isJsonPrimitive()) throw fail("should be a string, like \"abc\"");
                return javaString(v.getAsString());
            }
            case "List", "ArrayList", "LinkedList", "Collection", "Iterable", "Queue", "Deque", "ArrayDeque",
                 "Set", "HashSet", "LinkedHashSet", "TreeSet", "Stack" -> {
                return collection(c, v);
            }
            case "Map", "HashMap", "LinkedHashMap", "TreeMap" -> {
                return map(c, v);
            }
            default -> { }
        }
        if (treeClass(type).isPresent()) return tree(type, v);
        if (linkedClass(type).isPresent()) return linked(type, v, -1);
        throw fail("has type " + type.asString() + ", which the visualizer can't build from text yet");
    }

    private String collection(ClassOrInterfaceType c, JsonElement v) throws InputException {
        if (!v.isJsonArray()) throw fail("should be a list, like [1,2,3]");
        Type elem = typeArg(c, 0);
        List<String> items = new ArrayList<>();
        for (JsonElement e : v.getAsJsonArray()) items.add(expr(elem, e));
        String elemType = sourceType(elem);
        String list = "__LC.<" + elemType + ">listOf(" + String.join(", ", items) + ")";
        return switch (c.getNameAsString()) {
            case "List", "Collection", "Iterable" -> list;
            case "Queue", "Deque", "ArrayDeque" -> "new ArrayDeque<" + elemType + ">(" + list + ")";
            case "Set", "HashSet" -> "new HashSet<" + elemType + ">(" + list + ")";
            case "Stack" -> "__LC.stackOf(" + list + ")";
            default -> "new " + c.getNameAsString() + "<" + elemType + ">(" + list + ")";
        };
    }

    private String map(ClassOrInterfaceType c, JsonElement v) throws InputException {
        Type keyType = typeArg(c, 0);
        Type valueType = typeArg(c, 1);
        List<String> parts = new ArrayList<>();
        if (v.isJsonObject()) {
            for (Map.Entry<String, JsonElement> e : v.getAsJsonObject().entrySet()) {
                parts.add(expr(keyType, keyElement(keyType, e.getKey())));
                parts.add(expr(valueType, e.getValue()));
            }
        } else if (v.isJsonArray()) {
            for (JsonElement pair : v.getAsJsonArray()) {
                if (!pair.isJsonArray() || pair.getAsJsonArray().size() != 2) throw fail("should be {\"key\": value} or [[key, value], ...]");
                parts.add(expr(keyType, pair.getAsJsonArray().get(0)));
                parts.add(expr(valueType, pair.getAsJsonArray().get(1)));
            }
        } else {
            throw fail("should be a map, like {\"a\": 1}");
        }
        String generic = "<" + sourceType(keyType) + ", " + sourceType(valueType) + ">";
        String built = "__LC." + generic + "mapOf(" + String.join(", ", parts) + ")";
        String name = c.getNameAsString();
        return name.equals("Map") || name.equals("HashMap") ? built : "new " + name + generic + "(" + built + ")";
    }

    private static JsonElement keyElement(Type keyType, String key) {
        String n = keyType.asString();
        if (n.equals("String") || n.equals("Character")) return new JsonPrimitive(key);
        try {
            return JsonParser.parseString(key);
        } catch (JsonSyntaxException e) {
            return new JsonPrimitive(key);
        }
    }

    private String linked(Type type, JsonElement v, int cyclePos) throws InputException {
        if (!v.isJsonArray()) throw fail("should be a list of values, like [1,2,3]");
        String cls = linkedClass(type).orElseThrow();
        return "__LC.linked(" + cls + ".class, " + nodeValues(cls, v.getAsJsonArray()) + ", " + cyclePos + ")";
    }

    private String tree(Type type, JsonElement v) throws InputException {
        if (!v.isJsonArray()) throw fail("should be level-order values, like [3,9,20,null,null,15,7]");
        String cls = treeClass(type).orElseThrow();
        return "__LC.tree(" + cls + ".class, " + nodeValues(cls, v.getAsJsonArray()) + ")";
    }

    private String nodeValues(String cls, JsonArray values) throws InputException {
        Type valueType = StaticJavaParser.parseType(boxed(nodeValueType(cls)));
        List<String> items = new ArrayList<>();
        for (JsonElement e : values) items.add(expr(valueType, e));
        return "new Object[]{" + String.join(", ", items) + "}";
    }

    /** The source-level name of a node class with a self-typed {@code next} field, if {@code type} is one. */
    private Optional<String> linkedClass(Type type) {
        return nodeClass(type).filter(c -> selfFields(c).size() >= 1 && !isTreeShape(c));
    }

    private Optional<String> treeClass(Type type) {
        return nodeClass(type).filter(this::isTreeShape);
    }

    private boolean isTreeShape(String cls) {
        List<String> self = selfFields(cls);
        return self.contains("left") || self.contains("right");
    }

    private Optional<String> nodeClass(Type type) {
        if (!type.isClassOrInterfaceType()) return Optional.empty();
        String simple = type.asClassOrInterfaceType().getNameAsString();
        if (info.declared(simple).isPresent()) {
            String binary = info.declared(simple).get().qualifiedName();
            return Optional.of(binary.replace('$', '.'));
        }
        if (simple.equals("ListNode") || simple.equals("TreeNode")) return Optional.of(simple);
        return Optional.empty();
    }

    private List<SourceInfo.Param> fieldsOf(String cls) {
        String simple = cls.substring(cls.lastIndexOf('.') + 1);
        return info.declared(simple).map(SourceInfo.DeclaredClass::fields).orElseGet(() -> switch (simple) {
            case "ListNode" -> List.of(new SourceInfo.Param("val", "int"), new SourceInfo.Param("next", "ListNode"));
            case "TreeNode" -> List.of(new SourceInfo.Param("val", "int"), new SourceInfo.Param("left", "TreeNode"),
                    new SourceInfo.Param("right", "TreeNode"));
            default -> List.of();
        });
    }

    private List<String> selfFields(String cls) {
        String simple = cls.substring(cls.lastIndexOf('.') + 1);
        return fieldsOf(cls).stream().filter(f -> f.type().equals(simple)).map(SourceInfo.Param::name).toList();
    }

    private String nodeValueType(String cls) throws InputException {
        String simple = cls.substring(cls.lastIndexOf('.') + 1);
        List<SourceInfo.Param> values = fieldsOf(cls).stream().filter(f -> !f.type().equals(simple)).toList();
        for (SourceInfo.Param f : values) {
            if (List.of("val", "value", "data", "key").contains(f.name())) return f.type();
        }
        if (values.isEmpty()) throw fail("uses class " + simple + ", which has no value field");
        return values.get(0).type();
    }

    private String primitive(String kind, JsonElement v) throws InputException {
        if (!v.isJsonPrimitive()) throw fail("should be a single " + kind + " value");
        JsonPrimitive p = v.getAsJsonPrimitive();
        switch (kind) {
            case "boolean" -> {
                if (!p.isBoolean()) throw fail("should be true or false");
                return Boolean.toString(p.getAsBoolean());
            }
            case "char" -> {
                String s = p.getAsString();
                if (s.length() != 1) throw fail("should be a single character, like \"a\"");
                return javaChar(s.charAt(0));
            }
            case "double", "float" -> {
                if (!p.isNumber()) throw fail("should be a number");
                return p.getAsDouble() + (kind.equals("float") ? "f" : "d");
            }
            default -> {
                if (!p.isNumber()) throw fail("should be a whole number");
                double d = p.getAsDouble();
                if (d != Math.rint(d)) throw fail("should be a whole number");
                long n = p.getAsLong();
                return switch (kind) {
                    case "long" -> n + "L";
                    case "short" -> "(short) " + n;
                    case "byte" -> "(byte) " + n;
                    default -> {
                        if (n < Integer.MIN_VALUE || n > Integer.MAX_VALUE) throw fail("is too big for an int");
                        yield Long.toString(n);
                    }
                };
            }
        }
    }

    private Type typeArg(ClassOrInterfaceType c, int i) {
        return c.getTypeArguments().filter(args -> args.size() > i).map(args -> args.get(i))
                .orElseGet(() -> StaticJavaParser.parseType("Object"));
    }

    private static String sourceType(Type t) {
        return t.asString();
    }

    private static boolean isString(Type t) {
        return t.isClassOrInterfaceType() && t.asClassOrInterfaceType().getNameAsString().equals("String");
    }

    private static String unbox(String boxed) {
        return switch (boxed) {
            case "Integer" -> "int";
            case "Character" -> "char";
            default -> boxed.toLowerCase();
        };
    }

    private static String boxed(String type) {
        return switch (type) {
            case "int" -> "Integer";
            case "char" -> "Character";
            case "long", "short", "byte", "double", "float", "boolean" ->
                    Character.toUpperCase(type.charAt(0)) + type.substring(1);
            default -> type;
        };
    }

    private InputException fail(String message) {
        return new InputException(param, param + " " + message);
    }

    static String javaString(String s) {
        StringBuilder b = new StringBuilder("\"");
        for (char ch : s.toCharArray()) b.append(escape(ch, '"'));
        return b.append('"').toString();
    }

    private static String javaChar(char ch) {
        return "'" + escape(ch, '\'') + "'";
    }

    private static String escape(char ch, char quote) {
        if (ch == quote || ch == '\\') return "\\" + ch;
        if (ch == '\n') return "\\n";
        if (ch == '\t') return "\\t";
        if (ch == '\r') return "\\r";
        if (ch < 0x20 || ch > 0x7e) return String.format("\\u%04x", (int) ch);
        return String.valueOf(ch);
    }

    static JsonObject errorJson(InputException e) {
        JsonObject o = new JsonObject();
        o.addProperty("param", e.param);
        o.addProperty("message", e.getMessage());
        return o;
    }
}
