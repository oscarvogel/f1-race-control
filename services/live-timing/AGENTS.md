# AGENTS CODE RULES

This file defines the strict quality and development standards for this codebase (`f1-livetiming-api`). All rules must be followed at all times.

---

## GLOBAL BACKEND DEVELOPMENT RULES

### 1. Language & Environment
- **Vanilla JavaScript (Node.js):** This project uses plain JavaScript. Do NOT use TypeScript syntax (no type annotations, no interfaces, no generics).
- **Module System:** Use CommonJS (`require` and `module.exports`). Do not use ES Modules (`import`/`export`) unless explicitly requested to migrate.

### 2. Commenting & Documentation
- **JSDoc Mandatory:** All functions, classes, and complex logic must be documented using JSDoc. This is required for `npm run docs` to generate documentation correctly.
- **Language:** Write all comments exclusively in ENGLISH.
- **Conciseness:** Inline code comments should be extremely concise (1 or 2 lines maximum) and explain *why* the logic exists, not *what* it does.

### 3. Preserving Code & Diffing
- **No Random Renaming:** NEVER arbitrarily change the names of existing functions, variables, or routes.
- **Surgical Changes:** Alter ONLY the strictly necessary lines required to complete the task. Do not reformat, re-indent, or modify untouched surrounding code manually.
- **No Lazy Coding:** NEVER use placeholders like `// ... existing code ...`. Output the complete functional block required for the change.

### 4. Error Handling
- **No Silent Failures:** NEVER swallow errors silently. Using `try { ... } catch (e) { console.log(e) }` without proper handling or API error responses is strictly prohibited.
- **API Responses:** In Express routes, always return appropriate HTTP status codes (e.g., 500) and JSON error objects when exceptions occur.

### 5. Naming Conventions & Magic Numbers
- **Naming Conventions:** Use `camelCase` for variables and functions, `PascalCase` for classes (e.g., `F1LiveClient`), and `UPPER_SNAKE_CASE` for global constants.
- **No Magic Values:** Extract hardcoded values (like timeouts, specific API statuses, etc.) into descriptive constants.

### 6. Code Quality & Formatting
- **Async/Await:** Use `async/await` for asynchronous operations. Avoid deep `.then().catch()` chains.
- **Prettier:** Code formatting is managed by Prettier. You must ensure code aligns with the project's formatting rules, or remind the user to run `npm run format`.
- **Modularity:** Keep routes modular. Do not bloat `server.js`. Complex endpoints should be extracted into the `src/routes/` directory.

### 7. Dependencies
- **No Hallucinations:** Use only existing dependencies (`express`, `ws`, `cors`) unless explicitly requested to install new ones. 
- **Absolute vs Relative Paths:** Use correct relative paths (e.g., `../utils/logger.js`) to require local modules.

---

## COMMIT RULES

When asked to commit (`/commit`):
1. Stage all changes with `git add .`
2. Analyze staged changes via `git diff --staged` (base message on this, NOT chat history)
3. Conventional Commit title (max 72 chars): `feat:`, `fix:`, `refactor:`, `chore:`, `style:`
4. First letter of the commit title MUST be lowercase
5. Body as bulleted list: `- [File/Folder]: Brief explanation`
6. Execute `git commit -m "<TITLE>" -m "<BODY>"`
7. Push with `git push` (or `git push -u origin HEAD` if no upstream)
8. Output ONLY confirmation with commit hash

## PR RULES

When asked to open a PR (`/pr`):
1. Analyze FULL diff against base branch (`git diff origin/main...HEAD`)
2. Push branch if needed
3. Professional PR title in English
4. Body: follow the template in `.github/pull_request_template.md`
5. Execute `gh pr create --base main --title "<TITLE>" --body "<BODY>"`
6. Target `main` branch by default unless explicitly asked otherwise
7. Output ONLY the GitHub PR URL
