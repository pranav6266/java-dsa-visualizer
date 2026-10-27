package dsaviz.tracer;

import com.google.gson.Gson;
import com.google.gson.GsonBuilder;
import com.google.gson.JsonArray;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.io.PrintStream;
import java.nio.charset.StandardCharsets;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Optional;

/**
 * Entry point. Reads one JSON request and writes one JSON response.
 *
 * <ul>
 *   <li>{@code analyze}: parse and compile, returning methods, loops and compile errors.</li>
 *   <li>{@code run}: also build the inputs, run the method under the debugger and return the trace.</li>
 *   <li>{@code serve}: answer newline-delimited requests (each with an {@code op}) until stdin closes.</li>
 * </ul>
 */
public final class Main {

    private static final Gson GSON = new GsonBuilder().serializeNulls().disableHtmlEscaping().create();

    public static void main(String[] args) throws Exception {
        String mode = args.length > 0 ? args[0] : "serve";
        PrintStream out = new PrintStream(System.out, true, StandardCharsets.UTF_8);
        BufferedReader in = new BufferedReader(new InputStreamReader(System.in, StandardCharsets.UTF_8));
        if (mode.equals("serve")) {
            String line;
            while ((line = in.readLine()) != null) {
                if (line.isBlank()) continue;
                JsonObject request = JsonParser.parseString(line).getAsJsonObject();
                out.println(GSON.toJson(handle(request.get("op").getAsString(), request)));
            }
            return;
        }
        JsonObject request = JsonParser.parseReader(in).getAsJsonObject();
        out.println(GSON.toJson(handle(mode, request)));
    }

    private static JsonObject handle(String op, JsonObject request) {
        try {
            return switch (op) {
                case "analyze" -> analyze(request);
                case "run" -> run(request);
                default -> failure("unknown op " + op);
            };
        } catch (Exception e) {
            return failure(e.toString());
        }
    }

    private static JsonObject analyze(JsonObject request) throws Exception {
        String code = request.get("code").getAsString();
        SourceInfo info = SourceInfo.of(code);
        JsonObject out = info.parsed ? info.methodsJson() : emptyAnalysis();
        try (Workspace ws = new Workspace(code, info)) {
            out.add("diagnostics", ws.compile());
        }
        out.addProperty("ok", true);
        return out;
    }

    private static JsonObject run(JsonObject request) throws Exception {
        String code = request.get("code").getAsString();
        SourceInfo info = SourceInfo.of(code);
        JsonObject out = info.parsed ? info.methodsJson() : emptyAnalysis();
        out.addProperty("ok", true);
        try (Workspace ws = new Workspace(code, info)) {
            Optional<SourceInfo.MethodInfo> method = findMethod(info, request);
            if (!info.parsed || method.isEmpty()) {
                out.add("diagnostics", ws.compile());
                if (out.getAsJsonArray("diagnostics").isEmpty()) {
                    out.add("inputError", inputError(null, "Choose a method to run"));
                }
                return out;
            }
            try {
                ws.writeMain(new InputBuilder(info).mainSource(method.get(), inputs(request)));
            } catch (InputBuilder.InputException e) {
                out.add("diagnostics", ws.compile());
                out.add("inputError", InputBuilder.errorJson(e));
                return out;
            }
            JsonArray diagnostics = ws.compile();
            out.add("diagnostics", diagnostics);
            if (!diagnostics.isEmpty()) {
                boolean userErrors = diagnostics.asList().stream().anyMatch(d -> d.getAsJsonObject().get("line").getAsInt() > 0);
                if (!userErrors) {
                    out.add("inputError", inputError(null, "The inputs don't match the method's parameter types: "
                            + diagnostics.get(0).getAsJsonObject().get("message").getAsString()));
                    out.add("diagnostics", new JsonArray());
                }
                return out;
            }
            int maxSteps = request.has("maxSteps") ? request.get("maxSteps").getAsInt() : 10_000;
            long timeoutMs = request.has("timeoutMs") ? request.get("timeoutMs").getAsLong() : 10_000;
            Recorder recorder = new Recorder(ws.classes, method.get(), info.topLevelClassNames(), maxSteps, timeoutMs);
            JsonObject trace = recorder.record();
            JsonObject entry = new JsonObject();
            entry.addProperty("cls", method.get().cls());
            entry.addProperty("method", method.get().name());
            trace.add("entry", entry);
            out.add("trace", trace);
            return out;
        }
    }

    private static Optional<SourceInfo.MethodInfo> findMethod(SourceInfo info, JsonObject request) {
        if (!request.has("method") || request.get("method").isJsonNull()) {
            return info.methods.stream().findFirst();
        }
        String name = request.get("method").getAsString();
        String cls = request.has("cls") && !request.get("cls").isJsonNull() ? request.get("cls").getAsString() : null;
        return info.methods.stream()
                .filter(m -> m.name().equals(name) && (cls == null || m.cls().equals(cls)))
                .findFirst();
    }

    private static Map<String, String> inputs(JsonObject request) {
        Map<String, String> inputs = new LinkedHashMap<>();
        if (request.has("inputs")) {
            for (Map.Entry<String, JsonElement> e : request.getAsJsonObject("inputs").entrySet()) {
                inputs.put(e.getKey(), e.getValue().isJsonNull() ? "" : e.getValue().getAsString());
            }
        }
        return inputs;
    }

    private static JsonObject inputError(String param, String message) {
        JsonObject o = new JsonObject();
        o.addProperty("param", param);
        o.addProperty("message", message);
        return o;
    }

    private static JsonObject emptyAnalysis() {
        JsonObject o = new JsonObject();
        o.add("methods", new JsonArray());
        o.add("loops", new JsonArray());
        o.add("indexUses", new JsonArray());
        return o;
    }

    private static JsonObject failure(String message) {
        JsonObject o = new JsonObject();
        o.addProperty("ok", false);
        o.addProperty("message", message);
        return o;
    }
}
