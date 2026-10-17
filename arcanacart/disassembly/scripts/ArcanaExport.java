// Local ARMv4T assembly/pseudocode export. Pseudocode is NOT original source.
// Arguments: output-dir rom-sha256 start end batch(0=all) resume
// @category GBA
import ghidra.app.util.headless.HeadlessScript;
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.*;
import ghidra.program.model.mem.MemoryBlock;
import ghidra.program.model.symbol.Reference;
import ghidra.framework.Application;
import com.google.gson.*;
import java.nio.file.*;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.*;

public class ArcanaExport extends HeadlessScript {
    private final Gson gson = new GsonBuilder().setPrettyPrinting().create();

    private void write(Path target, String content) throws Exception {
        if (Files.isSymbolicLink(target) || Files.isSymbolicLink(target.getParent()))
            throw new IllegalArgumentException("Symlink output rejected");
        Path temp = Files.createTempFile(target.getParent(), ".arcana-", ".tmp");
        try {
            Files.writeString(temp, content, StandardCharsets.UTF_8);
            Files.move(temp, target, StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING);
        } finally { Files.deleteIfExists(temp); }
    }

    private String hash(String text) throws Exception {
        byte[] bytes = MessageDigest.getInstance("SHA-256").digest(text.getBytes(StandardCharsets.UTF_8));
        StringBuilder out = new StringBuilder();
        for (byte b : bytes) out.append(String.format("%02x", b & 255));
        return out.toString();
    }

    @Override
    protected void run() throws Exception {
        String[] args = getScriptArgs();
        if (args.length != 6) throw new IllegalArgumentException("output sha256 start end batch resume required");
        Path out = Paths.get(args[0]).toAbsolutePath().normalize();
        for (Path p = out; p != null; p = p.getParent())
            if (Files.isSymbolicLink(p)) throw new IllegalArgumentException("Symlink directory rejected");
        Files.createDirectories(out);
        String expectedHash = args[1];
        String actualHash = currentProgram.getExecutableSHA256();
        if (!expectedHash.equalsIgnoreCase(actualHash)) throw new IllegalArgumentException("ROM hash mismatch");
        if (!currentProgram.getLanguageID().toString().equals("ARM:LE:32:v4t"))
            throw new IllegalArgumentException("Expected ARMv4T little-endian, not generic ARMv7");
        Address base = toAddr(0x08000000L);
        MemoryBlock rom = currentProgram.getMemory().getBlock(base);
        if (rom == null || !rom.getStart().equals(base) || !rom.isInitialized())
            throw new IllegalArgumentException("Missing initialized ROM block at 0x08000000");
        if (currentProgram.getMemory().getBlock(toAddr(0x02000000L)) == null ||
            currentProgram.getMemory().getBlock(toAddr(0x03000000L)) == null)
            throw new IllegalArgumentException("GBA RAM blocks missing; use GBA loader");
        long start = Long.decode(args[2]), end = Long.decode(args[3]);
        int batch = Integer.parseInt(args[4]);
        boolean resume = Boolean.parseBoolean(args[5]);
        int total = 0, attempted = 0, failed = 0, skipped = 0, remaining = 0;
        boolean timedOut = isRunningHeadless() && analysisTimeoutOccurred();
        DecompInterface iface = new DecompInterface();
        JsonArray index = new JsonArray();
        try {
            if (!iface.openProgram(currentProgram)) throw new IllegalStateException("Decompiler failed to open program");
            FunctionIterator iterator = currentProgram.getFunctionManager().getFunctions(true);
            while (iterator.hasNext()) {
                Function f = iterator.next();
                long address = f.getEntryPoint().getOffset();
                if (address < start || address >= end) continue;
                total++;
                String key = String.format("%08x", address);
                String name = f.getName();
                Path recordFile = out.resolve(key+".json");
                StringBuilder asm = new StringBuilder();
                InstructionIterator instructions = currentProgram.getListing().getInstructions(f.getBody(), true);
                while (instructions.hasNext()) {
                    if (monitor.isCancelled()) break;
                    Instruction instruction = instructions.next();
                    asm.append(instruction.getAddress()).append("  ").append(instruction.toString()).append('\n');
                }
                String fingerprint = hash("arcana-export-v1\n"+Application.getApplicationVersion()+"\n"+asm.toString()+"\n"+name+"\n"+f.getSignature().toString());
                if (resume && Files.isRegularFile(recordFile) && !Files.isSymbolicLink(recordFile) && Files.size(recordFile) < 1024*1024) {
                    try {
                        JsonObject old = JsonParser.parseString(Files.readString(recordFile)).getAsJsonObject();
                        Path cFile = out.resolve(key+".c"), asmFile = out.resolve(key+".s");
                        if (old.has("assembly_sha256") && old.has("pseudocode_sha256") &&
                            expectedHash.equals(old.get("rom_sha256").getAsString()) &&
                            fingerprint.equals(old.get("analysis_fingerprint").getAsString()) &&
                            old.get("status").getAsString().equals("completed") &&
                            Files.isRegularFile(cFile) && !Files.isSymbolicLink(cFile) &&
                            Files.isRegularFile(asmFile) && !Files.isSymbolicLink(asmFile) &&
                            Files.size(cFile) < 32*1024*1024 && Files.size(asmFile) < 32*1024*1024 &&
                            hash(Files.readString(cFile)).equals(old.get("pseudocode_sha256").getAsString()) &&
                            hash(Files.readString(asmFile)).equals(old.get("assembly_sha256").getAsString())) {
                            index.add(old); skipped++; continue;
                        }
                    } catch (Exception corruptRecord) { /* Re-export corrupted/incomplete records. */ }
                }
                if (monitor.isCancelled() || batch > 0 && attempted >= batch) { remaining++; continue; }
                attempted++;
                JsonObject record = new JsonObject();
                record.addProperty("address", key); record.addProperty("name", name);
                record.addProperty("rom_sha256", expectedHash);
                record.addProperty("analysis_fingerprint", fingerprint);
                record.addProperty("language", currentProgram.getLanguageID().toString());
                record.addProperty("size_bytes", f.getBody().getNumAddresses());
                record.addProperty("assembly", key+".s");
                record.addProperty("pseudocode", key+".c");
                JsonArray calls = new JsonArray();
                for (Function called : f.getCalledFunctions(monitor)) calls.add(called.getEntryPoint().toString());
                record.add("calls", calls);
                JsonArray incoming = new JsonArray();
                for (Reference ref : getReferencesTo(f.getEntryPoint())) incoming.add(ref.getFromAddress().toString());
                record.add("references_from", incoming);
                record.addProperty("thumb_context", String.valueOf(currentProgram.getProgramContext().getValue(
                    currentProgram.getRegister("TMode"), f.getEntryPoint(), false)));
                String assembly = "; Recovered assembly; review ARM/Thumb context.\n"+asm;
                write(out.resolve(key+".s"), assembly);
                record.addProperty("assembly_sha256", hash(assembly));
                record.addProperty("ghidra_version", Application.getApplicationVersion());
                try {
                    DecompileResults result = iface.decompileFunction(f, 30, monitor);
                    if (!result.decompileCompleted() || result.getDecompiledFunction() == null)
                        throw new IllegalStateException(result.getErrorMessage());
                    String pseudocode = "/* Generated pseudocode, NOT original source. */\n"+result.getDecompiledFunction().getC();
                    write(out.resolve(key+".c"), pseudocode);
                    record.addProperty("pseudocode_sha256", hash(pseudocode));
                    record.addProperty("status", "completed");
                } catch (Exception ex) {
                    failed++; record.addProperty("status", "failed"); record.addProperty("error", ex.toString());
                }
                write(recordFile, gson.toJson(record)); index.add(record);
            }
        } finally { iface.dispose(); }
        JsonObject summary = new JsonObject();
        summary.addProperty("status", !timedOut && remaining == 0 && failed == 0 && !monitor.isCancelled() ? "completed" : "partial");
        summary.addProperty("rom_sha256", expectedHash);
        summary.addProperty("language", currentProgram.getLanguageID().toString());
        summary.addProperty("ghidra_version", Application.getApplicationVersion());
        summary.addProperty("identified_in_range", total); summary.addProperty("attempted", attempted);
        summary.addProperty("skipped_completed", skipped); summary.addProperty("failed", failed);
        summary.addProperty("remaining", remaining); summary.addProperty("analysis_timeout", timedOut);
        summary.addProperty("range_start", start); summary.addProperty("range_end", end);
        summary.add("functions", index);
        write(out.resolve("summary.json"), gson.toJson(summary));
        // All identifiers are escaped; no script/CDN needed to browse function exports.
        StringBuilder page = new StringBuilder("<!doctype html><html lang=\"es\"><meta charset=\"utf-8\"><title>ArcanaCart functions</title><h1>Functions</h1><ul>");
        for (JsonElement e : index) {
            JsonObject row = e.getAsJsonObject(); String key = row.get("address").getAsString();
            String safeName = row.get("name").getAsString().replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;");
            page.append("<li>").append(key).append(" ").append(safeName).append(" — <a href=\"").append(key).append(".s\">asm</a>");
            if (row.get("status").getAsString().equals("completed")) page.append(" <a href=\"").append(key).append(".c\">pseudocode</a>");
            page.append("</li>");
        }
        write(out.resolve("index.html"), page.append("</ul></html>").toString());
        println(gson.toJson(summary));
    }
}
