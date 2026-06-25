# services/github/constants.py
#
# All static pattern definitions used by the GitHub file analyzer.
# No logic here — pure data. Import from here everywhere else.

from typing import Dict, List, Set

# ==========================================
# FILE FILTERING
# ==========================================

# Paths/extensions to always skip — build artifacts, locks, media
IGNORE_PATTERNS: List[str] = [
    "node_modules/", "dist/", "build/", ".next/", "out/", "coverage/",
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", ".gitignore",
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".woff", ".woff2",
    "LICENSE", "CHANGELOG.md", ".DS_Store", ".vscode/", ".idea/",
    "__pycache__/", ".eslintrc", ".prettierrc", "tsconfig.json",
]

# Pre-built UI component paths — not worth AI analysis
BOILERPLATE_PATTERNS: List[str] = [
    "components/ui/", "@radix-ui", "lucide-react",
    "/ui/button.tsx", "/ui/input.tsx", "/ui/card.tsx", "/ui/dialog.tsx",
    "/ui/dropdown", "/ui/select", "/ui/toast", "/ui/alert", "/ui/badge",
    "/ui/avatar", "/ui/accordion", "/ui/table", "/ui/tabs", "/ui/checkbox",
    "/ui/radio", "/ui/slider", "/ui/switch", "/ui/tooltip", "/ui/popover",
    "/ui/sheet", "/ui/skeleton",
]

# Files that are likely entry points or core logic — get bigger chunk budgets
HIGH_PRIORITY_PATTERNS: List[str] = [
    "/api/", "route.ts", "route.js", "/actions/", "/lib/db", "/lib/auth",
    "middleware", "/hooks/", "/context/", "/utils/", "/services/",
    "/controllers/", "config", "schema", "/models/", "server.", "main.", "app.", "index.",
]

# CI/CD and config files — always include even if extension doesn't match
CICD_AND_CONFIG_PATTERNS: List[str] = [
    ".github/workflows/", ".gitlab-ci.yml", "jenkinsfile", ".circleci/",
    "azure-pipelines.yml", ".travis.yml", "package.json", "requirements.txt",
    "go.mod", "cargo.toml", "pyproject.toml", "pom.xml", "build.gradle",
    "docker-compose", "dockerfile", ".env.example",
]

# File extensions worth analyzing
CODE_EXTENSIONS: Set[str] = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".html", ".css", ".scss",
    ".java", ".go", ".rs", ".php", ".rb", ".swift", ".kt",
    ".json", ".yaml", ".yml", ".toml", ".xml", ".sql",
}

# Root-level important files — always include regardless of extension
IMPORTANT_FILES: Set[str] = {
    "readme", "changelog", "license", "contributing", "dockerfile", "makefile",
}

# ==========================================
# SIGNAL DEFINITIONS
# ==========================================

# Only these capabilities are valid signal targets
ALLOWED_CAPABILITIES: Set[str] = {
    "authentication",
    "ci_cd",
    "database",
    "testing",
    "api",
    "configuration",
    "validation",
}

# Only these signal types are valid
ALLOWED_SIGNAL_TYPES: Set[str] = {
    "structural",   # library/module/config EXISTS (import, require, class declaration)
    "behavioral",   # function IS CALLED or executes logic
    "wiring",       # connected to runtime flow (middleware applied, route mounted, CI triggered)
    "negative",     # expected behaviour is PROVABLY ABSENT
}

# Actions that carry zero signal value — dropped before aggregation
NOISE_ACTIONS: Set[str] = {
    # Boilerplate app lifecycle
    "router_exported",
    "app_listen_called",
    "root_route_responds_with_json",
    "send_data_to_api_register",
    "console_log_called",
    "module_exported",
    "app_imported",
    "express_json_middleware_imported",
    "root_route_defined",
    "express_app_initialized",
    "routes_imported",
    # LLM-emitted boilerplate duplicates
    "app_exported",
    "express_app_declared",
    "port_declared",
    "port_hardcoded",
    "app_started",
    "server_started",
    "routes_module_imported",
    "express_router_exported",
    # README/comment content mistakenly emitted as signals
    "jwt_secret_environment_variable_documented",
    "configuration_documented_in_readme",
}

# ==========================================
# FEATURE CLASSIFICATION
# ==========================================

# Maps detected feature → capability bucket for signal storage
FEATURE_TO_CAPABILITY: Dict[str, str] = {
    "authentication":   "authentication",
    "api_routes":       "api",
    "database":         "database",
    "ci_cd":            "ci_cd",
    "business_logic":   "configuration",
    "custom_components":"configuration",
    "ui_library":       "configuration",
    "validation":        "validation",
}

# Rules for classifying a file into a feature group.
# Each entry: paths/imports/functions/keywords to match + priority weight.
# Higher priority wins when a file matches multiple features.
FEATURE_PATTERNS: Dict[str, Dict] = {
    "authentication": {
        "paths":     ["/api/auth/", "/auth/", "login", "signup", "register", "signin", "middleware"],
        "imports":   ["bcrypt", "jsonwebtoken", "jwt", "passport", "next-auth", "argon2"],
        "functions": ["login", "signup", "register", "signin", "logout", "authenticate", "verifytoken"],
        "keywords":  ["password", "token", "session", "credential", "auth", "jwt", "cookie"],
        "priority":  10,
    },
    "api_routes": {
        "paths":     ["/api/", "route.ts", "route.js", "/controllers/", "/routes/", "/actions/"],
        "imports":   ["express", "NextRequest", "NextResponse", "fastapi", "flask", "koa"],
        "functions": ["GET", "POST", "PUT", "DELETE", "PATCH", "handler", "middleware"],
        "keywords":  ["endpoint", "request", "response", "api", "route", "handler"],
        "priority":  10,
    },
    "database": {
        "paths":     ["/models/", "/db/", "/database/", "dbconfig", "schema", ".model.", "prisma"],
        "imports":   [
            "mongoose", "prisma", "typeorm", "sequelize", "@/models",
            "mongodb", "pg", "mysql", "sqlalchemy", "pymongo",
        ],
        "functions": ["connect", "findOne", "findById", "create", "update", "delete", "save", "Schema"],
        "keywords":  ["schema", "model", "database", "connection", "collection", "query"],
        "priority":  9,
    },
    "ci_cd": {
        "paths":     [
            ".github/workflows/", ".gitlab-ci", ".circleci", "jenkinsfile",
            "azure-pipelines", ".travis", "ci.yml", "cd.yml",
        ],
        "imports":   [],
        "functions": [],
        "keywords":  [
            "npm test", "pytest", "jest", "lint", "deploy", "build",
            "workflow", "on: push", "on: pull_request", "runs-on",
        ],
        "priority":  9,
    },
    "business_logic": {
        "paths":     ["/services/", "/lib/", "/utils/", "/helpers/", "/hooks/", "/context/"],
        "imports":   ["lodash", "dayjs", "moment", "uuid", "crypto"],
        "functions": ["helper", "util", "format", "validate", "parse", "sanitize", "use"],
        "keywords":  ["helper", "utility", "utils", "lib", "hook", "context", "service"],
        "priority":  8,
    },
    "custom_components": {
        "paths":     ["/components/", "/modules/"],
        "imports":   ["react", "next/link", "next/image", "@/components"],
        "functions": ["Component"],
        "keywords":  ["component", "props", "onClick", "onChange"],
        "priority":  5,
    },
    "ui_library": {
        "paths":     ["components/ui/", "@radix-ui", "lucide-react"],
        "imports":   ["@radix-ui", "lucide-react", "@/components/ui"],
        "functions": [],
        "keywords":  ["radix", "shadcn", "lucide"],
        "priority":  1,
    },
     "validation": {
    "paths":     ["/validators/", "/validation/", "/middleware/", "/schemas/", "/rules/"],
    "imports":   ["joi", "zod", "yup", "express-validator", "class-validator", "validator"],
    "functions": ["validate", "sanitize", "parse", "check", "schema"],
    "keywords":  ["validate", "sanitize", "schema", "required", "minlength", "maxlength", "regex", "pattern", "isvalid"],
    "priority":  9,
}
}

# ==========================================
# TECHNOLOGY DETECTION
# ==========================================

# Maps lowercase keyword → display name for technology extraction
TECH_MAP: Dict[str, str] = {
    "jwt":       "JWT",
    "bcrypt":    "Bcrypt",
    "argon2":    "Argon2",
    "nextauth":  "NextAuth",
    "prisma":    "Prisma",
    "mongoose":  "Mongoose",
    "sequelize": "Sequelize",
    "express":   "Express",
    "fastapi":   "FastAPI",
    "flask":     "Flask",
    "jest":      "Jest",
    "vitest":    "Vitest",
    "pytest":    "Pytest",
    "docker":    "Docker",
    "github":    "GitHub Actions",
    "zod":       "Zod",
    "joi":       "Joi",
    "helmet":    "Helmet",
    "postgres":  "PostgreSQL",
    "mongodb":   "MongoDB",
    "redis":     "Redis",
    "react":     "React",
    "nextjs":    "Next.js",
    "vue":       "Vue",
}