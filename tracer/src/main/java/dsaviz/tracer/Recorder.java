package dsaviz.tracer;

import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import com.sun.jdi.AbsentInformationException;
import com.sun.jdi.ArrayReference;
import com.sun.jdi.Bootstrap;
import com.sun.jdi.BooleanValue;
import com.sun.jdi.CharValue;
import com.sun.jdi.Field;
import com.sun.jdi.IncompatibleThreadStateException;
import com.sun.jdi.LocalVariable;
import com.sun.jdi.Location;
import com.sun.jdi.Method;
import com.sun.jdi.ObjectReference;
import com.sun.jdi.PrimitiveValue;
import com.sun.jdi.ReferenceType;
import com.sun.jdi.StackFrame;
import com.sun.jdi.StringReference;
import com.sun.jdi.ThreadReference;
import com.sun.jdi.VMDisconnectedException;
import com.sun.jdi.Value;
import com.sun.jdi.VirtualMachine;
import com.sun.jdi.connect.Connector;
import com.sun.jdi.connect.LaunchingConnector;
import com.sun.jdi.event.BreakpointEvent;
import com.sun.jdi.event.ClassPrepareEvent;
import com.sun.jdi.event.Event;
import com.sun.jdi.event.EventSet;
import com.sun.jdi.event.ExceptionEvent;
import com.sun.jdi.event.MethodEntryEvent;
import com.sun.jdi.event.MethodExitEvent;
import com.sun.jdi.event.StepEvent;
import com.sun.jdi.event.VMDeathEvent;
import com.sun.jdi.event.VMDisconnectEvent;
import com.sun.jdi.request.BreakpointRequest;
import com.sun.jdi.request.ClassPrepareRequest;
import com.sun.jdi.request.EventRequest;
import com.sun.jdi.request.EventRequestManager;
import com.sun.jdi.request.ExceptionRequest;
import com.sun.jdi.request.MethodEntryRequest;
import com.sun.jdi.request.MethodExitRequest;
import com.sun.jdi.request.StepRequest;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Path;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Deque;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * Runs the generated {@code __Main} in a debuggee JVM and records a snapshot of the stack and the reachable heap
 * before every line the user's code executes.
 */
final class Recorder {

    private static final int MAX_HEAP_OBJECTS = 1500;
    private static final int MAX_ARRAY_ITEMS = 400;
    private static final int MAX_FRAMES = 200;
    private static final int MAX_OUTPUT = 64 * 1024;
    private static final String[] EXCLUDED = {"java.*", "javax.*", "jdk.*", "sun.*", "com.sun.*", "__*"};
    private static final Set<String> BOXES = Set.of("java.lang.Integer", "java.lang.Long", "java.lang.Short",
            "java.lang.Byte", "java.lang.Double", "java.lang.Float", "java.lang.Boolean", "java.lang.Character");

    private final Path classesDir;
    private final SourceInfo.MethodInfo entry;
    private final List<String> userClasses;
    private final int maxSteps;
    private final long timeoutMs;

    private VirtualMachine vm;
    private ThreadReference thread;
    private StepRequest step;
    private final List<EventRequest> callRequests = new ArrayList<>();
    private final JsonArray steps = new JsonArray();
    private final JsonObject classes = new JsonObject();
    private JsonObject error;
    private JsonObject returned;

    /** Ids of the user's active calls, outermost first, kept in sync by method entry and exit events. */
    private final Deque<Integer> callIds = new ArrayDeque<>();
    private final Deque<String> callNames = new ArrayDeque<>();
    private int nextCallId = 1;
    private int entryCallId;
    private final JsonArray pendingReturns = new JsonArray();
    private final List<ObjectReference> pendingRoots = new ArrayList<>();

    private final ByteArrayOutputStream stdout = new ByteArrayOutputStream();
    private boolean stdoutTruncated;
    private final StringBuilder stderr = new StringBuilder();

    /** The static counter of the debuggee's {@code __Out}, looked up once it is loaded. */
    private ReferenceType outType;
    private Field outWritten;

    Recorder(Path classesDir, SourceInfo.MethodInfo entry, List<String> userClasses, int maxSteps, long timeoutMs) {
        this.classesDir = classesDir;
        this.entry = entry;
        this.userClasses = userClasses;
        this.maxSteps = maxSteps;
        this.timeoutMs = timeoutMs;
    }

    JsonObject record() throws Exception {
        launch();
        long deadline = System.currentTimeMillis() + timeoutMs;
        EventRequestManager erm = vm.eventRequestManager();
        ClassPrepareRequest prepare = erm.createClassPrepareRequest();
        prepare.addClassFilter(entry.cls());
        prepare.enable();

        boolean running = true;
        while (running) {
            if (System.currentTimeMillis() > deadline) {
                fail("timeout", "Timeout", "Stopped after " + timeoutMs / 1000 + " seconds. Is there an infinite loop?");
                exitVm();
                break;
            }
            EventSet set = vm.eventQueue().remove(250);
            if (set == null) continue;
            boolean resume = true;
            for (Event event : set) {
                if (event instanceof VMDeathEvent || event instanceof VMDisconnectEvent) {
                    running = false;
                    resume = false;
                } else if (event instanceof ClassPrepareEvent e) {
                    onPrepare(e);
                } else if (event instanceof BreakpointEvent e) {
                    onBreakpoint(e);
                } else if (event instanceof MethodEntryEvent e) {
                    onEntry(e);
                } else if (event instanceof MethodExitEvent e) {
                    onExit(e);
                } else if (event instanceof StepEvent e) {
                    onStep(e);
                } else if (event instanceof ExceptionEvent e) {
                    onException(e);
                }
                if (error != null && error.get("kind").getAsString().equals("limit")) {
                    exitVm();
                    running = false;
                    resume = false;
                    break;
                }
            }
            if (resume) {
                try {
                    set.resume();
                } catch (VMDisconnectedException ignored) {
                    running = false;
                }
            }
        }
        waitForOutput();
        byte[] printed;
        synchronized (stdout) {
            printed = stdout.toByteArray();
        }
        toCharOffsets(printed);

        JsonObject out = new JsonObject();
        out.add("steps", steps);
        out.add("classes", classes);
        out.add("error", error);
        out.add("returned", returned);
        out.addProperty("stdout", new String(printed, StandardCharsets.UTF_8));
        out.addProperty("stdoutTruncated", stdoutTruncated);
        out.addProperty("stderr", stderr.toString());
        return out;
    }

    private void launch() throws Exception {
        LaunchingConnector connector = Bootstrap.virtualMachineManager().defaultConnector();
        Map<String, Connector.Argument> args = connector.defaultArguments();
        args.get("main").setValue("__Main");
        // JVM warnings go to stderr so stdout holds only what the user's code prints.
        args.get("options").setValue("-cp " + classesDir + " -Xss16m -XX:+ShowCodeDetailsInExceptionMessages -Xshare:auto"
                + " -Xlog:disable -Xlog:all=warning:stderr");
        vm = connector.launch(args);
        drain(vm.process().getInputStream(), (buf, n) -> {
            synchronized (stdout) {
                int room = MAX_OUTPUT - stdout.size();
                if (n > room) stdoutTruncated = true;
                stdout.write(buf, 0, Math.max(0, Math.min(n, room)));
            }
        });
        drain(vm.process().getErrorStream(), (buf, n) -> {
            synchronized (stderr) {
                if (stderr.length() < MAX_OUTPUT) stderr.append(new String(buf, 0, n, StandardCharsets.UTF_8));
            }
        });
    }

    private final List<Thread> drains = new ArrayList<>();

    private interface Sink {
        void accept(byte[] buf, int n);
    }

    /** Reads the stream to its end, even past the output cap, so the debuggee never blocks on a full pipe. */
    private void drain(InputStream in, Sink into) {
        Thread t = new Thread(() -> {
            byte[] buf = new byte[4096];
            try {
                int n;
                while ((n = in.read(buf)) > 0) into.accept(buf, n);
            } catch (IOException ignored) {
                // The debuggee exited.
            }
        });
        t.setDaemon(true);
        t.start();
        drains.add(t);
    }

    /** Bytes the user's code has printed so far, counted inside the debuggee so they line up with steps. */
    private long written() {
        if (outWritten == null) {
            List<ReferenceType> found = vm.classesByName("__Out");
            if (found.isEmpty()) return 0;
            outType = found.get(0);
            outWritten = outType.fieldByName("written");
        }
        return ((PrimitiveValue) outType.getValue(outWritten)).longValue();
    }

    /**
     * Rewrites each step's byte offset into stdout as a UTF-16 offset, which is how Java and the browser index
     * strings. Each print writes whole encoded characters, so every slice decodes cleanly.
     */
    private void toCharOffsets(byte[] printed) {
        int bytes = 0;
        int chars = 0;
        for (var element : steps) {
            JsonObject s = element.getAsJsonObject();
            int end = (int) Math.min(s.get("out").getAsLong(), printed.length);
            if (end > bytes) {
                chars += new String(printed, bytes, end - bytes, StandardCharsets.UTF_8).length();
                bytes = end;
            }
            s.addProperty("out", chars);
        }
    }

    private void waitForOutput() throws InterruptedException {
        for (Thread t : drains) t.join(1000);
    }

    private void onPrepare(ClassPrepareEvent e) {
        ReferenceType type = e.referenceType();
        Method target = null;
        for (Method m : type.methodsByName(entry.name())) {
            if (m.argumentTypeNames().size() != entry.params().size() || m.isAbstract()) continue;
            if (target == null || typesMatch(m)) target = m;
        }
        if (target == null || target.location() == null) {
            fail("internal", "Internal", "Couldn't find method " + entry.name());
            return;
        }
        BreakpointRequest bp = vm.eventRequestManager().createBreakpointRequest(target.location());
        bp.setSuspendPolicy(EventRequest.SUSPEND_EVENT_THREAD);
        bp.enable();
    }

    private boolean typesMatch(Method m) {
        List<String> names = m.argumentTypeNames();
        for (int i = 0; i < names.size(); i++) {
            String declared = entry.params().get(i).type().replaceAll("<.*>", "");
            String actual = names.get(i);
            if (!actual.endsWith(declared)) return false;
        }
        return true;
    }

    private void onBreakpoint(BreakpointEvent e) throws Exception {
        if (thread != null) return;
        thread = e.thread();
        vm.eventRequestManager().deleteEventRequest(e.request());
        entryCallId = nextCallId++;
        callIds.addLast(entryCallId);
        callNames.addLast(entry.name());

        EventRequestManager erm = vm.eventRequestManager();
        for (String cls : userClasses) {
            for (String filter : List.of(cls, cls + "$*")) {
                MethodEntryRequest in = erm.createMethodEntryRequest();
                in.addClassFilter(filter);
                in.addThreadFilter(thread);
                in.setSuspendPolicy(EventRequest.SUSPEND_EVENT_THREAD);
                in.enable();
                MethodExitRequest out = erm.createMethodExitRequest();
                out.addClassFilter(filter);
                out.addThreadFilter(thread);
                out.setSuspendPolicy(EventRequest.SUSPEND_EVENT_THREAD);
                out.enable();
                callRequests.add(in);
                callRequests.add(out);
            }
        }
        ExceptionRequest ex = erm.createExceptionRequest(null, false, true);
        ex.addThreadFilter(thread);
        ex.setSuspendPolicy(EventRequest.SUSPEND_EVENT_THREAD);
        ex.enable();

        step = erm.createStepRequest(thread, StepRequest.STEP_LINE, StepRequest.STEP_INTO);
        for (String pattern : EXCLUDED) step.addClassExclusionFilter(pattern);
        step.setSuspendPolicy(EventRequest.SUSPEND_EVENT_THREAD);
        step.enable();

        snapshot("step", e.location());
    }

    private void onEntry(MethodEntryEvent e) {
        if (e.method().isStaticInitializer()) return;
        callIds.addLast(nextCallId++);
        callNames.addLast(e.method().name());
    }

    private void onExit(MethodExitEvent e) throws Exception {
        if (e.method().isStaticInitializer() || callIds.isEmpty()) return;
        int id = callIds.peekLast();
        JsonObject ret = new JsonObject();
        ret.addProperty("callId", id);
        ret.addProperty("method", e.method().name());
        boolean isVoid = e.method().returnTypeName().equals("void") || e.method().isConstructor();
        if (e.method().isConstructor()) {
            // Between `new` returning and the assignment, the object lives only on the operand stack; keep it visible.
            ObjectReference self = e.thread().frame(0).thisObject();
            if (self != null) pendingRoots.add(self);
        }
        if (!isVoid) {
            Value value = e.returnValue();
            ret.add("value", convert(value, null));
            if (value instanceof ObjectReference o && !(value instanceof StringReference)) pendingRoots.add(o);
        }
        if (id == entryCallId) {
            returned = isVoid ? null : ret.get("value").getAsJsonObject();
            pendingReturns.add(ret);
            snapshot("return", e.location());
            stopStepping();
        } else {
            pendingReturns.add(ret);
        }
        callIds.removeLast();
        callNames.removeLast();
    }

    private void onStep(StepEvent e) throws Exception {
        if (e.location().lineNumber() < 0) return;
        if (!isUserClass(e.location().declaringType().name())) return;
        if (steps.size() >= maxSteps) {
            fail("limit", "Step limit", "Stopped after " + maxSteps + " steps. Is there an infinite loop?");
            return;
        }
        snapshot("step", e.location());
    }

    private void onException(ExceptionEvent e) throws Exception {
        if (step == null) return;
        stopStepping();
        ObjectReference ex = e.exception();
        String type = ex.referenceType().name();
        String message = null;
        try {
            Method getMessage = ex.referenceType().methodsByName("getMessage", "()Ljava/lang/String;").get(0);
            Value v = ex.invokeMethod(thread, getMessage, List.of(), ObjectReference.INVOKE_SINGLE_THREADED);
            if (v instanceof StringReference s) message = s.value();
        } catch (Exception ignored) {
            // A message is helpful but not essential.
        }
        int line = topUserLine();
        error = new JsonObject();
        error.addProperty("kind", "runtime");
        error.addProperty("type", type);
        error.addProperty("message", message);
        error.addProperty("line", line);
        snapshot("exception", null);
        error.addProperty("step", steps.size() - 1);
    }

    private void stopStepping() {
        EventRequestManager erm = vm.eventRequestManager();
        if (step != null) erm.deleteEventRequest(step);
        erm.deleteEventRequests(callRequests);
        callRequests.clear();
        step = null;
    }

    private int topUserLine() throws IncompatibleThreadStateException {
        for (StackFrame f : thread.frames()) {
            if (isUserClass(f.location().declaringType().name())) return f.location().lineNumber();
        }
        return 0;
    }

    private boolean isUserClass(String name) {
        for (String cls : userClasses) {
            if (name.equals(cls) || name.startsWith(cls + "$")) return true;
        }
        return false;
    }

    private void fail(String kind, String type, String message) {
        error = new JsonObject();
        error.addProperty("kind", kind);
        error.addProperty("type", type);
        error.addProperty("message", message);
        error.addProperty("line", steps.isEmpty() ? 0 : steps.get(steps.size() - 1).getAsJsonObject().get("line").getAsInt());
        error.addProperty("step", steps.size() - 1);
    }

    private void exitVm() {
        try {
            vm.exit(1);
        } catch (Exception ignored) {
            // Already gone.
        }
    }

    // ---- snapshots ----------------------------------------------------------------------------------------------

    private Map<Long, JsonObject> heap;
    private Deque<ObjectReference> heapQueue;

    private void snapshot(String kind, Location at) throws Exception {
        heap = new LinkedHashMap<>();
        heapQueue = new ArrayDeque<>();
        List<StackFrame> all = thread.frames();
        List<StackFrame> user = new ArrayList<>();
        for (StackFrame f : all) {
            if (isUserClass(f.location().declaringType().name())) user.add(f);
            if (user.size() >= MAX_FRAMES) break;
        }
        List<Integer> ids = new ArrayList<>(callIds);
        List<String> names = new ArrayList<>(callNames);

        JsonArray frames = new JsonArray();
        for (int i = 0; i < user.size(); i++) {
            StackFrame f = user.get(i);
            Location loc = f.location();
            JsonObject frame = new JsonObject();
            int idIndex = ids.size() - 1 - i;
            boolean aligned = idIndex >= 0 && names.get(idIndex).equals(loc.method().name());
            frame.addProperty("callId", aligned ? ids.get(idIndex) : -(i + 1));
            frame.addProperty("cls", loc.declaringType().name());
            frame.addProperty("method", loc.method().name());
            frame.addProperty("line", loc.lineNumber());
            frame.add("locals", locals(f));
            frames.add(frame);
        }

        JsonObject statics = staticFields();
        for (ObjectReference root : pendingRoots) enqueue(root);
        pendingRoots.clear();
        drainHeap();

        JsonObject s = new JsonObject();
        s.addProperty("event", kind);
        s.addProperty("line", at != null ? at.lineNumber() : topUserLine());
        s.add("frames", frames);
        s.add("statics", statics);
        JsonObject heapJson = new JsonObject();
        heap.forEach((id, obj) -> heapJson.add(Long.toString(id), obj));
        s.add("heap", heapJson);
        s.add("returns", pendingReturns.deepCopy());
        s.addProperty("out", written());
        while (!pendingReturns.isEmpty()) pendingReturns.remove(0);
        steps.add(s);
    }

    private JsonArray locals(StackFrame f) {
        JsonArray out = new JsonArray();
        try {
            ObjectReference self = f.thisObject();
            if (self != null && !self.referenceType().allFields().stream().allMatch(Field::isStatic)) {
                out.add(local("this", self.referenceType().name(), self));
            }
            for (LocalVariable v : f.visibleVariables()) {
                out.add(local(v.name(), v.typeName(), f.getValue(v)));
            }
        } catch (AbsentInformationException ignored) {
            // Compiled without -g; never happens for user classes.
        }
        return out;
    }

    private JsonObject local(String name, String type, Value value) {
        JsonObject o = new JsonObject();
        o.addProperty("name", name);
        o.addProperty("type", type);
        o.add("value", convert(value, null));
        return o;
    }

    private JsonObject staticFields() {
        JsonObject out = new JsonObject();
        for (ReferenceType type : vm.allClasses()) {
            if (!isUserClass(type.name()) || !type.isPrepared()) continue;
            for (Field f : type.fields()) {
                if (!f.isStatic() || f.isSynthetic() || (f.isFinal() && isConstantType(f))) continue;
                out.add(simpleName(type.name()) + "." + f.name(), convert(type.getValue(f), null));
            }
        }
        return out;
    }

    private static boolean isConstantType(Field f) {
        String t = f.typeName();
        return t.equals("java.lang.String") || !t.contains(".") && !t.endsWith("]");
    }

    private void drainHeap() {
        while (!heapQueue.isEmpty() && heap.size() < MAX_HEAP_OBJECTS) {
            ObjectReference o = heapQueue.poll();
            if (heap.containsKey(o.uniqueID())) continue;
            JsonObject placeholder = new JsonObject();
            heap.put(o.uniqueID(), placeholder);
            JsonObject obj = serialize(o);
            heap.put(o.uniqueID(), obj);
        }
    }

    private void enqueue(ObjectReference o) {
        if (!heap.containsKey(o.uniqueID())) heapQueue.add(o);
    }

    /** Converts a JDI value to JSON. Objects become references that are serialized into the heap separately. */
    private JsonObject convert(Value v, String declaredType) {
        JsonObject o = new JsonObject();
        if (v == null) {
            o.addProperty("k", "null");
            return o;
        }
        if (v instanceof PrimitiveValue p) {
            o.addProperty("k", "prim");
            o.addProperty("t", p.type().name());
            putPrimitive(o, p);
            return o;
        }
        if (v instanceof StringReference s) {
            o.addProperty("k", "str");
            o.addProperty("v", s.value());
            return o;
        }
        ObjectReference ref = (ObjectReference) v;
        String cls = ref.referenceType().name();
        if (BOXES.contains(cls)) {
            Value inner = ref.getValue(ref.referenceType().fieldByName("value"));
            o.addProperty("k", "prim");
            o.addProperty("t", simpleName(cls));
            putPrimitive(o, (PrimitiveValue) inner);
            return o;
        }
        o.addProperty("k", "ref");
        o.addProperty("id", ref.uniqueID());
        o.addProperty("cls", simpleName(cls));
        enqueue(ref);
        return o;
    }

    private static void putPrimitive(JsonObject o, PrimitiveValue p) {
        if (p instanceof BooleanValue b) o.addProperty("v", b.value());
        else if (p instanceof CharValue c) o.addProperty("v", String.valueOf(c.value()));
        else if (p instanceof com.sun.jdi.DoubleValue || p instanceof com.sun.jdi.FloatValue) o.addProperty("v", p.doubleValue());
        else o.addProperty("v", p.longValue());
    }

    private JsonObject serialize(ObjectReference o) {
        String cls = o.referenceType().name();
        JsonObject out = new JsonObject();
        out.addProperty("cls", simpleName(cls));
        if (o instanceof ArrayReference arr) {
            out.addProperty("kind", "array");
            out.addProperty("type", cls);
            int n = arr.length();
            out.addProperty("length", n);
            JsonArray items = new JsonArray();
            if (n > 0) {
                for (Value item : arr.getValues(0, Math.min(n, MAX_ARRAY_ITEMS))) items.add(convert(item, null));
            }
            out.add("items", items);
            return out;
        }
        try {
            switch (cls) {
                case "java.util.ArrayList", "java.util.Vector", "java.util.Stack" -> {
                    String sizeField = cls.equals("java.util.ArrayList") ? "size" : "elementCount";
                    return list(out, cls, items((ArrayReference) get(o, "elementData"), 0, intField(o, sizeField)));
                }
                case "java.util.Arrays$ArrayList" -> {
                    ArrayReference a = (ArrayReference) get(o, "a");
                    return list(out, cls, items(a, 0, a.length()));
                }
                case "java.util.LinkedList" -> {
                    JsonArray items = new JsonArray();
                    ObjectReference node = (ObjectReference) get(o, "first");
                    while (node != null && items.size() < MAX_ARRAY_ITEMS) {
                        items.add(convert(get(node, "item"), null));
                        node = (ObjectReference) get(node, "next");
                    }
                    return list(out, cls, items);
                }
                case "java.util.ArrayDeque" -> {
                    ArrayReference elements = (ArrayReference) get(o, "elements");
                    int head = intField(o, "head");
                    int tail = intField(o, "tail");
                    JsonArray items = new JsonArray();
                    int len = elements.length();
                    for (int i = head; i != tail && items.size() < MAX_ARRAY_ITEMS; i = (i + 1) % len) {
                        items.add(convert(elements.getValue(i), null));
                    }
                    return list(out, cls, items);
                }
                case "java.util.PriorityQueue" -> {
                    return list(out, cls, items((ArrayReference) get(o, "queue"), 0, intField(o, "size")));
                }
                case "java.util.HashMap", "java.util.LinkedHashMap", "java.util.TreeMap" -> {
                    out.addProperty("kind", "map");
                    out.add("entries", mapEntries(o, cls, false));
                    return out;
                }
                case "java.util.HashSet", "java.util.LinkedHashSet", "java.util.TreeSet" -> {
                    ObjectReference map = (ObjectReference) get(o, cls.equals("java.util.TreeSet") ? "m" : "map");
                    out.addProperty("kind", "set");
                    JsonArray items = new JsonArray();
                    for (var entry : mapEntries(map, map.referenceType().name(), true)) {
                        items.add(entry.getAsJsonArray().get(0));
                    }
                    out.add("items", items);
                    return out;
                }
                case "java.lang.StringBuilder", "java.lang.StringBuffer" -> {
                    out.addProperty("kind", "builder");
                    out.addProperty("value", builderText(o));
                    return out;
                }
                default -> { }
            }
        } catch (RuntimeException e) {
            out.addProperty("kind", "opaque");
            return out;
        }
        if (cls.startsWith("java.") || cls.startsWith("jdk.") || cls.startsWith("sun.")) {
            out.addProperty("kind", "opaque");
            return out;
        }
        out.addProperty("kind", "object");
        out.addProperty("type", cls);
        JsonArray fields = new JsonArray();
        ReferenceType type = o.referenceType();
        recordClass(type);
        for (Field f : type.allFields()) {
            if (f.isStatic() || f.isSynthetic()) continue;
            JsonObject field = new JsonObject();
            field.addProperty("name", f.name());
            field.add("value", convert(o.getValue(f), f.typeName()));
            fields.add(field);
        }
        out.add("fields", fields);
        return out;
    }

    private void recordClass(ReferenceType type) {
        String name = type.name();
        if (classes.has(name)) return;
        JsonObject c = new JsonObject();
        c.addProperty("simpleName", simpleName(name));
        JsonArray fields = new JsonArray();
        for (Field f : type.allFields()) {
            if (f.isStatic() || f.isSynthetic()) continue;
            JsonObject field = new JsonObject();
            field.addProperty("name", f.name());
            field.addProperty("type", f.typeName());
            fields.add(field);
        }
        c.add("fields", fields);
        classes.add(name, c);
    }

    private JsonObject list(JsonObject out, String cls, JsonArray items) {
        out.addProperty("kind", "list");
        out.add("items", items);
        return out;
    }

    private JsonArray items(ArrayReference arr, int from, int count) {
        JsonArray items = new JsonArray();
        int n = Math.min(count, MAX_ARRAY_ITEMS);
        if (arr == null || n <= 0) return items;
        for (Value v : arr.getValues(from, n)) items.add(convert(v, null));
        return items;
    }

    private JsonArray mapEntries(ObjectReference map, String cls, boolean keysOnly) {
        JsonArray entries = new JsonArray();
        if (cls.equals("java.util.TreeMap")) {
            Deque<ObjectReference> stack = new ArrayDeque<>();
            ObjectReference node = (ObjectReference) get(map, "root");
            while ((node != null || !stack.isEmpty()) && entries.size() < MAX_ARRAY_ITEMS) {
                while (node != null) {
                    stack.push(node);
                    node = (ObjectReference) get(node, "left");
                }
                node = stack.pop();
                entries.add(entry(node, keysOnly));
                node = (ObjectReference) get(node, "right");
            }
            return entries;
        }
        if (cls.equals("java.util.LinkedHashMap")) {
            ObjectReference node = (ObjectReference) get(map, "head");
            while (node != null && entries.size() < MAX_ARRAY_ITEMS) {
                entries.add(entry(node, keysOnly));
                node = (ObjectReference) get(node, "after");
            }
            return entries;
        }
        ArrayReference table = (ArrayReference) get(map, "table");
        if (table == null) return entries;
        for (Value bucket : table.getValues()) {
            ObjectReference node = (ObjectReference) bucket;
            while (node != null && entries.size() < MAX_ARRAY_ITEMS) {
                entries.add(entry(node, keysOnly));
                node = (ObjectReference) get(node, "next");
            }
        }
        return entries;
    }

    private JsonArray entry(ObjectReference node, boolean keysOnly) {
        JsonArray pair = new JsonArray();
        pair.add(convert(get(node, "key"), null));
        if (!keysOnly) pair.add(convert(get(node, "value"), null));
        return pair;
    }

    private String builderText(ObjectReference sb) {
        ArrayReference value = (ArrayReference) get(sb, "value");
        int count = intField(sb, "count");
        int coder = ((PrimitiveValue) get(sb, "coder")).intValue();
        if (value == null || count == 0) return "";
        StringBuilder text = new StringBuilder();
        if (coder == 0) {
            for (Value b : value.getValues(0, count)) text.append((char) (((PrimitiveValue) b).byteValue() & 0xff));
        } else {
            // UTF-16 in the JVM's native byte order.
            boolean little = java.nio.ByteOrder.nativeOrder() == java.nio.ByteOrder.LITTLE_ENDIAN;
            List<Value> bytes = value.getValues(0, count * 2);
            for (int i = 0; i < count; i++) {
                int first = ((PrimitiveValue) bytes.get(2 * i)).byteValue() & 0xff;
                int second = ((PrimitiveValue) bytes.get(2 * i + 1)).byteValue() & 0xff;
                text.append((char) (little ? second << 8 | first : first << 8 | second));
            }
        }
        return text.toString();
    }

    private static Value get(ObjectReference o, String field) {
        Field f = o.referenceType().fieldByName(field);
        if (f == null) throw new IllegalStateException("no field " + field);
        return o.getValue(f);
    }

    private static int intField(ObjectReference o, String field) {
        return ((PrimitiveValue) get(o, field)).intValue();
    }

    static String simpleName(String binary) {
        String s = binary.substring(binary.lastIndexOf('.') + 1);
        return s.substring(s.lastIndexOf('$') + 1);
    }
}
