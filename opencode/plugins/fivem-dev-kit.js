import { spawn } from "node:child_process"
import { fileURLToPath } from "node:url"
import { dirname, isAbsolute, relative, resolve, sep } from "node:path"
import { existsSync, readFileSync, realpathSync } from "node:fs"

// Keep the OpenCode adapter in this checkout and install it through symlinks.
const kitRoot = resolve(dirname(realpathSync(fileURLToPath(import.meta.url))), "../..")
const lintHandler = resolve(kitRoot, "hooks-handlers/post-edit-lint.py")
const editedTools = new Set(["write", "edit", "apply_patch"])
const workspaceRoot = resolve(kitRoot, "..")
let localSettings = {}
try {
  localSettings = JSON.parse(readFileSync(resolve(kitRoot, "config.json"), "utf8"))
} catch {
  // The adapter still works before the optional local kit config is created.
}
const resourceRoot = resolve(localSettings?.project?.workspace ?? resolve(workspaceRoot, "resources"))
const coreRoot = resolve(localSettings?.core?.path ?? resolve(resourceRoot, "core"))
const coreRules = resolve(coreRoot, "AGENTS.md")

function isWithin(path, root) {
  const rel = relative(root, resolve(path))
  return rel === "" || (rel !== ".." && !rel.startsWith(`..${sep}`) && !isAbsolute(rel))
}

function editedPaths(tool, args) {
  if (tool === "write" || tool === "edit") {
    const path = args?.filePath ?? args?.file_path
    return typeof path === "string" ? [path] : []
  }
  if (tool !== "apply_patch" || typeof args?.patch !== "string") return []
  return [...args.patch.matchAll(/^\*\*\* (?:Add|Update) File: (.+)$/gm)].map((match) => match[1].trim())
}

function lintEditedFile(path, cwd) {
  return new Promise((done) => {
    const child = spawn("python3", [lintHandler], { stdio: ["pipe", "pipe", "ignore"] })
    const chunks = []
    let size = 0
    const timeout = setTimeout(() => child.kill(), 12_000)
    child.stdout.on("data", (chunk) => {
      size += chunk.length
      if (size <= 65_536) chunks.push(chunk)
      else child.kill()
    })
    child.on("error", () => {
      clearTimeout(timeout)
      done("")
    })
    child.on("close", () => {
      clearTimeout(timeout)
      try {
        const result = JSON.parse(Buffer.concat(chunks).toString("utf8"))
        done(result?.hookSpecificOutput?.additionalContext ?? "")
      } catch {
        done("")
      }
    })
    child.stdin.on("error", () => {}) // A timeout can close stdin before the payload is written.
    child.stdin.end(JSON.stringify({
      cwd,
      tool_input: { file_path: isAbsolute(path) ? path : resolve(cwd, path) },
    }))
  })
}

export const FiveMDevKit = async ({ directory }) => ({
  config: async (config) => {
    const here = resolve(directory ?? process.cwd())
    const inResources = isWithin(here, resourceRoot)
    if (here !== workspaceRoot && !inResources) return
    if (!config.default_agent) config.default_agent = isWithin(here, coreRoot) ? "fivem-core" : "fivem"
    // resources/CLAUDE.md's @core/AGENTS.md reference is not auto-expanded by OpenCode.
    if (!isWithin(here, coreRoot) && existsSync(coreRules)) {
      const instructions = config.instructions ?? []
      if (!instructions.includes(coreRules)) config.instructions = [...instructions, coreRules]
    }
  },
  "shell.env": async (_input, output) => {
    output.env.FIVEM_DEV_KIT_ROOT = kitRoot
    output.env.CLAUDE_PLUGIN_ROOT = kitRoot // existing shared skill text also uses this name
    output.env.PATH = `${resolve(kitRoot, "bin")}:${output.env.PATH ?? process.env.PATH ?? ""}`
  },
  "tool.execute.after": async (input, output) => {
    if (!editedTools.has(input.tool)) return
    const cwd = directory ?? process.cwd()
    const paths = [...new Set(editedPaths(input.tool, input.args))].slice(0, 8)
    if (!paths.length) return
    const messages = await Promise.all(paths.map((path) => lintEditedFile(path, cwd)))
    const findings = messages.filter(Boolean)
    if (findings.length) output.output += `\n\n${findings.join("\n\n")}`
  },
})
