# Compatibility launcher for Ghidra installations with Jython enabled.
# Prefer ArcanaExport.java directly; Java works without the optional Jython runtime.
# @category GBA
args = list(getScriptArgs())
if not args:
    output = askDirectory("Output directory (private)", "Choose")
    args = [output.getAbsolutePath(), currentProgram.getExecutableSHA256(),
            "0x08000000", "0x0A000000", "0", "true"]
runScript("ArcanaExport.java", args)
